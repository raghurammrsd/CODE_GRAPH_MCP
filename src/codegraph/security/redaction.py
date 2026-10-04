"""Secret detection, connection-string sanitization, SQL parameter redaction, and SQLite security auditing.

Core Principle:
    CodeGraph may understand that a secret exists (e.g. `READS_ENV DATABASE_URL`,
    `provider=postgresql`, `table=products`).
    CodeGraph must NEVER reveal, index, persist, or return the secret value itself.

Boundaries protected by this module:
    1. Indexing & FTS chunk persistence
    2. Text search (`search_code`)
    3. File inspection (`get_file`, `read_file`)
    4. Context compilation (`get_context`)
    5. Database discovery, schema extraction & migration analysis
    6. Runtime trace / event / SQL log ingestion & querying
    7. MCP responses, diagnostics, logs & error messages
"""
from __future__ import annotations

import ast
import math
import re
import sqlite3
from typing import Any, cast

REDACTED_TOKEN = "[REDACTED]"
REDACTED_SECRET = "[REDACTED_SECRET]"
REDACTED_PRIVATE_KEY = "[REDACTED_PRIVATE_KEY]"
REDACTED_DB_CREDENTIALS = "DATABASE_CREDENTIALS: REDACTED"

# Environment variable / config key names that hold secrets
SECRET_ENV_EXACT_NAMES: frozenset[str] = frozenset({
    "DATABASE_URL",
    "DATABASE_URI",
    "SQLALCHEMY_DATABASE_URI",
    "TEST_DATABASE_URL",
    "ASYNC_DATABASE_URL",
    "DIRECT_URL",
    "SHADOW_DATABASE_URL",
    "REDIS_URL",
    "REDIS_URI",
    "MONGO_URI",
    "MONGODB_URI",
    "DB_PASSWORD",
    "DB_PASS",
    "DB_SECRET",
    "DB_USER",
    "DB_USERNAME",
    "POSTGRES_PASSWORD",
    "MYSQL_PASSWORD",
    "MYSQL_ROOT_PASSWORD",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "HF_TOKEN",
    "HUGGINGFACE_TOKEN",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GITLAB_TOKEN",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SESSION_TOKEN",
    "AZURE_CLIENT_SECRET",
    "GCP_SERVICE_ACCOUNT_KEY",
    "STRIPE_SECRET_KEY",
    "STRIPE_API_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "SMTP_PASSWORD",
    "SENDGRID_API_KEY",
    "TWILIO_AUTH_TOKEN",
    "JWT",
    "JWT_SECRET",
    "JWT_SECRET_KEY",
    "SECRET_KEY",
    "APP_SECRET",
    "API_KEY",
    "ACCESS_TOKEN",
    "REFRESH_TOKEN",
    "BEARER_TOKEN",
    "CLIENT_SECRET",
    "OAUTH_CLIENT_SECRET",
    "WEBHOOK_SECRET",
    "ENCRYPTION_KEY",
    "SIGNING_KEY",
    "PRIVATE_KEY",
    "SSH_PRIVATE_KEY",
    "COOKIE_SECRET",
    "SESSION_SECRET",
})

SECRET_ENV_SUFFIXES: tuple[str, ...] = (
    "_PASSWORD",
    "_PASS",
    "_PASSWD",
    "_SECRET",
    "_SECRET_KEY",
    "_TOKEN",
    "_API_KEY",
    "_APIKEY",
    "_PRIVATE_KEY",
    "_ACCESS_KEY",
    "_CLIENT_SECRET",
    "_WEBHOOK_SECRET",
    "_SIGNING_KEY",
    "_ENCRYPTION_KEY",
    "_AUTH_TOKEN",
    "_CREDENTIALS",
    "_CONN_STR",
    "_CONNECTION_STRING",
)

# Sensitive HTTP / Runtime telemetry keys that must never be persisted
SENSITIVE_RUNTIME_KEYS: frozenset[str] = frozenset({
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-auth-token",
    "x-csrf-token",
    "x-access-token",
    "password",
    "passwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "api_key",
    "apikey",
    "client_secret",
    "private_key",
    "request_body",
    "response_body",
    "raw_body",
    "body",
    "payload",
    "form_data",
    "credentials",
    "connection_string",
    "db.connection_string",
    "db.password",
    "db.user",
    "http.request.header.authorization",
    "http.request.header.cookie",
    "http.response.header.set_cookie",
    "http.request.body",
    "http.response.body",
    "session_id",
    "sessionid",
    "jwt",
})

# 1. PEM / SSH / PGP Private Key block pattern (multiline)
_PRIVATE_KEY_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z0-9 _-]*PRIVATE KEY(?:\s+BLOCK)?-----"
    r"[\s\S]*?"
    r"-----END [A-Z0-9 _-]*PRIVATE KEY(?:\s+BLOCK)?-----",
    re.MULTILINE,
)

# 2. Database URLs with credentials:
# e.g. postgresql://admin:FakePassword123@localhost:5432/shop
# e.g. mysql+pymysql://user:pass@host/db
_DB_CONN_URL_RE = re.compile(
    r"\b(?P<scheme>(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis(?:s)?|mssql|oracle|cockroachdb|clickhouse|amqp(?:s)?)"
    r"(?:\+[a-z0-9_]+)?)://"
    r"(?P<userinfo>[^/\s@\"'`]+@)"
    r"(?P<hostpath>[^\s\"'`,;)]+)",
    re.IGNORECASE,
)

# 3. Well-known API key / token formats
_KNOWN_TOKEN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # OpenAI / Stripe / Anthropic style sk-... keys (including sk-test-..., sk-live-..., sk-proj-...)
    (re.compile(r"\bsk-(?:test-|live-|proj-|ant-)?[A-Za-z0-9_-]{4,}\b"), REDACTED_SECRET),
    (re.compile(r"\brk_(?:test|live)_[A-Za-z0-9]{4,}\b"), REDACTED_SECRET),
    # Google / Gemini API keys (AIza...)
    (re.compile(r"\bAIza[0-9A-Za-z_-]{16,}\b"), REDACTED_SECRET),
    # AWS Access Key IDs
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), REDACTED_SECRET),
    # GitHub tokens
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{16,}\b"), REDACTED_SECRET),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{16,}\b"), REDACTED_SECRET),
    # GitLab tokens
    (re.compile(r"\bglpat-[A-Za-z0-9_-]{10,}\b"), REDACTED_SECRET),
    # Hugging Face tokens
    (re.compile(r"\bhf_[A-Za-z0-9]{10,}\b"), REDACTED_SECRET),
    # Slack tokens
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), REDACTED_SECRET),
    # Standard JWT (3 dot-separated base64url segments starting with eyJ)
    (re.compile(r"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\b"), REDACTED_SECRET),
    # Authorization Bearer / Basic header values
    (
        re.compile(
            r"(?i)\b(Authorization\s*[:=]\s*[\"']?(?:Bearer|Basic|Token)\s+)([^\s\"'`,;]+)"
        ),
        r"\1[REDACTED]",
    ),
)

# 4. Secret environment / config assignment pattern:
# Matches KEY = "value", KEY='value', KEY=value, "KEY": "value"
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?P<prefix>\b(?P<key>[A-Za-z_][A-Za-z0-9_]*)\b"
    r"(?:\s*\"?\s*[:=]\s*))"
    r"(?P<quote>[\"']?)"
    r"(?P<val>[^\s\"'#,;}\]\n]+)"
    r"(?P=quote)"
)


def is_secret_variable_name(name: str) -> bool:
    """Return True if an identifier or environment variable name denotes a secret or credential."""
    if not name:
        return False
    upper = name.strip().upper()
    if upper in SECRET_ENV_EXACT_NAMES:
        return True
    if any(upper.endswith(suffix) for suffix in SECRET_ENV_SUFFIXES):
        return True
    if "PASSWORD" in upper or "PRIVATE_KEY" in upper or "SECRET_KEY" in upper or "API_KEY" in upper:
        return True
    return False


def _shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    length = len(value)
    counts: dict[str, int] = {}
    for ch in value:
        counts[ch] = counts.get(ch, 0) + 1
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


def is_probable_secret_value(value: str, key_hint: str = "") -> bool:
    """Conservative secret value detector combining key-name rules, known prefixes, and entropy."""
    cleaned = value.strip().strip("\"'")
    if not cleaned or cleaned in (
        REDACTED_TOKEN,
        REDACTED_SECRET,
        REDACTED_PRIVATE_KEY,
        "REDACTED",
        "***",
        "None",
        "null",
        "true",
        "false",
        "True",
        "False",
        "localhost",
        "127.0.0.1",
        "postgres",
        "postgresql",
        "sqlite",
        "mysql",
    ):
        return False
    # Ignore code expressions such as os.getenv(...), os.environ.get(...), settings.X
    if cleaned.startswith(("os.", "settings.", "config.", "env.", "${", "$(")):
        return False
    if is_secret_variable_name(key_hint):
        return True
    if _PRIVATE_KEY_BLOCK_RE.search(cleaned) or _DB_CONN_URL_RE.search(cleaned):
        return True
    for pat, _ in _KNOWN_TOKEN_PATTERNS:
        if pat.search(cleaned):
            return True
    # High-entropy long token check
    if len(cleaned) >= 24 and _shannon_entropy(cleaned) >= 4.2 and not ("/" in cleaned or "." in cleaned):
        return True
    return False


def redact_connection_string(url: str) -> str:
    """Redact credentials in a database connection string while preserving structural host/db metadata.

    Example:
        postgresql://admin:FakePassword123@localhost:5432/shop
        -> postgresql://***:***@localhost:5432/shop
    """
    if not url:
        return url

    def _repl(match: re.Match[str]) -> str:
        scheme = match.group("scheme")
        hostpath = match.group("hostpath")
        return f"{scheme}://***:***@{hostpath}"

    redacted = _DB_CONN_URL_RE.sub(_repl, url) if "://" in url else url
    # Also redact query-string password/api_key parameters if present
    if "=" in redacted and ("?" in redacted or "&" in redacted):
        redacted = _CONN_QUERY_PARAM_RE.sub(r"\1[REDACTED]", redacted)
    return redacted


_CONN_QUERY_PARAM_RE = re.compile(
    r"(?i)([?&](?:password|passwd|pwd|secret|token|api_key|access_token)=)([^&\s\"']+)"
)

_KNOWN_TOKEN_TRIGGER_RE = re.compile(
    r"\b(?:sk-|rk_|AIza|AKIA|ASIA|gh[pousr]_|github_pat_|glpat-|hf_|xox[baprs]-|eyJ)|(?i:\bAuthorization\s*[:=])"
)


def parse_safe_connection_metadata(url: str) -> dict[str, str]:
    """Extract only safe structural database metadata from a connection URL, redacting credentials."""
    match = _DB_CONN_URL_RE.search(url or "")
    if not match:
        if "sqlite" in (url or "").lower():
            return {
                "provider": "sqlite",
                "dialect": "sqlite",
                "host": "local",
                "port": "",
                "database": "sqlite",
                "database_name": "sqlite",
                "credentials": "REDACTED",
            }
        return {
            "provider": "UNKNOWN",
            "dialect": "UNKNOWN",
            "host": "",
            "port": "",
            "database": "UNKNOWN",
            "database_name": "UNKNOWN",
            "credentials": "REDACTED",
        }
    scheme = match.group("scheme").lower().split("+")[0]
    if scheme == "postgres":
        scheme = "postgresql"
    dialect = "postgres" if scheme in ("postgres", "postgresql") else scheme
    hostpath = match.group("hostpath")
    host_port, _, db_name = hostpath.partition("/")
    db_name = db_name.split("?")[0] or "UNKNOWN"
    host, _, port = host_port.partition(":")
    return {
        "provider": scheme,
        "dialect": dialect,
        "host": host or "localhost",
        "port": port or "",
        "database": db_name,
        "database_name": db_name,
        "credentials": "REDACTED",
    }


def redact_secrets(text: str) -> str:
    """Deterministically redact private keys, DB credentials, API keys, JWTs, and secret assignments."""
    if not text:
        return text

    # 1. Private key blocks
    out = _PRIVATE_KEY_BLOCK_RE.sub(REDACTED_PRIVATE_KEY, text) if "PRIVATE KEY" in text else text

    # 2. Database connection URLs with embedded user:password@
    if "://" in out or ("=" in out and ("?" in out or "&" in out)):
        out = redact_connection_string(out)

    # 3. Known API key and token formats
    if _KNOWN_TOKEN_TRIGGER_RE.search(out):
        for pat, replacement in _KNOWN_TOKEN_PATTERNS:
            out = pat.sub(replacement, out)

    # 4. Secret variable assignments (e.g. OPENAI_API_KEY=..., GEMINI_API_KEY=..., JWT=..., AWS_SECRET_ACCESS_KEY=...)
    if "=" in out or ":" in out:
        def _assign_repl(match: re.Match[str]) -> str:
            key = match.group("key")
            prefix = match.group("prefix")
            quote = match.group("quote")
            val = match.group("val")
            if not is_secret_variable_name(key):
                return match.group(0)
            # Do not redact safe code references like os.environ / os.getenv / None
            if val.startswith(("os.", "settings.", "config.", "env.", "None", "null", "[REDACTED")):
                return match.group(0)
            # If the value is a DB connection URL that was already user/pass redacted, still redact if assigned to DATABASE_URL
            if key.upper() in ("DATABASE_URL", "DATABASE_URI", "SQLALCHEMY_DATABASE_URI", "REDIS_URL", "MONGO_URI"):
                if "://***:***@" in val:
                    return f"{prefix}{quote}{val}{quote}"
                return f"{prefix}{quote}{REDACTED_TOKEN}{quote}"
            return f"{prefix}{quote}{REDACTED_TOKEN}{quote}"

        out = _SECRET_ASSIGNMENT_RE.sub(_assign_repl, out)
    return out


def contains_private_key(text: str) -> bool:
    """Return True if text contains a PEM, RSA, EC, OpenSSH, or PGP private key block."""
    if not text or "PRIVATE KEY" not in text:
        return False
    return bool(_PRIVATE_KEY_BLOCK_RE.search(text))


def normalize_and_redact_sql(sql: str) -> str:
    """Normalize SQL queries and redact all literal bound parameter values.

    Example:
        INSERT INTO users(email, password) VALUES ('user@example.com', 'secret123')
        -> INSERT INTO users(email, password) VALUES (?, ?)
    """
    if not sql:
        return ""
    cleaned = redact_secrets(sql.strip())
    # Replace single-quoted SQL string literals with '?'
    cleaned = re.sub(r"'(?:''|[^'])*'", "?", cleaned)
    # Replace double-quoted literals inside VALUES (...) or = "..." with '?'
    cleaned = re.sub(r"(?i)(\bVALUES\s*\([^)]*)", lambda m: re.sub(r'"[^"]*"', "?", m.group(1)), cleaned)
    # Replace numeric literals inside VALUES (...) or after = / IN
    cleaned = re.sub(r"(?i)(=\s*)\b\d+(?:\.\d+)?\b", r"\1?", cleaned)
    cleaned = re.sub(
        r"(?i)(\bVALUES\s*\()([^)]+)(\))",
        lambda m: m.group(1) + ", ".join("?" for _ in m.group(2).split(",")) + m.group(3),
        cleaned,
    )
    # Collapse excessive whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def redact_payload[T](obj: T) -> T:
    """Recursively redact secrets, credentials, headers, cookies, and raw bodies from dicts/lists/strings."""
    if obj is None:
        return obj
    if isinstance(obj, str):
        return cast(T, redact_secrets(obj))
    if isinstance(obj, (int, float, bool)):
        return obj
    if isinstance(obj, list):
        return cast(T, [redact_payload(item) for item in obj])
    if isinstance(obj, tuple):
        return cast(T, tuple(redact_payload(item) for item in obj))
    if isinstance(obj, dict):
        sanitized: dict[str, Any] = {}
        for k, v in obj.items():
            key_str = str(k)
            key_lower = key_str.lower().strip()
            if key_lower in SENSITIVE_RUNTIME_KEYS or is_secret_variable_name(key_str):
                sanitized[key_str] = REDACTED_TOKEN
            elif key_lower in ("sql", "statement", "db.statement", "query_text", "normalized_sql") and isinstance(v, str):
                sanitized[key_str] = normalize_and_redact_sql(v)
            else:
                sanitized[key_str] = redact_payload(v)
        return cast(T, sanitized)
    return obj


def detect_env_variable_reads(
    content: str,
    file_path: str,
    module_name: str = "",
    tree: ast.AST | None = None,
) -> list[dict[str, Any]]:
    """Detect environment variable reads (`os.getenv`, `os.environ.get`, `os.environ[...]`)
    without ever recording the secret value itself.
    """
    results: list[dict[str, Any]] = []
    if not content:
        return results

    if file_path.endswith(".py"):
        if "getenv" not in content and "environ" not in content:
            return results
        if tree is None:
            try:
                tree = ast.parse(content)
            except SyntaxError:
                tree = None

        if tree is not None:
            current_scope: list[str] = []

            def _visit(node: ast.AST, scope_stack: list[str]) -> None:
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    next_scope = [*scope_stack, node.name]
                    for child in ast.iter_child_nodes(node):
                        _visit(child, next_scope)
                    return

                # Match os.getenv("DATABASE_URL") or os.environ.get("DATABASE_URL")
                if isinstance(node, ast.Call):
                    func_name = ""
                    if isinstance(node.func, ast.Attribute):
                        if isinstance(node.func.value, ast.Name) and node.func.value.id in ("os", "environ"):
                            func_name = f"{node.func.value.id}.{node.func.attr}"
                        elif (
                            isinstance(node.func.value, ast.Attribute)
                            and isinstance(node.func.value.value, ast.Name)
                            and node.func.value.value.id == "os"
                            and node.func.value.attr == "environ"
                        ):
                            func_name = f"os.environ.{node.func.attr}"
                    if func_name in ("os.getenv", "environ.get", "os.environ.get") and node.args:
                        first_arg = node.args[0]
                        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                            env_name = first_arg.value.strip()
                            if env_name:
                                src_id = (
                                    f"{module_name}.{'.'.join(scope_stack)}"
                                    if module_name and scope_stack
                                    else (module_name or file_path)
                                )
                                results.append({
                                    "source": src_id,
                                    "target": f"env.{env_name}",
                                    "env_name": env_name,
                                    "is_secret": is_secret_variable_name(env_name),
                                    "relationship": "READS_ENV",
                                    "file": file_path,
                                    "line": getattr(node, "lineno", 1),
                                    "evidence": f"{func_name}({env_name!r})",
                                    "confidence": "HIGH",
                                    "evidence_class": "AST_VERIFIED",
                                })

                # Match os.environ["DATABASE_URL"]
                if isinstance(node, ast.Subscript):
                    is_os_environ = (
                        isinstance(node.value, ast.Attribute)
                        and isinstance(node.value.value, ast.Name)
                        and node.value.value.id == "os"
                        and node.value.attr == "environ"
                    ) or (isinstance(node.value, ast.Name) and node.value.id == "environ")
                    if is_os_environ and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                        env_name = node.slice.value.strip()
                        if env_name:
                            src_id = (
                                f"{module_name}.{'.'.join(scope_stack)}"
                                if module_name and scope_stack
                                else (module_name or file_path)
                            )
                            results.append({
                                "source": src_id,
                                "target": f"env.{env_name}",
                                "env_name": env_name,
                                "is_secret": is_secret_variable_name(env_name),
                                "relationship": "READS_ENV",
                                "file": file_path,
                                "line": getattr(node, "lineno", 1),
                                "evidence": f"os.environ[{env_name!r}]",
                                "confidence": "HIGH",
                                "evidence_class": "AST_VERIFIED",
                            })

                for child in ast.iter_child_nodes(node):
                    _visit(child, scope_stack)

            _visit(tree, current_scope)

    # Also detect process.env.VAR_NAME in JS/TS or module-level secret variable names
    for line_no, raw_line in enumerate(content.splitlines(), start=1):
        for m in re.finditer(r"\bprocess\.env\.([A-Z_][A-Z0-9_]*)\b", raw_line):
            env_name = m.group(1)
            results.append({
                "source": module_name or file_path,
                "target": f"env.{env_name}",
                "env_name": env_name,
                "is_secret": is_secret_variable_name(env_name),
                "relationship": "READS_ENV",
                "file": file_path,
                "line": line_no,
                "evidence": f"process.env.{env_name}",
                "confidence": "HIGH",
                "evidence_class": "AST_VERIFIED",
            })

    return results


def audit_sqlite_for_secrets(
    con: sqlite3.Connection,
    seeded_secrets: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """Scan all SQLite tables (including FTS, graph_edges, chunks, database, and runtime tables)
    to verify that zero raw secret values or seeded test secrets were persisted.
    """
    violations: list[dict[str, Any]] = []
    tables = [
        str(r[0])
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]

    for tbl in tables:
        # Skip internal FTS shadow tables except the main content view
        if tbl.startswith("chunks_fts_") and tbl != "chunks_fts":
            continue
        try:
            rows = con.execute(f'SELECT * FROM "{tbl}"').fetchall()
        except sqlite3.OperationalError:
            continue

        for row_idx, row in enumerate(rows):
            if hasattr(row, "keys"):
                row_vals = [str(row[k]) for k in row.keys() if row[k] is not None]
            else:
                row_vals = [str(v) for v in row if v is not None]
            joined = " | ".join(row_vals)

            # Check explicit seeded secrets
            for secret in seeded_secrets:
                if secret and secret in joined:
                    violations.append({
                        "table": tbl,
                        "row_index": row_idx,
                        "reason": f"Seeded secret found in table '{tbl}'",
                        "matched": secret[:6] + "***",
                    })

            # Check private key blocks or unredacted DB URLs
            if _PRIVATE_KEY_BLOCK_RE.search(joined):
                violations.append({
                    "table": tbl,
                    "row_index": row_idx,
                    "reason": f"Unredacted private key block in table '{tbl}'",
                })
            for m in _DB_CONN_URL_RE.finditer(joined):
                if "***:***" not in m.group(0) and "[REDACTED]" not in m.group(0) and "<REDACTED>" not in m.group(0):
                    violations.append({
                        "table": tbl,
                        "row_index": row_idx,
                        "reason": f"Unredacted database connection string in table '{tbl}'",
                    })

    return {
        "clean": len(violations) == 0,
        "tables_scanned": len(tables),
        "violation_count": len(violations),
        "violations": violations,
        "findings": violations,
    }
