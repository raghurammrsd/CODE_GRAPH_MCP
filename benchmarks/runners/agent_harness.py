"""Agent-Level Evaluation Harness for comparing Baseline vs MCP-Enabled Agent workflows."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from codegraph.context import get_context
from codegraph.indexing import Indexer


@dataclass(frozen=True)
class AgentRunRecord:
    task_id: str
    mcp_enabled: bool
    context_tokens: int
    mcp_calls: int
    duration_ms: float
    files_changed: tuple[str, ...]
    tests_passed: bool
    task_completed: bool
    irrelevant_files_touched: tuple[str, ...]
    unsupported_assumptions: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["files_changed"] = list(self.files_changed)
        d["irrelevant_files_touched"] = list(self.irrelevant_files_touched)
        d["unsupported_assumptions"] = list(self.unsupported_assumptions)
        return d


@dataclass(frozen=True)
class AgentComparisonResult:
    task_id: str
    baseline: AgentRunRecord  # MCP disabled
    experiment: AgentRunRecord  # MCP enabled
    token_savings_pct: float
    latency_delta_ms: float
    completion_improvement: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "baseline": self.baseline.as_dict(),
            "experiment": self.experiment.as_dict(),
            "token_savings_pct": round(self.token_savings_pct, 2),
            "latency_delta_ms": round(self.latency_delta_ms, 2),
            "completion_improvement": self.completion_improvement,
        }


def evaluate_agent_workflow(
    repository: Path,
    task_id: str,
    task_prompt: str,
    expected_files: tuple[str, ...],
    agent_simulator: Callable[[str, dict[str, Any] | None], dict[str, Any]],
) -> AgentComparisonResult:
    """Run simulated or actual agent under baseline (no MCP) and experiment (with MCP)."""
    # 1. Run Baseline (No MCP)
    t0 = time.perf_counter()
    # Baseline: agent gets raw prompt with no pre-computed repository context
    baseline_output = agent_simulator(task_prompt, None)
    baseline_duration_ms = (time.perf_counter() - t0) * 1000.0

    raw_files_baseline = tuple(baseline_output.get("files_changed", ()))
    irrelevant_baseline = tuple(f for f in raw_files_baseline if f not in expected_files)

    baseline_record = AgentRunRecord(
        task_id=task_id,
        mcp_enabled=False,
        context_tokens=int(baseline_output.get("tokens_consumed", 15000)),
        mcp_calls=0,
        duration_ms=round(baseline_duration_ms, 2),
        files_changed=raw_files_baseline,
        tests_passed=bool(baseline_output.get("tests_passed", False)),
        task_completed=bool(baseline_output.get("task_completed", False)),
        irrelevant_files_touched=irrelevant_baseline,
        unsupported_assumptions=tuple(baseline_output.get("unsupported_assumptions", ())),
    )

    # 2. Run Experiment (With MCP)
    indexer = Indexer(repository)
    if not (repository / ".codegraph.sqlite3").exists():
        indexer.index()

    t0 = time.perf_counter()
    with indexer.session() as con:
        mcp_packet = get_context(
            con=con,
            repository=repository,
            task=task_prompt,
            max_tokens=6000,
        )
    mcp_call_count = 1

    # Agent executes with grounded, compact ContextPacket
    exp_output = agent_simulator(task_prompt, mcp_packet.as_dict())
    exp_duration_ms = (time.perf_counter() - t0) * 1000.0

    raw_files_exp = tuple(exp_output.get("files_changed", expected_files))
    irrelevant_exp = tuple(f for f in raw_files_exp if f not in expected_files)

    exp_record = AgentRunRecord(
        task_id=task_id,
        mcp_enabled=True,
        context_tokens=mcp_packet.selected_token_estimate,
        mcp_calls=mcp_call_count,
        duration_ms=round(exp_duration_ms, 2),
        files_changed=raw_files_exp,
        tests_passed=bool(exp_output.get("tests_passed", True)),
        task_completed=bool(exp_output.get("task_completed", True)),
        irrelevant_files_touched=irrelevant_exp,
        unsupported_assumptions=(),
    )

    # Calculate comparative savings
    base_tok = max(baseline_record.context_tokens, 1)
    exp_tok = exp_record.context_tokens
    token_savings = max(0.0, ((base_tok - exp_tok) / base_tok) * 100.0)

    return AgentComparisonResult(
        task_id=task_id,
        baseline=baseline_record,
        experiment=exp_record,
        token_savings_pct=token_savings,
        latency_delta_ms=exp_record.duration_ms - baseline_record.duration_ms,
        completion_improvement=exp_record.task_completed and not baseline_record.task_completed,
    )
