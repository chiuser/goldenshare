from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Sequence

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.biz.services.wealth.market.sector_overview.effective_a_stock_pool_query import (
    EffectiveAStockPoolQuery,
    EffectiveAStockPoolSnapshot,
)
from src.biz.services.wealth.market.sector_overview.sector_heat_contract import SectorPoolCounts
from src.biz.services.wealth.market.sector_overview.sector_heat_config import SectorHeatConfigResolver
from src.biz.services.wealth.market.sector_overview.sector_heat_materialization_service import (
    SectorHeatMaterializationError,
    SectorHeatMaterializationService,
)
from src.biz.services.wealth.market.sector_overview.sector_heat_source_query import (
    SectorDailySourceRow,
    SectorHeatSourceBundle,
    SectorIndexSourceRow,
    SectorMoneyflowSourceRow,
    SectorHeatSourceNotReadyError,
    SectorHeatSourceQuery,
    SourceCompletionEvidence,
)
from src.foundation.models.core.board_moneyflow_dc import BoardMoneyflowDc
from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core.dc_index import DcIndex
from src.foundation.models.core.dc_member import DcMember
from src.foundation.models.core.equity_limit_list import EquityLimitList
from src.foundation.models.core.equity_suspend_d import EquitySuspendD
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.security_serving import Security
from src.foundation.models.core_serving.wealth_sector_heat_daily import WealthSectorHeatDaily


def _engine(*tables):  # type: ignore[no-untyped-def]
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        for table in tables:
            table.__table__.create(connection)
    return engine


def test_effective_pool_counts_all_exclusions_from_one_relation() -> None:
    engine = _engine(DcMember, EquityLimitList, EquitySuspendD, EquityDailyBar, Security)
    target = date(2026, 8, 12)
    members = (
        "UP.SZ",
        "DOWN.SZ",
        "SUSPEND.SZ",
        "MISSING.SZ",
        "B.SH",
        "FUTURE.SZ",
        "DELIST.SZ",
    )
    with Session(engine) as session:
        session.add_all(
            [DcMember(trade_date=target, ts_code="BK001.DC", con_code=code, name=code) for code in members]
        )
        session.add_all(
            [
                Security(ts_code="UP.SZ", name="UP", curr_type="CNY", list_status="L", list_date=date(2020, 1, 1)),
                Security(ts_code="DOWN.SZ", name="DOWN", curr_type="CNY", list_status="L", list_date=date(2020, 1, 1)),
                Security(ts_code="SUSPEND.SZ", name="SUSPEND", curr_type="CNY", list_status="L", list_date=date(2020, 1, 1)),
                Security(ts_code="MISSING.SZ", name="MISSING", curr_type="CNY", list_status="L", list_date=date(2020, 1, 1)),
                Security(ts_code="B.SH", name="B", curr_type="USD", list_status="L", list_date=date(2020, 1, 1)),
                Security(ts_code="FUTURE.SZ", name="FUTURE", curr_type="CNY", list_status="L", list_date=date(2027, 1, 1)),
                Security(
                    ts_code="DELIST.SZ",
                    name="DELIST",
                    curr_type="CNY",
                    list_status="D",
                    list_date=date(2020, 1, 1),
                    delist_date=target,
                ),
            ]
        )
        session.add_all(
            [
                EquityDailyBar(ts_code="UP.SZ", trade_date=target, pct_chg=Decimal("2")),
                EquityDailyBar(ts_code="DOWN.SZ", trade_date=target, pct_chg=Decimal("-1")),
                EquityDailyBar(ts_code="SUSPEND.SZ", trade_date=target, pct_chg=Decimal("3")),
            ]
        )
        session.add(EquityLimitList(ts_code="UP.SZ", trade_date=target, limit_type="U"))
        session.add(
            EquitySuspendD(
                id=1,
                row_key_hash="a" * 64,
                ts_code="SUSPEND.SZ",
                trade_date=target,
                suspend_type="S",
            )
        )
        session.commit()

        snapshots = EffectiveAStockPoolQuery().load(
            session,
            ordered_trade_dates=[target],
            sector_codes_by_date={target: ["BK001.DC"]},
        )

    snapshot = snapshots[(target, "BK001.DC")]
    assert snapshot.counts.source_member_count == 7
    assert snapshot.counts.member_count == 4
    assert snapshot.counts.suspended_count == 1
    assert snapshot.counts.quote_eligible_count == 3
    assert snapshot.counts.valid_quote_count == 2
    assert snapshot.counts.missing_quote_count == 1
    assert snapshot.counts.quote_coverage == pytest.approx(2 / 3)
    assert snapshot.up_count == 1
    assert snapshot.limit_up_count == 1


def _source_query_engine():  # type: ignore[no-untyped-def]
    return _engine(
        TradeCalendar,
        DcIndex,
        DcDaily,
        DcMember,
        BoardMoneyflowDc,
        Security,
        EquityDailyBar,
        EquityLimitList,
        EquitySuspendD,
        WealthSectorHeatDaily,
    )


def _seed_source_query(session: Session) -> tuple[date, tuple[date, ...]]:
    target = date(2026, 8, 12)
    open_dates = tuple(target - timedelta(days=offset) for offset in reversed(range(26)))
    calculation_dates = open_dates[-6:]
    money_dates = open_dates[-10:]
    session.add_all(
        [TradeCalendar(exchange="SSE", trade_date=trade_date, is_open=True) for trade_date in open_dates]
    )
    session.add_all(
        [
            DcIndex(
                trade_date=trade_date,
                ts_code=sector_code,
                name=f"概念{sector_code}",
                idx_type="概念板块",
            )
            for trade_date in calculation_dates
            for sector_code in ("A.DC", "B.DC")
        ]
    )
    session.add_all(
        [
            DcDaily(
                trade_date=trade_date,
                ts_code=sector_code,
                category="概念板块",
                pct_change=Decimal("1"),
                amount=Decimal("100"),
            )
            for trade_date in open_dates
            for sector_code in ("A.DC", "B.DC")
            if not (trade_date == target and sector_code == "B.DC")
        ]
    )
    session.add_all(
        [
            DcMember(trade_date=trade_date, ts_code=sector_code, con_code=stock_code, name=stock_code)
            for trade_date in calculation_dates
            for sector_code, stock_code in (("A.DC", "A.SZ"), ("B.DC", "B.SZ"))
        ]
    )
    session.add_all(
        [
            BoardMoneyflowDc(
                trade_date=trade_date,
                content_type="概念板块",
                name=f"概念{sector_code}",
                ts_code=sector_code,
                net_amount=Decimal("10"),
                net_amount_rate=Decimal("1"),
            )
            for trade_date in money_dates
            for sector_code in ("A.DC", "B.DC")
        ]
    )
    session.add_all(
        [
            Security(ts_code=stock_code, name=stock_code, curr_type="CNY", list_status="L", list_date=date(2020, 1, 1))
            for stock_code in ("A.SZ", "B.SZ")
        ]
    )
    session.add_all(
        [
            EquityDailyBar(ts_code=stock_code, trade_date=trade_date, pct_chg=Decimal("1"))
            for trade_date in calculation_dates
            for stock_code in ("A.SZ", "B.SZ")
        ]
    )
    session.commit()
    return target, calculation_dates


def _zero_row_evidence(calculation_dates: Sequence[date]) -> tuple[SourceCompletionEvidence, ...]:
    return tuple(
        SourceCompletionEvidence(
            dataset_key=dataset_key,
            trade_date=trade_date,
            status="COMPLETE",
            evidence_type="test",
            evidence_id=f"{dataset_key}:{trade_date.isoformat()}",
            evidence_hash="e" * 64,
        )
        for trade_date in calculation_dates
        for dataset_key in ("limit_list_d", "suspend_d")
    )


def test_source_query_is_prod_bounded_and_allows_only_local_concept_gaps() -> None:
    engine = _source_query_engine()
    with Session(engine) as session:
        target, calculation_dates = _seed_source_query(session)
        query = SectorHeatSourceQuery()
        resolved = SectorHeatConfigResolver().resolve()
        first = query.load(
            session,
            trade_date=target,
            resolved_config=resolved,
            completion_evidence=_zero_row_evidence(calculation_dates),
        )
        second = query.load(
            session,
            trade_date=target,
            resolved_config=resolved,
            completion_evidence=_zero_row_evidence(calculation_dates),
        )

    assert len(first.all_open_dates) == 26
    assert len(first.calculation_dates) == 6
    assert len(first.moneyflow_dates) == 10
    assert len([row for row in first.index_rows if row.trade_date == target]) == 2
    assert len([row for row in first.daily_rows if row.trade_date == target]) == 1
    assert first.source_hash == second.source_hash


def test_zero_row_limit_or_suspend_source_requires_completion_evidence() -> None:
    engine = _source_query_engine()
    with Session(engine) as session:
        target, _ = _seed_source_query(session)
        with pytest.raises(SectorHeatSourceNotReadyError, match="zero rows without completion evidence"):
            SectorHeatSourceQuery().load(
                session,
                trade_date=target,
                resolved_config=SectorHeatConfigResolver().resolve(),
            )


class _SourceQueryStub:
    def __init__(self, bundle: SectorHeatSourceBundle) -> None:
        self.bundle = bundle

    def load(  # type: ignore[no-untyped-def]
        self,
        session,
        *,
        trade_date,
        resolved_config,
        completion_evidence=(),
        prior_published_override=None,
    ):
        del session, resolved_config, completion_evidence, prior_published_override
        assert trade_date == self.bundle.target_date
        return self.bundle


class _PoolQueryStub:
    def __init__(self, snapshots: dict[tuple[date, str], EffectiveAStockPoolSnapshot]) -> None:
        self.snapshots = snapshots

    def load(self, session, *, ordered_trade_dates, sector_codes_by_date):  # type: ignore[no-untyped-def]
        del session
        assert set(ordered_trade_dates) == {trade_date for trade_date, _ in self.snapshots}
        assert set(sector_codes_by_date) == set(ordered_trade_dates)
        return self.snapshots


def _materialization_fixtures() -> tuple[SectorHeatSourceBundle, dict[tuple[date, str], EffectiveAStockPoolSnapshot]]:
    target = date(2026, 8, 12)
    all_open_dates = tuple(target - timedelta(days=offset) for offset in reversed(range(26)))
    calculation_dates = all_open_dates[-6:]
    money_dates = all_open_dates[-10:]
    codes = ("A.DC", "B.DC", "C.DC")
    index_rows = tuple(
        SectorIndexSourceRow(trade_date, code, f"概念{code}")
        for trade_date in calculation_dates
        for code in codes
    )
    daily_rows = tuple(
        SectorDailySourceRow(
            trade_date,
            code,
            Decimal(str(index + 1)),
            Decimal(str((index + 1) * 100)),
        )
        for trade_date in all_open_dates
        for index, code in enumerate(codes)
    )
    money_rows = tuple(
        SectorMoneyflowSourceRow(
            trade_date,
            code,
            Decimal(str((index + 1) * 10)),
            Decimal(str(index + 1)),
        )
        for trade_date in money_dates
        for index, code in enumerate(codes)
    )
    bundle = SectorHeatSourceBundle(
        target_date=target,
        all_open_dates=all_open_dates,
        calculation_dates=calculation_dates,
        moneyflow_dates=money_dates,
        index_rows=index_rows,
        daily_rows=daily_rows,
        member_rows=(),
        moneyflow_rows=money_rows,
        security_rows=(),
        bar_rows=(),
        limit_up_rows=(),
        suspended_rows=(),
        prior_published_by_date={},
        source_dates_json={"target": target.isoformat()},
        source_row_counts_json={"dc_index": len(index_rows), "dc_daily": len(daily_rows)},
        source_hash="b" * 64,
    )
    snapshots = {
        (trade_date, code): EffectiveAStockPoolSnapshot(
            trade_date=trade_date,
            sector_code=code,
            counts=SectorPoolCounts(12, 12, 1, 11, 10, 1, 10 / 11),
            up_count=(index + 1) * 2,
            limit_up_count=index,
        )
        for trade_date in calculation_dates
        for index, code in enumerate(codes)
    }
    return bundle, snapshots


def _service(bundle, snapshots) -> SectorHeatMaterializationService:  # type: ignore[no-untyped-def]
    return SectorHeatMaterializationService(
        source_query=_SourceQueryStub(bundle),  # type: ignore[arg-type]
        pool_query=_PoolQueryStub(snapshots),  # type: ignore[arg-type]
    )


def test_single_day_materialization_replaces_and_reads_back_in_one_transaction() -> None:
    bundle, snapshots = _materialization_fixtures()
    engine = _engine(WealthSectorHeatDaily)
    with Session(engine) as session:
        result = _service(bundle, snapshots).materialize_trade_date(session, trade_date=bundle.target_date)
        stored = session.scalar(
            select(func.count()).select_from(WealthSectorHeatDaily).where(
                WealthSectorHeatDaily.trade_date == bundle.target_date
            )
        )

    assert result.rows_written == 3
    assert result.skipped_existing is False
    assert result.valid_count == 3
    assert result.invalid_count == 0
    assert stored == 3
    assert len(result.content_hash) == 64
    assert len(result.plan_hash) == 64


def test_replay_resume_skips_existing_content_after_revalidating_plan() -> None:
    bundle, snapshots = _materialization_fixtures()
    engine = _engine(WealthSectorHeatDaily)
    service = _service(bundle, snapshots)
    with Session(engine) as session:
        first = service.materialize_trade_date(session, trade_date=bundle.target_date)
        resumed = service.materialize_trade_date(
            session,
            trade_date=bundle.target_date,
            expected_plan_hash=first.plan_hash,
            expected_content_hash=first.content_hash,
        )
        stored = session.scalar(
            select(func.count()).select_from(WealthSectorHeatDaily).where(
                WealthSectorHeatDaily.trade_date == bundle.target_date
            )
        )

    assert resumed.rows_written == 0
    assert resumed.skipped_existing is True
    assert resumed.content_hash == first.content_hash
    assert stored == 3


def test_plan_drift_fails_before_replacing_existing_success() -> None:
    bundle, snapshots = _materialization_fixtures()
    engine = _engine(WealthSectorHeatDaily)
    service = _service(bundle, snapshots)
    with Session(engine) as session:
        service.materialize_trade_date(session, trade_date=bundle.target_date)
        with pytest.raises(SectorHeatMaterializationError, match="HEAT_PLAN_DRIFT"):
            service.materialize_trade_date(
                session,
                trade_date=bundle.target_date,
                expected_plan_hash="0" * 64,
            )
        stored = session.scalar(
            select(func.count()).select_from(WealthSectorHeatDaily).where(
                WealthSectorHeatDaily.trade_date == bundle.target_date
            )
        )

    assert stored == 3


def test_read_back_mismatch_rolls_back_and_preserves_previous_day_rows(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    bundle, snapshots = _materialization_fixtures()
    engine = _engine(WealthSectorHeatDaily)
    service = _service(bundle, snapshots)
    with Session(engine) as session:
        service.materialize_trade_date(session, trade_date=bundle.target_date)
        monkeypatch.setattr(service, "_read_back", lambda session, trade_date: [])
        with pytest.raises(SectorHeatMaterializationError, match="read-back mismatch"):
            service.materialize_trade_date(session, trade_date=bundle.target_date)
        stored = session.scalar(
            select(func.count()).select_from(WealthSectorHeatDaily).where(
                WealthSectorHeatDaily.trade_date == bundle.target_date
            )
        )

    assert stored == 3
