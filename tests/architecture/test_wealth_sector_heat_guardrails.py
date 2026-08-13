from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BIZ_HEAT_DIR = ROOT / "src/biz/services/wealth/market/sector_overview"
OPS_RUNTIME_DIR = ROOT / "src/ops/runtime"
APP_RUNTIME_DIR = ROOT / "src/app/runtime"
DG_SOURCE_DIR = ROOT / "lake_console/orchestrator/src"


def _python_texts(directory: Path) -> dict[Path, str]:
    return {path: path.read_text(encoding="utf-8") for path in directory.rglob("*.py")}


def test_ops_heat_port_and_dispatcher_do_not_import_biz() -> None:
    texts = _python_texts(OPS_RUNTIME_DIR)

    assert all("src.biz" not in text for text in texts.values())
    assert "MaintenanceExecutor" in (OPS_RUNTIME_DIR / "maintenance_executor.py").read_text(encoding="utf-8")


def test_heat_business_code_has_no_ops_lake_or_source_writes() -> None:
    texts = _python_texts(BIZ_HEAT_DIR)
    combined = "\n".join(texts.values())
    source_query = (BIZ_HEAT_DIR / "sector_heat_source_query.py").read_text(encoding="utf-8")
    pool_query = (BIZ_HEAT_DIR / "effective_a_stock_pool_query.py").read_text(encoding="utf-8")
    materializer = (BIZ_HEAT_DIR / "sector_heat_materialization_service.py").read_text(encoding="utf-8")

    assert "src.ops" not in combined
    assert "lake_console" not in combined
    assert "duckdb" not in combined.lower()
    assert "tushare" not in combined.lower()
    assert "delete(" not in source_query
    assert "insert(" not in source_query
    assert "delete(" not in pool_query
    assert "insert(" not in pool_query
    assert "delete(WealthSectorHeatDaily)" in materializer
    assert "insert(WealthSectorHeatDaily)" in materializer
    assert "TRUNCATE" not in combined.upper()
    assert "CREATE TABLE" not in combined.upper()


def test_app_reuses_existing_session_factory_without_sector_database_config() -> None:
    texts = _python_texts(APP_RUNTIME_DIR)
    combined = "\n".join(texts.values())
    factory = (APP_RUNTIME_DIR / "ops_worker_factory.py").read_text(encoding="utf-8")

    assert "get_session_factory" in factory
    assert "WEALTH_SECTOR_READ_DATABASE_URL" not in combined
    assert "WEALTH_SECTOR_HEAT_DATABASE_URL" not in combined
    assert "WEALTH_SECTOR_HIERARCHY_POSTGRES" not in combined


def test_dg_contains_no_heat_asset_or_second_heat_fact() -> None:
    texts = _python_texts(DG_SOURCE_DIR)
    combined = "\n".join(texts.values())

    assert "gold_wealth_sector_heat_daily" not in combined
    assert "wealth_sector_heat_daily" not in combined
    assert not any("sector_heat" in path.name for path in texts)


def test_heat_execution_chain_contains_no_kopia_dependency() -> None:
    heat_runtime_text = "\n".join(
        [
            *_python_texts(BIZ_HEAT_DIR).values(),
            *_python_texts(APP_RUNTIME_DIR).values(),
            (OPS_RUNTIME_DIR / "maintenance_executor.py").read_text(encoding="utf-8"),
            (OPS_RUNTIME_DIR / "task_run_dispatcher.py").read_text(encoding="utf-8"),
        ]
    )

    assert "kopia" not in heat_runtime_text.lower()
