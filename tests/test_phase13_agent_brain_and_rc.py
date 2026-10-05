"""Phase 13 Tests — Release Candidate Validation, Deep Agent Brain, Detailed Skill & Documentation Validator.

Verifies:
1. Single-source-of-truth documentation generation across Layer 1 (compact rules + capability summary),
   Layer 2 (`.agents/skills/codegraph/SKILL.md`), and Layer 3 (`docs/agent-brain.md`).
2. Automated documentation validation (`validate_agent_documentation`):
   - Every documented tool exists in `create_server(profile='full')` (39/39 tools)
   - Every documented parameter exists in the actual MCP tool function signature
   - Every documented relationship exists in `ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX` (41/41 relationships)
   - Every documented evidence class exists in `ALLOWED_EVIDENCE_CLASSES` (5/5 classes)
   - Every documented profile exists in `MCP_PROFILE_RECOMMENDATIONS` (5/5 profiles)
   - Package and command names are current with zero stale tool names
3. All 41 required sections, 25+ complex workflows, and 39 tool reference entries in `docs/agent-brain.md`.
4. All 10 operational steps, matrices, workflows, and stop conditions in `.agents/skills/codegraph/SKILL.md`.
5. On-disk synchronization of all 13 required Agent Brain & Rule files.
"""
from __future__ import annotations

import inspect
from pathlib import Path

from codegraph.agent_brain import (
    COMPLEX_WORKFLOW_EXAMPLES,
    RELATIONSHIP_SEMANTICS_REGISTRY,
    render_deep_agent_brain,
    render_tool_capabilities_summary,
    validate_agent_documentation,
)
from codegraph.agent_capabilities import (
    TOOL_CAPABILITY_REGISTRY,
)
from codegraph.agent_rules import (
    SUPPORTED_AGENTS,
    render_agent_rules,
    render_antigravity_skill,
    write_agent_brain_artifacts,
)
from codegraph.evidence_contract import (
    ALLOWED_EVIDENCE_CLASSES,
    ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX,
)
from codegraph.mcp.server import create_server
from codegraph.mcp_diagnostics import audit_tool_descriptions

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_p13_01_all_39_mcp_tools_registered_in_capability_registry(tmp_path: Path) -> None:
    """Every tool exposed by `create_server(profile='full')` is present in `TOOL_CAPABILITY_REGISTRY`."""
    srv = create_server(tmp_path, profile="full")
    mcp_tools = srv._tool_manager._tools
    assert len(mcp_tools) == len(TOOL_CAPABILITY_REGISTRY)
    assert len(TOOL_CAPABILITY_REGISTRY) == 62

    reg_names = {spec.tool_name for spec in TOOL_CAPABILITY_REGISTRY}
    assert reg_names == set(mcp_tools.keys())


def test_p13_02_every_documented_parameter_matches_mcp_tool_signature(tmp_path: Path) -> None:
    """Every documented required and optional input matches the exact MCP tool function signature."""
    srv = create_server(tmp_path, profile="full")
    mcp_tools = srv._tool_manager._tools

    for spec in TOOL_CAPABILITY_REGISTRY:
        fn = mcp_tools[spec.tool_name].fn
        sig_params = set(inspect.signature(fn).parameters.keys())
        doc_params = set(spec.required_inputs) | set(spec.optional_inputs)
        assert doc_params == sig_params, (
            f"Parameter mismatch for {spec.tool_name}: doc={doc_params} vs sig={sig_params}"
        )


def test_p13_03_all_39_tools_pass_description_quality_audit() -> None:
    """All 56 tools in `TOOL_CAPABILITY_REGISTRY` pass the description quality audit."""
    audit = audit_tool_descriptions()
    assert audit["total_tools_audited"] == len(TOOL_CAPABILITY_REGISTRY)
    assert audit["all_passed"] is True
    assert audit["issues"] == []


def test_p13_04_all_documented_relationships_exist_in_evidence_contract() -> None:
    """Every relationship in `RELATIONSHIP_SEMANTICS_REGISTRY` and `TOOL_CAPABILITY_REGISTRY` exists in `ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX`."""
    assert set(RELATIONSHIP_SEMANTICS_REGISTRY.keys()) == set(ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX.keys())
    for spec in TOOL_CAPABILITY_REGISTRY:
        for rel in spec.relationship_types_returned:
            assert rel in ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX, (
                f"Tool {spec.tool_name} references unknown relationship {rel}"
            )


def test_p13_05_deep_agent_brain_contains_all_41_required_sections() -> None:
    """`docs/agent-brain.md` contains all 41 numbered sections required by Phase 13 Section 3."""
    brain = render_deep_agent_brain()
    for sec_num in range(1, 42):
        assert f"## {sec_num}. " in brain, f"Missing Section {sec_num} in docs/agent-brain.md"


def test_p13_06_deep_agent_brain_contains_25_detailed_workflows() -> None:
    """`docs/agent-brain.md` contains at least 25 complex workflows with all 10 required fields."""
    assert len(COMPLEX_WORKFLOW_EXAMPLES) >= 25
    brain = render_deep_agent_brain()
    for wf in COMPLEX_WORKFLOW_EXAMPLES:
        assert f"### Workflow {wf.workflow_id}: {wf.title}" in brain
        assert wf.developer_request in brain
        assert wf.first_tool in brain
        assert wf.stop_condition in brain
        assert wf.source_read_fallback in brain
        assert wf.final_evidence_handling in brain
    for required_field in (
        "- **Developer request**:",
        "- **Task classification**:",
        "- **Why CodeGraph is appropriate**:",
        "- **First tool**:",
        "- **Arguments**:",
        "- **Expected result interpretation**:",
        "- **Follow-up tool**:",
        "- **Stop condition**:",
        "- **Source-read fallback**:",
        "- **Final evidence handling**:",
    ):
        assert brain.count(required_field) >= 25


def test_p13_07_deep_agent_brain_contains_all_39_tool_reference_sections() -> None:
    """`docs/agent-brain.md` documents all 56 tools with all 13 required subsections."""
    brain = render_deep_agent_brain()
    for spec in TOOL_CAPABILITY_REGISTRY:
        assert f"### `{spec.tool_name}`" in brain
    for subheading in (
        "#### Purpose",
        "#### Use when",
        "#### Avoid when",
        "#### Required inputs",
        "#### Optional inputs",
        "#### Minimal invocation",
        "#### Advanced invocation",
        "#### Result interpretation",
        "#### Evidence meaning",
        "#### Non-guarantees",
        "#### Typical follow-up",
        "#### Common mistakes",
        "#### Example",
    ):
        assert brain.count(subheading) == len(TOOL_CAPABILITY_REGISTRY)


def test_p13_08_detailed_skill_file_contains_10_steps_and_matrices() -> None:
    """`.agents/skills/codegraph/SKILL.md` contains all 10 steps, matrices, workflows, and stop conditions."""
    skill = render_antigravity_skill()
    assert skill.startswith("---\nname: codegraph\n")
    assert "# CodeGraph Agent Skill" in skill
    for step_num in range(1, 11):
        assert f"## STEP {step_num} —" in skill
    for section in (
        "## When to activate",
        "## When NOT to activate",
        "## Tool selection matrix",
        "## Evidence matrix",
        "## Relationship matrix",
        "## Common workflows",
        "## Failure/fallback workflow",
        "## Stop conditions",
    ):
        assert section in skill


def test_p13_09_compact_rules_and_capability_summary() -> None:
    """Layer 1 rules remain compact (2–6 KB) and `tool-capabilities-summary.md` covers all task domains."""
    for agent in SUPPORTED_AGENTS:
        rule_txt = render_agent_rules(agent)
        assert 2000 <= len(rule_txt) < 6000
        assert "## CodeGraph Mental Model" in rule_txt
        assert "## Always-On Principles" in rule_txt
        assert "## Task-Specific Tool Selection" in rule_txt
        assert "## Epistemic & Fallback Rules" in rule_txt

    summary_txt = render_tool_capabilities_summary()
    assert "## Task Routing & Evidence Expectations" in summary_txt
    assert "## Epistemic Status Quick Reference" in summary_txt
    for domain in ("LOCAL_EDIT", "SYMBOL_LOOKUP", "TRACE", "DI", "CHANGE_IMPACT", "PACKAGE", "TEST_DISCOVERY"):
        assert domain in summary_txt


def test_p13_10_automated_documentation_validator_passes_on_repository() -> None:
    """`validate_agent_documentation(REPO_ROOT)` passes with 0 errors and verifies on-disk synchronization."""
    res = validate_agent_documentation(REPO_ROOT)
    assert res["valid"] is True, f"Documentation validation errors: {res['errors']}"
    assert res["tools_documented"] == len(TOOL_CAPABILITY_REGISTRY)
    assert res["task_categories_documented"] == 13
    assert res["relationships_documented"] == len(ALLOWED_RELATIONSHIP_EVIDENCE_MATRIX)
    assert res["evidence_classes_documented"] == len(ALLOWED_EVIDENCE_CLASSES)
    assert res["workflows_documented"] >= 25
    assert res["profiles_documented"] == 6
    assert res["errors"] == []


def test_p13_11_write_agent_brain_artifacts_writes_all_13_files(tmp_path: Path) -> None:
    """`write_agent_brain_artifacts` writes all 13 required files and passes validation."""
    written = write_agent_brain_artifacts(tmp_path)
    expected = [
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
        "agent-rules/tool-capabilities-summary.md",
        "docs/agent-brain.md",
    ]
    assert written == expected
    val = validate_agent_documentation(tmp_path)
    assert val["valid"] is True


def test_p13_12_documentation_validator_fails_closed_on_drift(tmp_path: Path) -> None:
    """`validate_agent_documentation` fails closed if an on-disk file drifts from the canonical source."""
    write_agent_brain_artifacts(tmp_path)
    (tmp_path / "docs" / "agent-brain.md").write_text("# Corrupted doc\n", encoding="utf-8")
    val = validate_agent_documentation(tmp_path)
    assert val["valid"] is False
    assert any("docs/agent-brain.md" in str(e) for e in val["errors"])  # type: ignore[union-attr]
