# CodeGraph Agent Rule Pack

Deterministic, compact agent rules generated from `src/codegraph/agent_rules.py`.

## Rule Files

| File | Target Agent / Environment |
| :--- | :--- |
| `AGENTS.md` | Universal `AGENTS.md` standard |
| `GEMINI.md` | Gemini CLI / Google AI agents |
| `antigravity.md` | Google Antigravity IDE & CLI (`.agents/rules/codegraph.md`) |
| `claude.md` | Claude Code (`CLAUDE.md`) |
| `cursor.md` | Cursor (`.cursorrules`) |
| `codex.md` | OpenAI Codex agents |
| `cline.md` | Cline (`.clinerules`) |
| `tool-capabilities-summary.md` | Compact task -> preferred tool -> follow-up -> evidence table |

## MCP Server Configuration

```json
{
  "mcpServers": {
    "codegraph": {
      "command": "codegraph",
      "args": ["mcp", "serve"]
    }
  }
}
```

## Recommended MCP Profiles

- **`agent`** (`--profile agent`): Focused 14-tool agent workflow (`find_symbol`, `search_code`, `find_references`, `find_callers`, `find_callees`, `find_tests`, `find_routes`, `get_symbol`, `get_file`, `get_context`, `get_architecture`, `get_git_impact`, `trace_path`, `trace_flow`).
- **`core`** (`--profile core`): Simple symbol lookup, relationship queries, and context-light sessions (13 core tools).
- **`graph`** (`--profile graph`): Tracing, change-impact, test discovery, and architecture sessions (17 tools).
- **`minimal`** (`--profile minimal`): Core interrogation + `get_context` and `read_file` (21 tools).
- **`developer`** (`--profile developer`): Full interactive development with git history and impact tools (34 tools).
- **`full`** (`--profile full`): All 56 MCP tools (including Database Intelligence and Runtime Reconciliation) for complete administration and diagnostics.
