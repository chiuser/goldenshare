from __future__ import annotations

import ast
from pathlib import Path

from src.biz.services.wealth.market.index_turnover_insight.index_turnover_insight_exception_builder import (
    INDEX_TURNOVER_INSIGHT_EXCEPTION_SEVERITY,
)


ROOT = Path(__file__).resolve().parents[1]
QUERY_ROOT = ROOT / "src/biz/queries/wealth/market/index_turnover_insight"
SERVICE_ROOT = ROOT / "src/biz/services/wealth/market/index_turnover_insight"
API_PATH = ROOT / "src/biz/api/wealth/market/index_turnover_insight.py"
READER_PATH = ROOT / "src/foundation/clients/local_lake/major_index_turnover_reader.py"
REGISTRY_PATH = ROOT / "wealth/docs/system/exception-code-registry.md"


def test_index_chain_does_not_import_total_or_index_detail_business_contracts() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for root in (QUERY_ROOT, SERVICE_ROOT)
        for path in root.rglob("*.py")
    )
    assert "IndexDetailUniverseService" not in combined
    assert "turnover_insight_query_service" not in combined
    assert "TurnoverDailyAverageQuery" not in combined
    assert "lake_console.orchestrator" not in combined


def test_api_request_contract_has_no_source_scope_parameters() -> None:
    source = API_PATH.read_text(encoding="utf-8")
    module = ast.parse(source)
    allowed_assignment = next(
        statement
        for statement in module.body
        if isinstance(statement, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_ALLOWED_QUERY_PARAMS" for target in statement.targets)
    )
    assert isinstance(allowed_assignment.value, ast.Call)
    assert set(ast.literal_eval(allowed_assignment.value.args[0])) == {
        "market",
        "tradeDate",
        "debug",
    }
    assert 'Query(default=None, alias="codes")' not in source
    assert 'Query(default=None, alias="freq")' not in source


def test_reader_uses_no_glob_and_has_one_connection_site() -> None:
    source = READER_PATH.read_text(encoding="utf-8")
    assert ".glob(" not in source
    assert "rglob(" not in source
    assert source.count("duckdb.connect(") == 1
    assert 'config={"threads": 4}' in source
    assert "open, high, low, close" not in source


def test_exception_builder_and_registry_have_the_same_eight_codes() -> None:
    registry = REGISTRY_PATH.read_text(encoding="utf-8")
    registered = {
        line.split("`")[1]
        for line in registry.splitlines()
        if line.startswith("| `ITI_")
    }
    assert registered == set(INDEX_TURNOVER_INSIGHT_EXCEPTION_SEVERITY)
