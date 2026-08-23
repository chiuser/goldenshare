from __future__ import annotations

from pathlib import Path

from qtf.adapters.prod.sector_source_adapter import _begin_read_only
from qtf.modules.sector.input_contract import SECTOR_L2_SOURCE_CONTRACT


class _Dialect:
    name = "postgresql"


class _Bind:
    dialect = _Dialect()


class _RecordingSession:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def get_bind(self) -> _Bind:
        return _Bind()

    def execute(self, statement):  # type: ignore[no-untyped-def]
        self.statements.append(str(statement))


def test_prod_reader_begins_repeatable_read_read_only_transaction() -> None:
    session = _RecordingSession()

    _begin_read_only(session, statement_timeout_ms=60_000)  # type: ignore[arg-type]

    assert session.statements == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
        "SET LOCAL statement_timeout = 60000",
    ]


def test_sector_l2_source_contract_is_exact_and_adapter_has_no_forbidden_sources() -> None:
    assert set(SECTOR_L2_SOURCE_CONTRACT["datasets"]) == {
        "core_serving.trade_calendar",
        "core_serving.wealth_sector_hierarchy",
        "core_serving.dc_daily",
    }
    source = (Path(__file__).parents[1] / "adapters/prod/sector_source_adapter.py").read_text(encoding="utf-8")
    for forbidden in ("dc_member", "moneyflow", "news", "index_daily", "stk_mins", "sw_"):
        assert forbidden not in source.lower()
    for write_call in ("session.add(", "session.delete(", "session.commit("):
        assert write_call not in source
