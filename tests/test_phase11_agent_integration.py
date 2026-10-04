"""Phase 11 Tests — Agent Tool-Selection & MCP Integration Reliability.

Covers all 33 required areas (50 tests total):
- Capability manifest & determinism (no environment-specific paths)
- Task classification across all 13 categories
- Tool capability registry & mapping
- Deterministic rule generation (< 6,000 chars) for all 7 supported agents
- Antigravity MCP config example (`codegraph mcp serve`), rule, and 6-step skill (`SKILL.md`)
- `codegraph mcp doctor` health checks (executable, server startup, MCP initialize,
  tool discovery, resolve_symbol, get_context, get_callers, trace_path, test fixture query, clean shutdown)
- Read-only MCP configuration diagnostics (`CONFIGURED`, `NOT_CONFIGURED`, `INVALID`,
  `COMMAND_NOT_FOUND`, `SERVER_FAILED`, `TOOLS_UNAVAILABLE`) across macOS, Linux, and Windows
- Safe fallback policy & epistemic preservation (`UNKNOWN`, `POSSIBLE`, `AMBIGUOUS`, `STALE`)
- Tool description quality audit & MCP profile guidance (`core`, `graph`, `minimal`, `developer`, `full`)
- Rule robustness (simple-task bypass, no infinite loops, no repeated resolve_symbol, no tool spam)
- Local tool-usage observability (`ToolUsageRecord`, `get_tool_usage_summary`)
- 32-task evaluation harness, A/B rule effectiveness (Mode A vs Mode B), and Antigravity auth trace (Test A/B/C)
- Security & zero secret leakage in diagnostics
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codegraph.agent_capabilities import (
    CAPABILITY_MATRIX,
    MCP_PROFILE_RECOMMENDATIONS,
    RECOMMENDED_TOOL_SEQUENCES,
    TOOL_CAPABILITY_REGISTRY,
    AgentTaskCategory,
    classify_agent_task,
    evaluate_fallback_policy,
    get_capability_manifest,
    get_tool_capability,
)
from codegraph.agent_rules import (
    SUPPORTED_AGENTS,
    render_agent_rules,
    render_antigravity_mcp_config,
    render_antigravity_skill,
    write_agent_rule_pack,
)
from codegraph.cli import app
from codegraph.indexing.indexer import SCHEMA_VERSION
from codegraph.mcp import create_server
from codegraph.mcp_diagnostics import (
    MCPConfigStatus,
    audit_tool_descriptions,
    check_mcp_configuration,
    get_candidate_mcp_config_paths,
    run_mcp_doctor,
    sanitize_diagnostic_dict,
)
from codegraph.observability import MetricsRegistry, ToolUsageRecord
from codegraph.tool_selection_eval import (
    DEFAULT_TOOL_SELECTION_TASKS,
    run_antigravity_auth_trace_evaluation,
    run_tool_selection_ab_benchmark,
    validate_rule_robustness,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# 1. Capability Manifest & Determinism (Tests 1–5)
# ---------------------------------------------------------------------------


def test_01_capability_manifest_structure_and_fields() -> None:
    """1. get_capability_manifest() returns all required sections."""
    manifest = get_capability_manifest()
    for required_key in (
        "schema_version",
        "server_name",
        "version",
        "summary",
        "selection_principle",
        "capabilities",
        "profiles",
        "tool_mappings",
        "task_mappings",
        "recommended_sequences",
        "recommended_usage_order",
        "evidence_semantics",
        "limitations",
    ):
        assert required_key in manifest
    assert manifest["server_name"] == "codegraph"
    assert "repository relationships" in manifest["summary"]


def test_02_capability_manifest_is_deterministic_and_path_free() -> None:
    """2. Capability manifest is bit-for-bit deterministic and contains no environment-specific absolute paths."""
    m1 = json.dumps(get_capability_manifest(), sort_keys=True)
    m2 = json.dumps(get_capability_manifest(), sort_keys=True)
    assert m1 == m2
    assert "/Users/" not in m1
    assert "/home/" not in m1
    assert "C:\\" not in m1


def test_03_all_13_task_categories_defined_in_capability_matrix() -> None:
    """3. All 13 canonical AgentTaskCategory values exist in CAPABILITY_MATRIX."""
    expected = {
        "LOCAL_EDIT",
        "SYMBOL_LOOKUP",
        "RELATIONSHIP",
        "TRACE",
        "DEBUG",
        "CHANGE_IMPACT",
        "TEST_DISCOVERY",
        "ROUTE_DISCOVERY",
        "DIAGNOSTIC",
        "ARCHITECTURE",
        "PACKAGE",
        "MULTI_FILE_INVESTIGATION",
        "EXPLANATION",
    }
    actual = {c.value for c in AgentTaskCategory}
    assert actual == expected
    assert {c.value for c in CAPABILITY_MATRIX.keys()} == expected


def test_04_tool_capability_registry_completeness() -> None:
    """4. Every tool in TOOL_CAPABILITY_REGISTRY declares capability, task_types, inputs, outputs, and guarantees."""
    assert len(TOOL_CAPABILITY_REGISTRY) >= 16
    for spec in TOOL_CAPABILITY_REGISTRY:
        assert spec.tool_name
        assert spec.capability
        assert len(spec.task_types) >= 1
        assert spec.expected_output_type
        assert spec.evidence_guarantees
        assert spec.does_not_prove
        assert len(spec.useful_situations) >= 1
        assert len(spec.avoid_when) >= 1
        assert get_tool_capability(spec.tool_name) == spec


def test_05_recommended_tool_sequences_present() -> None:
    """5. Canonical recommended tool sequences cover auth lookup, callers, route trace, test impact, DI, and local edit."""
    assert len(RECOMMENDED_TOOL_SEQUENCES) >= 6
    questions = [str(s["question"]) for s in RECOMMENDED_TOOL_SEQUENCES]
    assert any("authentication" in q for q in questions)
    assert any("verify_password" in q for q in questions)
    assert any("route" in q for q in questions)
    assert any("tests" in q for q in questions)
    assert any("injected" in q for q in questions)


# ---------------------------------------------------------------------------
# 2. Task Classification & Tool Selection (Tests 6–15)
# ---------------------------------------------------------------------------


def test_06_classify_simple_local_edit_bypasses_codegraph() -> None:
    """6. Trivial single-file local edit classifies as LOCAL_EDIT and does NOT recommend CodeGraph."""
    res = classify_agent_task("Fix a typo in the docstring of format_date in utils/dates.py", file_count_hint=1)
    assert res.category == AgentTaskCategory.LOCAL_EDIT
    assert res.should_use_codegraph is False
    assert res.primary_tool is None
    assert res.direct_inspection_acceptable is True


def test_07_classify_symbol_lookup_task() -> None:
    """7. Symbol lookup question selects resolve_symbol."""
    res = classify_agent_task("Where is class UserRepository defined?")
    assert res.category == AgentTaskCategory.SYMBOL_LOOKUP
    assert res.should_use_codegraph is True
    assert res.primary_tool == "resolve_symbol"


def test_08_classify_relationship_callers_and_callees() -> None:
    """8. Caller/callee questions classify as RELATIONSHIP and select get_callers / get_callees."""
    res_callers = classify_agent_task("What calls verify_password?")
    assert res_callers.category == AgentTaskCategory.RELATIONSHIP
    assert res_callers.primary_tool == "get_callers"
    assert res_callers.recommended_sequence == ("resolve_symbol", "get_callers")

    res_callees = classify_agent_task("What does process_order call?")
    assert res_callees.category == AgentTaskCategory.RELATIONSHIP
    assert res_callees.primary_tool == "get_callees"
    assert res_callees.recommended_sequence == ("resolve_symbol", "get_callees")


def test_09_classify_trace_task() -> None:
    """9. Execution path tracing question classifies as TRACE and selects trace_path."""
    res = classify_agent_task("Trace the execution path from login_endpoint to find_by_email")
    assert res.category == AgentTaskCategory.TRACE
    assert res.primary_tool == "trace_path"
    assert "trace_path" in res.recommended_sequence


def test_10_classify_route_discovery_task() -> None:
    """10. Route discovery question classifies as ROUTE_DISCOVERY and selects list_routes."""
    res = classify_agent_task("Which route handles POST /api/v1/auth/login?")
    assert res.category == AgentTaskCategory.ROUTE_DISCOVERY
    assert res.primary_tool == "list_routes"


def test_11_classify_debugging_and_di_task() -> None:
    """11. Debugging and dependency-injection questions classify as DEBUG and select get_context."""
    res = classify_agent_task("How does UserRepository get injected via Depends(get_db)?")
    assert res.category == AgentTaskCategory.DEBUG
    assert res.primary_tool == "get_context"


def test_12_classify_test_discovery_task() -> None:
    """12. Test coverage question classifies as TEST_DISCOVERY and selects find_related_tests."""
    res = classify_agent_task("What tests are affected if UserService changes?")
    assert res.category == AgentTaskCategory.TEST_DISCOVERY
    assert res.primary_tool == "find_related_tests"


def test_13_classify_change_impact_task() -> None:
    """13. Git/blast-radius question classifies as CHANGE_IMPACT and selects get_git_impact."""
    res = classify_agent_task("Analyze git impact and blast radius of recent commits")
    assert res.category == AgentTaskCategory.CHANGE_IMPACT
    assert res.primary_tool == "get_git_impact"


def test_14_classify_architecture_and_package_tasks() -> None:
    """14. Architecture and monorepo package boundary questions select get_architecture / get_context."""
    res_arch = classify_agent_task("Give me a high-level architecture overview of the service")
    assert res_arch.category == AgentTaskCategory.ARCHITECTURE
    assert res_arch.primary_tool == "get_architecture"

    res_pkg = classify_agent_task("What workspace package dependencies exist across package boundaries?")
    assert res_pkg.category == AgentTaskCategory.PACKAGE
    assert res_pkg.primary_tool == "get_context"


def test_15_classify_multi_file_investigation_task() -> None:
    """15. Multi-file investigation selects search_symbols -> resolve_symbol -> get_context."""
    res = classify_agent_task("Where is authentication implemented across the repository?")
    assert res.category == AgentTaskCategory.MULTI_FILE_INVESTIGATION
    assert res.recommended_sequence == ("search_symbols", "resolve_symbol", "get_context")


# ---------------------------------------------------------------------------
# 3. Agent Rule Pack & Antigravity Integration (Tests 16–22)
# ---------------------------------------------------------------------------


def test_16_render_agent_rules_for_all_supported_agents() -> None:
    """16. render_agent_rules succeeds deterministically for all 7 supported agent targets."""
    for agent in SUPPORTED_AGENTS:
        r1 = render_agent_rules(agent)
        r2 = render_agent_rules(agent)
        assert r1 == r2
        assert len(r1) < 6000  # Section 9: < 6,000 characters
        assert "## Always-On Principles" in r1
        assert "## Task-Specific Tool Selection" in r1
        assert "## Epistemic & Fallback Rules" in r1
        assert "UNKNOWN" in r1
        assert "POSSIBLE" in r1


def test_17_render_agent_rules_rejects_unknown_agent() -> None:
    """17. Unsupported agent name raises ValueError."""
    with pytest.raises(ValueError, match="Unsupported agent"):
        render_agent_rules("nonexistent_agent_xyz")


def test_18_antigravity_mcp_config_uses_codegraph_mcp_serve() -> None:
    """18. Antigravity MCP config example uses `codegraph` with `["mcp", "serve"]`."""
    cfg = render_antigravity_mcp_config()
    assert cfg == {
        "mcpServers": {
            "codegraph": {
                "command": "codegraph",
                "args": ["mcp", "serve"],
            }
        }
    }


def test_19_antigravity_skill_contains_6_step_workflow() -> None:
    """19. Antigravity SKILL.md contains YAML frontmatter and all 6 concise workflow steps."""
    skill = render_antigravity_skill()
    assert skill.startswith("---\nname: codegraph\n")
    for step in ("STEP 1", "STEP 2", "STEP 3", "STEP 4", "STEP 5", "STEP 6"):
        assert step in skill
    assert "UNKNOWN" in skill
    assert "POSSIBLE" in skill
    assert "AMBIGUOUS" in skill


def test_20_write_agent_rule_pack_writes_all_files(tmp_path: Path) -> None:
    """20. write_agent_rule_pack writes all 8 agent-rules/ files and 3 .agents/ files."""
    written = write_agent_rule_pack(tmp_path)
    expected_files = [
        ".agents/mcp_config.json.example",
        ".agents/rules/codegraph.md",
        ".agents/skills/codegraph/SKILL.md",
        "agent-rules/AGENTS.md",
        "agent-rules/GEMINI.md",
        "agent-rules/README.md",
        "agent-rules/antigravity.md",
        "agent-rules/claude.md",
        "agent-rules/cline.md",
        "agent-rules/codex.md",
        "agent-rules/cursor.md",
    ]
    assert written == expected_files
    for rel in expected_files:
        assert (tmp_path / rel).exists()


def test_21_repository_agent_rules_and_agy_files_exist_on_disk() -> None:
    """21. Workspace root contains generated `agent-rules/` and `.agents/` files."""
    repo_root = Path(__file__).resolve().parent.parent
    assert (repo_root / ".agents" / "mcp_config.json.example").exists()
    assert (repo_root / ".agents" / "rules" / "codegraph.md").exists()
    assert (repo_root / ".agents" / "skills" / "codegraph" / "SKILL.md").exists()
    assert (repo_root / "agent-rules" / "AGENTS.md").exists()
    assert (repo_root / "agent-rules" / "antigravity.md").exists()


def test_22_never_claims_codegraph_will_always_be_used() -> None:
    """22. Non-negotiable principle: neither manifest nor rules claim CodeGraph is mandatory for every task."""
    manifest_str = json.dumps(get_capability_manifest()).lower()
    rules_str = render_agent_rules("antigravity").lower()
    assert "codegraph will always be used" not in manifest_str
    assert "codegraph will always be used" not in rules_str
    assert "local_edit" in rules_str


# ---------------------------------------------------------------------------
# 4. Epistemic & Fallback Policy (Tests 23–27)
# ---------------------------------------------------------------------------


def test_23_fallback_when_mcp_disconnected() -> None:
    """23. When CodeGraph MCP is DISCONNECTED, fallback to direct tools is allowed."""
    fb = evaluate_fallback_policy(mcp_state="DISCONNECTED")
    assert fb.fallback_allowed is True
    assert fb.epistemic_status == "DISCONNECTED"
    assert fb.relationship_exists_claim_allowed is False
    assert fb.no_relationship_claim_allowed is False


def test_24_fallback_when_index_is_stale() -> None:
    """24. When index freshness is STALE, agent is instructed to verify with read_file or re-index."""
    fb = evaluate_fallback_policy(mcp_state="CONNECTED", freshness="STALE")
    assert fb.fallback_allowed is True
    assert fb.epistemic_status == "STALE"
    assert fb.relationship_exists_claim_allowed is False


def test_25_epistemic_unknown_never_means_no_relationship() -> None:
    """25. UNKNOWN from CodeGraph never permits claiming 'there is no relationship'."""
    fb = evaluate_fallback_policy(mcp_state="CONNECTED", evidence_class="UNKNOWN")
    assert fb.epistemic_status == "UNKNOWN"
    assert fb.no_relationship_claim_allowed is False
    assert fb.relationship_exists_claim_allowed is False
    assert "NOT 'no relationship exists'" in fb.required_agent_action


def test_26_epistemic_possible_never_treated_as_verified_fact() -> None:
    """26. POSSIBLE relationship requires targeted source confirmation before claiming as fact."""
    fb = evaluate_fallback_policy(mcp_state="CONNECTED", evidence_class="POSSIBLE")
    assert fb.epistemic_status == "POSSIBLE"
    assert fb.relationship_exists_claim_allowed is False
    assert fb.fallback_allowed is True


def test_27_epistemic_ambiguous_preserves_alternatives() -> None:
    """27. AMBIGUOUS target resolution instructs agent to inspect alternatives."""
    fb = evaluate_fallback_policy(mcp_state="CONNECTED", ambiguity_state="AMBIGUOUS")
    assert fb.epistemic_status == "AMBIGUOUS"
    assert fb.relationship_exists_claim_allowed is False
    assert "alternatives" in fb.required_agent_action


# ---------------------------------------------------------------------------
# 5. MCP Doctor & Configuration Diagnostics (Tests 28–38)
# ---------------------------------------------------------------------------


def test_28_mcp_doctor_runs_all_10_checks_and_passes() -> None:
    """28. run_mcp_doctor executes all 10 required checks and reports healthy=True."""
    report = run_mcp_doctor()
    assert report.healthy is True
    check_names = [c.name for c in report.checks]
    assert check_names == [
        "executable",
        "server startup",
        "MCP initialize",
        "tool discovery",
        "resolve_symbol",
        "get_context",
        "get_callers",
        "trace_path",
        "test fixture query",
        "clean shutdown",
    ]
    human = report.format_human()
    assert "CodeGraph MCP Doctor" in human
    assert "✓ executable" in human
    assert "✓ trace_path" in human
    assert "✓ clean shutdown" in human


def test_29_mcp_doctor_cli_command_human_and_json() -> None:
    """29. `codegraph mcp doctor` CLI command works in both human-readable and --json modes."""
    res_human = runner.invoke(app, ["mcp", "doctor"])
    assert res_human.exit_code == 0
    assert "CodeGraph MCP Doctor" in res_human.stdout
    assert "✓ resolve_symbol" in res_human.stdout

    res_json = runner.invoke(app, ["mcp", "doctor", "--json"])
    assert res_json.exit_code == 0
    parsed = json.loads(res_json.stdout)
    assert parsed["healthy"] is True
    assert len(parsed["checks"]) == 10


def test_30_mcp_doctor_handles_missing_executable() -> None:
    """30. run_mcp_doctor reports unhealthy when custom executable does not exist."""
    report = run_mcp_doctor(custom_executable="nonexistent_codegraph_binary_xyz_999")
    assert report.healthy is False
    assert report.checks[0].name == "executable"
    assert report.checks[0].passed is False


def test_31_mcp_doctor_handles_simulated_server_failure() -> None:
    """31. run_mcp_doctor reports unhealthy when server startup fails."""
    report = run_mcp_doctor(simulate_server_failure=True)
    assert report.healthy is False
    startup_chk = next(c for c in report.checks if c.name == "server startup")
    assert startup_chk.passed is False


def test_32_config_diagnostics_configured_state(tmp_path: Path) -> None:
    """32. check_mcp_configuration reports CONFIGURED for valid .agents/mcp_config.json."""
    cfg_dir = tmp_path / ".agents"
    cfg_dir.mkdir()
    cfg_file = cfg_dir / "mcp_config.json"
    cfg_file.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "codegraph": {
                        "command": "python3",
                        "args": ["-m", "codegraph.cli", "mcp", "serve"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    rep = check_mcp_configuration(workspace_dir=tmp_path, config_file=cfg_file)
    assert rep.status == MCPConfigStatus.CONFIGURED
    assert rep.config_found is True
    assert rep.command_available is True
    assert rep.schema_valid is True


def test_33_config_diagnostics_not_configured_state(tmp_path: Path) -> None:
    """33. check_mcp_configuration reports NOT_CONFIGURED when no config file exists."""
    missing = tmp_path / "does_not_exist.json"
    rep = check_mcp_configuration(workspace_dir=tmp_path, config_file=missing)
    assert rep.status == MCPConfigStatus.NOT_CONFIGURED
    assert rep.config_found is False


def test_34_config_diagnostics_invalid_json_and_missing_entry(tmp_path: Path) -> None:
    """34. check_mcp_configuration reports INVALID for malformed JSON or missing codegraph key without mutating file."""
    bad_json = tmp_path / "bad.json"
    original_content = "{ not valid json "
    bad_json.write_text(original_content, encoding="utf-8")
    rep1 = check_mcp_configuration(workspace_dir=tmp_path, config_file=bad_json)
    assert rep1.status == MCPConfigStatus.INVALID
    assert bad_json.read_text(encoding="utf-8") == original_content  # Zero mutation!

    empty_obj = tmp_path / "empty.json"
    empty_obj.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    rep2 = check_mcp_configuration(workspace_dir=tmp_path, config_file=empty_obj)
    assert rep2.status == MCPConfigStatus.INVALID


def test_35_config_diagnostics_command_not_found(tmp_path: Path) -> None:
    """35. check_mcp_configuration reports COMMAND_NOT_FOUND when command binary is missing."""
    cfg = tmp_path / "mcp_config.json"
    cfg.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "codegraph": {
                        "command": "missing_codegraph_cmd_xyz_123",
                        "args": ["mcp", "serve"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    rep = check_mcp_configuration(workspace_dir=tmp_path, config_file=cfg)
    assert rep.status == MCPConfigStatus.COMMAND_NOT_FOUND
    assert rep.command_available is False


def test_36_config_diagnostics_server_failed_and_tools_unavailable(tmp_path: Path) -> None:
    """36. check_mcp_configuration reports SERVER_FAILED and TOOLS_UNAVAILABLE states."""
    cfg = tmp_path / "mcp_config.json"
    cfg.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "codegraph": {
                        "command": "python3",
                        "args": ["mcp", "serve"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    rep_fail = check_mcp_configuration(workspace_dir=tmp_path, config_file=cfg, simulate_server_failed=True)
    assert rep_fail.status == MCPConfigStatus.SERVER_FAILED

    rep_tools = check_mcp_configuration(workspace_dir=tmp_path, config_file=cfg, simulate_tools_unavailable=True)
    assert rep_tools.status == MCPConfigStatus.TOOLS_UNAVAILABLE


def test_37_cross_platform_config_paths_macos_linux_windows(tmp_path: Path) -> None:
    """37. Candidate config discovery supports macOS, Linux, and Windows path conventions."""
    mac_paths = get_candidate_mcp_config_paths(tmp_path, platform_name="darwin")
    linux_paths = get_candidate_mcp_config_paths(tmp_path, platform_name="linux")
    win_paths = get_candidate_mcp_config_paths(tmp_path, platform_name="win32")

    assert any("Application Support" in str(p) for p in mac_paths)
    assert any(".config" in str(p) for p in linux_paths)
    assert len(win_paths) >= 4


def test_38_security_no_secret_leakage_in_diagnostics(tmp_path: Path) -> None:
    """38. Diagnostics never expose secret environment variables, API tokens, or private keys."""
    secret_value = "sk-super-secret-api-token-999999"
    cfg = tmp_path / "mcp_config.json"
    cfg.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "codegraph": {
                        "command": "python3",
                        "args": ["mcp", "serve"],
                        "env": {
                            "OPENAI_API_KEY": secret_value,
                            "GITHUB_TOKEN": "ghp_secret_12345",
                            "PRIVATE_KEY": "-----BEGIN PRIVATE KEY-----",
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    rep = check_mcp_configuration(workspace_dir=tmp_path, config_file=cfg)
    serialized = json.dumps(rep.as_dict())
    assert secret_value not in serialized
    assert "ghp_secret_12345" not in serialized
    assert "BEGIN PRIVATE KEY" not in serialized

    sanitized = sanitize_diagnostic_dict(
        {
            "command": "codegraph",
            "api_token": secret_value,
            "env": {"SECRET_KEY": secret_value},
        }
    )
    sanitized_str = json.dumps(sanitized)
    assert secret_value not in sanitized_str
    assert sanitized["api_token"] == "[REDACTED]"
    assert sanitized["env_keys_configured"] == 1


# ---------------------------------------------------------------------------
# 6. Tool Description Quality, Profiles & Observability (Tests 39–43)
# ---------------------------------------------------------------------------


def test_39_tool_description_quality_audit_passes() -> None:
    """39. All tools in TOOL_CAPABILITY_REGISTRY pass the Section 20 description quality audit."""
    audit = audit_tool_descriptions()
    assert audit["all_passed"] is True
    assert audit["issues"] == []


def test_40_mcp_server_profiles_core_graph_minimal_developer_full(tmp_path: Path) -> None:
    """40. create_server supports core, graph, minimal, developer, and full profiles with expected tool counts."""
    counts: dict[str, int] = {}
    for prof in ("core", "graph", "minimal", "developer", "full"):
        srv = create_server(tmp_path, profile=prof)
        tools_dict = srv._tool_manager._tools
        counts[prof] = len(tools_dict)
        assert counts[prof] == MCP_PROFILE_RECOMMENDATIONS[prof]["tool_count"]

    assert counts["core"] < counts["graph"] < counts["minimal"] < counts["developer"] < counts["full"]


def test_41_tool_usage_observability_recording_and_summary() -> None:
    """41. MetricsRegistry records ToolUsageRecord items and computes deterministic tool-usage summary."""
    reg = MetricsRegistry()
    reg.record_tool_usage(
        ToolUsageRecord(
            request_classification="RELATIONSHIP",
            selected_codegraph_tool="get_callers",
            codegraph_used=True,
            codegraph_call_count=2,
            direct_file_reads_after=0,
            fallback_occurred=False,
        )
    )
    reg.record_tool_usage(
        ToolUsageRecord(
            request_classification="LOCAL_EDIT",
            selected_codegraph_tool=None,
            codegraph_used=False,
            codegraph_call_count=0,
            direct_file_reads_after=1,
            fallback_occurred=False,
        )
    )
    summary = reg.get_tool_usage_summary()
    assert summary["total_requests"] == 2
    assert summary["codegraph_used_count"] == 1
    assert summary["codegraph_invocation_rate"] == 0.5
    assert summary["total_codegraph_calls"] == 2
    assert summary["by_classification"] == {"LOCAL_EDIT": 1, "RELATIONSHIP": 1}


def test_42_rule_robustness_validation_all_8_checks_pass() -> None:
    """42. validate_rule_robustness confirms all 8 anti-loop, bypass, and epistemic checks pass."""
    rob = validate_rule_robustness()
    assert rob["all_passed"] is True
    for check_val in rob["checks"].values():  # type: ignore[union-attr]
        assert check_val is True


def test_43_cli_capabilities_and_rules_subcommands() -> None:
    """43. `codegraph mcp capabilities` and `codegraph mcp rules` CLI commands succeed deterministically."""
    res_cap = runner.invoke(app, ["mcp", "capabilities"])
    assert res_cap.exit_code == 0
    cap_data = json.loads(res_cap.stdout)
    assert cap_data["server_name"] == "codegraph"

    res_rules = runner.invoke(app, ["mcp", "rules", "--agent", "claude"])
    assert res_rules.exit_code == 0
    assert "# CodeGraph MCP Rules for Claude Code" in res_rules.stdout


# ---------------------------------------------------------------------------
# 7. 32-Task Evaluation Harness, A/B Test & Antigravity Trace (Tests 44–50)
# ---------------------------------------------------------------------------


def test_44_evaluation_harness_has_at_least_30_tasks_across_all_domains() -> None:
    """44. DEFAULT_TOOL_SELECTION_TASKS has 32 tasks covering all required domains."""
    assert len(DEFAULT_TOOL_SELECTION_TASKS) == 32
    domains = {t.domain for t in DEFAULT_TOOL_SELECTION_TASKS}
    for required_domain in (
        "symbol_lookup",
        "caller_callee",
        "route_tracing",
        "di",
        "registries",
        "events",
        "tests",
        "package_boundaries",
        "change_impact",
        "architecture",
        "debugging",
        "local_edit",
    ):
        assert required_domain in domains


def test_45_critical_ab_test_rules_improve_tool_selection() -> None:
    """45. Critical A/B test proves Mode B (with rules) improves invocation, accuracy, and reduces file reads vs Mode A."""
    ab = run_tool_selection_ab_benchmark(record_observability=False)
    mode_a = ab["mode_a"]
    mode_b = ab["mode_b"]
    delta = ab["delta"]

    assert mode_b["multi_file_codegraph_invocation_rate"] == 1.0  # type: ignore[index]
    assert mode_b["local_edit_bypass_rate"] == 1.0  # type: ignore[index]
    assert mode_b["first_tool_accuracy"] == 1.0  # type: ignore[index]
    assert mode_b["unnecessary_codegraph_calls"] == 0  # type: ignore[index]
    assert mode_b["unsupported_claims"] == 0  # type: ignore[index]

    assert float(mode_b["first_tool_accuracy"]) > float(mode_a["first_tool_accuracy"])  # type: ignore[index]
    assert float(mode_b["task_accuracy"]) > float(mode_a["task_accuracy"])  # type: ignore[index]
    assert int(mode_b["direct_file_reads"]) < int(mode_a["direct_file_reads"])  # type: ignore[index]
    assert int(delta["direct_file_reads_reduction"]) > 100  # type: ignore[index]


def test_46_ab_benchmark_is_deterministic() -> None:
    """46. Repeated runs of run_tool_selection_ab_benchmark produce identical JSON output."""
    r1 = json.dumps(run_tool_selection_ab_benchmark(record_observability=False), sort_keys=True)
    r2 = json.dumps(run_tool_selection_ab_benchmark(record_observability=False), sort_keys=True)
    assert r1 == r2


def test_47_antigravity_real_world_auth_trace_test_a_b_c() -> None:
    """47. Section 17 Antigravity evaluation executes real repository trace across TEST A, TEST B, and TEST C."""
    eval_res = run_antigravity_auth_trace_evaluation()
    test_a = eval_res["test_a"]
    test_b = eval_res["test_b"]
    test_c = eval_res["test_c"]

    assert test_a["mcp_connection_success"] is True  # type: ignore[index]
    assert test_b["mcp_connection_success"] is True  # type: ignore[index]
    assert test_c["mcp_connection_success"] is True  # type: ignore[index]

    # Test B and Test C select list_routes first and require 0 blind direct file reads
    assert test_b["first_selected_tool"] == "list_routes"  # type: ignore[index]
    assert test_c["first_selected_tool"] == "list_routes"  # type: ignore[index]
    assert test_b["direct_file_reads"] == 0  # type: ignore[index]
    assert test_c["direct_file_reads"] == 0  # type: ignore[index]
    assert test_b["task_completion"] is True  # type: ignore[index]
    assert test_c["task_completion"] is True  # type: ignore[index]
    assert test_b["unsupported_claims"] == 0  # type: ignore[index]
    assert test_c["unsupported_claims"] == 0  # type: ignore[index]
    assert "trace_path_verified" in test_c["verified_entities_found"]  # type: ignore[index, operator]


def test_48_schema_version_remains_v8() -> None:
    """48. SQLite schema version remains strictly 8."""
    assert SCHEMA_VERSION == 8


def test_49_mcp_server_injects_instructions_in_handshake(tmp_path: Path) -> None:
    """49. create_server populates FastMCP.instructions so rules are delivered via MCP handshake even without workspace rule files."""
    from codegraph.mcp.server import create_server

    server = create_server(tmp_path)
    assert server.instructions is not None
    assert "CodeGraph MCP Rules" in server.instructions
    assert "resolve_symbol" in server.instructions
    assert "UNKNOWN" in server.instructions


def test_50_index_grounded_classify_agent_task(tmp_path: Path) -> None:
    """50. classify_agent_task(prompt, con=con) grounds bare routes, tests, DI providers, and symbols against the SQLite index."""
    from codegraph.indexing.indexer import Indexer

    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI, Depends\n"
        "app = FastAPI()\n"
        "def get_token_provider():\n"
        "    return 'secret'\n"
        "class AuthService:\n"
        "    def verify_user(self, token: str) -> bool:\n"
        "        return True\n"
        "@app.post('/v2/session/refresh')\n"
        "def refresh_handler(tok: str = Depends(get_token_provider)):\n"
        "    return AuthService().verify_user(tok)\n",
        encoding="utf-8",
    )
    (tmp_path / "test_session.py").write_text(
        "from app import refresh_handler\n"
        "def test_refresh_session_flow():\n"
        "    assert refresh_handler('ok') is True\n",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    with indexer.session() as con:
        # Bare route path without keyword "route" or "endpoint"
        r_route = classify_agent_task("Check /v2/session/refresh", con=con)
        assert r_route.category == AgentTaskCategory.ROUTE_DISCOVERY
        assert r_route.confidence == "HIGH"

        # Bare test function name without keyword "test coverage" or "which tests"
        r_test = classify_agent_task("Inspect test_refresh_session_flow", con=con)
        assert r_test.category == AgentTaskCategory.TEST_DISCOVERY
        assert r_test.confidence == "HIGH"

        # Bare DI provider symbol without keyword "dependency injection"
        r_di = classify_agent_task("Examine get_token_provider", con=con)
        assert r_di.category == AgentTaskCategory.DEBUG
        assert r_di.confidence == "HIGH"

        # Two distinct symbols without keyword "trace"
        r_trace = classify_agent_task("Check refresh_handler and verify_user", con=con)
        assert r_trace.category == AgentTaskCategory.TRACE
        assert r_trace.confidence == "HIGH"

        # Single symbol without keyword "where is ... defined"
        r_sym = classify_agent_task("Inspect AuthService", con=con)
        assert r_sym.category == AgentTaskCategory.SYMBOL_LOOKUP
        assert r_sym.confidence == "HIGH"

