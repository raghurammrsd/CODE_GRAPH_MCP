"""Roblox & Luau Codebase Intelligence Engine (Phases R1–R9).

Provides deterministic, local-first static analysis for Roblox / Luau projects:
- Phase R1: Robust Luau parser (.lua, .luau) for functions, methods (: and .), tables,
            module exports, table.freeze, Luau types, exported types, and type annotations.
- Phase R2: Rojo project resolution (default.project.json parsed strictly as JSON) mapping
            ReplicatedStorage, ServerScriptService, StarterPlayer.StarterPlayerScripts,
            ServerStorage, Workspace, and ReplicatedFirst to physical repository files.
- Phase R3: Module / require(...) graph (REQUIRES_MODULE) with bounded script.Parent and
            Rojo alias resolution.
- Phase R4: Client <-> Server Network Graph (CLIENT_DISPATCHES_REMOTE, SERVER_HANDLES_REMOTE)
            for RemoteEvent and RemoteFunction.
- Phase R6: Knit framework support (PROVIDES_SERVICE, GETS_SERVICE).
- Phase R7: Flamework TypeScript support (@Service, @Controller, Dependency<T>).
- Phase R8: Roblox persistence intelligence (DataStoreService, ProfileService ->
            CONFIGURES_PERSISTENCE, READS_PERSISTENCE, WRITES_PERSISTENCE).
- Phase R9: CLI and MCP query helpers (remotes, modules, routes).
"""
from __future__ import annotations

import hashlib
import json
import posixpath
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from codegraph.indexing.parser import ParseResult

from codegraph.epistemic import RelationshipEvidenceClass
from codegraph.errors import SecurityError
from codegraph.graph.models import GraphEdge
from codegraph.indexing.models import (
    BindingRef,
    CallRef,
    ImportRef,
    Reference,
    Symbol,
    build_canonical_id,
    normalize_module,
)
from codegraph.security import safe_path

_ROBLOX_DATAMODEL_SERVICES = frozenset({
    "ReplicatedStorage",
    "ServerScriptService",
    "StarterPlayer",
    "StarterPlayerScripts",
    "StarterCharacterScripts",
    "StarterGui",
    "StarterPack",
    "ServerStorage",
    "Workspace",
    "ReplicatedFirst",
    "Players",
    "DataStoreService",
    "MemoryStoreService",
    "MessagingService",
    "HttpService",
    "RunService",
    "UserInputService",
    "TweenService",
    "CollectionService",
    "MarketplaceService",
    "SoundService",
    "Lighting",
    "Teams",
    "Chat",
    "TextChatService",
})

_LUAU_KEYWORDS_AND_BUILTINS = frozenset({
    "and", "break", "do", "else", "elseif", "end", "false", "for", "function",
    "if", "in", "local", "nil", "not", "or", "repeat", "return", "then",
    "true", "until", "while", "continue", "type", "export", "typeof",
    "print", "warn", "error", "assert", "pcall", "xpcall", "select", "tonumber",
    "tostring", "ipairs", "pairs", "next", "rawget", "rawset", "rawequal",
    "setmetatable", "getmetatable", "unpack", "require", "math", "string",
    "table", "coroutine", "os", "debug", " utf8", "bit32", "task", "vector",
    "Vector3", "Vector2", "CFrame", "Color3", "UDim", "UDim2", "Instance",
    "Enum", " RaycastParams", "BrickColor", "NumberRange", "NumberSequence",
    "ColorSequence", "Rect", "Region3", "TweenInfo", "wait", "delay", "spawn",
})

# ---------------------------------------------------------------------------
# Phase R2: Rojo Project Resolution (default.project.json)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RojoMapping:
    virtual_path: str  # e.g. "ReplicatedStorage.Packages" or "ServerScriptService.Services"
    physical_path: str  # repo-relative posix path e.g. "src/shared/Packages"


@dataclass
class RojoProject:
    name: str = "default"
    mappings: list[RojoMapping] = field(default_factory=list)
    is_valid: bool = False
    parse_error: str | None = None
    project_file: str = "default.project.json"

    @classmethod
    def load(cls, repository: Path | None) -> RojoProject:
        """Parse default.project.json strictly as JSON without executing anything."""
        if repository is None:
            return cls(is_valid=False)
        try:
            root = repository.resolve(strict=True)
        except OSError:
            return cls(is_valid=False)

        candidates = ["default.project.json"]
        try:
            for item in sorted(root.iterdir()):
                if item.is_file() and item.name.endswith(".project.json") and item.name != "default.project.json":
                    candidates.append(item.name)
        except OSError:
            pass

        project_path: Path | None = None
        rel_project_name = "default.project.json"
        for cand in candidates:
            try:
                resolved = safe_path(root, cand)
                if resolved.is_file():
                    project_path = resolved
                    rel_project_name = cand
                    break
            except SecurityError:
                continue

        if project_path is None:
            return cls(is_valid=False)

        try:
            raw_text = project_path.read_text(encoding="utf-8", errors="replace")
            data = json.loads(raw_text)
        except Exception as exc:
            return cls(
                is_valid=False,
                parse_error=f"Invalid JSON in {rel_project_name}: {exc}",
                project_file=rel_project_name,
            )

        if not isinstance(data, dict):
            return cls(
                is_valid=False,
                parse_error=f"Root of {rel_project_name} must be a JSON object",
                project_file=rel_project_name,
            )

        proj_name = str(data.get("name", "default"))
        tree = data.get("tree")
        if not isinstance(tree, dict):
            return cls(
                name=proj_name,
                is_valid=False,
                parse_error=f"Missing or invalid 'tree' object in {rel_project_name}",
                project_file=rel_project_name,
            )

        mappings: list[RojoMapping] = []

        def _walk_tree(node: dict[str, Any], vpath_parts: list[str]) -> None:
            raw_path = node.get("$path")
            if isinstance(raw_path, str) and raw_path.strip():
                try:
                    resolved_phys = safe_path(root, raw_path.strip())
                    rel_phys = resolved_phys.relative_to(root).as_posix()
                    vpath = ".".join(vpath_parts) if vpath_parts else "game"
                    mappings.append(RojoMapping(virtual_path=vpath, physical_path=rel_phys))
                except (SecurityError, ValueError, OSError):
                    # Block path traversal outside repository boundary
                    pass

            for key, child in sorted(node.items()):
                if key.startswith("$") or not isinstance(child, dict):
                    continue
                next_parts = [*vpath_parts, key]
                _walk_tree(child, next_parts)
                # Also create StarterPlayerScripts shortcut if under StarterPlayer.StarterPlayerScripts
                if next_parts == ["StarterPlayer", "StarterPlayerScripts"]:
                    child_path = child.get("$path")
                    if isinstance(child_path, str) and child_path.strip():
                        try:
                            resolved_sp = safe_path(root, child_path.strip())
                            rel_sp = resolved_sp.relative_to(root).as_posix()
                            mappings.append(
                                RojoMapping(
                                    virtual_path="StarterPlayerScripts",
                                    physical_path=rel_sp,
                                )
                            )
                        except (SecurityError, ValueError, OSError):
                            pass

        _walk_tree(tree, [])
        # Sort longest virtual_path first so most specific Rojo mapping wins
        mappings.sort(key=lambda m: (-len(m.virtual_path), m.virtual_path))
        return cls(
            name=proj_name,
            mappings=mappings,
            is_valid=True,
            project_file=rel_project_name,
        )

    def resolve_virtual_to_file(
        self,
        virtual_expr: str,
        known_files: set[str],
    ) -> tuple[str | None, str]:
        """Resolve a virtual Roblox DataModel path (e.g. 'ReplicatedStorage.Packages.Knit')
        to a physical repository file path in `known_files`.

        Returns (resolved_file_path, evidence_class).
        """
        clean = virtual_expr.strip()
        if clean.startswith("game."):
            clean = clean[len("game.") :]

        if not self.is_valid or not self.mappings:
            return None, RelationshipEvidenceClass.UNKNOWN.value

        for mapping in self.mappings:
            vp = mapping.virtual_path
            if clean == vp or clean.startswith(vp + "."):
                remainder = clean[len(vp) :].lstrip(".")
                rel_sub = remainder.replace(".", "/") if remainder else ""
                base_phys = (
                    posixpath.normpath(posixpath.join(mapping.physical_path, rel_sub))
                    if rel_sub
                    else posixpath.normpath(mapping.physical_path)
                )
                if base_phys.startswith(".."):
                    continue

                candidates = [
                    base_phys,
                    f"{base_phys}.luau",
                    f"{base_phys}.lua",
                    f"{base_phys}.server.luau",
                    f"{base_phys}.client.luau",
                    f"{base_phys}.server.lua",
                    f"{base_phys}.client.lua",
                    f"{base_phys}/init.luau",
                    f"{base_phys}/init.lua",
                    f"{base_phys}/init.server.luau",
                    f"{base_phys}/init.client.luau",
                    f"{base_phys}/init.server.lua",
                    f"{base_phys}/init.client.lua",
                    f"{base_phys}.ts",
                    f"{base_phys}.tsx",
                    f"{base_phys}/index.ts",
                    f"{base_phys}/index.tsx",
                ]
                for cand in candidates:
                    norm = cand.lstrip("./")
                    if norm in known_files:
                        return norm, RelationshipEvidenceClass.ROJO_VERIFIED.value

        return None, RelationshipEvidenceClass.UNKNOWN.value

    def file_to_virtual_path(self, file_path: str) -> str | None:
        """Map a physical repository file path back to its Rojo virtual DataModel path."""
        if not self.is_valid or not self.mappings:
            return None
        clean = file_path.replace("\\", "/").lstrip("./")
        for ext in (
            "/init.server.luau",
            "/init.client.luau",
            "/init.server.lua",
            "/init.client.lua",
            "/init.luau",
            "/init.lua",
            ".server.luau",
            ".client.luau",
            ".server.lua",
            ".client.lua",
            ".luau",
            ".lua",
            "/index.ts",
            "/index.tsx",
            ".ts",
            ".tsx",
        ):
            if clean.lower().endswith(ext):
                clean = clean[: -len(ext)]
                break

        for mapping in self.mappings:
            mp = mapping.physical_path.rstrip("/")
            if clean == mp:
                return mapping.virtual_path
            if clean.startswith(mp + "/"):
                rem = clean[len(mp) + 1 :].replace("/", ".")
                return f"{mapping.virtual_path}.{rem}" if rem else mapping.virtual_path
        return None


def resolve_luau_relative_script_path(
    script_expr: str,
    source_file: str,
    known_files: set[str],
    rojo: RojoProject | None = None,
) -> tuple[str | None, str]:
    """Deterministically resolve `script.Parent...` expressions within repository boundaries.

    In Roblox:
    - For a regular script `src/server/Services/PlayerService.luau`, `script` is the file itself,
      and `script.Parent` is the directory `src/server/Services`.
    - For an `init.luau` / `init.lua` file `src/shared/MyPkg/init.luau`, `script` is `src/shared/MyPkg`,
      and `script.Parent` is `src/shared`.
    """
    clean_expr = script_expr.strip()
    if not clean_expr.startswith("script"):
        return None, RelationshipEvidenceClass.UNKNOWN.value

    src_clean = source_file.replace("\\", "/").lstrip("./")
    is_init_script = any(
        src_clean.lower().endswith(suffix)
        for suffix in (
            "/init.luau",
            "/init.lua",
            "/init.server.luau",
            "/init.client.luau",
            "/init.server.lua",
            "/init.client.lua",
        )
    )
    current_dir = posixpath.dirname(src_clean) if is_init_script else src_clean

    parts = [p.strip() for p in clean_expr.split(".") if p.strip()]
    if not parts or parts[0] != "script":
        return None, RelationshipEvidenceClass.UNKNOWN.value

    for idx, part in enumerate(parts[1:], start=1):
        if part == "Parent":
            if not current_dir or current_dir in (".", "/"):
                # Escapes repository boundary!
                return None, RelationshipEvidenceClass.UNKNOWN.value
            # If current_dir is a file path (at step 1 for non-init script), dirname gives its folder
            if idx == 1 and not is_init_script:
                current_dir = posixpath.dirname(src_clean)
            else:
                parent_dir = posixpath.dirname(current_dir)
                if parent_dir == current_dir:
                    return None, RelationshipEvidenceClass.UNKNOWN.value
                current_dir = parent_dir
        else:
            # Descending into child module/folder
            if idx == 1 and not is_init_script:
                # `script.Child` on a non-init file: check sibling folder with same stem or current folder
                stem = src_clean
                for ext in (".server.luau", ".client.luau", ".server.lua", ".client.lua", ".luau", ".lua"):
                    if stem.lower().endswith(ext):
                        stem = stem[: -len(ext)]
                        break
                current_dir = posixpath.join(stem, part)
            else:
                current_dir = posixpath.join(current_dir, part) if current_dir else part

    norm_base = posixpath.normpath(current_dir) if current_dir else ""
    if norm_base.startswith("..") or norm_base.startswith("/"):
        return None, RelationshipEvidenceClass.UNKNOWN.value

    candidates = [
        norm_base,
        f"{norm_base}.luau",
        f"{norm_base}.lua",
        f"{norm_base}/init.luau",
        f"{norm_base}/init.lua",
    ]
    ev_cls = (
        RelationshipEvidenceClass.ROJO_VERIFIED.value
        if (rojo and rojo.is_valid)
        else RelationshipEvidenceClass.AST_VERIFIED.value
    )
    for cand in candidates:
        c_clean = cand.lstrip("./")
        if c_clean in known_files:
            return c_clean, ev_cls

    return None, RelationshipEvidenceClass.UNKNOWN.value


# ---------------------------------------------------------------------------
# Phase R1: First-Class Luau Parser (.lua, .luau)
# ---------------------------------------------------------------------------

_LUA_COMMENT_LINE_RE = re.compile(r"--(?!\[\[).*$")
_LUA_LOCAL_FUNC_RE = re.compile(
    r"^\s*local\s+function\s+([A-Za-z_]\w*)\s*(?:<[^>]*>)?\s*\(([^)]*)\)\s*(?::\s*(.+))?$"
)
_LUA_GLOBAL_FUNC_RE = re.compile(
    r"^\s*function\s+([A-Za-z_]\w*)\s*(?:<[^>]*>)?\s*\(([^)]*)\)\s*(?::\s*(.+))?$"
)
_LUA_METHOD_DECL_RE = re.compile(
    r"^\s*function\s+([A-Za-z_][\w.]*)([.:])([A-Za-z_]\w*)\s*(?:<[^>]*>)?\s*\(([^)]*)\)\s*(?::\s*(.+))?$"
)
_LUA_ASSIGN_FUNC_RE = re.compile(
    r"^\s*([A-Za-z_][\w.]*)\s*=\s*function\s*(?:<[^>]*>)?\s*\(([^)]*)\)\s*(?::\s*(.+))?$"
)
_LUA_LOCAL_ASSIGN_FUNC_RE = re.compile(
    r"^\s*local\s+([A-Za-z_]\w*)\s*(?::\s*[^=]+)?=\s*function\s*(?:<[^>]*>)?\s*\(([^)]*)\)\s*(?::\s*(.+))?$"
)
_LUA_TYPE_DECL_RE = re.compile(
    r"^\s*(export\s+)?type\s+([A-Za-z_]\w*)(?:<[^>]*>)?\s*=\s*(.+)$"
)
_LUA_TABLE_DECL_RE = re.compile(
    r"^\s*(?:local\s+)?([A-Za-z_]\w*)\s*(?::\s*([^=]+))?=\s*\{\s*\}"
)
_LUA_TYPED_VAR_RE = re.compile(
    r"^\s*local\s+([A-Za-z_]\w*)\s*:\s*([^=]+?)(?:\s*=\s*(.+))?$"
)
_LUA_RETURN_FREEZE_RE = re.compile(
    r"^\s*return\s+table\.freeze\(\s*([A-Za-z_]\w*)\s*\)"
)
_LUA_RETURN_IDENT_RE = re.compile(
    r"^\s*return\s+([A-Za-z_][\w.]*)\s*$"
)
_LUA_REQUIRE_ASSIGN_RE = re.compile(
    r"^\s*(?:local\s+)?([A-Za-z_]\w*)\s*(?::\s*[^=]+)?=\s*require\(\s*([^)]+?)\s*\)"
)
_LUA_BARE_REQUIRE_RE = re.compile(
    r"\brequire\(\s*([^)]+?)\s*\)"
)
_LUA_GET_SERVICE_RE = re.compile(
    r"^\s*local\s+([A-Za-z_]\w*)\s*(?::\s*[^=]+)?=\s*game:GetService\(\s*['\"]([A-Za-z_]\w*)['\"]\s*\)"
)
_LUA_ALIAS_CHAIN_RE = re.compile(
    r"^\s*local\s+([A-Za-z_]\w*)\s*(?::\s*[^=]+)?=\s*([A-Za-z_][\w.:()\"'\s]*)$"
)
_LUA_KNIT_CREATE_SERVICE_RE = re.compile(
    r"(?:local\s+([A-Za-z_]\w*)\s*=\s*)?Knit\.CreateService\(\s*\{([^}]*)\}"
)
_LUA_KNIT_CREATE_CONTROLLER_RE = re.compile(
    r"(?:local\s+([A-Za-z_]\w*)\s*=\s*)?Knit\.CreateController\(\s*\{([^}]*)\}"
)
_LUA_KNIT_GET_SERVICE_RE = re.compile(
    r"(?:local\s+([A-Za-z_]\w*)\s*=\s*)?Knit\.GetService\(\s*([^)]+?)\s*\)"
)
_LUA_KNIT_GET_CONTROLLER_RE = re.compile(
    r"(?:local\s+([A-Za-z_]\w*)\s*=\s*)?Knit\.GetController\(\s*([^)]+?)\s*\)"
)
_LUA_REMOTE_FIRE_RE = re.compile(
    r"([A-Za-z_][\w.:()\"']*?):(FireServer|InvokeServer|FireClient|FireAllClients)\s*\(([^)]*)\)"
)
_LUA_REMOTE_CONNECT_RE = re.compile(
    r"([A-Za-z_][\w.:()\"']*?)\.(OnServerEvent|OnClientEvent):Connect\s*\(\s*([^)]+?)\s*\)"
)
_LUA_REMOTE_INVOKE_ASSIGN_RE = re.compile(
    r"^\s*([A-Za-z_][\w.:()\"']*?)\.(OnServerInvoke|OnClientInvoke)\s*=\s*(.+)$"
)
_LUA_GET_DATASTORE_RE = re.compile(
    r"^\s*(?:local\s+)?([A-Za-z_][\w.]*)\s*=\s*([A-Za-z_][\w.:()\"']*?):(GetDataStore|GetOrderedDataStore)\s*\(\s*([^)]+?)\s*\)"
)
_LUA_PROFILESERVICE_STORE_RE = re.compile(
    r"^\s*(?:local\s+)?([A-Za-z_][\w.]*)\s*=\s*([A-Za-z_]\w*)\.GetProfileStore\s*\(\s*([^,)]+)"
)
_LUA_DATASTORE_OP_RE = re.compile(
    r"\b([A-Za-z_][\w.]*):(GetAsync|SetAsync|UpdateAsync|IncrementAsync|RemoveAsync|LoadProfileAsync)\s*\("
)
_LUA_CALL_SITE_RE = re.compile(
    r"\b(?:([A-Za-z_][\w.]*)([.:]))?([A-Za-z_]\w*)\s*\("
)


def _strip_luau_comment(line: str) -> str:
    """Strip single-line `--` comments outside string literals."""
    in_single = False
    in_double = False
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "-" and i + 1 < n and line[i + 1] == "-" and not in_single and not in_double:
            return line[:i]
        i += 1
    return line


def _normalize_roblox_chain(expr: str, local_aliases: dict[str, str]) -> tuple[str, bool]:
    """Normalize a Roblox instance access chain (including WaitForChild / FindFirstChild and local aliases).

    Returns (normalized_dotted_chain, is_dynamic).
    Example:
        `game:GetService("ReplicatedStorage"):WaitForChild("Remotes"):WaitForChild("Inventory")`
        -> (`ReplicatedStorage.Remotes.Inventory`, False)
    """
    raw = expr.strip()
    if not raw:
        return "", True

    # Replace game:GetService("X") with X
    norm = re.sub(
        r"""game:GetService\(\s*['"]([A-Za-z_]\w*)['"]\s*\)""",
        r"\1",
        raw,
    )

    # Check if WaitForChild or FindFirstChild has a non-literal argument
    for m_wait in re.finditer(r""":(?:WaitForChild|FindFirstChild)\(\s*([^)]+?)\s*\)""", norm):
        arg = m_wait.group(1).split(",")[0].strip()
        if not ((arg.startswith('"') and arg.endswith('"')) or (arg.startswith("'") and arg.endswith("'"))):
            return norm, True

    # Replace :WaitForChild("X") and :FindFirstChild("X") with .X
    norm = re.sub(
        r""":(?:WaitForChild|FindFirstChild)\(\s*['"]([^'"]+)['"](?:\s*,[^)]*)?\s*\)""",
        r".\1",
        norm,
    )

    # Check for bracket indexing: e.g. Remotes["Inventory"] vs Remotes[dynamicVar]
    for m_idx in re.finditer(r"""\[\s*([^]]+?)\s*\]""", norm):
        idx_arg = m_idx.group(1).strip()
        if (idx_arg.startswith('"') and idx_arg.endswith('"')) or (idx_arg.startswith("'") and idx_arg.endswith("'")):
            lit = idx_arg[1:-1]
            norm = norm.replace(m_idx.group(0), f".{lit}")
        else:
            return norm, True

    # If any function call parens remain, it's dynamic unless it was resolved
    if "(" in norm or ")" in norm or ".." in norm:
        return norm, True

    parts = [p.strip() for p in norm.split(".") if p.strip()]
    if not parts:
        return "", True

    # Expand leading alias iteratively (bounded to 8 steps to prevent cycles)
    for _ in range(8):
        head = parts[0]
        if head in local_aliases:
            alias_target = local_aliases[head]
            if alias_target.startswith("<DYNAMIC"):
                return f"{alias_target}.{'.'.join(parts[1:])}", True
            alias_parts = [p for p in alias_target.split(".") if p]
            parts = [*alias_parts, *parts[1:]]
        else:
            break

    return ".".join(parts), False


def _estimate_luau_block_end(lines: list[str], start_idx: int) -> int:
    """Estimate the closing `end` line of a Luau function/block starting at `start_idx`."""
    depth = 0
    opened = False
    open_pattern = re.compile(r"\b(?:function|if|for|while|repeat|do)\b")
    close_pattern = re.compile(r"\b(?:end|until)\b")

    for i in range(start_idx, len(lines)):
        clean = _strip_luau_comment(lines[i]).strip()
        if not clean:
            continue
        opens = len(open_pattern.findall(clean))
        # `elseif` does not open a new `end` block
        elseif_count = len(re.findall(r"\belseif\b", clean))
        # `for ... do` or `while ... do` has both `for`/`while` and `do` on the same line for a single `end`
        loop_do_count = len(re.findall(r"\b(?:for|while)\b.*\bdo\b", clean))
        effective_opens = max(0, opens - elseif_count - loop_do_count)
        closes = len(close_pattern.findall(clean))
        if effective_opens > 0:
            opened = True
        depth += effective_opens - closes
        if opened and depth <= 0:
            return i + 1
    return len(lines)


def _count_luau_params(params_str: str, is_colon_method: bool = False) -> int:
    clean = params_str.strip()
    if not clean:
        return 1 if is_colon_method else 0
    # Split on top-level commas (ignoring generic `<...>` or function types `(...) -> ...`)
    depth = 0
    count = 1
    for ch in clean:
        if ch in "(<{":
            depth += 1
        elif ch in ")>}":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            count += 1
    return count + (1 if is_colon_method else 0)


def parse_luau(content: str, file_path: str) -> ParseResult:
    """Parse a `.lua` or `.luau` source file in a single scoped pass and return a `ParseResult`."""
    from codegraph.indexing.parser import ParseResult, _normalized_body_hash

    source_hash = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
    module = normalize_module(file_path, "luau")
    lines = content.splitlines()

    symbols: list[Symbol] = []
    imports: list[ImportRef] = []
    calls: list[CallRef] = []
    bindings: list[BindingRef] = []
    exports: list[str] = []
    seen_canonical: set[str] = set()

    # Track local tables/classes and aliases for static resolution
    known_tables: dict[str, int] = {}  # table_name -> start_line
    local_aliases: dict[str, str] = {}  # var_name -> normalized chain (e.g. ReplicatedStorage.Packages)
    active_func: tuple[str, str, int] | None = None  # (qname, canonical_id, end_line)
    in_multiline_comment = False

    for idx, raw_line in enumerate(lines):
        lineno = idx + 1

        # Handle multiline comments `--[[ ... ]]`
        stripped_raw = raw_line.strip()
        if in_multiline_comment:
            if "]]" in stripped_raw:
                in_multiline_comment = False
            continue
        if stripped_raw.startswith("--[["):
            if "]]" not in stripped_raw[4:]:
                in_multiline_comment = True
            continue

        line = _strip_luau_comment(raw_line)
        stripped = line.strip()
        if not stripped:
            continue

        if active_func and lineno > active_func[2]:
            active_func = None

        current_scope = active_func[0] if active_func else ""
        caller_canon = active_func[1] if active_func else module

        # 1. Type declarations: `type State = ...` and `export type Config = ...`
        m_type = _LUA_TYPE_DECL_RE.match(line)
        if m_type:
            is_exported = bool(m_type.group(1))
            type_name = m_type.group(2)
            type_rhs = m_type.group(3).strip()
            end_ln = _estimate_block_end_braces(lines, idx) if "{" in type_rhs and "}" not in type_rhs else lineno
            canon_id = build_canonical_id(module, "", type_name)
            if canon_id not in seen_canonical:
                seen_canonical.add(canon_id)
                symbols.append(
                    Symbol(
                        id=canon_id,
                        canonical_id=canon_id,
                        name=type_name,
                        qualified_name=type_name,
                        kind="type",
                        language="luau",
                        module=module,
                        path=file_path,
                        file_path=file_path,
                        scope="",
                        signature=f"{'export ' if is_exported else ''}type {type_name} = {type_rhs}",
                        start_line=lineno,
                        end_line=end_ln,
                        content_hash=_normalized_body_hash(lines, lineno, end_ln),
                        visibility="public" if is_exported else "private",
                    )
                )
            if is_exported and type_name not in exports:
                exports.append(type_name)
            continue

        # 2. Knit Service / Controller creation: `Knit.CreateService({ Name = "InventoryService" })`
        m_knit_svc = _LUA_KNIT_CREATE_SERVICE_RE.search(line)
        if m_knit_svc or "Knit.CreateService" in line:
            var_nm = m_knit_svc.group(1) if m_knit_svc else None
            if not var_nm:
                m_var = re.match(r"^\s*(?:local\s+)?([A-Za-z_]\w*)\s*=\s*Knit\.CreateService", line)
                var_nm = m_var.group(1) if m_var else None
            block_end = _estimate_block_end_braces(lines, idx)
            block_text = "\n".join(lines[idx:block_end])
            m_name = re.search(r"""Name\s*=\s*(['"][^'"]+['"]|[A-Za-z_][\w.]*)""", block_text)
            svc_raw_name = m_name.group(1).strip() if m_name else ""
            is_static_name = (
                (svc_raw_name.startswith('"') and svc_raw_name.endswith('"'))
                or (svc_raw_name.startswith("'") and svc_raw_name.endswith("'"))
            )
            svc_name = svc_raw_name[1:-1] if is_static_name else (var_nm or "<DYNAMIC>")
            table_ident = var_nm or (svc_name if is_static_name else "KnitService")
            known_tables[table_ident] = lineno
            canon_id = build_canonical_id(module, "", table_ident)
            if canon_id not in seen_canonical:
                seen_canonical.add(canon_id)
                symbols.append(
                    Symbol(
                        id=canon_id,
                        canonical_id=canon_id,
                        name=table_ident,
                        qualified_name=table_ident,
                        kind="class",
                        language="luau",
                        module=module,
                        path=file_path,
                        file_path=file_path,
                        scope="",
                        signature=f"Knit.CreateService({svc_raw_name or table_ident})",
                        start_line=lineno,
                        end_line=block_end,
                        decorators=["Knit.CreateService"],
                        content_hash=_normalized_body_hash(lines, lineno, block_end),
                    )
                )
            bindings.append(
                BindingRef(
                    target_name=svc_name if is_static_name else "<DYNAMIC>",
                    file_path=file_path,
                    line=lineno,
                    scope=table_ident,
                    expr_kind="ROBLOX_KNIT_CREATE_SERVICE",
                    source_expr=canon_id,
                    base_expr="Knit",
                    attr_name="CreateService",
                    is_conditional=not is_static_name,
                )
            )

        m_knit_ctrl = _LUA_KNIT_CREATE_CONTROLLER_RE.search(line)
        if m_knit_ctrl or "Knit.CreateController" in line:
            var_nm = m_knit_ctrl.group(1) if m_knit_ctrl else None
            if not var_nm:
                m_var = re.match(r"^\s*(?:local\s+)?([A-Za-z_]\w*)\s*=\s*Knit\.CreateController", line)
                var_nm = m_var.group(1) if m_var else None
            block_end = _estimate_block_end_braces(lines, idx)
            block_text = "\n".join(lines[idx:block_end])
            m_name = re.search(r"""Name\s*=\s*(['"][^'"]+['"]|[A-Za-z_][\w.]*)""", block_text)
            ctrl_raw_name = m_name.group(1).strip() if m_name else ""
            is_static_name = (
                (ctrl_raw_name.startswith('"') and ctrl_raw_name.endswith('"'))
                or (ctrl_raw_name.startswith("'") and ctrl_raw_name.endswith("'"))
            )
            ctrl_name = ctrl_raw_name[1:-1] if is_static_name else (var_nm or "<DYNAMIC>")
            table_ident = var_nm or (ctrl_name if is_static_name else "KnitController")
            known_tables[table_ident] = lineno
            canon_id = build_canonical_id(module, "", table_ident)
            if canon_id not in seen_canonical:
                seen_canonical.add(canon_id)
                symbols.append(
                    Symbol(
                        id=canon_id,
                        canonical_id=canon_id,
                        name=table_ident,
                        qualified_name=table_ident,
                        kind="class",
                        language="luau",
                        module=module,
                        path=file_path,
                        file_path=file_path,
                        scope="",
                        signature=f"Knit.CreateController({ctrl_raw_name or table_ident})",
                        start_line=lineno,
                        end_line=block_end,
                        decorators=["Knit.CreateController"],
                        content_hash=_normalized_body_hash(lines, lineno, block_end),
                    )
                )

        # 3. Knit.GetService(...) / Knit.GetController(...)
        m_get_svc = _LUA_KNIT_GET_SERVICE_RE.search(line)
        if m_get_svc:
            local_var = m_get_svc.group(1) or ""
            arg_raw = m_get_svc.group(2).strip()
            is_static = (
                (arg_raw.startswith('"') and arg_raw.endswith('"'))
                or (arg_raw.startswith("'") and arg_raw.endswith("'"))
            )
            svc_target = arg_raw[1:-1] if is_static else "<DYNAMIC>"
            if local_var and is_static:
                local_aliases[local_var] = f"KnitService:{svc_target}"
            bindings.append(
                BindingRef(
                    target_name=svc_target,
                    file_path=file_path,
                    line=lineno,
                    scope=current_scope,
                    expr_kind="ROBLOX_KNIT_GET_SERVICE",
                    source_expr=arg_raw,
                    base_expr=local_var or caller_canon,
                    attr_name="GetService",
                    is_conditional=not is_static,
                )
            )

        # 4. Module / class table declaration: `local Service = {}` or `Service = {}`
        m_tbl = _LUA_TABLE_DECL_RE.match(line)
        if m_tbl and not active_func:
            tbl_name = m_tbl.group(1)
            tbl_type = (m_tbl.group(2) or "").strip() or None
            if tbl_name not in _LUAU_KEYWORDS_AND_BUILTINS:
                known_tables[tbl_name] = lineno
                canon_id = build_canonical_id(module, "", tbl_name)
                if canon_id not in seen_canonical:
                    seen_canonical.add(canon_id)
                    symbols.append(
                        Symbol(
                            id=canon_id,
                            canonical_id=canon_id,
                            name=tbl_name,
                            qualified_name=tbl_name,
                            kind="class",
                            language="luau",
                            module=module,
                            path=file_path,
                            file_path=file_path,
                            scope="",
                            signature=f"table {tbl_name}" + (f": {tbl_type}" if tbl_type else ""),
                            start_line=lineno,
                            end_line=len(lines),
                            return_type=tbl_type,
                            content_hash=_normalized_body_hash(lines, lineno, min(len(lines), lineno + 25)),
                        )
                    )

        # 5. Method declaration: `function Service:Init(...)` or `function Service.Method(...)`
        m_meth = _LUA_METHOD_DECL_RE.match(line)
        if m_meth:
            tbl_name = m_meth.group(1)
            sep = m_meth.group(2)
            meth_name = m_meth.group(3)
            params_str = m_meth.group(4)
            ret_type = (m_meth.group(5) or "").strip() or None
            end_ln = _estimate_luau_block_end(lines, idx)
            qname = f"{tbl_name}.{meth_name}"
            canon_id = build_canonical_id(module, tbl_name, meth_name)
            parent_id: str | None = build_canonical_id(module, "", tbl_name)
            param_cnt = _count_luau_params(params_str, is_colon_method=(sep == ":"))
            sig = f"function {tbl_name}{sep}{meth_name}({params_str})" + (f": {ret_type}" if ret_type else "")
            if canon_id not in seen_canonical:
                seen_canonical.add(canon_id)
                symbols.append(
                    Symbol(
                        id=canon_id,
                        canonical_id=canon_id,
                        name=meth_name,
                        qualified_name=qname,
                        kind="method",
                        language="luau",
                        module=module,
                        path=file_path,
                        file_path=file_path,
                        scope=tbl_name,
                        signature=sig,
                        start_line=lineno,
                        end_line=end_ln,
                        content_hash=_normalized_body_hash(lines, lineno, end_ln),
                        parent_symbol_id=parent_id,
                        return_type=ret_type,
                        parameter_count=param_cnt,
                    )
                )
            active_func = (qname, canon_id, end_ln)
            continue

        # 6. Assignment method / function: `Service.Method = function(...)`
        m_assign_fn = _LUA_ASSIGN_FUNC_RE.match(line)
        if m_assign_fn and not m_assign_fn.group(1).endswith((".OnServerInvoke", ".OnClientInvoke")):
            lhs = m_assign_fn.group(1)
            params_str = m_assign_fn.group(2)
            ret_type = (m_assign_fn.group(3) or "").strip() or None
            end_ln = _estimate_luau_block_end(lines, idx)
            if "." in lhs:
                tbl_name, meth_name = lhs.rsplit(".", 1)
                qname = f"{tbl_name}.{meth_name}"
                canon_id = build_canonical_id(module, tbl_name, meth_name)
                parent_id = build_canonical_id(module, "", tbl_name)
                kind = "method"
                scope_str = tbl_name
            else:
                meth_name = lhs
                qname = lhs
                canon_id = build_canonical_id(module, "", lhs)
                parent_id = None
                kind = "function"
                scope_str = ""
            param_cnt = _count_luau_params(params_str, is_colon_method=False)
            sig = f"{lhs} = function({params_str})" + (f": {ret_type}" if ret_type else "")
            if canon_id not in seen_canonical:
                seen_canonical.add(canon_id)
                symbols.append(
                    Symbol(
                        id=canon_id,
                        canonical_id=canon_id,
                        name=meth_name,
                        qualified_name=qname,
                        kind=kind,
                        language="luau",
                        module=module,
                        path=file_path,
                        file_path=file_path,
                        scope=scope_str,
                        signature=sig,
                        start_line=lineno,
                        end_line=end_ln,
                        content_hash=_normalized_body_hash(lines, lineno, end_ln),
                        parent_symbol_id=parent_id,
                        return_type=ret_type,
                        parameter_count=param_cnt,
                    )
                )
            active_func = (qname, canon_id, end_ln)
            continue

        # 7. Local function declaration: `local function foo(x: number): string` or `local foo = function(...)`
        m_loc_fn = _LUA_LOCAL_FUNC_RE.match(line) or _LUA_LOCAL_ASSIGN_FUNC_RE.match(line)
        if m_loc_fn:
            fn_name = m_loc_fn.group(1)
            params_str = m_loc_fn.group(2)
            ret_type = (m_loc_fn.group(3) or "").strip() or None
            end_ln = _estimate_luau_block_end(lines, idx)
            canon_id = build_canonical_id(module, "", fn_name)
            param_cnt = _count_luau_params(params_str, is_colon_method=False)
            sig = f"local function {fn_name}({params_str})" + (f": {ret_type}" if ret_type else "")
            if canon_id not in seen_canonical:
                seen_canonical.add(canon_id)
                symbols.append(
                    Symbol(
                        id=canon_id,
                        canonical_id=canon_id,
                        name=fn_name,
                        qualified_name=fn_name,
                        kind="function",
                        language="luau",
                        module=module,
                        path=file_path,
                        file_path=file_path,
                        scope="",
                        signature=sig,
                        start_line=lineno,
                        end_line=end_ln,
                        content_hash=_normalized_body_hash(lines, lineno, end_ln),
                        visibility="private",
                        return_type=ret_type,
                        parameter_count=param_cnt,
                    )
                )
            active_func = (fn_name, canon_id, end_ln)
            continue

        # 8. Global function declaration: `function globalHelper(...)`
        m_glob_fn = _LUA_GLOBAL_FUNC_RE.match(line)
        if m_glob_fn:
            fn_name = m_glob_fn.group(1)
            params_str = m_glob_fn.group(2)
            ret_type = (m_glob_fn.group(3) or "").strip() or None
            end_ln = _estimate_luau_block_end(lines, idx)
            canon_id = build_canonical_id(module, "", fn_name)
            param_cnt = _count_luau_params(params_str, is_colon_method=False)
            sig = f"function {fn_name}({params_str})" + (f": {ret_type}" if ret_type else "")
            if canon_id not in seen_canonical:
                seen_canonical.add(canon_id)
                symbols.append(
                    Symbol(
                        id=canon_id,
                        canonical_id=canon_id,
                        name=fn_name,
                        qualified_name=fn_name,
                        kind="function",
                        language="luau",
                        module=module,
                        path=file_path,
                        file_path=file_path,
                        scope="",
                        signature=sig,
                        start_line=lineno,
                        end_line=end_ln,
                        content_hash=_normalized_body_hash(lines, lineno, end_ln),
                        visibility="public",
                        return_type=ret_type,
                        parameter_count=param_cnt,
                    )
                )
            active_func = (fn_name, canon_id, end_ln)
            continue

        # 9. `game:GetService("...")` binding
        m_svc = _LUA_GET_SERVICE_RE.match(line)
        if m_svc:
            var_name = m_svc.group(1)
            service_name = m_svc.group(2)
            local_aliases[var_name] = service_name
            bindings.append(
                BindingRef(
                    target_name=var_name,
                    file_path=file_path,
                    line=lineno,
                    scope=current_scope,
                    expr_kind="ROBLOX_SERVICE_BINDING",
                    source_expr=service_name,
                    base_expr="game",
                    attr_name="GetService",
                )
            )
            continue

        # 10. DataStore / ProfileService persistence configuration
        m_ds = _LUA_GET_DATASTORE_RE.match(line)
        if m_ds:
            store_var = m_ds.group(1)
            svc_expr = m_ds.group(2).strip()
            ds_method = m_ds.group(3)
            arg_raw = m_ds.group(4).split(",")[0].strip()
            norm_svc, _ = _normalize_roblox_chain(svc_expr, local_aliases)
            if norm_svc == "DataStoreService" or "DataStoreService" in svc_expr:
                is_static = (
                    (arg_raw.startswith('"') and arg_raw.endswith('"'))
                    or (arg_raw.startswith("'") and arg_raw.endswith("'"))
                )
                store_name = arg_raw[1:-1] if is_static else "<DYNAMIC>"
                local_aliases[store_var] = f"persistence.roblox.datastore.{store_name}"
                bindings.append(
                    BindingRef(
                        target_name=f"persistence.roblox.datastore.{store_name}" if is_static else "persistence.roblox.datastore.<DYNAMIC>",
                        file_path=file_path,
                        line=lineno,
                        scope=current_scope,
                        expr_kind="ROBLOX_CONFIGURE_PERSISTENCE",
                        source_expr=caller_canon,
                        base_expr=store_var,
                        attr_name=ds_method,
                        is_conditional=not is_static,
                    )
                )
            continue

        m_ps = _LUA_PROFILESERVICE_STORE_RE.match(line)
        if m_ps:
            store_var = m_ps.group(1)
            ps_recv = m_ps.group(2)
            arg_raw = m_ps.group(3).strip()
            if ps_recv == "ProfileService" or local_aliases.get(ps_recv, "").endswith("ProfileService"):
                is_static = (
                    (arg_raw.startswith('"') and arg_raw.endswith('"'))
                    or (arg_raw.startswith("'") and arg_raw.endswith("'"))
                )
                store_name = arg_raw[1:-1] if is_static else "<DYNAMIC>"
                local_aliases[store_var] = f"persistence.roblox.datastore.{store_name}"
                bindings.append(
                    BindingRef(
                        target_name=f"persistence.roblox.datastore.{store_name}" if is_static else "persistence.roblox.datastore.<DYNAMIC>",
                        file_path=file_path,
                        line=lineno,
                        scope=current_scope,
                        expr_kind="ROBLOX_CONFIGURE_PERSISTENCE",
                        source_expr=caller_canon,
                        base_expr=store_var,
                        attr_name="GetProfileStore",
                        is_conditional=not is_static,
                    )
                )
            continue

        # 11. `require(...)` statements
        m_req = _LUA_REQUIRE_ASSIGN_RE.match(line)
        if m_req:
            local_var = m_req.group(1)
            req_expr = m_req.group(2).strip()
            norm_req, is_dyn = _normalize_roblox_chain(req_expr, local_aliases)
            # Also check if string literal require("...")
            if (req_expr.startswith('"') and req_expr.endswith('"')) or (
                req_expr.startswith("'") and req_expr.endswith("'")
            ):
                norm_req = req_expr[1:-1]
                is_dyn = False
            local_aliases[local_var] = norm_req
            imports.append(
                ImportRef(
                    module=norm_req if not is_dyn else req_expr,
                    imported_module=norm_req if not is_dyn else req_expr,
                    name=None,
                    alias=local_var,
                    local_name=local_var,
                    import_type="module",
                    line=lineno,
                    source_file=file_path,
                    source_module=module,
                )
            )
            bindings.append(
                BindingRef(
                    target_name=local_var,
                    file_path=file_path,
                    line=lineno,
                    scope=current_scope,
                    expr_kind="ROBLOX_REQUIRE",
                    source_expr=norm_req if not is_dyn else "<DYNAMIC>",
                    base_expr=req_expr,
                    attr_name=caller_canon,
                    is_conditional=is_dyn,
                )
            )
            continue

        # Bare `require(...)` (e.g., `return require(...)` or inline `require(...)`)
        for m_bare_req in _LUA_BARE_REQUIRE_RE.finditer(line):
            req_expr = m_bare_req.group(1).strip()
            norm_req, is_dyn = _normalize_roblox_chain(req_expr, local_aliases)
            if (req_expr.startswith('"') and req_expr.endswith('"')) or (
                req_expr.startswith("'") and req_expr.endswith("'")
            ):
                norm_req = req_expr[1:-1]
                is_dyn = False
            imports.append(
                ImportRef(
                    module=norm_req if not is_dyn else req_expr,
                    imported_module=norm_req if not is_dyn else req_expr,
                    name=None,
                    alias=None,
                    local_name=norm_req.split(".")[-1] if norm_req else "require",
                    import_type="module",
                    line=lineno,
                    source_file=file_path,
                    source_module=module,
                )
            )
            bindings.append(
                BindingRef(
                    target_name="require",
                    file_path=file_path,
                    line=lineno,
                    scope=current_scope,
                    expr_kind="ROBLOX_REQUIRE",
                    source_expr=norm_req if not is_dyn else "<DYNAMIC>",
                    base_expr=req_expr,
                    attr_name=caller_canon,
                    is_conditional=is_dyn,
                )
            )

        # 12. Return statements (`return table.freeze(Module)` / `return Service`)
        m_freeze = _LUA_RETURN_FREEZE_RE.match(line)
        if m_freeze:
            exp_ident = m_freeze.group(1)
            if exp_ident not in exports:
                exports.append(exp_ident)
            bindings.append(
                BindingRef(
                    target_name=exp_ident,
                    file_path=file_path,
                    line=lineno,
                    scope=current_scope,
                    expr_kind="ROBLOX_MODULE_EXPORT",
                    source_expr="table.freeze",
                    base_expr=module,
                )
            )
            continue

        m_ret = _LUA_RETURN_IDENT_RE.match(line)
        if m_ret and not active_func:
            exp_ident = m_ret.group(1)
            if exp_ident not in _LUAU_KEYWORDS_AND_BUILTINS and exp_ident not in exports:
                exports.append(exp_ident)
                bindings.append(
                    BindingRef(
                        target_name=exp_ident,
                        file_path=file_path,
                        line=lineno,
                        scope="",
                        expr_kind="ROBLOX_MODULE_EXPORT",
                        source_expr=exp_ident,
                        base_expr=module,
                    )
                )
            continue

        # 13. Remote networking: FireServer / InvokeServer / OnServerEvent:Connect / OnServerInvoke
        m_rem_fire = _LUA_REMOTE_FIRE_RE.search(line)
        if m_rem_fire:
            rem_expr = m_rem_fire.group(1).strip()
            fire_method = m_rem_fire.group(2)
            norm_rem, is_dyn = _normalize_roblox_chain(rem_expr, local_aliases)
            bindings.append(
                BindingRef(
                    target_name=norm_rem if not is_dyn else "<DYNAMIC>",
                    file_path=file_path,
                    line=lineno,
                    scope=current_scope,
                    expr_kind="ROBLOX_REMOTE_DISPATCH",
                    source_expr=caller_canon,
                    base_expr=rem_expr,
                    attr_name=fire_method,
                    is_conditional=is_dyn,
                )
            )

        m_rem_conn = _LUA_REMOTE_CONNECT_RE.search(line)
        if m_rem_conn:
            rem_expr = m_rem_conn.group(1).strip()
            event_prop = m_rem_conn.group(2)
            handler_arg = m_rem_conn.group(3).strip()
            norm_rem, is_dyn = _normalize_roblox_chain(rem_expr, local_aliases)
            handler_sym = caller_canon
            if re.match(r"^[A-Za-z_][\w.]*$", handler_arg) and not handler_arg.startswith("function"):
                handler_sym = f"{module}.{handler_arg}"
            elif handler_arg.startswith("function") and active_func is None:
                end_ln = _estimate_luau_block_end(lines, idx)
                active_func = (current_scope or "OnServerEvent", caller_canon, end_ln)
            bindings.append(
                BindingRef(
                    target_name=norm_rem if not is_dyn else "<DYNAMIC>",
                    file_path=file_path,
                    line=lineno,
                    scope=current_scope,
                    expr_kind="ROBLOX_REMOTE_HANDLER",
                    source_expr=handler_sym,
                    base_expr=rem_expr,
                    attr_name=event_prop,
                    is_conditional=is_dyn,
                )
            )

        m_rem_inv = _LUA_REMOTE_INVOKE_ASSIGN_RE.match(line)
        if m_rem_inv:
            rem_expr = m_rem_inv.group(1).strip()
            inv_prop = m_rem_inv.group(2)
            rhs_expr = m_rem_inv.group(3).strip()
            norm_rem, is_dyn = _normalize_roblox_chain(rem_expr, local_aliases)
            handler_sym = caller_canon
            if re.match(r"^[A-Za-z_][\w.]*$", rhs_expr) and not rhs_expr.startswith("function"):
                handler_sym = f"{module}.{rhs_expr}"
            elif rhs_expr.startswith("function") and active_func is None:
                end_ln = _estimate_luau_block_end(lines, idx)
                active_func = (current_scope or "OnServerInvoke", caller_canon, end_ln)
            bindings.append(
                BindingRef(
                    target_name=norm_rem if not is_dyn else "<DYNAMIC>",
                    file_path=file_path,
                    line=lineno,
                    scope=current_scope,
                    expr_kind="ROBLOX_REMOTE_HANDLER",
                    source_expr=handler_sym,
                    base_expr=rem_expr,
                    attr_name=inv_prop,
                    is_conditional=is_dyn,
                )
            )

        # 14. DataStore / ProfileService read & write operations
        for m_ds_op in _LUA_DATASTORE_OP_RE.finditer(line):
            recv_var = m_ds_op.group(1)
            op_name = m_ds_op.group(2)
            mapped_store = local_aliases.get(recv_var, "")
            if mapped_store.startswith("persistence.roblox.datastore."):
                op_kind = (
                    "ROBLOX_READ_PERSISTENCE"
                    if op_name in ("GetAsync", "LoadProfileAsync")
                    else "ROBLOX_WRITE_PERSISTENCE"
                )
                is_dyn_store = mapped_store.endswith("<DYNAMIC>")
                bindings.append(
                    BindingRef(
                        target_name=mapped_store,
                        file_path=file_path,
                        line=lineno,
                        scope=current_scope,
                        expr_kind=op_kind,
                        source_expr=caller_canon,
                        base_expr=recv_var,
                        attr_name=op_name,
                        is_conditional=is_dyn_store,
                    )
                )

        # 15. Local alias chains: `local Packages = ReplicatedStorage.Packages`
        # or `local Remotes = ReplicatedStorage:WaitForChild("Remotes")`
        # or `local x: string = "hello"`
        m_typed = _LUA_TYPED_VAR_RE.match(line)
        if m_typed and not active_func:
            v_name = m_typed.group(1)
            v_type = m_typed.group(2).strip()
            canon_id = build_canonical_id(module, "", v_name)
            if canon_id not in seen_canonical and v_name not in known_tables:
                seen_canonical.add(canon_id)
                symbols.append(
                    Symbol(
                        id=canon_id,
                        canonical_id=canon_id,
                        name=v_name,
                        qualified_name=v_name,
                        kind="variable",
                        language="luau",
                        module=module,
                        path=file_path,
                        file_path=file_path,
                        scope="",
                        signature=f"local {v_name}: {v_type}",
                        start_line=lineno,
                        end_line=lineno,
                        return_type=v_type,
                        visibility="private",
                        content_hash=_normalized_body_hash(lines, lineno, lineno),
                    )
                )

        m_alias = _LUA_ALIAS_CHAIN_RE.match(line)
        if m_alias:
            lhs_var = m_alias.group(1)
            rhs_val = m_alias.group(2).strip()
            if not rhs_val.startswith(("function", "{", "require(")):
                norm_chain, is_dyn = _normalize_roblox_chain(rhs_val, local_aliases)
                if norm_chain and not is_dyn:
                    head_seg = norm_chain.split(".")[0]
                    if head_seg in _ROBLOX_DATAMODEL_SERVICES or head_seg == "script":
                        local_aliases[lhs_var] = norm_chain
                elif is_dyn and any(s in rhs_val for s in ("WaitForChild", "FindFirstChild", "ReplicatedStorage", "ServerScriptService")):
                    local_aliases[lhs_var] = "<DYNAMIC>"

        # 16. General function / method call sites
        for cm in _LUA_CALL_SITE_RE.finditer(line):
            recv = cm.group(1)
            sep = cm.group(2)
            callee_nm = cm.group(3)
            if callee_nm in _LUAU_KEYWORDS_AND_BUILTINS:
                continue
            if callee_nm in ("FireServer", "InvokeServer", "FireClient", "FireAllClients", "Connect", "WaitForChild", "FindFirstChild", "GetService"):
                continue
            if recv in _LUAU_KEYWORDS_AND_BUILTINS:
                continue
            resolved_recv = recv
            if recv == "self" and current_scope and "." in current_scope:
                resolved_recv = current_scope.split(".")[0]
            elif recv and recv in local_aliases:
                alias_val = local_aliases[recv]
                if alias_val.startswith("KnitService:"):
                    resolved_recv = alias_val.split(":", 1)[1]
                elif not alias_val.startswith(("persistence.", "<DYNAMIC")):
                    resolved_recv = alias_val.split(".")[-1]
            q_callee = f"{resolved_recv}.{callee_nm}" if resolved_recv else callee_nm
            calls.append(
                CallRef(
                    callee=callee_nm,
                    qualified_callee=q_callee,
                    line=lineno,
                    end_line=lineno,
                    source_file=file_path,
                    confidence="LOW",
                    caller_symbol=current_scope or None,
                    caller_canonical_id=caller_canon,
                    receiver=resolved_recv,
                )
            )

    symbols.sort(key=lambda s: (s.start_line, s.canonical_id))
    return ParseResult(
        path=file_path,
        language="luau",
        source_hash=source_hash,
        symbols=tuple(symbols),
        imports=tuple(imports),
        calls=tuple(calls),
        bindings=tuple(bindings),
        exports=tuple(exports),
        parse_failed=False,
    )


def _estimate_block_end_braces(lines: list[str], start_idx: int) -> int:
    depth = 0
    opened = False
    for i in range(start_idx, len(lines)):
        clean = _strip_luau_comment(lines[i])
        opens = clean.count("{")
        closes = clean.count("}")
        if opens > 0:
            opened = True
        depth += opens - closes
        if opened and depth <= 0:
            return i + 1
    return len(lines)


# ---------------------------------------------------------------------------
# Phase R7: Flamework TypeScript Support (@Service, @Controller, Dependency<T>)
# ---------------------------------------------------------------------------

_FLAMEWORK_DECORATOR_RE = re.compile(r"@(Service|Controller)\s*\(")
_FLAMEWORK_CLASS_RE = re.compile(r"\bexport\s+class\s+([A-Za-z_$][\w$]*)")
_FLAMEWORK_DEPENDENCY_RE = re.compile(
    r"(?:(?:const|let|var|readonly|private|protected|public)\s+([A-Za-z_$][\w$]*)\s*=\s*)?Dependency\s*<\s*([A-Za-z_$][\w$]*)\s*>\s*\(\s*\)"
)


def extract_flamework_bindings(content: str, file_path: str, module: str) -> list[BindingRef]:
    """Extract Flamework `@Service()`, `@Controller()`, and `Dependency<T>()` bindings from TypeScript files."""
    if "@flamework" not in content and "Dependency<" not in content and "@Service" not in content and "@Controller" not in content:
        return []

    bindings: list[BindingRef] = []
    lines = content.splitlines()
    pending_decorator: tuple[str, int] | None = None
    active_class: str | None = None

    for idx, line in enumerate(lines):
        lineno = idx + 1
        m_dec = _FLAMEWORK_DECORATOR_RE.search(line)
        if m_dec:
            pending_decorator = (m_dec.group(1), lineno)

        m_cls = _FLAMEWORK_CLASS_RE.search(line)
        if m_cls:
            cls_name = m_cls.group(1)
            active_class = cls_name
            if pending_decorator:
                dec_kind, dec_line = pending_decorator
                bindings.append(
                    BindingRef(
                        target_name=cls_name,
                        file_path=file_path,
                        line=dec_line,
                        scope=cls_name,
                        expr_kind="ROBLOX_FLAMEWORK_PROVIDER",
                        source_expr=f"{module}.{cls_name}",
                        base_expr="Flamework",
                        attr_name=dec_kind,
                    )
                )
                pending_decorator = None

        m_dep = _FLAMEWORK_DEPENDENCY_RE.search(line)
        if m_dep:
            dep_type = m_dep.group(2)
            caller_scope = f"{module}.{active_class}" if active_class else module
            bindings.append(
                BindingRef(
                    target_name=dep_type,
                    file_path=file_path,
                    line=lineno,
                    scope=active_class or "",
                    expr_kind="ROBLOX_FLAMEWORK_DEPENDENCY",
                    source_expr=caller_scope,
                    base_expr="Flamework",
                    attr_name="Dependency",
                )
            )

    return bindings


# ---------------------------------------------------------------------------
# Global Resolution Pass for Roblox Intelligence (Phases R2–R8)
# ---------------------------------------------------------------------------


def resolve_roblox_intelligence(
    *,
    repository: Path | None,
    symbols: list[Symbol],
    bindings: list[BindingRef],
    known_files: set[str],
    file_hashes: dict[str, str],
    indexed_commit: str | None,
    add_ref: Any,
    add_edge: Any,
    resolved_imports: dict[tuple[str, int, str], tuple[str | None, str | None]],
) -> None:
    """Resolve Rojo virtual paths, Luau module requires, RemoteEvent/RemoteFunction networking,
    Knit/Flamework services, and DataStore/ProfileService persistence into verified graph edges.
    """
    rojo = RojoProject.load(repository)

    # Index Knit & Flamework provided services: service_name -> provider_canonical_id
    service_providers: dict[str, str] = {}
    for b in bindings:
        if b.expr_kind == "ROBLOX_KNIT_CREATE_SERVICE" and b.target_name != "<DYNAMIC>":
            service_providers[b.target_name] = b.source_expr
        elif b.expr_kind == "ROBLOX_FLAMEWORK_PROVIDER":
            service_providers[b.target_name] = b.source_expr

    # Also index symbols by short name and module for Knit/Flamework fallback
    short_to_symbols: dict[str, list[Symbol]] = {}
    for s in symbols:
        short_to_symbols.setdefault(s.name, []).append(s)

    for b in bindings:
        f_hash = file_hashes.get(b.file_path, "")

        # 1. Phase R2 & R3: ROBLOX_REQUIRE -> REQUIRES_MODULE
        if b.expr_kind == "ROBLOX_REQUIRE":
            caller_id = b.attr_name or normalize_module(b.file_path)
            req_target = b.source_expr
            raw_expr = b.base_expr

            if b.is_conditional or req_target == "<DYNAMIC>":
                # Dynamic require -> UNKNOWN
                ev_str = f"Dynamic require({raw_expr}) in {b.file_path}:{b.line}"
                add_edge(
                    GraphEdge(
                        source=caller_id,
                        target=f"unresolved.module.{raw_expr}",
                        relationship="REQUIRES_MODULE",
                        confidence="UNKNOWN",
                        file=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_str,
                        evidence_class=RelationshipEvidenceClass.UNKNOWN.value,
                        reason="dynamic_luau_require",
                    )
                )
                continue

            target_file: str | None = None
            ev_cls = RelationshipEvidenceClass.AST_VERIFIED.value

            if req_target.startswith("script"):
                target_file, ev_cls = resolve_luau_relative_script_path(
                    req_target, b.file_path, known_files, rojo=rojo
                )
            elif any(req_target.startswith(svc) for svc in _ROBLOX_DATAMODEL_SERVICES):
                target_file, ev_cls = rojo.resolve_virtual_to_file(req_target, known_files)

            if target_file:
                target_mod = normalize_module(target_file)
                resolved_imports[(b.file_path, b.line, b.target_name)] = (target_file, target_mod)
                ev_str = f"require({raw_expr}) -> {target_file} ({ev_cls})"
                add_ref(
                    Reference(
                        source_symbol_id=caller_id,
                        target_symbol_id=target_mod,
                        relationship="REQUIRES_MODULE",
                        confidence="HIGH",
                        path=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_str,
                        source_hash=f_hash,
                        indexed_commit=indexed_commit,
                    )
                )
                add_edge(
                    GraphEdge(
                        source=caller_id,
                        target=target_mod,
                        relationship="REQUIRES_MODULE",
                        confidence="HIGH",
                        file=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_str,
                        evidence_class=ev_cls,
                        reason=f"luau_require:{target_file}",
                    )
                )
            else:
                # Unresolved require (e.g. plain Lua `require("x")` or missing Rojo mapping)
                # Negative test 5: Plain non-Roblox Lua file with `require("x")` must NOT fabricate Rojo paths!
                ev_str = f"Unresolved require({raw_expr}) in {b.file_path}:{b.line}"
                add_edge(
                    GraphEdge(
                        source=caller_id,
                        target=req_target,
                        relationship="REQUIRES_MODULE",
                        confidence="UNKNOWN",
                        file=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_str,
                        evidence_class=RelationshipEvidenceClass.UNKNOWN.value,
                        reason="unresolved_luau_require",
                    )
                )

        # 2. Phase R4: ROBLOX_REMOTE_DISPATCH -> CLIENT_DISPATCHES_REMOTE
        elif b.expr_kind == "ROBLOX_REMOTE_DISPATCH":
            caller_id = b.source_expr
            remote_chain = b.target_name
            fire_method = b.attr_name
            raw_expr = b.base_expr

            # Negative Test 4: Non-Roblox `:FireServer()` on an arbitrary local table must NOT be a verified Remote!
            is_verified_roblox_remote = (
                not b.is_conditional
                and remote_chain != "<DYNAMIC>"
                and any(remote_chain.startswith(svc + ".") for svc in _ROBLOX_DATAMODEL_SERVICES)
            )
            if is_verified_roblox_remote:
                ev_cls = (
                    RelationshipEvidenceClass.ROJO_VERIFIED.value
                    if rojo.is_valid
                    else RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value
                )
                ev_str = f"Client dispatches remote '{remote_chain}' via :{fire_method}() at {b.file_path}:{b.line}"
                add_ref(
                    Reference(
                        source_symbol_id=caller_id,
                        target_symbol_id=remote_chain,
                        relationship="CLIENT_DISPATCHES_REMOTE",
                        confidence="HIGH",
                        path=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_str,
                        source_hash=f_hash,
                        indexed_commit=indexed_commit,
                    )
                )
                add_edge(
                    GraphEdge(
                        source=caller_id,
                        target=remote_chain,
                        relationship="CLIENT_DISPATCHES_REMOTE",
                        confidence="HIGH",
                        file=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_str,
                        evidence_class=ev_cls,
                        reason=f"roblox_remote_dispatch:{fire_method}",
                    )
                )
            elif b.is_conditional or (
                any(s in raw_expr for s in ("ReplicatedStorage", "Remotes", "WaitForChild"))
            ):
                # Dynamic remote lookup -> POSSIBLE / UNKNOWN
                dyn_target = f"remote.dynamic.{raw_expr}"
                ev_str = f"Dynamic remote dispatch '{raw_expr}:{fire_method}()' at {b.file_path}:{b.line}"
                add_edge(
                    GraphEdge(
                        source=caller_id,
                        target=dyn_target,
                        relationship="CLIENT_DISPATCHES_REMOTE",
                        confidence="UNKNOWN",
                        file=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_str,
                        evidence_class=RelationshipEvidenceClass.UNKNOWN.value,
                        reason="dynamic_remote_dispatch",
                    )
                )

        # 3. Phase R4: ROBLOX_REMOTE_HANDLER -> SERVER_HANDLES_REMOTE
        elif b.expr_kind == "ROBLOX_REMOTE_HANDLER":
            handler_id = b.source_expr
            remote_chain = b.target_name
            event_prop = b.attr_name
            raw_expr = b.base_expr

            # Negative Test 3: Non-Roblox `:Connect(...)` is never captured here because regex requires
            # `.OnServerEvent:Connect` or `.OnClientEvent:Connect`, AND we verify Roblox DataModel root.
            is_verified_roblox_remote = (
                not b.is_conditional
                and remote_chain != "<DYNAMIC>"
                and any(remote_chain.startswith(svc + ".") for svc in _ROBLOX_DATAMODEL_SERVICES)
            )
            if is_verified_roblox_remote:
                ev_cls = (
                    RelationshipEvidenceClass.ROJO_VERIFIED.value
                    if rojo.is_valid
                    else RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value
                )
                ev_str = f"Server handles remote '{remote_chain}' via .{event_prop} -> {handler_id} at {b.file_path}:{b.line}"
                add_ref(
                    Reference(
                        source_symbol_id=remote_chain,
                        target_symbol_id=handler_id,
                        relationship="SERVER_HANDLES_REMOTE",
                        confidence="HIGH",
                        path=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_str,
                        source_hash=f_hash,
                        indexed_commit=indexed_commit,
                    )
                )
                add_edge(
                    GraphEdge(
                        source=remote_chain,
                        target=handler_id,
                        relationship="SERVER_HANDLES_REMOTE",
                        confidence="HIGH",
                        file=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_str,
                        evidence_class=ev_cls,
                        reason=f"roblox_remote_handler:{event_prop}",
                    )
                )
            elif b.is_conditional or (
                any(s in raw_expr for s in ("ReplicatedStorage", "Remotes", "WaitForChild"))
            ):
                dyn_target = f"remote.dynamic.{raw_expr}"
                ev_str = f"Dynamic remote handler '{raw_expr}.{event_prop}' at {b.file_path}:{b.line}"
                add_edge(
                    GraphEdge(
                        source=dyn_target,
                        target=handler_id,
                        relationship="SERVER_HANDLES_REMOTE",
                        confidence="UNKNOWN",
                        file=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_str,
                        evidence_class=RelationshipEvidenceClass.UNKNOWN.value,
                        reason="dynamic_remote_handler",
                    )
                )

        # 4. Phase R6: Knit Service Provider & Consumer
        elif b.expr_kind == "ROBLOX_KNIT_CREATE_SERVICE":
            provider_canon = b.source_expr
            svc_name = b.target_name
            if not b.is_conditional and svc_name != "<DYNAMIC>":
                ev_str = f"Knit.CreateService provides '{svc_name}' ({provider_canon}) at {b.file_path}:{b.line}"
                add_ref(
                    Reference(
                        source_symbol_id=provider_canon,
                        target_symbol_id=svc_name,
                        relationship="PROVIDES_SERVICE",
                        confidence="HIGH",
                        path=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_str,
                        source_hash=f_hash,
                        indexed_commit=indexed_commit,
                    )
                )
                add_edge(
                    GraphEdge(
                        source=provider_canon,
                        target=svc_name,
                        relationship="PROVIDES_SERVICE",
                        confidence="HIGH",
                        file=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_str,
                        evidence_class=RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value,
                        reason=f"knit_create_service:{svc_name}",
                    )
                )
            else:
                add_edge(
                    GraphEdge(
                        source=provider_canon,
                        target="service.knit.<DYNAMIC>",
                        relationship="PROVIDES_SERVICE",
                        confidence="UNKNOWN",
                        file=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=f"Dynamic Knit.CreateService at {b.file_path}:{b.line}",
                        evidence_class=RelationshipEvidenceClass.UNKNOWN.value,
                        reason="dynamic_knit_service_name",
                    )
                )

        elif b.expr_kind == "ROBLOX_KNIT_GET_SERVICE":
            caller_mod = normalize_module(b.file_path)
            caller_id = f"{caller_mod}.{b.scope}" if b.scope else caller_mod
            svc_name = b.target_name
            if not b.is_conditional and svc_name != "<DYNAMIC>":
                target_provider = service_providers.get(svc_name)
                if not target_provider and svc_name in short_to_symbols:
                    target_provider = short_to_symbols[svc_name][0].canonical_id
                resolved_target = target_provider or svc_name
                ev_str = f"Knit.GetService('{svc_name}') -> '{resolved_target}' at {b.file_path}:{b.line}"
                add_ref(
                    Reference(
                        source_symbol_id=caller_id,
                        target_symbol_id=resolved_target,
                        relationship="GETS_SERVICE",
                        confidence="HIGH",
                        path=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_str,
                        source_hash=f_hash,
                        indexed_commit=indexed_commit,
                    )
                )
                add_edge(
                    GraphEdge(
                        source=caller_id,
                        target=resolved_target,
                        relationship="GETS_SERVICE",
                        confidence="HIGH",
                        file=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_str,
                        evidence_class=RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value,
                        reason=f"knit_get_service:{svc_name}",
                    )
                )
            else:
                add_edge(
                    GraphEdge(
                        source=caller_id,
                        target=f"service.knit.dynamic.{b.source_expr}",
                        relationship="GETS_SERVICE",
                        confidence="UNKNOWN",
                        file=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=f"Dynamic Knit.GetService({b.source_expr}) at {b.file_path}:{b.line}",
                        evidence_class=RelationshipEvidenceClass.UNKNOWN.value,
                        reason="dynamic_knit_get_service",
                    )
                )

        # 5. Phase R7: Flamework TypeScript @Service, @Controller, Dependency<T>
        elif b.expr_kind == "ROBLOX_FLAMEWORK_PROVIDER":
            provider_canon = b.source_expr
            svc_name = b.target_name
            ev_str = f"Flamework @{b.attr_name} provides '{svc_name}' ({provider_canon}) at {b.file_path}:{b.line}"
            add_ref(
                Reference(
                    source_symbol_id=provider_canon,
                    target_symbol_id=svc_name,
                    relationship="PROVIDES_SERVICE",
                    confidence="HIGH",
                    path=b.file_path,
                    start_line=b.line,
                    end_line=b.line,
                    evidence=ev_str,
                    source_hash=f_hash,
                    indexed_commit=indexed_commit,
                )
            )
            add_edge(
                GraphEdge(
                    source=provider_canon,
                    target=svc_name,
                    relationship="PROVIDES_SERVICE",
                    confidence="HIGH",
                    file=b.file_path,
                    start_line=b.line,
                    end_line=b.line,
                    evidence=ev_str,
                    evidence_class=RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value,
                    reason=f"flamework_{b.attr_name.lower()}:{svc_name}",
                )
            )

        elif b.expr_kind == "ROBLOX_FLAMEWORK_DEPENDENCY":
            caller_id = b.source_expr
            dep_type = b.target_name
            target_provider = service_providers.get(dep_type)
            if not target_provider and dep_type in short_to_symbols:
                target_provider = short_to_symbols[dep_type][0].canonical_id
            resolved_target = target_provider or dep_type
            ev_str = f"Flamework Dependency<{dep_type}>() -> '{resolved_target}' at {b.file_path}:{b.line}"
            add_ref(
                Reference(
                    source_symbol_id=caller_id,
                    target_symbol_id=resolved_target,
                    relationship="GETS_SERVICE",
                    confidence="HIGH",
                    path=b.file_path,
                    start_line=b.line,
                    end_line=b.line,
                    evidence=ev_str,
                    source_hash=f_hash,
                    indexed_commit=indexed_commit,
                )
            )
            add_edge(
                GraphEdge(
                    source=caller_id,
                    target=resolved_target,
                    relationship="GETS_SERVICE",
                    confidence="HIGH",
                    file=b.file_path,
                    start_line=b.line,
                    end_line=b.line,
                    evidence=ev_str,
                    evidence_class=RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value,
                    reason=f"flamework_dependency:{dep_type}",
                )
            )

        # 6. Phase R8: Roblox Persistence (DataStoreService & ProfileService)
        elif b.expr_kind in (
            "ROBLOX_CONFIGURE_PERSISTENCE",
            "ROBLOX_READ_PERSISTENCE",
            "ROBLOX_WRITE_PERSISTENCE",
        ):
            caller_id = b.source_expr
            store_id = b.target_name
            op_method = b.attr_name
            rel_map = {
                "ROBLOX_CONFIGURE_PERSISTENCE": "CONFIGURES_PERSISTENCE",
                "ROBLOX_READ_PERSISTENCE": "READS_PERSISTENCE",
                "ROBLOX_WRITE_PERSISTENCE": "WRITES_PERSISTENCE",
            }
            rel_type = rel_map[b.expr_kind]
            is_dyn = b.is_conditional or store_id.endswith("<DYNAMIC>")
            ev_cls = (
                RelationshipEvidenceClass.UNKNOWN.value
                if is_dyn
                else RelationshipEvidenceClass.FRAMEWORK_VERIFIED.value
            )
            conf = "UNKNOWN" if is_dyn else "HIGH"
            ev_str = f"Roblox persistence {op_method} on '{store_id}' at {b.file_path}:{b.line}"
            if not is_dyn:
                add_ref(
                    Reference(
                        source_symbol_id=caller_id,
                        target_symbol_id=store_id,
                        relationship=rel_type,
                        confidence=conf,
                        path=b.file_path,
                        start_line=b.line,
                        end_line=b.line,
                        evidence=ev_str,
                        source_hash=f_hash,
                        indexed_commit=indexed_commit,
                    )
                )
            add_edge(
                GraphEdge(
                    source=caller_id,
                    target=store_id,
                    relationship=rel_type,
                    confidence=conf,
                    file=b.file_path,
                    start_line=b.line,
                    end_line=b.line,
                    evidence=ev_str,
                    evidence_class=ev_cls,
                    reason=f"roblox_persistence:{op_method}",
                )
            )


# ---------------------------------------------------------------------------
# Phase R9: CLI and MCP Query Helpers (remotes, modules, routes)
# ---------------------------------------------------------------------------


def list_roblox_remotes(con: sqlite3.Connection, repository: Path) -> dict[str, Any]:
    """List all discovered Roblox RemoteEvent and RemoteFunction channels, client senders, and server handlers."""
    rows = con.execute(
        "SELECT source, target, relationship, confidence, file, start_line, evidence, evidence_class "
        "FROM graph_edges "
        "WHERE relationship IN ('CLIENT_DISPATCHES_REMOTE', 'SERVER_HANDLES_REMOTE') "
        "ORDER BY file ASC, start_line ASC"
    ).fetchall()

    remotes_map: dict[str, dict[str, Any]] = {}
    for r in rows:
        rel = str(r["relationship"])
        remote_id = str(r["target"]) if rel == "CLIENT_DISPATCHES_REMOTE" else str(r["source"])
        entry = remotes_map.setdefault(
            remote_id,
            {
                "remote": remote_id,
                "client_dispatches": [],
                "client_dispatchers": [],
                "server_handlers": [],
                "evidence_class": str(r["evidence_class"] or "ROJO_VERIFIED"),
            },
        )
        if rel == "CLIENT_DISPATCHES_REMOTE":
            item = {
                "caller": str(r["source"]),
                "symbol": str(r["source"]),
                "file": str(r["file"]),
                "line": int(r["start_line"]),
                "confidence": str(r["confidence"]),
                "evidence_class": str(r["evidence_class"]),
                "evidence": str(r["evidence"]),
            }
            entry["client_dispatches"].append(item)
            entry["client_dispatchers"].append(item)
        else:
            entry["server_handlers"].append(
                {
                    "handler": str(r["target"]),
                    "symbol": str(r["target"]),
                    "file": str(r["file"]),
                    "line": int(r["start_line"]),
                    "confidence": str(r["confidence"]),
                    "evidence_class": str(r["evidence_class"]),
                    "evidence": str(r["evidence"]),
                }
            )

    remotes_list = sorted(remotes_map.values(), key=lambda x: str(x["remote"]))
    return {
        "status": "ok",
        "repository": str(repository),
        "count": len(remotes_list),
        "remotes": remotes_list,
    }


def list_roblox_modules(con: sqlite3.Connection, repository: Path) -> dict[str, Any]:
    """List indexed Luau/Lua modules, Rojo virtual DataModel mappings, and `REQUIRES_MODULE` edges."""
    rojo = RojoProject.load(repository)
    file_rows = con.execute(
        "SELECT path, hash FROM files WHERE language='luau' AND status='ok' ORDER BY path ASC"
    ).fetchall()

    req_rows = con.execute(
        "SELECT source, target, confidence, file, start_line, evidence, evidence_class "
        "FROM graph_edges WHERE relationship='REQUIRES_MODULE' ORDER BY file ASC, start_line ASC"
    ).fetchall()

    requires_by_file: dict[str, list[dict[str, Any]]] = {}
    requires = []
    for r in req_rows:
        req_item = {
            "source": str(r["source"]),
            "target": str(r["target"]),
            "file": str(r["file"]),
            "line": int(r["start_line"]),
            "confidence": str(r["confidence"]),
            "evidence_class": str(r["evidence_class"]),
            "evidence": str(r["evidence"]),
        }
        requires.append(req_item)
        requires_by_file.setdefault(str(r["file"]), []).append(req_item)

    modules = []
    for fr in file_rows:
        fpath = str(fr["path"])
        mod_id = normalize_module(fpath, "luau")
        vpath = rojo.file_to_virtual_path(fpath)
        modules.append(
            {
                "file": fpath,
                "module": mod_id,
                "virtual_path": vpath,
                "rojo_virtual_path": vpath,
                "evidence_class": "ROJO_VERIFIED" if vpath else "AST_VERIFIED",
                "requires": requires_by_file.get(fpath, []),
            }
        )

    return {
        "status": "ok",
        "repository": str(repository),
        "rojo_configured": rojo.is_valid,
        "rojo_project": {
            "is_valid": rojo.is_valid,
            "name": rojo.name,
            "project_file": rojo.project_file,
            "parse_error": rojo.parse_error,
            "mappings": [
                {"virtual_path": m.virtual_path, "physical_path": m.physical_path}
                for m in rojo.mappings
            ],
        },
        "module_count": len(modules),
        "modules": modules,
        "requires_count": len(requires),
        "requires": requires,
    }


def list_roblox_routes(con: sqlite3.Connection, repository: Path) -> dict[str, Any]:
    """List end-to-end Roblox Client -> Remote -> Server handler routes, Knit/Flamework service links, and persistence."""
    remotes_data = list_roblox_remotes(con, repository)
    routes = []
    for rem in remotes_data.get("remotes", []):
        remote_name = rem["remote"]
        dispatches = rem["client_dispatches"]
        handlers = rem["server_handlers"]
        if dispatches and handlers:
            for d in dispatches:
                for h in handlers:
                    routes.append(
                        {
                            "client": d["caller"],
                            "client_caller": d["caller"],
                            "client_file": d["file"],
                            "client_line": d["line"],
                            "remote": remote_name,
                            "server": h["handler"],
                            "server_handler": h["handler"],
                            "server_file": h["file"],
                            "server_line": h["line"],
                            "evidence_class": h["evidence_class"],
                        }
                    )
        elif handlers:
            for h in handlers:
                routes.append(
                    {
                        "client": None,
                        "client_caller": None,
                        "client_file": None,
                        "client_line": None,
                        "remote": remote_name,
                        "server": h["handler"],
                        "server_handler": h["handler"],
                        "server_file": h["file"],
                        "server_line": h["line"],
                        "evidence_class": h["evidence_class"],
                    }
                )
        elif dispatches:
            for d in dispatches:
                routes.append(
                    {
                        "client": d["caller"],
                        "client_caller": d["caller"],
                        "client_file": d["file"],
                        "client_line": d["line"],
                        "remote": remote_name,
                        "server": None,
                        "server_handler": None,
                        "server_file": None,
                        "server_line": None,
                        "evidence_class": d["evidence_class"],
                    }
                )

    svc_rows = con.execute(
        "SELECT source, target, relationship, confidence, file, start_line, evidence_class "
        "FROM graph_edges WHERE relationship IN ('PROVIDES_SERVICE', 'GETS_SERVICE') "
        "ORDER BY file ASC, start_line ASC"
    ).fetchall()
    services = [
        {
            "provider": str(r["source"]),
            "source": str(r["source"]),
            "service": str(r["target"]),
            "target": str(r["target"]),
            "relationship": str(r["relationship"]),
            "file": str(r["file"]),
            "line": int(r["start_line"]),
            "confidence": str(r["confidence"]),
            "evidence_class": str(r["evidence_class"]),
        }
        for r in svc_rows
    ]

    pers_rows = con.execute(
        "SELECT source, target, relationship, confidence, file, start_line, evidence_class "
        "FROM graph_edges WHERE relationship IN ('CONFIGURES_PERSISTENCE', 'READS_PERSISTENCE', 'WRITES_PERSISTENCE') "
        "ORDER BY file ASC, start_line ASC"
    ).fetchall()
    persistence = [
        {
            "symbol": str(r["source"]),
            "store": str(r["target"]),
            "relationship": str(r["relationship"]),
            "file": str(r["file"]),
            "line": int(r["start_line"]),
            "confidence": str(r["confidence"]),
            "evidence_class": str(r["evidence_class"]),
        }
        for r in pers_rows
    ]

    return {
        "status": "ok",
        "repository": str(repository),
        "route_count": len(routes),
        "routes": routes,
        "services": services,
        "service_edges": services,
        "persistence": persistence,
    }

