from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    SectorAnalysisDailyFactsSourceNotReadyError,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.source_query import (
    SectorAnalysisDailyFactsSourceQuery,
)
from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.dc_member import DcMember
from src.foundation.models.core_serving.equity_adj_factor import EquityAdjFactor
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.wealth_sector_hierarchy import WealthSectorHierarchy


MODELS = (
    TradeCalendar,
    WealthSectorHierarchy,
    DcDaily,
    DcMember,
    EquityDailyBar,
    EquityAdjFactor,
)


def _engine():  # type: ignore[no-untyped-def]
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core")
        for model in MODELS:
            model.__table__.create(connection)
    return engine


def _seed(session: Session) -> tuple[date, ...]:
    start = date(2026, 6, 1)
    open_dates = tuple(start + timedelta(days=offset) for offset in range(60))
    published_at = datetime(2026, 8, 31, tzinfo=timezone.utc)
    session.add_all(
        TradeCalendar(exchange="SSE", trade_date=trade_date, is_open=True)
        for trade_date in open_dates
    )
    session.add_all(
        (
            WealthSectorHierarchy(
                sector_code="L1.DC",
                sector_name="一级",
                industry_level=1,
                industry_level_name="一级行业",
                parent_sector_code=None,
                parent_sector_name=None,
                root_sector_code="L1.DC",
                root_sector_name="一级",
                hierarchy_path="一级",
                is_leaf=False,
                display_order=1,
                baseline_version="v1",
                source_received_date=open_dates[-1],
                code_reference_trade_date=open_dates[-1],
                published_at=published_at,
            ),
            WealthSectorHierarchy(
                sector_code="L2.DC",
                sector_name="二级",
                industry_level=2,
                industry_level_name="二级行业",
                parent_sector_code="L1.DC",
                parent_sector_name="一级",
                root_sector_code="L1.DC",
                root_sector_name="一级",
                hierarchy_path="一级 > 二级",
                is_leaf=False,
                display_order=1,
                baseline_version="v1",
                source_received_date=open_dates[-1],
                code_reference_trade_date=open_dates[-1],
                published_at=published_at,
            ),
            WealthSectorHierarchy(
                sector_code="L3.DC",
                sector_name="三级",
                industry_level=3,
                industry_level_name="三级行业",
                parent_sector_code="L2.DC",
                parent_sector_name="二级",
                root_sector_code="L1.DC",
                root_sector_name="一级",
                hierarchy_path="一级 > 二级 > 三级",
                is_leaf=True,
                display_order=1,
                baseline_version="v1",
                source_received_date=open_dates[-1],
                code_reference_trade_date=open_dates[-1],
                published_at=published_at,
            ),
        )
    )
    for offset, trade_date in enumerate(open_dates, start=1):
        session.add_all(
            DcDaily(
                ts_code=code,
                trade_date=trade_date,
                category="行业板块",
                close=Decimal(100 + offset),
                pct_change=Decimal("1"),
                amount=Decimal(1000 + offset),
            )
            for code in ("L1.DC", "L2.DC", "L3.DC")
        )
        session.add_all(
            DcMember(
                trade_date=trade_date,
                ts_code=code,
                con_code="000001.SZ",
                name="股票A",
            )
            for code in ("L1.DC", "L2.DC", "L3.DC")
        )
        session.add(
            EquityDailyBar(
                ts_code="000001.SZ",
                trade_date=trade_date,
                close=Decimal(10 + offset),
                pct_chg=Decimal("1"),
                amount=Decimal(100 + offset),
            )
        )
        session.add(
            EquityAdjFactor(
                ts_code="000001.SZ",
                trade_date=trade_date,
                adj_factor=Decimal("1"),
            )
        )
    session.commit()
    return open_dates


def test_source_query_reads_one_stable_sixty_day_six_source_bundle() -> None:
    engine = _engine()
    with Session(engine) as session:
        open_dates = _seed(session)
        first = SectorAnalysisDailyFactsSourceQuery().load_bundle(
            session,
            trade_date=open_dates[-1],
        )
        second = SectorAnalysisDailyFactsSourceQuery().load_bundle(
            session,
            trade_date=open_dates[-1],
        )

    assert first.open_dates == open_dates
    assert first.previous_trade_date == open_dates[-2]
    assert tuple(pool.scope for pool in first.comparison_pools) == (
        "LEVEL_1",
        "LEVEL_2",
        "LEVEL_3",
        "LEVEL_1_CHILDREN",
        "LEVEL_2_CHILDREN",
    )
    assert first.source_row_counts == {
        "trade_calendar": 60,
        "wealth_sector_hierarchy": 3,
        "dc_daily": 180,
        "dc_member": 180,
        "equity_daily_bar": 60,
        "equity_adj_factor": 60,
    }
    assert first.source_hash == second.source_hash


def test_source_query_blocks_whole_target_date_gap_without_fallback() -> None:
    engine = _engine()
    with Session(engine) as session:
        open_dates = _seed(session)
        session.query(DcDaily).filter(DcDaily.trade_date == open_dates[-1]).delete(
            synchronize_session=False
        )
        session.commit()

        with pytest.raises(SectorAnalysisDailyFactsSourceNotReadyError, match="目标日行业行情整体未发布"):
            SectorAnalysisDailyFactsSourceQuery().load_bundle(
                session,
                trade_date=open_dates[-1],
            )


def test_duplicate_and_non_finite_source_guards_are_fail_closed() -> None:
    with pytest.raises(SectorAnalysisDailyFactsSourceNotReadyError, match="业务键重复"):
        SectorAnalysisDailyFactsSourceQuery._assert_unique((("A", date.min), ("A", date.min)), "dc_daily")


def test_whole_adj_factor_date_gap_is_blocking_but_not_filled() -> None:
    engine = _engine()
    with Session(engine) as session:
        open_dates = _seed(session)
        session.query(EquityAdjFactor).filter(
            EquityAdjFactor.trade_date == open_dates[-1]
        ).delete(synchronize_session=False)
        session.commit()

        with pytest.raises(SectorAnalysisDailyFactsSourceNotReadyError, match="equity_adj_factor 来源日期整体未发布"):
            SectorAnalysisDailyFactsSourceQuery().load_bundle(
                session,
                trade_date=open_dates[-1],
            )


def test_source_query_checks_cancellation_between_source_reads() -> None:
    engine = _engine()
    checks = 0

    def cancel_check() -> None:
        nonlocal checks
        checks += 1
        if checks == 3:
            raise RuntimeError("stop between source reads")

    with Session(engine) as session:
        open_dates = _seed(session)
        with pytest.raises(RuntimeError, match="stop between source reads"):
            SectorAnalysisDailyFactsSourceQuery().load_bundle(
                session,
                trade_date=open_dates[-1],
                cancel_check=cancel_check,
            )

    assert checks == 3
