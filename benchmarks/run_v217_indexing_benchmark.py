"""Reproducible 4-tier large repository indexing benchmark for CodeGraph v2.1.7.

Evaluates:
1. small   (~54 files)
2. medium  (~304 files)
3. large   (~1,004 files)
4. stress  (~2,504 files, Home Assistant Core style architecture)

Records:
- Total index time (s)
- All 16 phase timings (s)
- Peak RSS & Peak tracemalloc memory (MB)
- Post-parse RSS & Steady-state RSS (MB)
- Final DB size & Peak/Final WAL size (MB)
- Throughput (files/sec, symbols/sec, edges/sec)
- 1-file incremental update latency (s)
"""
from __future__ import annotations

import argparse
import gc
import json
import shutil
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from codegraph.config import Settings
from codegraph.indexing.indexer import Indexer, check_database_health
from codegraph.indexing.telemetry import get_process_rss_mb
from codegraph.resources import get_parse_cache


def generate_ha_style_repo(root: Path, num_files: int = 2000) -> None:
    """Generate a deterministic Home Assistant Core style repository with realistic structure."""
    core_dir = root / "homeassistant" / "core"
    helpers_dir = root / "homeassistant" / "helpers"
    components_dir = root / "homeassistant" / "components"
    tests_dir = root / "tests" / "components"

    core_dir.mkdir(parents=True, exist_ok=True)
    helpers_dir.mkdir(parents=True, exist_ok=True)
    components_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)

    (root / "homeassistant" / "__init__.py").write_text(
        '"""Home Assistant root package."""\n'
        "from homeassistant.core.hass import HomeAssistant, ServiceCall\n"
        '__all__ = ["HomeAssistant", "ServiceCall"]\n',
        encoding="utf-8",
    )
    (core_dir / "__init__.py").write_text(
        "from .hass import HomeAssistant, ServiceCall, callback\n"
        '__all__ = ["HomeAssistant", "ServiceCall", "callback"]\n',
        encoding="utf-8",
    )
    (core_dir / "hass.py").write_text(
        '''"""Core HomeAssistant object."""
from typing import Any, Callable

def callback(func: Callable[..., Any]) -> Callable[..., Any]:
    return func

class ServiceCall:
    def __init__(self, domain: str, service: str, data: dict[str, Any]) -> None:
        self.domain = domain
        self.service = service
        self.data = data

class EventBus:
    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable[..., Any]]] = {}

    def async_listen(self, event_type: str, listener: Callable[..., Any]) -> None:
        self._listeners.setdefault(event_type, []).append(listener)

    def async_fire(self, event_type: str, event_data: dict[str, Any] | None = None) -> None:
        pass

class ServiceRegistry:
    def async_register(self, domain: str, service: str, service_func: Callable[..., Any]) -> None:
        pass

class HomeAssistant:
    def __init__(self) -> None:
        self.bus = EventBus()
        self.services = ServiceRegistry()
        self.data: dict[str, Any] = {}

    def verify_state(self, entity_id: str) -> bool:
        return True
''',
        encoding="utf-8",
    )

    (helpers_dir / "__init__.py").write_text(
        "from .entity import Entity, SensorEntity\n"
        "from .update_coordinator import DataUpdateCoordinator\n"
        '__all__ = ["Entity", "SensorEntity", "DataUpdateCoordinator"]\n',
        encoding="utf-8",
    )
    (helpers_dir / "entity.py").write_text(
        '''"""Entity base classes."""
from homeassistant.core.hass import HomeAssistant

class Entity:
    entity_id: str = ""
    def __init__(self, hass: HomeAssistant, name: str) -> None:
        self.hass = hass
        self._attr_name = name

    def async_write_ha_state(self) -> None:
        self.hass.verify_state(self.entity_id)

class SensorEntity(Entity):
    @property
    def native_value(self) -> str | int | float | None:
        return None
''',
        encoding="utf-8",
    )
    (helpers_dir / "update_coordinator.py").write_text(
        '''"""Data update coordinator."""
from homeassistant.core.hass import HomeAssistant

class DataUpdateCoordinator:
    def __init__(self, hass: HomeAssistant, name: str) -> None:
        self.hass = hass
        self.name = name

    async def async_config_entry_first_refresh(self) -> None:
        self.hass.bus.async_fire("coordinator_refreshed", {"name": self.name})
''',
        encoding="utf-8",
    )

    rec_dir = components_dir / "recorder"
    rec_dir.mkdir(parents=True, exist_ok=True)
    (rec_dir / "__init__.py").write_text("from .models import States, Events\n", encoding="utf-8")
    (rec_dir / "models.py").write_text(
        '''"""Recorder SQLAlchemy models."""
from sqlalchemy import Column, Integer, String, ForeignKey, create_engine
from sqlalchemy.orm import DeclarativeBase

engine = create_engine("postgresql://user:secret@localhost:5432/homeassistant")

class Base(DeclarativeBase):
    pass

class States(Base):
    __tablename__ = "states"
    state_id = Column(Integer, primary_key=True)
    entity_id = Column(String(255), index=True, nullable=False)
    state = Column(String(255))
    event_id = Column(Integer, ForeignKey("events.event_id"))

class Events(Base):
    __tablename__ = "events"
    event_id = Column(Integer, primary_key=True)
    event_type = Column(String(64), index=True)
''',
        encoding="utf-8",
    )
    (rec_dir / "queries.py").write_text(
        '''"""Recorder DB queries."""
from .models import States, Events

def get_entity_states(session, entity_id: str):
    return session.query(States).filter_by(entity_id=entity_id).all()

def record_state(session, entity_id: str, state_val: str):
    row = States(entity_id=entity_id, state=state_val)
    session.add(row)
    session.commit()
    return row
''',
        encoding="utf-8",
    )

    remaining = max(1, num_files - 10)
    num_domains = max(1, remaining // 5)

    for i in range(num_domains):
        dom = f"integration_{i:04d}"
        dom_dir = components_dir / dom
        dom_dir.mkdir(parents=True, exist_ok=True)
        t_dom_dir = tests_dir / dom
        t_dom_dir.mkdir(parents=True, exist_ok=True)

        (dom_dir / "const.py").write_text(
            f'''"""Constants for {dom}."""
DOMAIN = "{dom}"
DEFAULT_NAME = "Device {i}"
EVENT_UPDATED = "{dom}_updated"
''',
            encoding="utf-8",
        )

        (dom_dir / "coordinator.py").write_text(
            f'''"""Coordinator for {dom}."""
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from .const import DOMAIN, EVENT_UPDATED

class Dom{i}Coordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(hass, DOMAIN)

    async def async_refresh_data(self) -> dict[str, int]:
        await self.async_config_entry_first_refresh()
        self.hass.bus.async_fire(EVENT_UPDATED, {{"domain": DOMAIN}})
        return {{"value": {i}}}

def create_coordinator_{i}(hass: HomeAssistant) -> Dom{i}Coordinator:
    return Dom{i}Coordinator(hass)
''',
            encoding="utf-8",
        )

        (dom_dir / "sensor.py").write_text(
            f'''"""Sensor platform for {dom}."""
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import SensorEntity
from .const import DOMAIN, DEFAULT_NAME
from .coordinator import Dom{i}Coordinator, create_coordinator_{i}

class Dom{i}Sensor(SensorEntity):
    def __init__(self, hass: HomeAssistant, coordinator: Dom{i}Coordinator) -> None:
        super().__init__(hass, DEFAULT_NAME)
        self.coordinator = coordinator

    @callback
    def handle_update(self) -> None:
        self.async_write_ha_state()

async def async_setup_entry(hass: HomeAssistant) -> Dom{i}Sensor:
    coord = create_coordinator_{i}(hass)
    sensor = Dom{i}Sensor(hass, coord)
    sensor.handle_update()
    return sensor
''',
            encoding="utf-8",
        )

        (dom_dir / "__init__.py").write_text(
            f'''"""The {dom} integration."""
from homeassistant.core import HomeAssistant
from .const import DOMAIN
from .sensor import async_setup_entry, Dom{i}Sensor

__all__ = ["DOMAIN", "async_setup_entry", "Dom{i}Sensor"]

async def async_setup(hass: HomeAssistant) -> bool:
    sensor = await async_setup_entry(hass)
    hass.data[DOMAIN] = sensor
    return True
''',
            encoding="utf-8",
        )

        (t_dom_dir / f"test_{dom}.py").write_text(
            f'''"""Tests for {dom}."""
from homeassistant.core import HomeAssistant
from homeassistant.components.{dom} import async_setup
from homeassistant.components.{dom}.sensor import async_setup_entry

async def test_{dom}_setup(hass: HomeAssistant, entry_id: str = "{dom}") -> None:
    ok = await async_setup(hass)
    assert ok is True
    sensor = await async_setup_entry(hass)
    sensor.handle_update()
''',
            encoding="utf-8",
        )


def measure_tier(tier_name: str, num_files: int) -> dict[str, Any]:
    """Run full and incremental indexing on a single benchmark tier."""
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"cg_v217_{tier_name}_"))
    try:
        generate_ha_style_repo(tmp_dir, num_files=num_files)
        get_parse_cache().clear()
        gc.collect()

        indexer = Indexer(tmp_dir, Settings(repository=tmp_dir))
        tracemalloc.start()
        rss_before = get_process_rss_mb()
        t_start = time.perf_counter()
        res = indexer.index()
        total_time = time.perf_counter() - t_start
        _cur_traced, peak_traced = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        gc.collect()
        rss_after = get_process_rss_mb()

        tel = indexer.last_telemetry
        assert tel is not None

        with indexer.session() as con:
            health = check_database_health(con, tmp_dir)
            assert health["status"] == "OK", f"Health check failed: {health}"

        # Incremental 1-file update timing
        target_py = tmp_dir / "homeassistant" / "components" / "integration_0000" / "sensor.py"
        if target_py.exists():
            target_py.write_text(
                target_py.read_text(encoding="utf-8") + "\n# touched\n",
                encoding="utf-8",
            )
        t_inc0 = time.perf_counter()
        indexer_inc = Indexer(tmp_dir, Settings(repository=tmp_dir))
        inc_res = indexer_inc.index()
        inc_time = time.perf_counter() - t_inc0
        assert inc_res["indexed"] == 1

        p = tel.phases
        return {
            "tier": tier_name,
            "files": res["scanned"],
            "symbols": tel.symbols_count,
            "edges": tel.edges_count,
            "total_index_time_s": round(total_time, 3),
            "scan_time_s": round(p["repository_scan"].elapsed_seconds, 3),
            "file_classification_time_s": round(p["file_classification"].elapsed_seconds, 3),
            "file_reading_time_s": round(p["file_reading"].elapsed_seconds, 3),
            "parse_time_s": round(p["ast_parsing"].elapsed_seconds, 3),
            "symbol_extraction_time_s": round(p["symbol_extraction"].elapsed_seconds, 3),
            "import_extraction_time_s": round(p["import_extraction"].elapsed_seconds, 3),
            "framework_analysis_time_s": round(p["framework_analysis"].elapsed_seconds, 3),
            "symbol_resolution_time_s": round(p["symbol_resolution"].elapsed_seconds, 3),
            "relationship_resolution_time_s": round(p["relationship_resolution"].elapsed_seconds, 3),
            "graph_edge_creation_time_s": round(p["graph_edge_creation"].elapsed_seconds, 3),
            "ranking_index_building_time_s": round(p["ranking_index_building"].elapsed_seconds, 3),
            "db_analysis_time_s": round(p["database_analysis"].elapsed_seconds, 3),
            "sqlite_write_time_s": round(p["sqlite_writes"].elapsed_seconds, 3),
            "fts_time_s": round(p["fts_updates"].elapsed_seconds, 3),
            "post_processing_time_s": round(p["post_processing"].elapsed_seconds, 3),
            "final_commit_checkpoint_time_s": round(p["final_commit_checkpoint"].elapsed_seconds, 3),
            "rss_before_mb": round(rss_before, 2),
            "post_parse_rss_mb": round(tel.post_parse_rss_mb, 2),
            "peak_memory_mb": round(max(rss_after, tel.peak_rss_mb), 2),
            "peak_tracemalloc_mb": round(peak_traced / (1024 * 1024), 2),
            "steady_state_rss_mb": round(rss_after, 2),
            "final_db_size_mb": round(tel.final_db_bytes / (1024 * 1024), 2),
            "peak_wal_size_mb": round(tel.peak_wal_bytes / (1024 * 1024), 3),
            "final_wal_size_mb": round(tel.final_wal_bytes / (1024 * 1024), 3),
            "files_per_sec": round(res["scanned"] / max(0.001, total_time), 1),
            "symbols_per_sec": round(tel.symbols_count / max(0.001, total_time), 1),
            "edges_per_sec": round(tel.edges_count / max(0.001, total_time), 1),
            "incremental_update_time_s": round(inc_time, 3),
            "slowest_phase": tel.slowest_phase,
            "commit_batches": tel.commit_batches,
            "checkpoints": tel.checkpoints,
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def run_benchmark_suite(quick: bool = False) -> dict[str, dict[str, Any]]:
    tiers = [("small", 55), ("medium", 305)] if quick else [
        ("small", 55),
        ("medium", 305),
        ("large", 1005),
        ("stress", 2505),
    ]
    results: dict[str, dict[str, Any]] = {}
    for name, n_files in tiers:
        m = measure_tier(name, n_files)
        results[name] = m
        print(
            f"[{name}] files={m['files']} symbols={m['symbols']} edges={m['edges']} "
            f"total={m['total_index_time_s']}s post={m['post_processing_time_s']}s "
            f"db_pass={m['db_analysis_time_s']}s tracemalloc={m['peak_tracemalloc_mb']}MB "
            f"peak_wal={m['peak_wal_size_mb']}MB final_wal={m['final_wal_size_mb']}MB "
            f"inc={m['incremental_update_time_s']}s rate={m['files_per_sec']} files/s"
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CodeGraph v2.1.7 4-tier indexing benchmark")
    parser.add_argument("--quick", action="store_true", help="Run only small and medium tiers")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path")
    args = parser.parse_args()

    results = run_benchmark_suite(quick=args.quick)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
