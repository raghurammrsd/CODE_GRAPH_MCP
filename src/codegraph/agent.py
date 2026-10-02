from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass

from codegraph.llm import LLMProvider
from codegraph.llm.context import assemble_context
from codegraph.search import search


@dataclass(frozen=True)
class Answer:
    answer: str
    evidence: list[dict[str, object]]
    generated: bool


async def answer_question(con: sqlite3.Connection, question: str, provider: LLMProvider | None, max_context: int, max_tool_calls: int) -> Answer:
    results = search(con, question, min(max_tool_calls, 20))
    evidence = [asdict(item) for item in results]
    context = assemble_context(results, max_context)
    if provider is None:
        summary = "No LLM provider is configured. Relevant source evidence is returned below."
        return Answer(summary, evidence, False)
    answer = await provider.complete(question, context)
    return Answer(answer, evidence, True)
