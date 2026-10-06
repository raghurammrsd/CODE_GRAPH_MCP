"""Test Python AI / ML Stack Intelligence (Pillar 2):
1. PyTorch nn.Module forward resolution (submodule and model instance __call__ -> forward).
2. Epistemic discipline: AST_VERIFIED for concrete instances, POSSIBLE for abstract/unbound instances.
3. LangChain / LlamaIndex agent tool decorators (@tool, @function_tool) & agent tool registrations.
4. Ray remote task lineage (@ray.remote, task.remote()).
5. LangChain LCEL pipeline flow (prompt | llm | output_parser).
6. End-to-end multi-layer AI service trace.
"""

from pathlib import Path

from codegraph.indexing.indexer import Indexer
from codegraph.interrogation import (
    get_callers,
    trace_path,
)


def test_pytorch_nn_module_forward_resolution(tmp_path: Path) -> None:
    model_file = tmp_path / "models.py"
    model_file.write_text(
        """import torch.nn as nn

class Encoder(nn.Module):
    def forward(self, x):
        return x * 2

class Classifier(nn.Module):
    def __init__(self):
        super().__init__()
        self.encoder = Encoder()

    def forward(self, x):
        # Submodule invocation: self.encoder(x)
        features = self.encoder(x)
        return features + 1

def run_inference(inputs):
    # Concrete instance invocation: model(inputs)
    model = Classifier()
    return model(inputs)

def run_abstract_inference(unbound_model, inputs):
    # Abstract / unbound module invocation
    return unbound_model(inputs)
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()
    with indexer.session() as con:
        # 1. Check graph_edges for DISPATCHES_FORWARD
        fwd_edges = con.execute(
            "SELECT source, target, relationship, confidence, evidence_class "
            "FROM graph_edges WHERE relationship='DISPATCHES_FORWARD' "
            "ORDER BY source ASC"
        ).fetchall()

        assert len(fwd_edges) >= 2

        # Submodule invocation in Classifier.forward -> Encoder.forward
        submod_edge = [e for e in fwd_edges if "Classifier.forward" in e["source"] and "Encoder.forward" in e["target"]]
        assert len(submod_edge) == 1
        assert submod_edge[0]["confidence"] == "HIGH"
        assert submod_edge[0]["evidence_class"] == "AST_VERIFIED"

        # Concrete instance invocation in run_inference -> Classifier.forward
        concrete_edge = [e for e in fwd_edges if "run_inference" in e["source"] and "Classifier.forward" in e["target"]]
        assert len(concrete_edge) == 1
        assert concrete_edge[0]["confidence"] == "HIGH"
        assert concrete_edge[0]["evidence_class"] == "AST_VERIFIED"

        # 2. Check callers of Encoder.forward
        callers = get_callers(con, tmp_path, symbol="Encoder.forward")
        assert callers["status"] == "ok"
        caller_names = [c["caller"] for c in callers["callers"]]
        assert any("Classifier.forward" in name for name in caller_names)

        # 3. Check trace from run_inference all the way down to Encoder.forward
        trace_res = trace_path(con, tmp_path, from_symbol="run_inference", to_symbol="Encoder.forward")
        assert trace_res["status"] == "ok"
        assert trace_res["path_length"] >= 2

        # 4. Epistemic discipline: unbound model invocation does not falsely produce AST_VERIFIED forward edges
        assert not any("run_abstract_inference" in e["source"] for e in fwd_edges)


def test_agentic_tool_calling_and_registration(tmp_path: Path) -> None:
    agent_file = tmp_path / "agents.py"
    agent_file.write_text(
        """from langchain.tools import tool
from llama_index.core.tools import function_tool

@tool
def search_web_tool(query: str) -> str:
    return "results"

@function_tool
def calculator_tool(expr: str) -> int:
    return 42

def build_agent():
    # Tools passed in tools=[...] keyword argument
    agent = AgentExecutor(tools=[search_web_tool, calculator_tool])
    return agent
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()
    with indexer.session() as con:
        # Check TOOL_HANDLER edges
        tool_edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges "
            "WHERE relationship='TOOL_HANDLER' ORDER BY source ASC"
        ).fetchall()

        assert len(tool_edges) >= 2
        sources = [e["source"] for e in tool_edges]
        assert any("search_web_tool" in s for s in sources)
        assert any("calculator_tool" in s for s in sources)

        # Check REGISTERS edges from build_agent to tools
        reg_edges = con.execute(
            "SELECT source, target, relationship FROM graph_edges "
            "WHERE relationship='REGISTERS' ORDER BY target ASC"
        ).fetchall()

        targets = [e["target"] for e in reg_edges]
        assert any("search_web_tool" in t for t in targets)
        assert any("calculator_tool" in t for t in targets)


def test_ray_remote_task_lineage(tmp_path: Path) -> None:
    ray_file = tmp_path / "workers.py"
    ray_file.write_text(
        """import ray

@ray.remote
def process_batch_embeddings(items: list) -> list:
    return items

def submit_embeddings_job(data: list):
    # Ray remote task invocation
    future = process_batch_embeddings.remote(data)
    return future
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()
    with indexer.session() as con:
        # Check TASK_HANDLER for @ray.remote
        task_edges = con.execute(
            "SELECT source, target, relationship FROM graph_edges "
            "WHERE relationship='TASK_HANDLER' AND target LIKE '%process_batch_embeddings%'"
        ).fetchall()
        assert len(task_edges) >= 1

        # Check DISPATCHES_TASK from submit_embeddings_job to process_batch_embeddings
        dispatch_edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges "
            "WHERE relationship='DISPATCHES_TASK' AND source LIKE '%submit_embeddings_job%'"
        ).fetchall()
        assert len(dispatch_edges) >= 1
        assert "process_batch_embeddings" in dispatch_edges[0]["target"]
        assert dispatch_edges[0]["evidence_class"] == "FRAMEWORK_VERIFIED"

        # Check trace_path
        trace_res = trace_path(con, tmp_path, from_symbol="submit_embeddings_job", to_symbol="process_batch_embeddings")
        assert trace_res["status"] == "ok"
        assert trace_res["path_length"] >= 1


def test_lcel_pipeline_pipe_chain(tmp_path: Path) -> None:
    chain_file = tmp_path / "pipelines.py"
    chain_file.write_text(
        """def make_prompt(t): return t
def chat_model(p): return "out"
def json_parser(r): return {}

def build_qa_pipeline():
    prompt = make_prompt
    llm = chat_model
    parser = json_parser
    # LCEL pipeline composition
    chain = prompt | llm | parser
    return chain
""",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()
    with indexer.session() as con:
        # Check PIPELINE_STEP edges connecting prompt -> llm -> parser
        pipe_edges = con.execute(
            "SELECT source, target, relationship, evidence_class FROM graph_edges "
            "WHERE relationship='PIPELINE_STEP' ORDER BY start_line ASC"
        ).fetchall()

        assert len(pipe_edges) >= 2
        # First pipe step: make_prompt -> chat_model
        assert any("make_prompt" in e["source"] and "chat_model" in e["target"] for e in pipe_edges)
        # Second pipe step: chat_model -> json_parser
        assert any("chat_model" in e["source"] and "json_parser" in e["target"] for e in pipe_edges)

        # Trace path from make_prompt to json_parser
        trace_res = trace_path(con, tmp_path, from_symbol="make_prompt", to_symbol="json_parser")
        assert trace_res["status"] == "ok"
        assert trace_res["path_length"] >= 2
