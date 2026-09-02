from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from time import perf_counter
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import event, select

from src.foundation.config.settings import get_settings
from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core.dc_member import DcMember
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.equity_adj_factor import EquityAdjFactor
from src.foundation.models.core_serving.wealth_sector_hierarchy import (
    WealthSectorHierarchy,
)
from src.foundation.models.core_serving.wealth_sector_analysis_publish_batch import (
    WealthSectorAnalysisPublishBatch,
)
from src.foundation.models.core_serving.wealth_sector_momentum_daily import (
    WealthSectorMomentumDaily,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    FORMULA_BUNDLE_VERSION,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_calculator import (
    SectorMomentumCalculator,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    FORMULA_KEY as MOMENTUM_FORMULA_KEY,
    FORMULA_VERSION as MOMENTUM_FORMULA_VERSION,
    SectorDailyFact,
    SectorReturnFact,
    global_level_pool,
    parent_pool,
    resolve_scope_pool,
)
from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchyQuery,
)
from src.biz.queries.wealth.market.sector_analysis.sector_momentum_snapshot_query_service import (
    SectorMomentumSnapshotQueryService,
)


TARGET_DATE = date(2026, 4, 30)
OPEN_DATES = tuple(TARGET_DATE - timedelta(days=offset) for offset in range(64, -1, -1))


def _ensure_tables(db_session) -> None:
    bind = db_session.get_bind()
    DcDaily.__table__.create(bind, checkfirst=True)
    DcMember.__table__.create(bind, checkfirst=True)
    EquityAdjFactor.__table__.create(bind, checkfirst=True)
    EquityDailyBar.__table__.create(bind, checkfirst=True)
    WealthSectorHierarchy.__table__.create(bind, checkfirst=True)
    WealthSectorAnalysisPublishBatch.__table__.create(bind, checkfirst=True)
    WealthSectorMomentumDaily.__table__.create(bind, checkfirst=True)


def _hierarchy_rows() -> tuple[tuple[str, str, int, str | None, str, str], ...]:
    return (
        ("BK1001.DC", "一级甲", 1, None, "BK1001.DC", "一级甲"),
        ("BK1002.DC", "一级乙", 1, None, "BK1002.DC", "一级乙"),
        ("BK1101.DC", "二级甲一", 2, "BK1001.DC", "BK1001.DC", "一级甲/二级甲一"),
        ("BK1102.DC", "二级甲二", 2, "BK1001.DC", "BK1001.DC", "一级甲/二级甲二"),
        ("BK1103.DC", "二级乙一", 2, "BK1002.DC", "BK1002.DC", "一级乙/二级乙一"),
        (
            "BK1201.DC",
            "三级甲一一",
            3,
            "BK1101.DC",
            "BK1001.DC",
            "一级甲/二级甲一/三级甲一一",
        ),
        (
            "BK1202.DC",
            "三级甲一二",
            3,
            "BK1101.DC",
            "BK1001.DC",
            "一级甲/二级甲一/三级甲一二",
        ),
    )


def _seed_sector_analysis(db_session) -> None:
    _ensure_tables(db_session)
    rows = _hierarchy_rows()
    previous: date | None = None
    for item in OPEN_DATES:
        db_session.add(
            TradeCalendar(
                exchange="SSE",
                trade_date=item,
                is_open=True,
                pretrade_date=previous,
            )
        )
        previous = item
    for order, (code, name, level, parent, root, path) in enumerate(rows, start=1):
        parent_name = next((row[1] for row in rows if row[0] == parent), None)
        root_name = next(row[1] for row in rows if row[0] == root)
        db_session.add(
            WealthSectorHierarchy(
                sector_code=code,
                sector_name=name,
                industry_level=level,
                industry_level_name=f"{level}级行业",
                parent_sector_code=parent,
                parent_sector_name=parent_name,
                root_sector_code=root,
                root_sector_name=root_name,
                hierarchy_path=path,
                is_leaf=level == 3,
                display_order=order,
                baseline_version="2026-04-30-v1",
                source_received_date=TARGET_DATE,
                code_reference_trade_date=TARGET_DATE,
                published_at=datetime(2026, 4, 30, 20, 0, tzinfo=timezone.utc),
            )
        )
        for date_index, item in enumerate(OPEN_DATES):
            close = Decimal(100 + order * 10 + date_index)
            db_session.add(
                DcDaily(
                    ts_code=code,
                    trade_date=item,
                    category="行业板块",
                    close=close,
                    open=close,
                    high=close,
                    low=close,
                    change=Decimal(order),
                    pct_change=Decimal(10 - order),
                    vol=Decimal("100"),
                    amount=Decimal("1000"),
                    swing=Decimal("1"),
                    turnover_rate=Decimal("2"),
                )
            )
    _seed_momentum_serving_facts(db_session, rows=rows)
    db_session.commit()


def _seed_momentum_serving_facts(db_session, *, rows) -> None:  # type: ignore[no-untyped-def]
    calculator = SectorMomentumCalculator()
    facts = tuple(
        SectorDailyFact(
            sector_code=code,
            trade_date=item,
            close=Decimal(100 + order * 10 + date_index),
            pct_change=Decimal(10 - order),
        )
        for order, (code, *_rest) in enumerate(rows, start=1)
        for date_index, item in enumerate(OPEN_DATES)
    )
    fact_index = calculator.index_facts(facts)
    by_code = {row[0]: row for row in rows}
    pools: list[tuple[str, str, str | None, tuple[str, ...]]] = []
    for level in (1, 2, 3):
        pools.append(
            (
                f"LEVEL_{level}",
                f"GLOBAL:L{level}",
                None,
                tuple(row[0] for row in rows if row[2] == level),
            )
        )
    for parent_code, _name, parent_level, *_rest in rows:
        if parent_level not in (1, 2):
            continue
        children = tuple(row[0] for row in rows if row[3] == parent_code)
        if children:
            pools.append(
                (
                    f"LEVEL_{parent_level}_CHILDREN",
                    f"PARENT:L{parent_level}:{parent_code}",
                    parent_code,
                    children,
                )
            )
    calculated_at = datetime(2026, 4, 30, 20, 0, tzinfo=timezone.utc)
    for target_date in OPEN_DATES:
        batch_id = uuid5(NAMESPACE_URL, f"sector-analysis-test:{target_date.isoformat()}")
        fact_count = sum(len(pool[3]) * 5 for pool in pools)
        db_session.add(
            WealthSectorAnalysisPublishBatch(
                batch_id=batch_id,
                trade_date=target_date,
                status="PUBLISHED",
                previous_trade_date=None,
                previous_batch_id=None,
                hierarchy_version="2026-04-30-v1",
                formula_bundle_version=FORMULA_BUNDLE_VERSION,
                template_version="sector-daily-insight-template@1",
                source_hash="a" * 64,
                plan_hash="b" * 64,
                content_hash="c" * 64,
                source_dates_json={},
                source_row_counts_json={},
                expected_fact_counts_json={"wealth_sector_momentum_daily": fact_count},
                actual_fact_counts_json={"wealth_sector_momentum_daily": fact_count},
                started_at=calculated_at,
                calculated_at=calculated_at,
                published_at=calculated_at,
            )
        )
        for scope, comparison_key, parent_code, sector_codes in pools:
            for period in (1, 5, 10, 20, 30):
                returns = calculator.calculate_for_date(
                    sector_codes=sector_codes,
                    open_dates=OPEN_DATES,
                    target_date=target_date,
                    period=period,  # type: ignore[arg-type]
                    fact_index=fact_index,
                )
                ranked = calculator.rank_strength(returns)
                return_by_code = {row.sector_code: row for row in returns}
                calculable_count = sum(row.return_pct is not None for row in ranked)
                for rank in ranked:
                    code, name, level, _parent, _root, path = by_code[rank.sector_code]
                    return_fact = return_by_code[code]
                    db_session.add(
                        WealthSectorMomentumDaily(
                            batch_id=batch_id,
                            trade_date=target_date,
                            comparison_scope=scope,
                            comparison_key=comparison_key,
                            parent_sector_code=parent_code,
                            sector_code=code,
                            sector_name=name,
                            industry_level=level,
                            hierarchy_path=path,
                            period=period,
                            return_pct=rank.return_pct,
                            strength_rank=rank.strength_rank,
                            rankable_count=(
                                calculable_count if rank.strength_rank is not None else None
                            ),
                            percentile=rank.percentile,
                            formula_key=MOMENTUM_FORMULA_KEY,
                            formula_version=MOMENTUM_FORMULA_VERSION,
                            calculation_status=(
                                "CALCULABLE"
                                if rank.return_pct is not None
                                else "UNAVAILABLE"
                            ),
                            missing_reason=return_fact.missing_reason,
                            calculated_at=calculated_at,
                        )
                    )


def _mark_momentum_unavailable(
    db_session,
    *,
    trade_date: date,
    comparison_key: str,
    sector_code: str,
    period: int = 1,
) -> None:
    rows = tuple(
        db_session.scalars(
        select(WealthSectorMomentumDaily).where(
            WealthSectorMomentumDaily.trade_date == trade_date,
            WealthSectorMomentumDaily.comparison_key == comparison_key,
            WealthSectorMomentumDaily.period == period,
        )
        )
    )
    row = next((item for item in rows if item.sector_code == sector_code), None)
    assert row is not None
    row.return_pct = None
    row.strength_rank = None
    row.rankable_count = None
    row.percentile = None
    row.calculation_status = "UNAVAILABLE"
    row.missing_reason = "DATE_MISSING"
    ranked = SectorMomentumCalculator.rank_strength(
        SectorReturnFact(
            sector_code=item.sector_code,
            trade_date=trade_date,
            return_pct=item.return_pct,
            missing_reason=item.missing_reason,
        )
        for item in rows
    )
    rank_by_code = {item.sector_code: item for item in ranked}
    calculable_count = sum(item.return_pct is not None for item in ranked)
    for item in rows:
        updated = rank_by_code[item.sector_code]
        item.strength_rank = updated.strength_rank
        item.rankable_count = (
            calculable_count if updated.strength_rank is not None else None
        )
        item.percentile = updated.percentile


def _unpublish_momentum_date(db_session, *, trade_date: date) -> None:
    batch = db_session.scalar(
        select(WealthSectorAnalysisPublishBatch).where(
            WealthSectorAnalysisPublishBatch.trade_date == trade_date,
            WealthSectorAnalysisPublishBatch.status == "PUBLISHED",
        )
    )
    assert batch is not None
    batch.status = "FAILED"
    batch.failed_at = datetime(2026, 5, 1, tzinfo=timezone.utc)
    batch.failure_reason_code = "TEST_UNPUBLISHED"


def _seed_sector_members(db_session) -> None:
    for code, name in (
        ("000001.SZ", "股票甲"),
        ("000003.SZ", None),
        ("200001.SZ", "B股样本"),
    ):
        db_session.add(
            DcMember(
                trade_date=TARGET_DATE,
                ts_code="BK1201.DC",
                con_code=code,
                name=name,
            )
        )
    for item in OPEN_DATES[-5:]:
        for code, pct_chg in (("000001.SZ", "1"), ("200001.SZ", "2")):
            db_session.add(
                EquityDailyBar(
                    ts_code=code,
                    trade_date=item,
                    open=Decimal("10"),
                    high=Decimal("10"),
                    low=Decimal("10"),
                    close=None
                    if code == "200001.SZ" and item == TARGET_DATE
                    else Decimal("10"),
                    pre_close=Decimal("10"),
                    change_amount=Decimal("0"),
                    pct_chg=Decimal(pct_chg),
                    vol=Decimal("100"),
                    amount=Decimal("1000"),
                )
            )
    db_session.add(
        EquityDailyBar(
            ts_code="000003.SZ",
            trade_date=TARGET_DATE,
            open=Decimal("8"),
            high=Decimal("8"),
            low=Decimal("8"),
            close=Decimal("8"),
            pre_close=Decimal("8"),
            change_amount=Decimal("0"),
            pct_chg=None,
            vol=Decimal("100"),
            amount=Decimal("1000"),
        )
    )
    db_session.commit()


def _seed_member_breadth(db_session) -> None:
    """Seed complete bounded facts for all seven hierarchy nodes."""

    _seed_sector_analysis(db_session)
    for sector_index, (sector_code, *_rest) in enumerate(_hierarchy_rows(), start=1):
        stock_codes = tuple(
            f"{sector_index:02d}{stock_index:04d}.SZ" for stock_index in range(1, 6)
        )
        for item in OPEN_DATES[-20:]:
            for stock_index, stock_code in enumerate(stock_codes, start=1):
                db_session.add(
                    DcMember(
                        trade_date=item,
                        ts_code=sector_code,
                        con_code=stock_code,
                        name=f"股票{sector_index}-{stock_index}",
                    )
                )
        for date_index, item in enumerate(OPEN_DATES[-60:], start=1):
            for stock_index, stock_code in enumerate(stock_codes, start=1):
                close = Decimal(10 + stock_index) + Decimal(date_index) / Decimal(10)
                positive_count = min(sector_index, 5)
                pct_chg = Decimal(1 if stock_index <= positive_count else -1)
                db_session.add(
                    EquityDailyBar(
                        ts_code=stock_code,
                        trade_date=item,
                        open=close,
                        high=close,
                        low=close,
                        close=close,
                        pre_close=close,
                        change_amount=Decimal(0),
                        pct_chg=pct_chg,
                        vol=Decimal(100),
                        amount=Decimal(100 * stock_index),
                    )
                )
                db_session.add(
                    EquityAdjFactor(
                        ts_code=stock_code,
                        trade_date=item,
                        adj_factor=Decimal(1),
                    )
                )
    db_session.commit()


def _count_request_sql(engine, callback) -> tuple[int, object]:
    statements: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        response = callback()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return len(statements), response


def test_meta_returns_hierarchy_and_complete_open_date_coverage_in_three_sql(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_sector_analysis(db_session)

    sql_count, response = _count_request_sql(
        web_engine,
        lambda: app_client.get("/api/v1/wealth/market/sector-analysis/meta"),
    )

    assert response.status_code == 200
    assert sql_count == 3
    payload = response.json()
    assert payload["coverageStartDate"] == OPEN_DATES[0].isoformat()
    assert payload["coverageEndDate"] == TARGET_DATE.isoformat()
    assert len(payload["hierarchy"]["nodes"]) == 7
    assert len(payload["tradeDates"]) == 65
    assert {item["availability"] for item in payload["tradeDates"]} == {"COMPLETE"}
    assert payload["formula"] == {
        "formulaKey": "sector-cross-sectional-momentum",
        "formulaVersion": 1,
        "periods": [1, 5, 10, 20, 30],
        "historyRanges": [20, 30, 60],
        "scopes": [
            "LEVEL_1",
            "LEVEL_2",
            "LEVEL_3",
            "LEVEL_1_CHILDREN",
            "LEVEL_2_CHILDREN",
        ],
        "directions": ["GAINERS", "LOSERS"],
    }


def test_rankings_returns_full_gain_and_loss_lists_with_stable_strength_ranks_in_four_sql(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_sector_analysis(db_session)

    sql_count, gainers = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/momentum/rankings",
            params={
                "tradeDate": TARGET_DATE.isoformat(),
                "scope": "LEVEL_1",
                "debug": 1,
            },
        ),
    )
    losers = app_client.get(
        "/api/v1/wealth/market/sector-analysis/momentum/rankings",
        params={
            "tradeDate": TARGET_DATE.isoformat(),
            "scope": "LEVEL_1",
            "direction": "LOSERS",
        },
    )

    assert gainers.status_code == 200
    assert losers.status_code == 200
    assert sql_count == 4
    gain_payload = gainers.json()
    loss_payload = losers.json()
    assert gain_payload["status"] == "READY"
    assert gain_payload["ranking"]["totalCount"] == 2
    assert gain_payload["ranking"]["calculableCount"] == 2
    assert [row["sectorCode"] for row in gain_payload["ranking"]["rows"]] == [
        "BK1001.DC",
        "BK1002.DC",
    ]
    assert [row["sectorCode"] for row in loss_payload["ranking"]["rows"]] == [
        "BK1002.DC",
        "BK1001.DC",
    ]
    gain_ranks = {
        row["sectorCode"]: row["strengthRank"]
        for row in gain_payload["ranking"]["rows"]
    }
    loss_ranks = {
        row["sectorCode"]: row["strengthRank"]
        for row in loss_payload["ranking"]["rows"]
    }
    assert gain_ranks == loss_ranks == {"BK1001.DC": 1, "BK1002.DC": 2}
    assert gain_payload["debugInfo"]["sampleSectorCodes"] == ["BK1001.DC", "BK1002.DC"]


def test_history_returns_current_global_and_parent_ranks_and_sixty_slots_in_five_sql(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_sector_analysis(db_session)

    sql_count, response = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/momentum/history",
            params={
                "tradeDate": TARGET_DATE.isoformat(),
                "scope": "LEVEL_1_CHILDREN",
                "level1Code": "BK1001.DC",
                "period": 1,
                "historyRange": 60,
                "sectorCode": "BK1101.DC",
            },
        ),
    )

    assert response.status_code == 200
    assert sql_count == 5
    payload = response.json()
    assert payload["status"] == "READY"
    assert len(payload["rollingReturns"]) == 60
    assert len(payload["historicalRanks"]) == 60
    assert [row["tradeDate"] for row in payload["rollingReturns"]] == [
        row["tradeDate"] for row in payload["historicalRanks"]
    ]
    assert payload["detail"]["currentScopeTotalCount"] == 2
    assert payload["detail"]["globalLevelTotalCount"] == 3
    assert payload["detail"]["parentTotalCount"] == 2
    assert payload["detail"]["scopeTitle"] == "一级甲内二级行业"


def test_m24_all_momentum_scopes_periods_and_directions_match_online_oracle(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    calculator = SectorMomentumCalculator()
    oracle = SectorMomentumSnapshotQueryService()
    scope_cases = (
        ("LEVEL_1", None, None),
        ("LEVEL_2", None, None),
        ("LEVEL_3", None, None),
        ("LEVEL_1_CHILDREN", "BK1001.DC", None),
        ("LEVEL_2_CHILDREN", "BK1001.DC", "BK1101.DC"),
    )
    for scope, level1_code, level2_code in scope_cases:
        for period in (1, 5, 10, 20, 30):
            snapshot = oracle.build(
                db_session,
                market="CN_A",
                trade_date=TARGET_DATE,
                scope=scope,  # type: ignore[arg-type]
                level1_code=level1_code,
                level2_code=level2_code,
                period=period,  # type: ignore[arg-type]
            )
            node_by_code = {row.node.sector_code: row.node for row in snapshot.rows}
            rank_rows = tuple(row.rank_fact for row in snapshot.rows)
            for direction in ("GAINERS", "LOSERS"):
                response = app_client.get(
                    "/api/v1/wealth/market/sector-analysis/momentum/rankings",
                    params={
                        key: value
                        for key, value in {
                            "tradeDate": TARGET_DATE.isoformat(),
                            "scope": scope,
                            "level1Code": level1_code,
                            "level2Code": level2_code,
                            "period": period,
                            "direction": direction,
                        }.items()
                        if value is not None
                    },
                )
                assert response.status_code == 200
                payload = response.json()
                assert payload["status"] == "READY"
                expected = calculator.sort_ranking_rows(
                    rank_rows,
                    direction=direction,  # type: ignore[arg-type]
                )
                assert payload["ranking"]["totalCount"] == len(snapshot.rows)
                assert payload["ranking"]["calculableCount"] == sum(
                    row.return_pct is not None for row in expected
                )
                assert [
                    (
                        row["listPosition"],
                        row["sectorCode"],
                        row["strengthRank"],
                        row["returnPct"],
                        row["percentile"],
                    )
                    for row in payload["ranking"]["rows"]
                ] == [
                    (
                        index,
                        row.sector_code,
                        row.strength_rank,
                        calculator.as_json_return(row.return_pct),
                        calculator.as_json_percentile(row.percentile),
                    )
                    for index, row in enumerate(expected, start=1)
                ]
                assert all(row.sector_code in node_by_code for row in expected)


def test_m24_all_momentum_history_ranges_match_online_calculator(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    hierarchy = SectorHierarchyQuery().load(db_session)
    calculator = SectorMomentumCalculator()
    facts = tuple(
        SectorDailyFact(
            sector_code=row.ts_code,
            trade_date=row.trade_date,
            close=row.close,
            pct_change=row.pct_change,
        )
        for row in db_session.scalars(
            select(DcDaily).where(DcDaily.category == "行业板块")
        )
    )
    fact_index = calculator.index_facts(facts)
    scope_cases = (
        ("LEVEL_1", None, None),
        ("LEVEL_2", None, None),
        ("LEVEL_3", None, None),
        ("LEVEL_1_CHILDREN", "BK1001.DC", None),
        ("LEVEL_2_CHILDREN", "BK1001.DC", "BK1101.DC"),
    )
    for scope, level1_code, level2_code in scope_cases:
        pool = resolve_scope_pool(
            hierarchy,
            scope=scope,  # type: ignore[arg-type]
            level1_code=level1_code,
            level2_code=level2_code,
        )
        selected = pool[0]
        global_pool = global_level_pool(
            hierarchy,
            industry_level=selected.industry_level,
        )
        selected_parent_pool = parent_pool(hierarchy, node=selected)
        for period in (1, 5, 10, 20, 30):
            for history_range in (20, 30, 60):
                display_dates = OPEN_DATES[-history_range:]
                returns_by_date = calculator.calculate_for_dates(
                    sector_codes=(node.sector_code for node in pool),
                    open_dates=OPEN_DATES,
                    target_dates=display_dates,
                    period=period,  # type: ignore[arg-type]
                    fact_index=fact_index,
                )
                ranked_by_date = {
                    item: calculator.rank_strength(returns_by_date[item])
                    for item in display_dates
                }
                response = app_client.get(
                    "/api/v1/wealth/market/sector-analysis/momentum/history",
                    params={
                        key: value
                        for key, value in {
                            "tradeDate": TARGET_DATE.isoformat(),
                            "scope": scope,
                            "level1Code": level1_code,
                            "level2Code": level2_code,
                            "period": period,
                            "historyRange": history_range,
                            "sectorCode": selected.sector_code,
                        }.items()
                        if value is not None
                    },
                )
                assert response.status_code == 200
                payload = response.json()
                assert payload["status"] == "READY"
                expected_selected = [
                    next(
                        row
                        for row in ranked_by_date[item]
                        if row.sector_code == selected.sector_code
                    )
                    for item in display_dates
                ]
                assert payload["rollingReturns"] == [
                    {
                        "tradeDate": item.isoformat(),
                        "returnPct": calculator.as_json_return(row.return_pct),
                    }
                    for item, row in zip(
                        display_dates,
                        expected_selected,
                        strict=True,
                    )
                ]
                assert payload["historicalRanks"] == [
                    {
                        "tradeDate": item.isoformat(),
                        "strengthRank": row.strength_rank,
                        "calculableCount": sum(
                            rank.return_pct is not None for rank in ranked_by_date[item]
                        ),
                        "totalCount": len(pool),
                        "percentile": calculator.as_json_percentile(row.percentile),
                    }
                    for item, row in zip(
                        display_dates,
                        expected_selected,
                        strict=True,
                    )
                ]
                assert payload["detail"]["currentScopeTotalCount"] == len(pool)
                assert payload["detail"]["globalLevelTotalCount"] == len(global_pool)
                assert payload["detail"]["parentTotalCount"] == (
                    len(selected_parent_pool)
                    if selected_parent_pool is not None
                    else None
                )


def test_explicit_partial_keeps_full_pool_and_null_row_without_fallback(
    app_client, db_session
) -> None:
    _seed_sector_analysis(db_session)
    _mark_momentum_unavailable(
        db_session,
        trade_date=TARGET_DATE,
        comparison_key="GLOBAL:L1",
        sector_code="BK1002.DC",
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/sector-analysis/momentum/rankings",
        params={"tradeDate": TARGET_DATE.isoformat(), "scope": "LEVEL_1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "READY"
    assert payload["tradingDay"]["expectedAvailability"] == "PARTIAL"
    assert payload["tradingDay"]["observedTradeDate"] == TARGET_DATE.isoformat()
    assert payload["ranking"]["totalCount"] == 2
    assert payload["ranking"]["calculableCount"] == 1
    assert payload["ranking"]["rows"][-1]["sectorCode"] == "BK1002.DC"
    assert payload["ranking"]["rows"][-1]["returnPct"] is None


def test_default_partial_published_batch_stays_on_expected_day_and_reports_ready(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    _mark_momentum_unavailable(
        db_session,
        trade_date=TARGET_DATE,
        comparison_key="GLOBAL:L3",
        sector_code="BK1202.DC",
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/sector-analysis/momentum/rankings",
        params={"scope": "LEVEL_1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "READY"
    assert payload["exceptionCode"] is None
    assert payload["tradingDay"]["expectedTradeDate"] == TARGET_DATE.isoformat()
    assert payload["tradingDay"]["observedTradeDate"] == TARGET_DATE.isoformat()
    assert payload["tradingDay"]["expectedAvailability"] == "PARTIAL"
    assert payload["tradingDay"]["observedAvailability"] == "PARTIAL"


def test_default_unpublished_day_falls_back_to_latest_published_day(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    _unpublish_momentum_date(db_session, trade_date=TARGET_DATE)
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/sector-analysis/momentum/rankings",
        params={"scope": "LEVEL_1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "DELAYED"
    assert payload["exceptionCode"] == "SA_SOURCE_DELAYED"
    assert payload["tradingDay"]["expectedAvailability"] == "MISSING"
    assert payload["tradingDay"]["observedTradeDate"] == OPEN_DATES[-2].isoformat()
    assert payload["tradingDay"]["observedAvailability"] == "COMPLETE"


def test_explicit_missing_day_is_empty_and_never_falls_back(
    app_client, db_session
) -> None:
    _seed_sector_analysis(db_session)
    _unpublish_momentum_date(db_session, trade_date=TARGET_DATE)
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/sector-analysis/momentum/rankings",
        params={"tradeDate": TARGET_DATE.isoformat()},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "EMPTY"
    assert payload["exceptionCode"] == "SA_SOURCE_EMPTY"
    assert payload["tradingDay"]["expectedAvailability"] == "MISSING"
    assert payload["tradingDay"]["observedTradeDate"] == TARGET_DATE.isoformat()
    assert payload["ranking"] is None


def test_meta_keeps_partial_missing_days_and_ignores_codes_outside_current_hierarchy(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    partial_date = OPEN_DATES[-2]
    missing_date = OPEN_DATES[-3]
    _mark_momentum_unavailable(
        db_session,
        trade_date=partial_date,
        comparison_key="GLOBAL:L3",
        sector_code="BK1202.DC",
    )
    _unpublish_momentum_date(db_session, trade_date=missing_date)
    db_session.add(
        DcDaily(
            ts_code="BK9999.DC",
            trade_date=missing_date,
            category="行业板块",
            close=Decimal("100"),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            change=Decimal("1"),
            pct_change=Decimal("1"),
            vol=Decimal("1"),
            amount=Decimal("1"),
            swing=Decimal("1"),
            turnover_rate=Decimal("1"),
        )
    )
    db_session.commit()

    payload = app_client.get("/api/v1/wealth/market/sector-analysis/meta").json()
    by_date = {item["tradeDate"]: item for item in payload["tradeDates"]}
    assert by_date[partial_date.isoformat()] == {
        "tradeDate": partial_date.isoformat(),
        "availability": "PARTIAL",
        "expectedSectorCount": 7,
        "validSectorCount": 6,
    }
    assert missing_date.isoformat() not in by_date


def test_history_retains_missing_date_slot_instead_of_filling_or_dropping_it(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    missing_date = OPEN_DATES[-10]
    _mark_momentum_unavailable(
        db_session,
        trade_date=missing_date,
        comparison_key="PARENT:L1:BK1001.DC",
        sector_code="BK1101.DC",
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/sector-analysis/momentum/history",
        params={
            "scope": "LEVEL_1_CHILDREN",
            "level1Code": "BK1001.DC",
            "period": 1,
            "historyRange": 20,
            "sectorCode": "BK1101.DC",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    return_by_date = {item["tradeDate"]: item for item in payload["rollingReturns"]}
    rank_by_date = {item["tradeDate"]: item for item in payload["historicalRanks"]}
    assert return_by_date[missing_date.isoformat()]["returnPct"] is None
    assert rank_by_date[missing_date.isoformat()]["strengthRank"] is None
    assert rank_by_date[missing_date.isoformat()]["calculableCount"] == 1
    assert rank_by_date[missing_date.isoformat()]["totalCount"] == 2


def test_api_rejects_unknown_duplicate_direction_on_history_and_invalid_closure(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    cases = (
        "/api/v1/wealth/market/sector-analysis/meta?unknown=1",
        "/api/v1/wealth/market/sector-analysis/momentum/rankings?period=1&period=5",
        (
            "/api/v1/wealth/market/sector-analysis/momentum/history"
            "?sectorCode=BK1001.DC&direction=GAINERS"
        ),
        (
            "/api/v1/wealth/market/sector-analysis/momentum/rankings"
            "?scope=LEVEL_2_CHILDREN&level1Code=BK1002.DC&level2Code=BK1101.DC"
        ),
    )

    for path in cases:
        response = app_client.get(path)
        assert response.status_code == 400
        assert response.json()["code"] == "SA_SCOPE_INVALID"


def test_history_rejects_sector_outside_current_pool(app_client, db_session) -> None:
    _seed_sector_analysis(db_session)
    response = app_client.get(
        "/api/v1/wealth/market/sector-analysis/momentum/history",
        params={"scope": "LEVEL_1", "sectorCode": "BK1101.DC"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "SA_SELECTION_INVALID"


def test_api_rejects_invalid_market_date_code_and_non_open_trade_date(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    closed_date = OPEN_DATES[-5]
    calendar = db_session.get(
        TradeCalendar, {"exchange": "SSE", "trade_date": closed_date}
    )
    calendar.is_open = False
    db_session.commit()
    cases = (
        ("/api/v1/wealth/market/sector-analysis/meta", {"market": "US"}),
        (
            "/api/v1/wealth/market/sector-analysis/momentum/rankings",
            {"tradeDate": "2026-02-30"},
        ),
        (
            "/api/v1/wealth/market/sector-analysis/momentum/rankings",
            {"scope": "LEVEL_1_CHILDREN", "level1Code": "bk1001.dc"},
        ),
        (
            "/api/v1/wealth/market/sector-analysis/momentum/rankings",
            {"tradeDate": closed_date.isoformat()},
        ),
    )
    for path, params in cases:
        response = app_client.get(path, params=params)
        assert response.status_code == 400
        assert response.json()["code"] == "SA_SCOPE_INVALID"


def test_meta_hierarchy_failure_is_safe_http_500(app_client, db_session) -> None:
    _ensure_tables(db_session)
    response = app_client.get("/api/v1/wealth/market/sector-analysis/meta")
    assert response.status_code == 500
    assert response.json()["code"] == "SA_HIERARCHY_UNAVAILABLE"
    assert "SELECT" not in response.text


def test_rankings_hierarchy_and_query_failures_use_safe_business_error_shells(
    app_client,
    db_session,
) -> None:
    _ensure_tables(db_session)
    hierarchy_payload = app_client.get(
        "/api/v1/wealth/market/sector-analysis/momentum/rankings",
        params={"debug": 1},
    ).json()
    assert hierarchy_payload["status"] == "ERROR"
    assert hierarchy_payload["exceptionCode"] == "SA_HIERARCHY_UNAVAILABLE"
    assert "hierarchy" not in hierarchy_payload["message"].lower()

    _seed_sector_analysis(db_session)
    WealthSectorMomentumDaily.__table__.drop(db_session.get_bind())
    query_response = app_client.get(
        "/api/v1/wealth/market/sector-analysis/momentum/rankings",
        params={"debug": 1},
    )
    assert query_response.status_code == 200
    query_payload = query_response.json()
    assert query_payload["status"] == "ERROR"
    assert query_payload["exceptionCode"] == "SA_QUERY_FAILED"
    assert "SELECT" not in query_response.text
    assert "dc_daily" not in query_response.text


def test_momentum_rankings_remain_ready_when_online_dc_daily_is_unavailable(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    DcDaily.__table__.drop(db_session.get_bind())

    response = app_client.get(
        "/api/v1/wealth/market/sector-analysis/momentum/rankings",
        params={"tradeDate": TARGET_DATE.isoformat(), "scope": "LEVEL_1"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "READY"


def test_debug_payload_is_hidden_outside_local_dev_and_test(
    app_client, db_session, monkeypatch
) -> None:
    _seed_sector_analysis(db_session)
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv(
        "GOLDENSHARE_ENV_FILE",
        "/private/tmp/sector-analysis-missing.env",
    )
    get_settings.cache_clear()
    try:
        response = app_client.get(
            "/api/v1/wealth/market/sector-analysis/momentum/rankings",
            params={"debug": 1},
        )
        assert response.status_code == 200
        assert response.json()["debugInfo"] is None
    finally:
        monkeypatch.setenv("APP_ENV", "test")
        get_settings.cache_clear()


def test_members_returns_complete_source_rows_and_compounded_returns_in_four_sql(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_sector_analysis(db_session)
    _seed_sector_members(db_session)

    sql_count, response = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/momentum/members",
            params={
                "market": "CN_A",
                "tradeDate": TARGET_DATE.isoformat(),
                "hierarchyVersion": "2026-04-30-v1",
                "sectorCode": "BK1201.DC",
                "period": 5,
                "direction": "GAINERS",
            },
        ),
    )

    assert response.status_code == 200
    assert sql_count == 4
    payload = response.json()
    assert payload["status"] == "READY"
    assert payload["totalMemberCount"] == 3
    assert payload["closeAvailableCount"] == 2
    assert payload["calculableCount"] == 2
    assert [row["stockCode"] for row in payload["rows"]] == [
        "200001.SZ",
        "000001.SZ",
        "000003.SZ",
    ]
    assert payload["rows"][0]["close"] is None
    assert payload["rows"][0]["returnPct"] == 10.4081
    assert payload["rows"][1]["returnPct"] == 5.101
    assert payload["rows"][2] == {
        "stockName": None,
        "stockCode": "000003.SZ",
        "close": 8.0,
        "returnPct": None,
    }


def test_members_keeps_four_sql_for_139_members_and_thirty_open_days(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_sector_analysis(db_session)
    stock_codes = tuple(f"{1000 + index:06d}.SZ" for index in range(139))
    db_session.add_all(
        DcMember(
            trade_date=TARGET_DATE,
            ts_code="BK1201.DC",
            con_code=stock_code,
            name=f"样本{index:03d}",
        )
        for index, stock_code in enumerate(stock_codes)
    )
    db_session.add_all(
        EquityDailyBar(
            ts_code=stock_code,
            trade_date=trade_date,
            open=Decimal("10"),
            high=Decimal("10"),
            low=Decimal("10"),
            close=Decimal("10"),
            pre_close=Decimal("10"),
            change_amount=Decimal("0"),
            pct_chg=Decimal("0.1"),
            vol=Decimal("100"),
            amount=Decimal("1000"),
        )
        for stock_code in stock_codes
        for trade_date in OPEN_DATES[-30:]
    )
    db_session.commit()

    sql_count, response = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/momentum/members",
            params={
                "market": "CN_A",
                "tradeDate": TARGET_DATE.isoformat(),
                "hierarchyVersion": "2026-04-30-v1",
                "sectorCode": "BK1201.DC",
                "period": 30,
                "direction": "GAINERS",
            },
        ),
    )

    assert response.status_code == 200
    assert sql_count == 4
    assert response.json()["totalMemberCount"] == 139
    assert response.json()["calculableCount"] == 139


def test_members_losers_reverse_only_valid_values_and_keep_null_last(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    _seed_sector_members(db_session)
    response = app_client.get(
        "/api/v1/wealth/market/sector-analysis/momentum/members",
        params={
            "market": "CN_A",
            "tradeDate": TARGET_DATE.isoformat(),
            "hierarchyVersion": "2026-04-30-v1",
            "sectorCode": "BK1201.DC",
            "period": 5,
            "direction": "LOSERS",
        },
    )

    assert response.status_code == 200
    assert [row["stockCode"] for row in response.json()["rows"]] == [
        "000001.SZ",
        "200001.SZ",
        "000003.SZ",
    ]


def test_members_empty_is_local_200_state(app_client, db_session) -> None:
    _seed_sector_analysis(db_session)
    response = app_client.get(
        "/api/v1/wealth/market/sector-analysis/momentum/members",
        params={
            "market": "CN_A",
            "tradeDate": TARGET_DATE.isoformat(),
            "hierarchyVersion": "2026-04-30-v1",
            "sectorCode": "BK1202.DC",
            "period": 1,
            "direction": "GAINERS",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "EMPTY"
    assert payload["exceptionCode"] == "SA_MEMBER_SOURCE_EMPTY"
    assert payload["rows"] == []


def test_members_version_mismatch_returns_409_before_member_queries(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_sector_analysis(db_session)
    _seed_sector_members(db_session)

    sql_count, response = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/momentum/members",
            params={
                "market": "CN_A",
                "tradeDate": TARGET_DATE.isoformat(),
                "hierarchyVersion": "stale-version",
                "sectorCode": "BK1201.DC",
                "period": 1,
                "direction": "GAINERS",
            },
        ),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "SA_MEMBER_FACT_MISMATCH"
    assert sql_count == 1


def test_members_rejects_missing_unknown_duplicate_non_level_three_and_closed_date(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    closed_date = OPEN_DATES[-5]
    calendar = db_session.get(
        TradeCalendar, {"exchange": "SSE", "trade_date": closed_date}
    )
    calendar.is_open = False
    db_session.commit()
    base = {
        "market": "CN_A",
        "tradeDate": TARGET_DATE.isoformat(),
        "hierarchyVersion": "2026-04-30-v1",
        "sectorCode": "BK1201.DC",
        "period": 1,
        "direction": "GAINERS",
    }
    cases = (
        {key: value for key, value in base.items() if key != "market"},
        {**base, "scope": "LEVEL_3"},
        {**base, "sectorCode": "BK1101.DC"},
        {**base, "tradeDate": closed_date.isoformat()},
    )
    for params in cases:
        response = app_client.get(
            "/api/v1/wealth/market/sector-analysis/momentum/members",
            params=params,
        )
        assert response.status_code == 400
    duplicate = app_client.get(
        "/api/v1/wealth/market/sector-analysis/momentum/members"
        "?market=CN_A&market=CN_A&tradeDate=2026-04-30"
        "&hierarchyVersion=2026-04-30-v1&sectorCode=BK1201.DC&period=1&direction=GAINERS"
    )
    assert duplicate.status_code == 400
    assert duplicate.json()["code"] == "SA_SCOPE_INVALID"


def test_quote_auth_requirement_is_reused(app_client, monkeypatch) -> None:
    monkeypatch.setenv("QUOTE_API_AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    try:
        response = app_client.get("/api/v1/wealth/market/sector-analysis/meta")
        assert response.status_code == 401
        assert response.json()["code"] == "auth_required"
        member_response = app_client.get(
            "/api/v1/wealth/market/sector-analysis/momentum/members"
        )
        assert member_response.status_code == 401
        assert member_response.json()["code"] == "auth_required"
        dual_meta_response = app_client.get(
            "/api/v1/wealth/market/sector-analysis/dual-momentum/meta"
        )
        assert dual_meta_response.status_code == 401
        dual_results_response = app_client.get(
            "/api/v1/wealth/market/sector-analysis/dual-momentum/results"
        )
        assert dual_results_response.status_code == 401
        relative_meta_response = app_client.get(
            "/api/v1/wealth/market/sector-analysis/relative-rotation/meta"
        )
        assert relative_meta_response.status_code == 401
        relative_results_response = app_client.get(
            "/api/v1/wealth/market/sector-analysis/relative-rotation/results"
        )
        assert relative_results_response.status_code == 401
        breadth_meta_response = app_client.get(
            "/api/v1/wealth/market/sector-analysis/member-breadth/meta"
        )
        assert breadth_meta_response.status_code == 401
        breadth_rankings_response = app_client.get(
            "/api/v1/wealth/market/sector-analysis/member-breadth/rankings"
        )
        assert breadth_rankings_response.status_code == 401
        breadth_details_response = app_client.get(
            "/api/v1/wealth/market/sector-analysis/member-breadth/details"
        )
        assert breadth_details_response.status_code == 401
        price_volume_meta = app_client.get(
            "/api/v1/wealth/market/sector-analysis/price-volume/meta"
        )
        assert price_volume_meta.status_code == 401
        price_volume_snapshot = app_client.get(
            "/api/v1/wealth/market/sector-analysis/price-volume/snapshot"
        )
        assert price_volume_snapshot.status_code == 401
        price_volume_details = app_client.get(
            "/api/v1/wealth/market/sector-analysis/price-volume/details"
        )
        assert price_volume_details.status_code == 401
    finally:
        monkeypatch.setenv("QUOTE_API_AUTH_REQUIRED", "false")
        get_settings.cache_clear()


def _price_volume_snapshot_params(**overrides):
    params = {
        "market": "CN_A",
        "tradeDate": TARGET_DATE.isoformat(),
        "scope": "LEVEL_3",
        "period": 1,
        "hierarchyVersion": "2026-04-30-v1",
        "debug": 1,
    }
    params.update(overrides)
    return params


def _price_volume_details_params(**overrides):
    params = {
        **_price_volume_snapshot_params(),
        "historyRange": 60,
        "sectorCode": "BK1201.DC",
    }
    params.update(overrides)
    return params


def test_price_volume_meta_snapshot_and_details_follow_three_five_five_sql(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_sector_analysis(db_session)

    meta_sql, meta_response = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/price-volume/meta",
            params={"market": "CN_A"},
        ),
    )
    snapshot_sql, snapshot_response = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/price-volume/snapshot",
            params=_price_volume_snapshot_params(),
        ),
    )
    details_sql, details_response = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/price-volume/details",
            params=_price_volume_details_params(),
        ),
    )

    assert meta_response.status_code == 200
    assert snapshot_response.status_code == 200
    assert details_response.status_code == 200
    assert (meta_sql, snapshot_sql, details_sql) == (3, 5, 5)

    meta = meta_response.json()
    assert meta["formulaKey"] == "sector-price-volume-distribution"
    assert meta["formulaVersion"] == 1
    assert meta["periods"] == [1, 5, 10, 20, 30]
    assert meta["historyRanges"] == [20, 30, 60]
    assert meta["dateContext"] == {
        "expectedTradeDate": TARGET_DATE.isoformat(),
        "defaultTradeDate": TARGET_DATE.isoformat(),
        "defaultStatus": "READY",
        "displayText": f"{TARGET_DATE.isoformat()} 盘后数据",
    }
    assert len(meta["hierarchy"]["nodes"]) == 7
    assert len(meta["tradeDates"]) == 65

    snapshot = snapshot_response.json()
    assert snapshot["status"] == "READY"
    assert snapshot["snapshot"]["totalCount"] == 2
    assert snapshot["snapshot"]["coordinateCount"] == 2
    assert snapshot["snapshot"]["missingCoordinateCount"] == 0
    assert all(item["state"] == "PRICE_ONLY" for item in snapshot["snapshot"]["rows"])
    assert snapshot["debugInfo"]["requestedOpenDateCount"] == 2
    assert len(snapshot_response.content) < 256 * 1024

    details = details_response.json()
    assert details["status"] == "READY"
    assert details["details"]["selected"]["sectorCode"] == "BK1201.DC"
    assert len(details["details"]["history"]) == 60
    assert details["details"]["history"][-1]["tradeDate"] == TARGET_DATE.isoformat()
    assert len(details_response.content) < 64 * 1024


def test_price_volume_partial_and_missing_dates_keep_exact_requested_day(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    partial = db_session.scalar(
        select(DcDaily).where(
            DcDaily.ts_code == "BK1002.DC",
            DcDaily.trade_date == TARGET_DATE,
            DcDaily.category == "行业板块",
        )
    )
    partial.amount = None
    db_session.commit()

    partial_response = app_client.get(
        "/api/v1/wealth/market/sector-analysis/price-volume/snapshot",
        params=_price_volume_snapshot_params(scope="LEVEL_1"),
    )
    assert partial_response.status_code == 200
    partial_payload = partial_response.json()
    assert partial_payload["status"] == "READY"
    assert partial_payload["snapshot"]["observedTradeDate"] == TARGET_DATE.isoformat()
    assert partial_payload["snapshot"]["availability"] == "PARTIAL"
    assert partial_payload["snapshot"]["totalCount"] == 2
    assert partial_payload["snapshot"]["coordinateCount"] == 1
    missing_row = next(
        item
        for item in partial_payload["snapshot"]["rows"]
        if item["sectorCode"] == "BK1002.DC"
    )
    assert missing_row["priceMomentumPct"] is not None
    assert missing_row["amountActivityPct"] is None
    assert missing_row["amountMissingReason"] == "AMOUNT_MISSING"
    assert missing_row["state"] is None

    for row in db_session.scalars(
        select(DcDaily).where(
            DcDaily.trade_date == TARGET_DATE,
            DcDaily.category == "行业板块",
        )
    ).all():
        db_session.delete(row)
    db_session.commit()

    missing_response = app_client.get(
        "/api/v1/wealth/market/sector-analysis/price-volume/snapshot",
        params=_price_volume_snapshot_params(scope="LEVEL_1"),
    )
    assert missing_response.status_code == 200
    missing_payload = missing_response.json()
    assert missing_payload["status"] == "EMPTY"
    assert missing_payload["snapshot"]["observedTradeDate"] == TARGET_DATE.isoformat()
    assert missing_payload["snapshot"]["availability"] == "MISSING"
    assert missing_payload["snapshot"]["totalCount"] == 2
    assert missing_payload["snapshot"]["coordinateCount"] == 0


def test_price_volume_rejects_open_day_before_source_coverage(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    earlier = OPEN_DATES[0] - timedelta(days=1)
    db_session.add(
        TradeCalendar(
            exchange="SSE",
            trade_date=earlier,
            is_open=True,
            pretrade_date=None,
        )
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/sector-analysis/price-volume/snapshot",
        params=_price_volume_snapshot_params(tradeDate=earlier.isoformat()),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "SA_SELECTION_INVALID"


def test_price_volume_version_mismatch_stops_after_two_sql(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_sector_analysis(db_session)
    sql_count, response = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/price-volume/snapshot",
            params=_price_volume_snapshot_params(hierarchyVersion="stale"),
        ),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "SA_PRICE_VOLUME_FACT_MISMATCH"
    assert sql_count == 2


def test_price_volume_rejects_unknown_duplicate_invalid_scope_selection_and_date(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    unknown = app_client.get(
        "/api/v1/wealth/market/sector-analysis/price-volume/meta?unknown=1"
    )
    duplicate = app_client.get(
        "/api/v1/wealth/market/sector-analysis/price-volume/snapshot"
        "?market=CN_A&tradeDate=2026-04-30&scope=LEVEL_3&period=1&period=5"
        "&hierarchyVersion=2026-04-30-v1"
    )
    bad_closure = app_client.get(
        "/api/v1/wealth/market/sector-analysis/price-volume/snapshot",
        params=_price_volume_snapshot_params(
            scope="LEVEL_2_CHILDREN",
            level1Code="BK1002.DC",
            level2Code="BK1101.DC",
        ),
    )
    bad_selection = app_client.get(
        "/api/v1/wealth/market/sector-analysis/price-volume/details",
        params=_price_volume_details_params(sectorCode="BK1001.DC"),
    )
    bad_date = app_client.get(
        "/api/v1/wealth/market/sector-analysis/price-volume/snapshot",
        params=_price_volume_snapshot_params(tradeDate="2026-02-30"),
    )

    assert unknown.status_code == 400
    assert duplicate.status_code == 400
    assert bad_closure.status_code == 400
    assert bad_selection.status_code == 400
    assert bad_date.status_code == 400
    assert unknown.json()["code"] == "SA_SCOPE_INVALID"
    assert duplicate.json()["code"] == "SA_SCOPE_INVALID"
    assert bad_closure.json()["code"] == "SA_SCOPE_INVALID"
    assert bad_selection.json()["code"] == "SA_SELECTION_INVALID"
    assert bad_date.json()["code"] == "SA_SELECTION_INVALID"


def _dual_results_params(**overrides):
    params = {
        "market": "CN_A",
        "tradeDate": TARGET_DATE.isoformat(),
        "scope": "LEVEL_2",
        "period": 20,
        "leadingThreshold": 80,
        "hierarchyVersion": "2026-04-30-v1",
        "debug": 1,
    }
    params.update(overrides)
    return params


def test_dual_meta_returns_dedicated_contract_in_three_sql(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_sector_analysis(db_session)

    sql_count, response = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/dual-momentum/meta",
            params={"market": "CN_A"},
        ),
    )
    assert response.status_code == 200
    assert sql_count == 3
    payload = response.json()
    assert payload["status"] == "READY"
    assert payload["formula"] == {
        "formulaKey": "sector-dual-momentum",
        "formulaVersion": 1,
        "basisFormulaKey": "sector-cross-sectional-momentum",
        "basisFormulaVersion": 1,
        "periods": [5, 10, 20, 30],
        "leadingThresholds": [70, 80, 90],
        "minimumGroupSize": 3,
        "scopes": [
            "LEVEL_1",
            "LEVEL_2",
            "LEVEL_3",
            "LEVEL_1_CHILDREN",
            "LEVEL_2_CHILDREN",
        ],
    }
    assert payload["defaults"] == {
        "scope": "LEVEL_1",
        "period": 20,
        "leadingThreshold": 80,
        "resultView": "QUALIFIED",
    }
    assert "directions" not in payload["formula"]
    assert "historyRanges" not in payload["formula"]
    assert 1 not in payload["formula"]["periods"]


def test_dual_results_returns_full_canonical_rows_and_five_counts_in_five_sql(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_sector_analysis(db_session)

    sql_count, response = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/dual-momentum/results",
            params=_dual_results_params(),
        ),
    )

    assert response.status_code == 200
    assert sql_count == 5
    payload = response.json()
    assert payload["status"] == "READY"
    analysis = payload["analysis"]
    assert analysis["totalCount"] == 3
    assert analysis["calculableCount"] == 3
    assert analysis["qualifiedCount"] == 1
    assert analysis["insufficientCount"] == 0
    assert analysis["plottableCount"] == 3
    assert [item["sectorCode"] for item in analysis["items"]] == [
        "BK1101.DC",
        "BK1102.DC",
        "BK1103.DC",
    ]
    assert analysis["items"][0]["qualificationStatus"] == "QUALIFIED"
    assert analysis["items"][0]["displayStatus"] == "QUALIFIED"
    assert analysis["items"][-1]["percentile"] == 0.0
    assert payload["debugInfo"]["sampleSectorCodes"] == [
        "BK1101.DC",
        "BK1102.DC",
        "BK1103.DC",
    ]


def test_dual_results_supports_all_frozen_scopes_periods_and_thresholds(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    scopes = (
        ("LEVEL_1", {}),
        ("LEVEL_2", {}),
        ("LEVEL_3", {}),
        ("LEVEL_1_CHILDREN", {"level1Code": "BK1001.DC"}),
        (
            "LEVEL_2_CHILDREN",
            {"level1Code": "BK1001.DC", "level2Code": "BK1101.DC"},
        ),
    )

    for scope, parents in scopes:
        for period in (5, 10, 20, 30):
            for threshold in (70, 80, 90):
                response = app_client.get(
                    "/api/v1/wealth/market/sector-analysis/dual-momentum/results",
                    params=_dual_results_params(
                        scope=scope,
                        period=period,
                        leadingThreshold=threshold,
                        **parents,
                    ),
                )
                assert response.status_code == 200
                payload = response.json()
                assert payload["status"] == "READY"
                assert payload["analysis"]["scope"] == scope
                assert payload["analysis"]["period"] == period
                assert payload["analysis"]["leadingThreshold"] == threshold


def test_dual_small_group_is_ready_with_plottable_facts_and_no_qualification(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)

    response = app_client.get(
        "/api/v1/wealth/market/sector-analysis/dual-momentum/results",
        params=_dual_results_params(scope="LEVEL_1"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "READY"
    assert payload["analysis"]["calculableCount"] == 2
    assert payload["analysis"]["qualifiedCount"] == 0
    assert payload["analysis"]["insufficientCount"] == 2
    assert payload["analysis"]["plottableCount"] == 2
    assert {item["displayStatus"] for item in payload["analysis"]["items"]} == {
        "SAMPLE_INSUFFICIENT"
    }


def test_dual_no_qualified_is_ready_and_keeps_all_negative_facts(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    for code in ("BK1101.DC", "BK1102.DC", "BK1103.DC"):
        row = db_session.scalar(
            select(DcDaily).where(
                DcDaily.ts_code == code,
                DcDaily.trade_date == TARGET_DATE,
                DcDaily.category == "行业板块",
            )
        )
        row.close = Decimal("1")
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/sector-analysis/dual-momentum/results",
        params=_dual_results_params(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "READY"
    assert payload["analysis"]["calculableCount"] == 3
    assert payload["analysis"]["qualifiedCount"] == 0
    assert all(
        item["absoluteStatus"] == "NOT_POSITIVE"
        for item in payload["analysis"]["items"]
    )


def test_dual_explicit_partial_is_ready_and_preserves_missing_coordinate(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    db_session.delete(
        db_session.scalar(
            select(DcDaily).where(
                DcDaily.ts_code == "BK1103.DC",
                DcDaily.trade_date == TARGET_DATE,
                DcDaily.category == "行业板块",
            )
        )
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/sector-analysis/dual-momentum/results",
        params=_dual_results_params(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "READY"
    assert payload["tradingDay"]["expectedAvailability"] == "PARTIAL"
    assert payload["analysis"]["totalCount"] == 3
    assert payload["analysis"]["calculableCount"] == 2
    missing = payload["analysis"]["items"][-1]
    assert missing["sectorCode"] == "BK1103.DC"
    assert missing["coordinateStatus"] == "UNAVAILABLE"
    assert missing["displayStatus"] == "DATA_INSUFFICIENT"
    assert missing["missingReason"] == "DATE_MISSING"


def test_dual_default_partial_falls_back_and_meta_reports_same_delayed_date(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    db_session.delete(
        db_session.scalar(
            select(DcDaily).where(
                DcDaily.ts_code == "BK1202.DC",
                DcDaily.trade_date == TARGET_DATE,
                DcDaily.category == "行业板块",
            )
        )
    )
    db_session.commit()

    meta = app_client.get("/api/v1/wealth/market/sector-analysis/dual-momentum/meta")
    params = _dual_results_params()
    params.pop("tradeDate")
    results = app_client.get(
        "/api/v1/wealth/market/sector-analysis/dual-momentum/results",
        params=params,
    )

    assert meta.status_code == results.status_code == 200
    assert meta.json()["status"] == results.json()["status"] == "DELAYED"
    assert meta.json()["tradingDay"]["observedTradeDate"] == OPEN_DATES[-2].isoformat()
    assert (
        results.json()["tradingDay"]["observedTradeDate"] == OPEN_DATES[-2].isoformat()
    )


def test_dual_explicit_missing_is_empty_without_window_or_fact_queries(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_sector_analysis(db_session)
    for row in db_session.scalars(
        select(DcDaily).where(
            DcDaily.trade_date == TARGET_DATE,
            DcDaily.category == "行业板块",
        )
    ).all():
        db_session.delete(row)
    db_session.commit()

    sql_count, response = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/dual-momentum/results",
            params=_dual_results_params(),
        ),
    )

    assert response.status_code == 200
    assert sql_count == 3
    assert response.json()["status"] == "EMPTY"
    assert response.json()["analysis"] is None
    assert response.json()["exceptionCode"] == "SA_SOURCE_EMPTY"


def test_dual_version_mismatch_returns_409_before_window_or_daily_facts(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_sector_analysis(db_session)
    statements: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement)

    event.listen(web_engine, "before_cursor_execute", record)
    try:
        response = app_client.get(
            "/api/v1/wealth/market/sector-analysis/dual-momentum/results",
            params=_dual_results_params(hierarchyVersion="stale"),
        )
    finally:
        event.remove(web_engine, "before_cursor_execute", record)

    assert response.status_code == 409
    assert response.json()["code"] == "SA_FACT_VERSION_MISMATCH"
    assert len(statements) == 2
    assert "dc_daily" not in "\n".join(statements).lower()


def test_dual_results_rejects_missing_unknown_duplicate_invalid_enum_and_date(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    base = _dual_results_params()
    cases = (
        {key: value for key, value in base.items() if key != "market"},
        {key: value for key, value in base.items() if key != "scope"},
        {key: value for key, value in base.items() if key != "period"},
        {key: value for key, value in base.items() if key != "leadingThreshold"},
        {key: value for key, value in base.items() if key != "hierarchyVersion"},
        {**base, "period": 1},
        {**base, "leadingThreshold": 75},
        {**base, "resultView": "ALL"},
        {**base, "direction": "GAINERS"},
    )
    for params in cases:
        response = app_client.get(
            "/api/v1/wealth/market/sector-analysis/dual-momentum/results",
            params=params,
        )
        assert response.status_code == 400
        assert response.json()["code"] == "SA_SCOPE_INVALID"

    duplicate = app_client.get(
        "/api/v1/wealth/market/sector-analysis/dual-momentum/results"
        "?market=CN_A&market=CN_A&tradeDate=2026-04-30&scope=LEVEL_2"
        "&period=20&leadingThreshold=80&hierarchyVersion=2026-04-30-v1"
    )
    assert duplicate.status_code == 400
    assert duplicate.json()["code"] == "SA_SCOPE_INVALID"

    invalid_date = app_client.get(
        "/api/v1/wealth/market/sector-analysis/dual-momentum/results",
        params=_dual_results_params(tradeDate="2026-02-30"),
    )
    assert invalid_date.status_code == 400
    assert invalid_date.json()["code"] == "SA_SELECTION_INVALID"


def test_dual_meta_rejects_unknown_and_duplicate_query_parameters(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    unknown = app_client.get(
        "/api/v1/wealth/market/sector-analysis/dual-momentum/meta",
        params={"market": "CN_A", "period": 20},
    )
    duplicate = app_client.get(
        "/api/v1/wealth/market/sector-analysis/dual-momentum/meta"
        "?market=CN_A&market=CN_A"
    )

    assert unknown.status_code == duplicate.status_code == 400
    assert unknown.json()["code"] == duplicate.json()["code"] == "SA_SCOPE_INVALID"


def test_dual_meta_and_results_use_safe_hierarchy_and_query_failures(
    app_client,
    db_session,
) -> None:
    _ensure_tables(db_session)
    meta = app_client.get("/api/v1/wealth/market/sector-analysis/dual-momentum/meta")
    results = app_client.get(
        "/api/v1/wealth/market/sector-analysis/dual-momentum/results",
        params=_dual_results_params(),
    )

    assert meta.status_code == 500
    assert meta.json()["code"] == "SA_HIERARCHY_UNAVAILABLE"
    assert results.status_code == 200
    assert results.json()["status"] == "ERROR"
    assert results.json()["exceptionCode"] == "SA_HIERARCHY_UNAVAILABLE"

    _seed_sector_analysis(db_session)
    DcDaily.__table__.drop(db_session.get_bind())
    query_failure = app_client.get(
        "/api/v1/wealth/market/sector-analysis/dual-momentum/results",
        params=_dual_results_params(),
    )
    assert query_failure.status_code == 200
    assert query_failure.json()["status"] == "ERROR"
    assert query_failure.json()["exceptionCode"] == "SA_QUERY_FAILED"
    assert "dc_daily" not in query_failure.text.lower()


def _seed_maximum_dual_pool(
    db_session,
    *,
    open_date_count: int = 21,
) -> tuple[date, str]:
    _ensure_tables(db_session)
    target_date = date(2026, 6, 30)
    open_dates = tuple(
        target_date - timedelta(days=offset)
        for offset in range(open_date_count - 1, -1, -1)
    )
    previous = None
    for trade_date in open_dates:
        db_session.add(
            TradeCalendar(
                exchange="SSE",
                trade_date=trade_date,
                is_open=True,
                pretrade_date=previous,
            )
        )
        previous = trade_date
    level_1_rows = [
        (f"BK{1000 + index:04d}.DC", f"一级样本{index:02d}") for index in range(31)
    ]
    level_2_rows = [
        (
            f"BK{2000 + index:04d}.DC",
            f"二级样本{index:03d}",
            level_1_rows[index % len(level_1_rows)],
        )
        for index in range(128)
    ]
    hierarchy_rows = [(code, name, 1, None, code, name) for code, name in level_1_rows]
    hierarchy_rows.extend(
        (
            code,
            name,
            2,
            parent[0],
            parent[0],
            f"{parent[1]}/{name}",
        )
        for code, name, parent in level_2_rows
    )
    hierarchy_rows.extend(
        (
            f"BK{3000 + index:04d}.DC",
            f"三级样本{index:03d}",
            3,
            level_2_rows[index % len(level_2_rows)][0],
            level_2_rows[index % len(level_2_rows)][2][0],
            (
                f"{level_2_rows[index % len(level_2_rows)][2][1]}/"
                f"{level_2_rows[index % len(level_2_rows)][1]}/"
                f"三级样本{index:03d}"
            ),
        )
        for index in range(337)
    )
    names_by_code = {row[0]: row[1] for row in hierarchy_rows}
    for order, (code, name, level, parent, root, path) in enumerate(
        hierarchy_rows,
        start=1,
    ):
        parent_name = names_by_code.get(parent)
        root_name = names_by_code[root]
        db_session.add(
            WealthSectorHierarchy(
                sector_code=code,
                sector_name=name,
                industry_level=level,
                industry_level_name=f"{level}级行业",
                parent_sector_code=parent,
                parent_sector_name=parent_name,
                root_sector_code=root,
                root_sector_name=root_name,
                hierarchy_path=path,
                is_leaf=level == 3,
                display_order=order,
                baseline_version="maximum-v1",
                source_received_date=target_date,
                code_reference_trade_date=target_date,
                published_at=datetime(2026, 6, 30, 20, 0, tzinfo=timezone.utc),
            )
        )
        for date_index, trade_date in enumerate(open_dates):
            close = Decimal(100 + order) + Decimal(date_index)
            db_session.add(
                DcDaily(
                    ts_code=code,
                    trade_date=trade_date,
                    category="行业板块",
                    close=close,
                    open=close,
                    high=close,
                    low=close,
                    change=Decimal("1"),
                    pct_change=Decimal("1"),
                    vol=Decimal("100"),
                    amount=Decimal("1000"),
                    swing=Decimal("1"),
                    turnover_rate=Decimal("2"),
                )
            )
    db_session.commit()
    return target_date, "maximum-v1"


def test_dual_maximum_337_pool_meets_sql_payload_and_local_p95_budgets(
    app_client,
    db_session,
    web_engine,
) -> None:
    target_date, hierarchy_version = _seed_maximum_dual_pool(db_session)
    params = {
        "market": "CN_A",
        "tradeDate": target_date.isoformat(),
        "scope": "LEVEL_3",
        "period": 20,
        "leadingThreshold": 80,
        "hierarchyVersion": hierarchy_version,
    }

    meta_sql_count, first_meta = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/dual-momentum/meta",
            params={"market": "CN_A"},
        ),
    )
    meta_durations = []
    for _index in range(20):
        started = perf_counter()
        meta_response = app_client.get(
            "/api/v1/wealth/market/sector-analysis/dual-momentum/meta",
            params={"market": "CN_A"},
        )
        meta_durations.append(perf_counter() - started)
        assert meta_response.status_code == 200

    sql_count, first = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/dual-momentum/results",
            params=params,
        ),
    )
    durations = []
    for _index in range(20):
        started = perf_counter()
        response = app_client.get(
            "/api/v1/wealth/market/sector-analysis/dual-momentum/results",
            params=params,
        )
        durations.append(perf_counter() - started)
        assert response.status_code == 200

    assert first.status_code == 200
    assert first_meta.status_code == 200
    assert len(first_meta.json()["hierarchy"]["nodes"]) == 496
    assert meta_sql_count == 3
    assert len(first_meta.content) <= 256 * 1024
    assert sorted(meta_durations)[18] <= 0.5
    assert first.json()["analysis"]["totalCount"] == 337
    assert first.json()["analysis"]["calculableCount"] == 337
    assert sql_count == 5
    assert len(first.content) <= 256 * 1024
    assert sorted(durations)[18] <= 0.5


def _relative_results_params(**overrides):
    params = {
        "market": "CN_A",
        "tradeDate": TARGET_DATE.isoformat(),
        "scope": "LEVEL_2",
        "period": 20,
        "trailLength": 20,
        "hierarchyVersion": "2026-04-30-v1",
        "debug": 1,
    }
    params.update(overrides)
    return params


def test_relative_rotation_meta_and_results_keep_three_and_five_sql_contracts(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_sector_analysis(db_session)

    meta_sql_count, meta_response = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/relative-rotation/meta",
            params={"market": "CN_A"},
        ),
    )
    result_sql_count, result_response = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/relative-rotation/results",
            params=_relative_results_params(),
        ),
    )

    assert meta_response.status_code == 200
    assert meta_sql_count == 3
    assert meta_response.json()["formula"] == {
        "formulaKey": "sector-relative-rotation",
        "formulaVersion": 1,
        "basisFormulaKey": "sector-cross-sectional-momentum",
        "basisFormulaVersion": 1,
        "periods": [5, 10, 20, 30],
        "improvementLookbackDays": 5,
        "trailLengths": [20, 30, 60],
        "minimumGroupSize": 3,
        "scopes": [
            "LEVEL_1",
            "LEVEL_2",
            "LEVEL_3",
            "LEVEL_1_CHILDREN",
            "LEVEL_2_CHILDREN",
        ],
        "xDomain": [0, 100],
        "xSplit": 50,
        "ySplit": 0,
    }
    assert result_response.status_code == 200
    assert result_sql_count == 5
    payload = result_response.json()
    assert payload["status"] == "READY"
    analysis = payload["analysis"]
    assert analysis["totalCount"] == 3
    assert analysis["currentCalculableCount"] == 3
    assert analysis["plottableCount"] == 3
    assert analysis["missingCoordinateCount"] == 0
    assert analysis["selectedTrail"]["sectorCode"] == analysis["selectedSectorCode"]
    assert analysis["selectedTrail"]["dateSlotCount"] == 20
    assert (
        analysis["selectedTrail"]["points"][-1]["tradeDate"] == TARGET_DATE.isoformat()
    )


def test_relative_rotation_supports_all_scopes_periods_and_trail_lengths(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    scopes = (
        ("LEVEL_1", {}),
        ("LEVEL_2", {}),
        ("LEVEL_3", {}),
        ("LEVEL_1_CHILDREN", {"level1Code": "BK1001.DC"}),
        (
            "LEVEL_2_CHILDREN",
            {"level1Code": "BK1001.DC", "level2Code": "BK1101.DC"},
        ),
    )

    for scope, parents in scopes:
        for period in (5, 10, 20, 30):
            for trail_length in (20, 30, 60):
                response = app_client.get(
                    "/api/v1/wealth/market/sector-analysis/relative-rotation/results",
                    params=_relative_results_params(
                        scope=scope,
                        period=period,
                        trailLength=trail_length,
                        **parents,
                    ),
                )
                assert response.status_code == 200
                assert response.json()["status"] == "READY"
                assert response.json()["analysis"]["scope"] == scope
                assert response.json()["analysis"]["period"] == period
                assert response.json()["analysis"]["trailLength"] == trail_length


def test_relative_rotation_version_mismatch_returns_409_before_daily_reads(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_sector_analysis(db_session)

    sql_count, response = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/relative-rotation/results",
            params=_relative_results_params(hierarchyVersion="stale"),
        ),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "SA_FACT_VERSION_MISMATCH"
    assert sql_count == 2


def test_relative_rotation_rejects_missing_unknown_duplicate_and_illegal_inputs(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    path = "/api/v1/wealth/market/sector-analysis/relative-rotation/results"
    invalid_cases = (
        {
            key: value
            for key, value in _relative_results_params().items()
            if key != "market"
        },
        {**_relative_results_params(), "period": 1},
        {**_relative_results_params(), "trailLength": 90},
        {**_relative_results_params(), "improvementLookbackDays": 5},
        {**_relative_results_params(), "sectorCode": "BK9999.DC"},
        {**_relative_results_params(), "scope": "LEVEL_1_CHILDREN"},
        {**_relative_results_params(), "tradeDate": "2026-02-30"},
    )
    for params in invalid_cases:
        response = app_client.get(path, params=params)
        assert response.status_code == 400
        assert response.json()["code"] in {
            "SA_SCOPE_INVALID",
            "SA_SELECTION_INVALID",
        }
    duplicate = app_client.get(
        path
        + "?market=CN_A&market=CN_A&scope=LEVEL_1&period=20&trailLength=20"
        + "&hierarchyVersion=2026-04-30-v1"
    )
    assert duplicate.status_code == 400
    assert duplicate.json()["code"] == "SA_SCOPE_INVALID"


def test_relative_rotation_maximum_window_meets_sql_and_payload_budgets(
    app_client,
    db_session,
    web_engine,
) -> None:
    target_date, hierarchy_version = _seed_maximum_dual_pool(
        db_session,
        open_date_count=95,
    )
    params = {
        "market": "CN_A",
        "tradeDate": target_date.isoformat(),
        "scope": "LEVEL_3",
        "period": 30,
        "trailLength": 60,
        "hierarchyVersion": hierarchy_version,
    }

    sql_count, first = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/relative-rotation/results",
            params=params,
        ),
    )
    assert first.status_code == 200
    assert first.json()["analysis"]["totalCount"] == 337
    assert first.json()["analysis"]["currentCalculableCount"] == 337
    assert first.json()["analysis"]["selectedTrail"]["dateSlotCount"] == 60
    assert sql_count == 5
    assert len(first.content) <= 256 * 1024


def _member_breadth_rankings_params(**overrides):
    params = {
        "market": "CN_A",
        "tradeDate": TARGET_DATE.isoformat(),
        "scope": "LEVEL_1",
        "direction": "UP",
        "metric": "MEMBER_COUNT",
        "maPeriod": 20,
        "hierarchyVersion": "2026-04-30-v1",
    }
    params.update(overrides)
    return params


def _member_breadth_details_params(**overrides):
    params = {
        "market": "CN_A",
        "tradeDate": TARGET_DATE.isoformat(),
        "sectorCode": "BK1201.DC",
        "direction": "UP",
        "maPeriod": 20,
        "historyRange": 20,
        "hierarchyVersion": "2026-04-30-v1",
    }
    params.update(overrides)
    return params


def test_member_breadth_meta_reuses_public_context_and_three_sql_contract(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_sector_analysis(db_session)

    started = perf_counter()
    sql_count, response = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/member-breadth/meta",
            params={"market": "CN_A"},
        ),
    )
    elapsed = perf_counter() - started

    assert response.status_code == 200
    assert sql_count == 3
    assert elapsed < 1
    payload = response.json()
    assert payload["formulaKey"] == "sector-member-breadth"
    assert payload["formulaVersion"] == 1
    assert payload["dateCoverageBasis"] == "INDUSTRY_DAILY"
    assert payload["dateContext"] == {
        "expectedTradeDate": TARGET_DATE.isoformat(),
        "defaultTradeDate": TARGET_DATE.isoformat(),
        "defaultStatus": "READY",
        "displayText": f"当前展示 {TARGET_DATE.isoformat()} 盘后数据",
    }
    assert payload["metrics"] == ["MEMBER_COUNT", "TURNOVER", "MA_POSITION"]
    assert payload["maPeriods"] == [5, 10, 15, 20, 30, 60]
    assert payload["historyRanges"] == [20, 30, 60]
    assert payload["minimumCalculableCount"] == 5
    assert payload["minimumCoveragePct"] == 80


def test_member_breadth_rankings_return_full_list_in_four_sql(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_member_breadth(db_session)

    started = perf_counter()
    sql_count, response = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/member-breadth/rankings",
            params=_member_breadth_rankings_params(),
        ),
    )
    elapsed = perf_counter() - started

    assert response.status_code == 200
    assert sql_count == 4
    assert elapsed < 1
    payload = response.json()
    assert payload["status"] == "READY"
    assert payload["totalSectorCount"] == 2
    assert payload["eligibleSectorCount"] == 2
    assert len(payload["rows"]) == 2
    assert [row["sectorCode"] for row in payload["rows"]] == [
        "BK1002.DC",
        "BK1001.DC",
    ]
    assert [row["metricValuePct"] for row in payload["rows"]] == [40.0, 20.0]
    assert [row["rank"] for row in payload["rows"]] == [1, 2]


def test_member_breadth_ma_rankings_read_factors_without_extra_sql(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_member_breadth(db_session)

    started = perf_counter()
    sql_count, response = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/member-breadth/rankings",
            params=_member_breadth_rankings_params(
                metric="MA_POSITION",
                maPeriod=60,
            ),
        ),
    )
    elapsed = perf_counter() - started

    assert response.status_code == 200
    assert sql_count == 4
    assert elapsed < 2
    payload = response.json()
    assert payload["status"] == "READY"
    assert payload["availability"]["status"] == "AVAILABLE"
    assert [row["metricValuePct"] for row in payload["rows"]] == [100.0, 100.0]
    assert [row["rank"] for row in payload["rows"]] == [1, 1]


def test_member_breadth_details_return_three_metrics_trend_and_members_in_four_sql(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_member_breadth(db_session)

    started = perf_counter()
    sql_count, response = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/member-breadth/details",
            params=_member_breadth_details_params(),
        ),
    )
    elapsed = perf_counter() - started

    assert response.status_code == 200
    assert sql_count == 4
    assert elapsed < 1
    assert len(response.content) <= 512 * 1024
    payload = response.json()
    assert payload["status"] == "READY"
    assert [item["metric"] for item in payload["compositions"]] == [
        "MEMBER_COUNT",
        "TURNOVER",
        "MA_POSITION",
    ]
    assert len(payload["trend"]) == 20
    assert payload["trend"][-1]["tradeDate"] == TARGET_DATE.isoformat()
    assert len(payload["members"]) == 5
    assert [row["stockCode"] for row in payload["members"]] == [
        "060005.SZ",
        "060004.SZ",
        "060003.SZ",
        "060002.SZ",
        "060001.SZ",
    ]
    assert all(row["maRelation"] == "ABOVE" for row in payload["members"])


def test_member_breadth_details_projection_preserves_independent_missing_reasons(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_member_breadth(db_session)
    first = db_session.get(
        EquityDailyBar,
        {"ts_code": "060001.SZ", "trade_date": TARGET_DATE},
    )
    second = db_session.get(
        EquityDailyBar,
        {"ts_code": "060002.SZ", "trade_date": TARGET_DATE},
    )
    missing_market = db_session.get(
        EquityDailyBar,
        {"ts_code": "060003.SZ", "trade_date": TARGET_DATE},
    )
    negative_amount = db_session.get(
        EquityDailyBar,
        {"ts_code": "060005.SZ", "trade_date": TARGET_DATE},
    )
    missing_factor = db_session.get(
        EquityAdjFactor,
        {"ts_code": "060004.SZ", "trade_date": OPEN_DATES[-5]},
    )
    assert all(
        item is not None
        for item in (first, second, missing_market, negative_amount, missing_factor)
    )
    first.pct_chg = None
    second.amount = None
    negative_amount.amount = Decimal("-1")
    db_session.delete(missing_market)
    db_session.delete(missing_factor)
    db_session.commit()

    sql_count, response = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/member-breadth/details",
            params=_member_breadth_details_params(),
        ),
    )

    assert response.status_code == 200
    assert sql_count == 4
    payload = response.json()
    assert payload["status"] == "READY"
    compositions = {item["metric"]: item for item in payload["compositions"]}
    assert compositions["MEMBER_COUNT"]["calculableCount"] == 3
    assert compositions["TURNOVER"]["calculableCount"] == 1
    assert compositions["MA_POSITION"]["calculableCount"] == 3
    assert compositions["MEMBER_COUNT"]["reasonCodes"] == [
        "MARKET_ROW_MISSING",
        "PCT_CHANGE_MISSING",
        "MINIMUM_COUNT_NOT_MET",
        "COVERAGE_NOT_MET",
    ]
    assert compositions["TURNOVER"]["reasonCodes"] == [
        "MARKET_ROW_MISSING",
        "PCT_CHANGE_MISSING",
        "AMOUNT_MISSING",
        "AMOUNT_NON_POSITIVE",
        "MINIMUM_COUNT_NOT_MET",
        "COVERAGE_NOT_MET",
    ]
    assert compositions["MA_POSITION"]["reasonCodes"] == [
        "MARKET_ROW_MISSING",
        "ADJ_FACTOR_MISSING",
        "MA_HISTORY_INSUFFICIENT",
        "MINIMUM_COUNT_NOT_MET",
        "COVERAGE_NOT_MET",
    ]
    members = {item["stockCode"]: item for item in payload["members"]}
    assert members["060001.SZ"]["dailyPctChg"] is None
    assert members["060001.SZ"]["amountThousandYuan"] == 100.0
    assert members["060002.SZ"]["amountThousandYuan"] is None
    assert members["060003.SZ"]["reasonCodes"] == [
        "MARKET_ROW_MISSING",
        "MA_HISTORY_INSUFFICIENT",
    ]
    assert members["060004.SZ"]["reasonCodes"] == [
        "ADJ_FACTOR_MISSING",
        "MA_HISTORY_INSUFFICIENT",
    ]
    assert members["060005.SZ"]["reasonCodes"] == ["AMOUNT_NON_POSITIVE"]


def test_member_breadth_version_mismatch_stops_after_hierarchy_read(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_sector_analysis(db_session)

    sql_count, response = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/member-breadth/rankings",
            params=_member_breadth_rankings_params(hierarchyVersion="stale"),
        ),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "SA_BREADTH_FACT_MISMATCH"
    assert sql_count == 1


def test_member_breadth_rejects_missing_unknown_duplicate_and_illegal_inputs(
    app_client,
    db_session,
) -> None:
    _seed_sector_analysis(db_session)
    path = "/api/v1/wealth/market/sector-analysis/member-breadth/rankings"
    base = _member_breadth_rankings_params()
    scope_invalid_cases = (
        {key: value for key, value in base.items() if key != "market"},
        {key: value for key, value in base.items() if key != "scope"},
        {**base, "metric": "PRICE"},
        {**base, "direction": "GAINERS"},
        {**base, "maPeriod": 25},
        {**base, "unknown": "value"},
    )
    for params in scope_invalid_cases:
        response = app_client.get(path, params=params)
        assert response.status_code == 400
        assert response.json()["code"] == "SA_SCOPE_INVALID"

    invalid_date = app_client.get(
        path,
        params={**base, "tradeDate": "2026-02-30"},
    )
    assert invalid_date.status_code == 400
    assert invalid_date.json()["code"] == "SA_SELECTION_INVALID"

    duplicate = app_client.get(
        path
        + "?market=CN_A&market=CN_A&tradeDate=2026-04-30&scope=LEVEL_1"
        + "&direction=UP&metric=MEMBER_COUNT&maPeriod=20"
        + "&hierarchyVersion=2026-04-30-v1"
    )
    assert duplicate.status_code == 400
    assert duplicate.json()["code"] == "SA_SCOPE_INVALID"


def test_member_breadth_rejects_future_closed_and_precoverage_dates(
    app_client,
    db_session,
) -> None:
    _seed_member_breadth(db_session)
    closed_date = OPEN_DATES[-2]
    calendar = db_session.get(
        TradeCalendar,
        {"exchange": "SSE", "trade_date": closed_date},
    )
    calendar.is_open = False
    precoverage_date = OPEN_DATES[0] - timedelta(days=1)
    db_session.add(
        TradeCalendar(
            exchange="SSE",
            trade_date=precoverage_date,
            is_open=True,
            pretrade_date=None,
        )
    )
    db_session.commit()

    for trade_date in (
        TARGET_DATE + timedelta(days=1),
        closed_date,
        precoverage_date,
    ):
        response = app_client.get(
            "/api/v1/wealth/market/sector-analysis/member-breadth/rankings",
            params=_member_breadth_rankings_params(
                tradeDate=trade_date.isoformat(),
            ),
        )
        assert response.status_code == 400
        assert response.json()["code"] == "SA_SELECTION_INVALID"


def test_member_breadth_missing_selected_relations_returns_safe_empty_details(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_sector_analysis(db_session)

    sql_count, response = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/member-breadth/details",
            params=_member_breadth_details_params(),
        ),
    )

    assert response.status_code == 200
    assert sql_count == 3
    assert response.json()["status"] == "EMPTY"
    assert response.json()["exceptionCode"] == "SA_BREADTH_SOURCE_EMPTY"
    assert response.json()["compositions"] == []
    assert response.json()["trend"] == []
    assert response.json()["members"] == []


def test_member_breadth_hierarchy_unavailable_keeps_common_exception_semantics(
    app_client,
    db_session,
    web_engine,
) -> None:
    _seed_sector_analysis(db_session)
    for row in db_session.scalars(select(WealthSectorHierarchy)).all():
        db_session.delete(row)
    db_session.commit()

    meta_sql_count, meta = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/member-breadth/meta",
            params={"market": "CN_A"},
        ),
    )
    ranking_sql_count, rankings = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/member-breadth/rankings",
            params=_member_breadth_rankings_params(),
        ),
    )
    details_sql_count, details = _count_request_sql(
        web_engine,
        lambda: app_client.get(
            "/api/v1/wealth/market/sector-analysis/member-breadth/details",
            params=_member_breadth_details_params(),
        ),
    )

    assert meta.status_code == 500
    assert meta.json()["code"] == "SA_HIERARCHY_UNAVAILABLE"
    assert meta_sql_count == 2
    assert rankings.status_code == 200
    assert rankings.json()["status"] == "ERROR"
    assert rankings.json()["exceptionCode"] == "SA_HIERARCHY_UNAVAILABLE"
    assert ranking_sql_count == 1
    assert details.status_code == 200
    assert details.json()["status"] == "ERROR"
    assert details.json()["exceptionCode"] == "SA_HIERARCHY_UNAVAILABLE"
    assert details_sql_count == 1
