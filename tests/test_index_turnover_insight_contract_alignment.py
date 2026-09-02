from __future__ import annotations

import ast
from pathlib import Path

from src.biz.services.wealth.market.index_turnover_insight.index_turnover_insight_universe import (
    INDEX_TURNOVER_INSIGHT_UNIVERSE,
)
from src.foundation.clients.local_lake.major_index_mins_contract import (
    MAJOR_INDEX_MINS_GOLD_CODES,
    MAJOR_INDEX_TURNOVER_MAX_PARTITIONS,
    MAJOR_INDEX_TURNOVER_MAX_ROWS,
)


ROOT = Path(__file__).resolve().parents[1]
DG_CONTRACT = ROOT / (
    "lake_console/orchestrator/src/orchestrator/defs/run_contracts/major_index_mins.py"
)


def _assigned_expression(module: ast.Module, name: str) -> ast.expr:
    for statement in module.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in statement.targets
        ):
            return statement.value
    raise AssertionError(f"missing assignment: {name}")


def test_foundation_business_and_dg_gold_code_sets_are_aligned() -> None:
    module = ast.parse(DG_CONTRACT.read_text(encoding="utf-8"))
    scopes = _assigned_expression(module, "MAJOR_INDEX_MINS_SOURCE_SCOPES")
    excluded = _assigned_expression(module, "MAJOR_INDEX_MINS_SILVER_EXCLUDED_CODES")
    assert isinstance(scopes, ast.Tuple)
    source_codes = {
        ast.literal_eval(call.args[0])
        for call in scopes.elts
        if isinstance(call, ast.Call) and call.args
    }
    excluded_codes = set(ast.literal_eval(excluded))
    dg_gold_codes = source_codes - excluded_codes

    business_codes = tuple(
        identity.ts_code for identity in INDEX_TURNOVER_INSIGHT_UNIVERSE
    )
    assert dg_gold_codes == MAJOR_INDEX_MINS_GOLD_CODES == set(business_codes)
    assert len(business_codes) == len(set(business_codes)) == 10
    assert "899050.BJ" not in business_codes
    assert "932000.CSI" not in business_codes


def test_batch_bounds_are_derived_from_the_physical_contract() -> None:
    assert MAJOR_INDEX_TURNOVER_MAX_PARTITIONS == 24
    assert MAJOR_INDEX_TURNOVER_MAX_ROWS == 57_840


def test_src_has_no_runtime_orchestrator_import() -> None:
    offenders: list[Path] = []
    for path in (ROOT / "src").rglob("*.py"):
        if "lake_console.orchestrator" in path.read_text(encoding="utf-8"):
            offenders.append(path)
    assert offenders == []
