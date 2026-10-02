from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.fastmcp.exceptions import ToolError

from codegraph.indexing import Indexer
from codegraph.mcp import create_server


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "auth.py").write_text("""class AuthService:
    def login(self, email):
        return email

def handler(email):
    return AuthService().login(email)
""")
    (tmp_path / ".env").write_text("TOKEN=secret")
    Indexer(tmp_path).index()
    return tmp_path


async def _direct_calls(repo: Path) -> None:
    server = create_server(repo)
    names = {tool.name for tool in await server.list_tools()}
    assert {
        "search_code", "read_file", "find_symbol", "trace_call", "get_graph",
        "search_memory", "get_evidence",
    } <= names
    result, structured = await server.call_tool("search_code", {"query": "login", "top_k": 1})
    assert "auth.py" in result[0].text and structured["result"][0]["file"] == "auth.py"
    read, _ = await server.call_tool("read_file", {"path": "auth.py", "start_line": 1, "end_line": 3})
    assert "AuthService" in read[0].text
    with pytest.raises(ToolError, match="sensitive"):
        await server.call_tool("read_file", {"path": ".env"})
    graph, metadata = await server.call_tool("get_graph", {"limit": 10})
    assert graph and metadata["result"][0]["confidence"] == "HIGH"
    evidence, metadata = await server.call_tool(
        "get_evidence", {"path": "auth.py", "symbol": "AuthService.login"}
    )
    assert "AuthService.login" in evidence[0].text
    assert metadata["result"][0]["evidence_type"] == "source"


def test_mcp_tool_schemas_and_direct_calls(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    asyncio.run(_direct_calls(repo))


async def _protocol_flow(repo: Path) -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "codegraph.cli", "serve", "-r", str(repo)],
    )
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert any(tool.name == "search_code" for tool in tools.tools)
            search = await session.call_tool("search_code", {"query": "login", "top_k": 1})
            assert not search.isError and "auth.py" in search.content[0].text
            read = await session.call_tool("read_file", {"path": "auth.py", "start_line": 1, "end_line": 3})
            assert not read.isError and "AuthService" in read.content[0].text
            symbol = await session.call_tool("find_symbol", {"name": "login"})
            assert not symbol.isError and "AuthService.login" in symbol.content[0].text
            trace = await session.call_tool("trace_call", {"symbol": "login"})
            assert not trace.isError and "HIGH" in trace.content[0].text
            blocked = await session.call_tool("read_file", {"path": "../outside"})
            assert blocked.isError


def test_mcp_stdio_protocol_flow(tmp_path: Path) -> None:
    asyncio.run(_protocol_flow(_repo(tmp_path)))
