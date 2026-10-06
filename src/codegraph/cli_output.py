"""Centralized cross-platform CLI output utility for Windows/macOS/Linux encoding safety.

Guarantees:
- Never assumes stdout/stderr is UTF-8 (safe on Windows cp1252, cp437, ASCII, and redirected pipes).
- Preserves rich Unicode symbols (`✓`, `✗`, `⚠`, `↻`, `(•)`) when the target stream supports them.
- Automatically degrades to deterministic ASCII markers (`[OK]`, `[ERROR]`, `[WARN]`, `[REPAIRED]`, `(*)`)
  when the stream encoding does not support Unicode box/status glyphs.
- Ensures `--json` output is strictly machine-readable and never contains decorative Unicode glyphs.
"""
from __future__ import annotations

import codecs
import os
import sys
from dataclasses import dataclass
from typing import Any, TextIO

import typer

_PROBE_GLYPHS = "✓✗⚠↻•→↓─—–├──└──│📄📞🌐🧪💾⚠️✅❌"

# Ordered replacements so multi-char patterns (e.g. "(•)") are replaced before single chars ("•")
_UNICODE_TO_ASCII_MAP: tuple[tuple[str, str], ...] = (
    ("(•)", "(*)"),
    ("├── ", "|-- "),
    ("└── ", "\\-- "),
    ("├──", "|--"),
    ("└──", "\\--"),
    ("├─", "|-"),
    ("└─", "\\-"),
    ("│", "|"),
    ("─", "-"),
    ("✓", "[OK]"),
    ("✗", "[ERROR]"),
    ("⚠", "[WARN]"),
    ("↻", "[REPAIRED]"),
    ("⚠️", "[WARN]"),
    ("✅", "[OK]"),
    ("❌", "[ERROR]"),
    ("📄", "[FILE]"),
    ("📞", "[CALLER]"),
    ("🌐", "[ROUTE]"),
    ("🧪", "[TEST]"),
    ("💾", "[DB]"),
    ("•", "*"),
    ("→", "->"),
    ("↓", "v"),
    ("—", "--"),
    ("–", "-"),
)


@dataclass(frozen=True)
class CliSymbols:
    """Encoding-aware CLI status symbols."""

    unicode_enabled: bool
    ok: str
    error: str
    warn: str
    repair: str
    radio_on: str
    radio_off: str
    arrow_right: str
    arrow_down: str


UNICODE_SYMBOLS = CliSymbols(
    unicode_enabled=True,
    ok="✓",
    error="✗",
    warn="⚠",
    repair="↻",
    radio_on="(•)",
    radio_off="( )",
    arrow_right="→",
    arrow_down="↓",
)

ASCII_SYMBOLS = CliSymbols(
    unicode_enabled=False,
    ok="[OK]",
    error="[ERROR]",
    warn="[WARN]",
    repair="[REPAIRED]",
    radio_on="(*)",
    radio_off="( )",
    arrow_right="->",
    arrow_down="v",
)


def detect_stream_encoding(stream: Any = None) -> str:
    """Safely detect the character encoding of `stream` (defaults to `sys.stdout`)."""
    target = stream if stream is not None else sys.stdout
    enc = getattr(target, "encoding", None)
    if not enc or not isinstance(enc, str):
        return "ascii"
    try:
        info = codecs.lookup(enc)
        return info.name
    except LookupError:
        return "ascii"


def supports_unicode(
    stream: Any = None,
    *,
    unicode_override: bool | None = None,
) -> bool:
    """Return True if `stream` can encode all CodeGraph Unicode status glyphs without error."""
    if unicode_override is not None:
        return unicode_override

    env_ascii = os.environ.get("CODEGRAPH_ASCII_OUTPUT", "").strip().lower()
    if env_ascii in ("1", "true", "yes", "on"):
        return False

    env_unicode = os.environ.get("CODEGRAPH_UNICODE_OUTPUT", "").strip().lower()
    if env_unicode in ("1", "true", "yes", "on"):
        return True
    if env_unicode in ("0", "false", "no", "off"):
        return False

    enc = detect_stream_encoding(stream)
    try:
        _PROBE_GLYPHS.encode(enc, errors="strict")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def get_cli_symbols(
    stream: Any = None,
    *,
    unicode_override: bool | None = None,
) -> CliSymbols:
    """Return `UNICODE_SYMBOLS` when supported by `stream`, else `ASCII_SYMBOLS`."""
    if supports_unicode(stream, unicode_override=unicode_override):
        return UNICODE_SYMBOLS
    return ASCII_SYMBOLS


def sanitize_text_for_stream(
    text: str,
    stream: Any = None,
    *,
    unicode_override: bool | None = None,
) -> str:
    """Format `text` safely for `stream`, converting decorative Unicode when unsupported."""
    if not text:
        return text

    target = stream if stream is not None else sys.stdout
    use_unicode = supports_unicode(target, unicode_override=unicode_override)
    out = text
    if not use_unicode:
        for uni_tok, ascii_tok in _UNICODE_TO_ASCII_MAP:
            if uni_tok in out:
                out = out.replace(uni_tok, ascii_tok)

    enc = detect_stream_encoding(target)
    try:
        out.encode(enc, errors="strict")
        return out
    except (UnicodeEncodeError, LookupError):
        # Replace any remaining unencodable glyphs cleanly so write() never raises UnicodeEncodeError
        for uni_tok, ascii_tok in _UNICODE_TO_ASCII_MAP:
            if uni_tok in out:
                out = out.replace(uni_tok, ascii_tok)
        return out.encode(enc, errors="replace").decode(enc, errors="replace")


def sanitize_json_string(raw_json: str, stream: Any = None) -> str:
    """Ensure machine-readable JSON output never crashes non-UTF-8 streams."""
    enc = detect_stream_encoding(stream)
    try:
        raw_json.encode(enc, errors="strict")
        return raw_json
    except (UnicodeEncodeError, LookupError):
        # Escape non-ASCII characters using standard JSON \uXXXX escapes
        return raw_json.encode("unicode_escape").decode("ascii")


def cli_echo(
    message: str = "",
    *,
    nl: bool = True,
    err: bool = False,
    json_mode: bool = False,
    stream: TextIO | None = None,
    unicode_override: bool | None = None,
) -> None:
    """Centralized safe CLI output function replacing raw `typer.echo`."""
    target = stream if stream is not None else (sys.stderr if err else sys.stdout)
    if json_mode:
        safe_msg = sanitize_json_string(str(message), target)
    else:
        safe_msg = sanitize_text_for_stream(str(message), target, unicode_override=unicode_override)

    if stream is not None:
        stream.write(safe_msg + ("\n" if nl else ""))
        stream.flush()
    else:
        typer.echo(safe_msg, nl=nl, err=err)
