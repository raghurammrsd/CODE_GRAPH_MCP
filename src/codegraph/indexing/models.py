"""Data models for the indexing, symbol identity, and reference resolution pipeline.

Normalization rules for canonical symbol IDs:
1. Path separators ('\\' and '/') are normalized to '/'.
2. Leading './' and '/' prefixes are stripped.
3. Supported source extensions (.py, .pyi, .ts, .tsx, .js, .jsx, .mjs, .cjs) are stripped.
4. Package index filenames ('/__init__' for Python, '/index' for JS/TS) are collapsed to
   their parent package path (e.g. 'src/auth/__init__.py' -> 'src.auth',
   'src/auth/index.ts' -> 'src.auth'). Root-level '__init__.py' or 'index.ts' retain
   '__init__' or 'index'.
5. Path segments are joined with '.' to form the normalized module name.
6. Canonical ID is constructed deterministically as:
   - f"{module}.{scope}.{name}" when scope is non-empty
   - f"{module}.{name}" when scope is empty
   Line numbers are never part of the canonical identity.
"""
from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from functools import lru_cache

_SOURCE_EXTENSIONS = (
    ".d.ts",
    ".pyi",
    ".tsx",
    ".jsx",
    ".mjs",
    ".cjs",
    ".py",
    ".ts",
    ".js",
)


@lru_cache(maxsize=65536)
def normalize_module(file_path: str, language: str = "") -> str:
    """Deterministically normalize a repository-relative file path into a dotted module ID."""
    del language  # normalization is uniform across Python/JS/TS after extension/index rules
    cleaned = file_path.replace("\\", "/").strip()
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    cleaned = cleaned.lstrip("/")
    if not cleaned:
        return "root"

    cleaned = posixpath.normpath(cleaned)
    if cleaned in (".", ""):
        return "root"

    lower = cleaned.lower()
    for ext in _SOURCE_EXTENSIONS:
        if lower.endswith(ext):
            cleaned = cleaned[: -len(ext)]
            break

    if cleaned.endswith("/__init__"):
        cleaned = cleaned[: -len("/__init__")]
    elif cleaned.endswith("/index"):
        cleaned = cleaned[: -len("/index")]

    parts = [p for p in cleaned.split("/") if p and p != "."]
    return ".".join(parts) if parts else "root"


def build_canonical_id(module: str, scope: str, name: str) -> str:
    """Build a deterministic canonical symbol ID from normalized module, scope, and name."""
    mod = module.strip(".")
    scp = scope.strip(".")
    nm = name.strip(".") or "default"
    if mod and scp:
        return f"{mod}.{scp}.{nm}"
    if mod:
        return f"{mod}.{nm}"
    if scp:
        return f"{scp}.{nm}"
    return nm


@dataclass(frozen=True)
class Symbol:
    name: str
    qualified_name: str
    kind: str  # function | method | class | interface | type | variable
    start_line: int
    end_line: int
    file_path: str
    decorators: list[str] = field(default_factory=list)
    id: str = ""
    canonical_id: str = ""
    language: str = "python"
    module: str = ""
    path: str = ""
    scope: str = ""
    signature: str = ""
    content_hash: str = ""
    parent_symbol_id: str | None = None
    visibility: str = ""
    return_type: str | None = None
    parameter_count: int | None = None
    documentation: str | None = None

    def __post_init__(self) -> None:
        path_val = self.path or self.file_path
        object.__setattr__(self, "path", path_val)

        mod_val = self.module or normalize_module(path_val, self.language)
        object.__setattr__(self, "module", mod_val)

        scope_val = self.scope
        if not scope_val and "." in self.qualified_name:
            scope_val = self.qualified_name.rsplit(".", 1)[0]
        object.__setattr__(self, "scope", scope_val)

        canon_val = self.canonical_id or build_canonical_id(mod_val, scope_val, self.name)
        object.__setattr__(self, "canonical_id", canon_val)

        id_val = self.id or canon_val
        object.__setattr__(self, "id", id_val)

        if self.parent_symbol_id is None and scope_val:
            parent_id = f"{mod_val}.{scope_val}" if mod_val else scope_val
            object.__setattr__(self, "parent_symbol_id", parent_id)

        if not self.visibility:
            is_private = self.name.startswith("_") and not (
                self.name.startswith("__") and self.name.endswith("__")
            )
            object.__setattr__(self, "visibility", "private" if is_private else "public")

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "canonical_id": self.canonical_id,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "kind": self.kind,
            "language": self.language,
            "module": self.module,
            "path": self.path,
            "file": self.path,
            "file_path": self.file_path,
            "scope": self.scope,
            "signature": self.signature,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "content_hash": self.content_hash,
            "parent_symbol_id": self.parent_symbol_id,
            "visibility": self.visibility,
            "decorators": list(self.decorators),
            "decorator": ",".join(self.decorators),
            "return_type": self.return_type,
            "parameter_count": self.parameter_count,
            "documentation": self.documentation,
        }

    def __getitem__(self, key: str) -> object:
        return self.as_dict()[key]

    def get(self, key: str, default: object = None) -> object:
        return self.as_dict().get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self.as_dict()


@dataclass(frozen=True)
class ImportRef:
    module: str
    source_file: str
    name: str | None = None  # imported name (from X import name)
    alias: str | None = None  # as Y
    full: str | None = None  # module.name combined
    line: int = 1
    source_module: str = ""
    imported_module: str = ""
    imported_name: str | None = None
    local_name: str = ""
    import_type: str = ""  # named | alias | namespace | default | module | reexport
    is_reexport: bool = False
    exported_name: str | None = None

    def __post_init__(self) -> None:
        src_mod = self.source_module or normalize_module(self.source_file)
        object.__setattr__(self, "source_module", src_mod)

        imp_mod = self.imported_module or self.module
        object.__setattr__(self, "imported_module", imp_mod)

        imp_name = self.imported_name if self.imported_name is not None else self.name
        object.__setattr__(self, "imported_name", imp_name)

        if not self.local_name:
            if self.alias:
                loc = self.alias
            elif imp_name and imp_name != "*":
                loc = imp_name
            else:
                loc = imp_mod.lstrip(".").split("/")[0].split(".")[0]
            object.__setattr__(self, "local_name", loc)

        if not self.import_type:
            if self.is_reexport:
                itype = "reexport"
            elif self.alias and imp_name == "*":
                itype = "namespace"
            elif self.alias and imp_name is None:
                itype = "namespace"
            elif self.alias:
                itype = "alias"
            elif imp_name == "default":
                itype = "default"
            elif imp_name:
                itype = "named"
            else:
                itype = "module"
            object.__setattr__(self, "import_type", itype)

        if self.full is None:
            full_val = f"{imp_mod}.{imp_name}" if (imp_mod and imp_name) else imp_mod
            object.__setattr__(self, "full", full_val)

    def as_dict(self) -> dict[str, object]:
        return {
            "source_file": self.source_file,
            "source_module": self.source_module,
            "module": self.module,
            "imported_module": self.imported_module,
            "name": self.name,
            "imported_name": self.imported_name,
            "alias": self.alias,
            "local_name": self.local_name,
            "import_type": self.import_type,
            "is_reexport": self.is_reexport,
            "exported_name": self.exported_name or self.alias or self.imported_name,
            "full": self.full,
            "line": self.line,
        }

    def __getitem__(self, key: str) -> object:
        return self.as_dict()[key]

    def get(self, key: str, default: object = None) -> object:
        return self.as_dict().get(key, default)


@dataclass(frozen=True)
class CallRef:
    callee: str
    source_file: str
    confidence: str = "LOW"
    qualified_callee: str | None = None
    line: int = 1
    end_line: int = 0
    caller_symbol: str | None = None  # qualified_name within file, or None for module scope
    caller_canonical_id: str | None = None
    receiver: str | None = None

    def __post_init__(self) -> None:
        if self.end_line <= 0:
            object.__setattr__(self, "end_line", self.line)
        if self.caller_canonical_id is None:
            mod = normalize_module(self.source_file)
            if self.caller_symbol:
                object.__setattr__(self, "caller_canonical_id", f"{mod}.{self.caller_symbol}")
            else:
                object.__setattr__(self, "caller_canonical_id", mod)


@dataclass(frozen=True)
class InheritanceRef:
    source_symbol: str  # qualified_name in source_file
    base_name: str  # raw base/interface identifier (e.g. Base or mod.Base)
    relationship: str  # EXTENDS | IMPLEMENTS
    source_file: str
    line: int = 1
    source_canonical_id: str = ""

    def __post_init__(self) -> None:
        if not self.source_canonical_id:
            mod = normalize_module(self.source_file)
            object.__setattr__(self, "source_canonical_id", f"{mod}.{self.source_symbol}")


@dataclass(frozen=True)
class Reference:
    source_symbol_id: str
    target_symbol_id: str | None
    relationship: str  # CALLS | REFERENCES | IMPORTS | EXPORTS | REEXPORTS | EXTENDS | IMPLEMENTS | USES | UNRESOLVED_REFERENCE
    confidence: str  # HIGH | MEDIUM | LOW | UNKNOWN
    path: str
    start_line: int
    end_line: int
    evidence: str
    source_hash: str = ""
    indexed_commit: str | None = None
    evidence_status: str = "current"

    def as_dict(self) -> dict[str, object]:
        return {
            "source_symbol_id": self.source_symbol_id,
            "target_symbol_id": self.target_symbol_id,
            "source": self.source_symbol_id,
            "target": self.target_symbol_id,
            "symbol": self.source_symbol_id,
            "callee": self.target_symbol_id.split(".")[-1] if self.target_symbol_id else None,
            "qualified_callee": self.target_symbol_id,
            "relationship": self.relationship,
            "confidence": self.confidence,
            "path": self.path,
            "file": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "line": self.start_line,
            "evidence": self.evidence,
            "source_hash": self.source_hash,
            "indexed_commit": self.indexed_commit,
            "evidence_status": self.evidence_status,
        }

    def __getitem__(self, key: str) -> object:
        return self.as_dict()[key]

    def get(self, key: str, default: object = None) -> object:
        return self.as_dict().get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self.as_dict()


@dataclass(frozen=True)
class Chunk:
    file_path: str
    language: str
    symbol: str | None
    symbol_type: str | None
    start_line: int
    end_line: int
    content: str
    content_hash: str


@dataclass(frozen=True)
class BindingRef:
    """Local variable alias or expression binding for conservative data-flow resolution."""

    target_name: str
    file_path: str
    line: int
    column: int | None = None
    scope: str = ""
    expr_kind: str = "IDENTIFIER"  # IDENTIFIER | ATTRIBUTE | DICT_LITERAL | LIST_LITERAL | SUBSCRIPT | DYNAMIC
    source_expr: str = ""
    is_conditional: bool = False
    base_expr: str = ""
    attr_name: str = ""
    dict_entries: tuple[tuple[str, str], ...] = ()
    list_entries: tuple[str, ...] = ()
    subscript_target: str | None = None
    subscript_key: str | None = None
    subscript_index: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "target_name": self.target_name,
            "file_path": self.file_path,
            "line": self.line,
            "column": self.column,
            "scope": self.scope,
            "expr_kind": self.expr_kind,
            "source_expr": self.source_expr,
            "is_conditional": self.is_conditional,
            "base_expr": self.base_expr,
            "attr_name": self.attr_name,
            "dict_entries": list(self.dict_entries),
            "list_entries": list(self.list_entries),
            "subscript_target": self.subscript_target,
            "subscript_key": self.subscript_key,
            "subscript_index": self.subscript_index,
        }


@dataclass(frozen=True)
class RegistrationRef:
    """Explicit registry, dispatch mapping, or event listener fact."""

    pattern: str  # CALL_REGISTER | DICT_ASSIGN | EVENT_ON | SUBSCRIBE | COMMAND
    registry_expr: str
    key_or_event: str
    target_expr: str
    file_path: str
    line: int
    scope: str = ""
    is_conditional: bool = False
    is_dynamic_key: bool = False
    is_dynamic_target: bool = False
    evidence: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "pattern": self.pattern,
            "registry_expr": self.registry_expr,
            "key_or_event": self.key_or_event,
            "target_expr": self.target_expr,
            "file_path": self.file_path,
            "line": self.line,
            "scope": self.scope,
            "is_conditional": self.is_conditional,
            "is_dynamic_key": self.is_dynamic_key,
            "is_dynamic_target": self.is_dynamic_target,
            "evidence": self.evidence,
        }

