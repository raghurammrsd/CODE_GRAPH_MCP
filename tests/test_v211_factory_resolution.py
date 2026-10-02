import tempfile
from pathlib import Path

from codegraph.config import Settings
from codegraph.graph import find_callees, find_callers
from codegraph.indexing import Indexer


def test_factory_receiver_resolution_with_annotation():
    """Test that svc = get_order_service() where get_order_service() -> OrderService
    resolves svc.place_order() to OrderService.place_order and links both calls."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        src_dir = root / "src"
        src_dir.mkdir()

        code = """class OrderService:
    def place_order(self, item_id: str) -> bool:
        return True

def get_order_service() -> OrderService:
    return OrderService()

def process_checkout():
    svc = get_order_service()
    return svc.place_order("item_123")
"""
        (src_dir / "orders.py").write_text(code, encoding="utf-8")

        indexer = Indexer(root, Settings(repository=root))
        indexer.index()

        with indexer.session() as con:
            # 1. Verify process_checkout calls get_order_service
            # 2. Verify process_checkout calls OrderService.place_order
            callees = find_callees(con, "src.orders.process_checkout")
            callee_targets = {str(c.get("qualified_callee") or c.get("callee")) for c in callees}

            assert any("get_order_service" in t for t in callee_targets), f"Missing factory call in {callee_targets}"
            assert any("OrderService.place_order" in t for t in callee_targets), f"Missing resolved place_order call in {callee_targets}"

            # Verify callers of OrderService.place_order includes process_checkout
            callers = find_callers(con, "src.orders.OrderService.place_order")
            caller_syms = {str(c.get("symbol") or c.get("caller")) for c in callers}
            assert any("process_checkout" in s for s in caller_syms), f"Missing process_checkout caller in {caller_syms}"


def test_factory_receiver_resolution_with_inferred_constructor():
    """Test that def _service(): return ItemRepository(...) infers return type
    and resolves repo.get() -> ItemRepository.get."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        src_dir = root / "src"
        src_dir.mkdir()

        code = """class ItemRepository:
    def get(self, id: str):
        return {"id": id}

def _service():
    return ItemRepository()

def fetch_item():
    repo = _service()
    return repo.get("42")
"""
        (src_dir / "items.py").write_text(code, encoding="utf-8")

        indexer = Indexer(root, Settings(repository=root))
        indexer.index()

        with indexer.session() as con:
            callees = find_callees(con, "src.items.fetch_item")
            callee_targets = {str(c.get("qualified_callee") or c.get("callee")) for c in callees}

            assert any("_service" in t for t in callee_targets), f"Missing _service call in {callee_targets}"
            assert any("ItemRepository.get" in t for t in callee_targets), f"Missing ItemRepository.get in {callee_targets}"


def test_unresolved_function_remains_conservative():
    """Test that arbitrary functions without return evidence do NOT bind to random methods."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        src_dir = root / "src"
        src_dir.mkdir()

        code = """def mystery():
    pass

def run():
    x = mystery()
    return x.do_something()
"""
        (src_dir / "mystery.py").write_text(code, encoding="utf-8")

        indexer = Indexer(root, Settings(repository=root))
        indexer.index()

        with indexer.session() as con:
            # Should NOT have resolved to mystery.do_something as a valid method call
            rows = con.execute("SELECT relationship, confidence FROM 'references' WHERE target_symbol_id LIKE '%do_something%'").fetchall()
            assert len(rows) == 0 or all(r[1] in ("UNKNOWN", "LOW") for r in rows)
