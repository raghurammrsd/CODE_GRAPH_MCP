"""Tests for new MCP workflow tools: compile_task, plan_retrieval, resources, and prompts."""
import asyncio
from pathlib import Path

from codegraph.indexing import Indexer
from codegraph.mcp import create_server


def _create_sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "mcp_sample_repo"
    repo.mkdir()
    (repo / "auth.py").write_text("""class AuthService:
    def login(self, email: str, password: str) -> bool:
        return True

def handle_login(email: str):
    return AuthService().login(email, "secret")
""")
    Indexer(repo).index()
    return repo


async def _run_mcp_workflow_tests(repo: Path) -> None:
    server = create_server(repo)
    tools = await server.list_tools()
    tool_names = {t.name for t in tools}

    assert "compile_task" in tool_names
    assert "plan_retrieval" in tool_names
    assert "get_context" in tool_names
    assert "get_recent_changes" in tool_names
    assert "get_file_history" in tool_names
    assert "analyze_change_impact" in tool_names

    # Test plan_retrieval
    plan_res, plan_meta = await server.call_tool(
        "plan_retrieval",
        {"task": "Debug login failure in handle_login", "max_tokens": 5000},
    )
    assert plan_res is not None
    # Depending on fastmcp return format, check either plan_res or plan_meta
    plan_dict = plan_meta.get("result") or plan_meta
    assert "query_groups" in plan_dict
    assert plan_dict["schema_version"] == "1.0"

    # Test compile_task
    compile_res, compile_meta = await server.call_tool(
        "compile_task",
        {"task": "Understand AuthService", "max_tokens": 4000},
    )
    assert compile_res is not None
    compile_dict = compile_meta.get("result") or compile_meta
    assert "task_spec" in compile_dict
    assert "retrieval_plan" in compile_dict
    assert "ambiguities" in compile_dict

    # Test get_context
    ctx_res, ctx_meta = await server.call_tool(
        "get_context",
        {"task": "Explain AuthService", "max_tokens": 4000},
    )
    assert ctx_res is not None
    ctx_dict = ctx_meta.get("result") or ctx_meta
    assert "files" in ctx_dict
    assert ctx_dict["task"] == "Explain AuthService"

    # Test resources
    resources = await server.list_resources()
    resource_uris = {str(r.uri) for r in resources}
    assert "codebase://status" in resource_uris
    assert "codebase://architecture" in resource_uris
    assert "codebase://modules" in resource_uris
    assert "codebase://health" in resource_uris

    # Test prompts
    prompts = await server.list_prompts()
    prompt_names = {p.name for p in prompts}
    assert "understand_repository" in prompt_names
    assert "trace_request" in prompt_names
    assert "review_change" in prompt_names
    assert "debug_issue" in prompt_names


def test_mcp_workflow_tools(tmp_path: Path) -> None:
    repo = _create_sample_repo(tmp_path)
    asyncio.run(_run_mcp_workflow_tests(repo))
