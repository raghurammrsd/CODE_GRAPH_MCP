import json
import tempfile
from pathlib import Path

from typer.testing import CliRunner

from codegraph.cli import app

runner = CliRunner()


def test_cli_imports_and_dependents():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        src = root / "src"
        src.mkdir()

        (src / "service.py").write_text("class MyService:\n    def run(self): pass\n", encoding="utf-8")
        (src / "app.py").write_text("from src.service import MyService\ns = MyService()\n", encoding="utf-8")

        # Initialize and index
        res = runner.invoke(app, ["init", str(root)])
        assert res.exit_code == 0

        # Test codegraph imports src/app.py
        res = runner.invoke(app, ["imports", "src/app.py", "--repository", str(root)])
        assert res.exit_code == 0
        data = json.loads(res.stdout)
        assert data.get("status") == "ok"
        imports_list = data.get("imports", [])
        assert any(imp.get("target") == "src.service" or imp.get("resolved_target") == "src/service.py" for imp in imports_list)

        # Test codegraph dependents src/service.py
        res = runner.invoke(app, ["dependents", "src/service.py", "--repository", str(root)])
        assert res.exit_code == 0
        data = json.loads(res.stdout)
        assert data.get("status") == "ok"
        dependents_list = data.get("dependents", [])
        assert any("src/app.py" in str(dep.get("dependent") or dep.get("file")) for dep in dependents_list)


def test_cli_trace_default_both_directions():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        src = root / "src"
        src.mkdir()

        code = """def helper():
    return 42

def caller_fn():
    return helper()
"""
        (src / "test_trace.py").write_text(code, encoding="utf-8")

        res = runner.invoke(app, ["init", str(root)])
        assert res.exit_code == 0

        # Run codegraph trace helper without direction flags
        res = runner.invoke(app, ["trace", "src.test_trace.helper", "--repository", str(root)])
        assert res.exit_code == 0
        data = json.loads(res.stdout)

        # Must contain DEFINES and CALLER (since default is both)
        relationships = {item.get("relationship") for item in data}
        assert "DEFINES" in relationships
        assert "CALLER" in relationships
