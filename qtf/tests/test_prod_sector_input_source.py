from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from qtf.adapters.prod.sector_source_adapter import ProdSectorInputSource, _begin_read_only
from qtf.contracts.errors import QtfRequestInvalid
from qtf.modules.sector.input_contract import SECTOR_L2_SOURCE_CONTRACT, SectorInputRequest
from src.foundation.models.base import Base
from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.wealth_sector_hierarchy import WealthSectorHierarchy


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


def test_prod_reader_resolves_requested_history_and_future_trade_day_counts() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _attach_core_serving(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("ATTACH DATABASE ':memory:' AS core_serving")
        cursor.close()

    Base.metadata.create_all(
        engine,
        tables=[
            TradeCalendar.__table__,
            WealthSectorHierarchy.__table__,
            DcDaily.__table__,
        ],
    )
    days = tuple(date(2026, 8, 1) + timedelta(days=offset) for offset in range(10))
    published_at = datetime(2026, 8, 10, 13, 0, tzinfo=timezone.utc)
    with Session(engine) as session:
        session.add_all(
            TradeCalendar(
                exchange="SSE",
                trade_date=day,
                is_open=True,
                pretrade_date=days[index - 1] if index else None,
            )
            for index, day in enumerate(days)
        )
        session.add_all(
            [
                WealthSectorHierarchy(
                    sector_code="P",
                    sector_name="父行业",
                    industry_level=1,
                    industry_level_name="一级",
                    parent_sector_code=None,
                    parent_sector_name=None,
                    root_sector_code="P",
                    root_sector_name="父行业",
                    hierarchy_path="P",
                    is_leaf=False,
                    display_order=1,
                    baseline_version="v1",
                    source_received_date=days[-1],
                    code_reference_trade_date=days[-1],
                    published_at=published_at,
                ),
                *(
                    WealthSectorHierarchy(
                        sector_code=code,
                        sector_name=f"子行业{code}",
                        industry_level=2,
                        industry_level_name="二级",
                        parent_sector_code="P",
                        parent_sector_name="父行业",
                        root_sector_code="P",
                        root_sector_name="父行业",
                        hierarchy_path=f"P/{code}",
                        is_leaf=True,
                        display_order=index,
                        baseline_version="v1",
                        source_received_date=days[-1],
                        code_reference_trade_date=days[-1],
                        published_at=published_at,
                    )
                    for index, code in enumerate(("A", "B"), start=1)
                ),
            ]
        )
        session.add_all(
            DcDaily(
                ts_code=code,
                trade_date=day,
                category="行业板块",
                pct_change=Decimal("1.0000"),
                amount=Decimal("100.0000"),
            )
            for day in days
            for code in ("A", "B")
        )
        session.commit()

    snapshot = ProdSectorInputSource(lambda: Session(engine)).read(
        SectorInputRequest(
            start_date=days[4],
            end_date=days[5],
            history_trade_days=2,
            future_trade_days=2,
        )
    )

    assert snapshot.trade_dates == days[2:8]
    assert len(snapshot.observations) == 12
    assert snapshot.dataset_evidence[0].start_date == days[2]
    assert snapshot.dataset_evidence[0].end_date == days[7]


def test_prod_reader_rejects_negative_range_expansion_before_opening_a_session() -> None:
    def _must_not_open() -> Session:
        raise AssertionError("session must not be opened")

    source = ProdSectorInputSource(_must_not_open)
    with pytest.raises(QtfRequestInvalid, match="non-negative"):
        source.read(
            SectorInputRequest(
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                history_trade_days=-1,
            )
        )
