"""TypeScript and JavaScript Path Alias Resolution (tsconfig.json / jsconfig.json).

Provides deterministic resolution of compilerOptions.paths and baseUrl across
monorepos, Next.js, Vite, and React projects without external dependencies.
"""
from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path


def strip_json_comments(text: str) -> str:
    """Strip single-line and multi-line comments and trailing commas from tsconfig/jsconfig JSON."""
    # Remove block comments /* ... */
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)
    # Remove line comments // ... (not inside quotes)
    lines: list[str] = []
    for line in text.splitlines():
        # Match // not preceded by a quote mark
        cleaned_line = re.sub(r'(?<![:"\'\\])//.*$', '', line)
        lines.append(cleaned_line)
    cleaned = "\n".join(lines)
    # Remove trailing commas before } or ]
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    return cleaned


@dataclass(frozen=True)
class TsConfig:
    config_path: str
    base_dir: str
    base_url: str
    paths: dict[str, tuple[str, ...]] = field(default_factory=dict)


class TsConfigResolver:
    """Manages tsconfig.json and jsconfig.json path mappings across workspaces."""

    def __init__(self, configs: list[TsConfig] | None = None) -> None:
        self.configs: list[TsConfig] = configs or []

    @classmethod
    def load_from_repo(cls, repo_root: Path) -> TsConfigResolver:
        """Scan workspace for tsconfig.json, jsconfig.json, and vite.config.* files."""
        configs: list[TsConfig] = []
        candidates = (
            list(repo_root.glob("**/tsconfig*.json"))
            + list(repo_root.glob("**/jsconfig*.json"))
            + list(repo_root.glob("**/vite.config.*"))
        )

        for c_path in candidates:
            # Skip node_modules or build outputs
            parts = c_path.parts
            if any(p in ("node_modules", ".git", "dist", "build", ".next", ".cache") for p in parts):
                continue
            if c_path.name.startswith("vite.config."):
                cfg = cls._parse_vite_config(c_path, repo_root)
            else:
                cfg = cls._parse_single_config(c_path, repo_root)
            if cfg:
                configs.append(cfg)

        # Sort configs: deepest path first for nearest-config resolution
        configs.sort(key=lambda c: len(c.base_dir), reverse=True)
        return cls(configs)

    @staticmethod
    def _parse_vite_config(file_path: Path, repo_root: Path) -> TsConfig | None:
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            parsed_paths: dict[str, tuple[str, ...]] = {}

            # 1. Object alias: alias: { '@': path.resolve(__dirname, './src'), ... }
            alias_match = re.search(r"alias\s*:\s*\{([^}]+)\}", content)
            if alias_match:
                entries = re.findall(
                    r"""['"]([^'"]+)['"]\s*:\s*(?:(?:path\.)?resolve\([^)]*['"]([^'"]+)['"]\)|['"]([^'"]+)['"])""",
                    alias_match.group(1),
                )
                for key, target1, target2 in entries:
                    raw_target = (target1 or target2 or "").strip().replace("\\", "/").lstrip("./")
                    if raw_target:
                        clean_key = key.rstrip("/")
                        parsed_paths[f"{clean_key}/*"] = (f"{raw_target}/*",)
                        parsed_paths[clean_key] = (raw_target,)

            # 2. Array alias: alias: [ { find: '@', replacement: path.resolve(__dirname, './src') } ]
            array_entries = re.findall(
                r"""find\s*:\s*['"]([^'"]+)['"][\s\S]*?replacement\s*:\s*(?:(?:path\.)?resolve\([^)]*['"]([^'"]+)['"]\)|['"]([^'"]+)['"])""",
                content,
            )
            for key, target1, target2 in array_entries:
                raw_target = (target1 or target2 or "").strip().replace("\\", "/").lstrip("./")
                if raw_target:
                    clean_key = key.rstrip("/")
                    parsed_paths[f"{clean_key}/*"] = (f"{raw_target}/*",)
                    parsed_paths[clean_key] = (raw_target,)

            if not parsed_paths:
                return None

            base_dir_path = file_path.parent
            rel_base_dir = posixpath.normpath(base_dir_path.relative_to(repo_root).as_posix())
            if rel_base_dir == ".":
                rel_base_dir = ""

            return TsConfig(
                config_path=posixpath.normpath(file_path.relative_to(repo_root).as_posix()),
                base_dir=rel_base_dir,
                base_url=".",
                paths=parsed_paths,
            )
        except Exception:
            return None

    @staticmethod
    def _parse_single_config(file_path: Path, repo_root: Path) -> TsConfig | None:
        try:
            raw = file_path.read_text(encoding="utf-8", errors="replace")
            cleaned = strip_json_comments(raw)
            data = json.loads(cleaned)
            compiler_opts = data.get("compilerOptions", {})

            base_dir_path = file_path.parent
            rel_base_dir = posixpath.normpath(base_dir_path.relative_to(repo_root).as_posix())
            if rel_base_dir == ".":
                rel_base_dir = ""

            base_url = compiler_opts.get("baseUrl", ".")
            raw_paths = compiler_opts.get("paths", {})

            parsed_paths: dict[str, tuple[str, ...]] = {}
            for pattern, targets in raw_paths.items():
                if isinstance(targets, list):
                    parsed_paths[pattern] = tuple(str(t) for t in targets)
                elif isinstance(targets, str):
                    parsed_paths[pattern] = (targets,)

            if not parsed_paths and base_url in (".", ""):
                return None

            return TsConfig(
                config_path=posixpath.normpath(file_path.relative_to(repo_root).as_posix()),
                base_dir=rel_base_dir,
                base_url=base_url,
                paths=parsed_paths,
            )
        except Exception:
            return None

    def resolve_alias(
        self,
        imported_module: str,
        source_file: str,
        known_files: set[str],
    ) -> str | None:
        """Resolve an aliased module (e.g. '@/components/Button') to a file path in known_files."""
        if not imported_module or imported_module.startswith("."):
            return None

        clean_src = source_file.replace("\\", "/").lstrip("./")

        # Pick matching config: deepest base_dir matching source_file, or fallback to root config
        chosen_config: TsConfig | None = None
        for cfg in self.configs:
            if not cfg.base_dir or clean_src.startswith(f"{cfg.base_dir}/"):
                chosen_config = cfg
                break
        if not chosen_config and self.configs:
            chosen_config = self.configs[-1]

        if not chosen_config:
            return None

        # Check paths mappings
        for pattern, targets in chosen_config.paths.items():
            if "*" in pattern:
                star_idx = pattern.index("*")
                prefix = pattern[:star_idx]
                suffix = pattern[star_idx + 1:]
                if imported_module.startswith(prefix) and (not suffix or imported_module.endswith(suffix)):
                    wildcard = imported_module[len(prefix):len(imported_module) - len(suffix) if suffix else None]
                    for target_tmpl in targets:
                        target = target_tmpl.replace("*", wildcard)
                        resolved = self._test_target(
                            chosen_config.base_dir, chosen_config.base_url, target, known_files
                        )
                        if resolved:
                            return resolved
            else:
                # Exact match pattern (e.g. "@lib": ["src/lib"])
                if imported_module == pattern:
                    for target in targets:
                        resolved = self._test_target(
                            chosen_config.base_dir, chosen_config.base_url, target, known_files
                        )
                        if resolved:
                            return resolved

        # Fallback to baseUrl-relative imports if baseUrl is configured
        if chosen_config.base_url and chosen_config.base_url not in (".", ""):
            resolved = self._test_target(
                chosen_config.base_dir, chosen_config.base_url, imported_module, known_files
            )
            if resolved:
                return resolved

        return None

    @staticmethod
    def _test_target(
        base_dir: str,
        base_url: str,
        target_path: str,
        known_files: set[str],
    ) -> str | None:
        """Check candidate target path against known repository files with extensions and index files."""
        # Join base_dir, base_url, and target_path in posix style
        parts = [p for p in (base_dir, base_url, target_path) if p and p not in (".", "")]
        base = posixpath.normpath("/".join(parts)).lstrip("./")

        candidates = [base]
        for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".css", ".scss"):
            candidates.append(f"{base}{ext}")
        for idx in ("index.ts", "index.tsx", "index.js", "index.jsx"):
            candidates.append(posixpath.join(base, idx))

        for cand in candidates:
            cand_norm = cand.lstrip("./")
            if cand_norm in known_files:
                return cand_norm
        return None
