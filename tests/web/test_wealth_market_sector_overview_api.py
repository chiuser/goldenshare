from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.biz.schemas.wealth.market.sector_overview import PageStatusDto
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
from src.foundation.models.core_serving.wealth_sector_hierarchy import WealthSectorHierarchy


TARGET_DATE = date(2026, 4, 28)


def _ensure_source_tables(db_session) -> None:
    bind = db_session.get_bind()
    for table in (
        DcDaily.__table__,
        BoardMoneyflowDc.__table__,
        EquityDailyBar.__table__,
        EquityLimitList.__table__,
        EquitySuspendD.__table__,
        WealthSectorHierarchy.__table__,
        WealthSectorHeatDaily.__table__,
    ):
        table.create(bind, checkfirst=True)


def _add_board(
    db_session,
    *,
    code: str,
    name: str,
    category: str,
    content_type: str,
    pct: Decimal,
    up_count: int,
) -> None:
    db_session.add(
        DcDaily(
            ts_code=code,
            trade_date=TARGET_DATE,
            category=category,
            close=Decimal("100"),
            open=Decimal("99"),
            high=Decimal("101"),
            low=Decimal("98"),
            change=Decimal("1"),
            pct_change=pct,
            vol=Decimal("100000"),
            amount=Decimal("250000000"),
            swing=Decimal("2"),
            turnover_rate=Decimal("3"),
        )
    )
    db_session.add(
        DcIndex(
            ts_code=code,
            trade_date=TARGET_DATE,
            name=name,
            idx_type=category,
            leading=f"{name}领涨",
            leading_code="000001.SZ",
            pct_change=pct + Decimal("9"),  # Deliberately differs from dc_daily.
            leading_pct=Decimal("5.25"),
            total_mv=Decimal("10000000000"),
            turnover_rate=Decimal("2.5"),
            up_num=up_count,
            down_num=5,
            level=None,
        )
    )
    db_session.add(
        BoardMoneyflowDc(
            trade_date=TARGET_DATE,
            content_type=content_type,
            name=name,
            ts_code=code,
            pct_change=pct,
            close=Decimal("100"),
            net_amount=Decimal(up_count) * Decimal("100000000"),
            net_amount_rate=Decimal("0.3"),
            buy_elg_amount=Decimal("100000000"),
            buy_elg_amount_rate=Decimal("0.03"),
            buy_lg_amount=Decimal("200000000"),
            buy_lg_amount_rate=Decimal("0.06"),
            buy_md_amount=Decimal("300000000"),
            buy_md_amount_rate=Decimal("0.09"),
            buy_sm_amount=Decimal("400000000"),
            buy_sm_amount_rate=Decimal("0.12"),
            buy_sm_amount_stock="样本股",
            rank=up_count,
        )
    )


def _heat_row(*, trade_date: date, code: str, name: str, rank: int, invalid: bool = False) -> WealthSectorHeatDaily:
    return WealthSectorHeatDaily(
        trade_date=trade_date,
        sector_code=code,
        sector_name=name,
        heat_status="INVALID" if invalid else "VALID",
        invalid_reason="FEATURE_MISSING" if invalid else None,
        base_heat_score=None if invalid else Decimal(101 - rank),
        base_heat_rank=None if invalid else rank,
        heat_score=None if invalid else Decimal(101 - rank),
        heat_rank=None if invalid else rank,
        heat_level="NONE" if invalid else ("BOILING" if rank <= 10 else "HOT"),
        heat_delta_1d=None if invalid else Decimal(rank),
        heat_trend="UNKNOWN" if invalid else "HEATING",
        raw_heat_trend="UNKNOWN" if invalid else "HEATING",
        price_strength_score=None if invalid else Decimal("0.5"),
        breadth_score=None if invalid else Decimal("0.5"),
        capital_flow_score=None if invalid else Decimal("0.5"),
        activity_score=None if invalid else Decimal("0.5"),
        persistence_score=None if invalid else Decimal("0.5"),
        source_member_count=5,
        member_count=5,
        suspended_count=0,
        quote_eligible_count=5,
        valid_quote_count=5,
        missing_quote_count=0,
        quote_coverage=Decimal("1"),
        score_version="concept-heat-eod-v1",
        config_hash="a" * 64,
        source_dates_json={"target": trade_date.isoformat()},
        source_row_counts_json={"dc_index": 20},
        source_hash="b" * 64,
        calculated_at=datetime(2026, 4, 28, 20, 0, tzinfo=timezone.utc),
    )


def _seed_members(db_session, *, sector_codes: tuple[str, ...]) -> None:
    for index in range(1, 7):
        stock_code = f"000{index:03d}.SZ"
        db_session.add(
            Security(
                ts_code=stock_code,
                symbol=f"000{index:03d}",
                name=f"证券主数据名{index}",
                curr_type="CNY",
                list_status="L",
                list_date=date(2020, 1, 1),
                delist_date=None,
                security_type="EQUITY",
                source="tushare",
            )
        )
        db_session.add(
            EquityDailyBar(
                ts_code=stock_code,
                trade_date=TARGET_DATE,
                open=Decimal("10"),
                high=Decimal("11"),
                low=Decimal("9"),
                close=Decimal("10.5"),
                pre_close=Decimal("10"),
                change_amount=Decimal("0.5"),
                pct_chg=Decimal(20 - index),
                vol=Decimal("100"),
                amount=Decimal("1000"),
                source="tushare",
            )
        )
        for sector_code in sector_codes:
            db_session.add(
                DcMember(
                    trade_date=TARGET_DATE,
                    ts_code=sector_code,
                    con_code=stock_code,
                    name=f"成分股{index}",
                )
            )


def _seed_sector_overview_v2(db_session) -> None:
    _ensure_source_tables(db_session)
    db_session.add(
        TradeCalendar(
            exchange="SSE",
            trade_date=TARGET_DATE,
            is_open=True,
            pretrade_date=date(2026, 4, 27),
        )
    )

    hierarchy_nodes: list[tuple[str, str, int, str | None, str, str]] = []
    for index in range(1, 6):
        code = f"BK10{index:02d}.DC"
        hierarchy_nodes.append((code, f"一级行业{index}", 1, None, code, f"一级行业{index}"))
    for index in range(1, 6):
        code = f"BK11{index:02d}.DC"
        hierarchy_nodes.append((code, f"二级行业{index}", 2, "BK1001.DC", "BK1001.DC", f"一级行业1/二级行业{index}"))
    for index in range(1, 6):
        code = f"BK12{index:02d}.DC"
        hierarchy_nodes.append((code, f"三级行业{index}", 3, "BK1101.DC", "BK1001.DC", f"一级行业1/二级行业1/三级行业{index}"))

    for order, (code, name, level, parent, root, path) in enumerate(hierarchy_nodes, start=1):
        db_session.add(
            WealthSectorHierarchy(
                sector_code=code,
                sector_name=name,
                industry_level=level,
                industry_level_name=f"{level}级行业",
                parent_sector_code=parent,
                parent_sector_name=None if parent is None else "父行业",
                root_sector_code=root,
                root_sector_name="一级行业1" if root == "BK1001.DC" else name,
                hierarchy_path=path,
                is_leaf=level == 3,
                display_order=order,
                baseline_version="2026-04-28-v1",
                source_received_date=TARGET_DATE,
                code_reference_trade_date=TARGET_DATE,
                published_at=datetime(2026, 4, 28, 19, 0, tzinfo=timezone.utc),
            )
        )
        _add_board(
            db_session,
            code=code,
            name=name,
            category="行业板块",
            content_type="行业",
            pct=Decimal(20 - order),
            up_count=40 - order,
        )

    for index in range(1, 21):
        code = f"BK20{index:02d}.DC"
        name = f"概念板块{index}"
        _add_board(
            db_session,
            code=code,
            name=name,
            category="概念板块",
            content_type="概念",
            pct=Decimal(30 - index),
            up_count=60 - index,
        )
        db_session.add(_heat_row(trade_date=TARGET_DATE, code=code, name=name, rank=index))

    for index in range(1, 32):
        code = f"BK30{index:02d}.DC"
        _add_board(
            db_session,
            code=code,
            name=f"地域板块{index}",
            category="地域板块",
            content_type="地域",
            pct=Decimal(40 - index),
            up_count=80 - index,
        )

    for offset in range(1, 22):
        history_date = TARGET_DATE - timedelta(days=offset)
        db_session.add(
            _heat_row(
                trade_date=history_date,
                code="BK2001.DC",
                name="概念板块1",
                rank=1,
                invalid=offset == 2,
            )
        )

    _seed_members(
        db_session,
        sector_codes=tuple(code for code, *_rest in hierarchy_nodes)
        + tuple(f"BK20{index:02d}.DC" for index in range(1, 21))
        + tuple(f"BK30{index:02d}.DC" for index in range(1, 32)),
    )
    db_session.commit()


def test_industry_workspace_resolves_three_levels_and_uses_frozen_fields(app_client, db_session) -> None:
    _seed_sector_overview_v2(db_session)

    response = app_client.get(
        "/api/v1/wealth/market/sector-overview",
        params={"tradeDate": TARGET_DATE.isoformat(), "debug": 1},
    )
    assert response.status_code == 200
    payload = response.json()
    panel = payload["sectorOverview"]

    assert panel["view"] == "INDUSTRY"
    assert "concept" not in panel and "region" not in panel
    assert "columns" not in panel and "heatMapItems" not in panel
    workspace = panel["industry"]
    assert [len(column["rows"]) for column in workspace["columns"]] == [5, 5, 5]
    assert workspace["selection"] == {
        "level1Code": "BK1001.DC",
        "level2Code": "BK1101.DC",
        "level3Code": "BK1201.DC",
        "detailSectorCode": "BK1201.DC",
    }
    first = workspace["columns"][0]["rows"][0]
    assert first["sectorName"] == "一级行业1"
    assert set(first) == {
        "rank",
        "sectorCode",
        "sectorName",
        "industryLevel",
        "primaryMetric",
        "leader",
        "selected",
    }
    assert first["industryLevel"] == 1
    assert first["primaryMetric"]["value"] == 19.0  # dc_daily, not dc_index.pct_change.
    assert first["leader"] == {"stockCode": "000001.SZ", "stockName": "一级行业1领涨", "changePct": 5.25}
    assert len(workspace["detail"]["members"]) == 5
    assert workspace["detail"]["members"][0]["stockName"] == "成分股1"
    assert workspace["detail"]["leader"]["stockName"] == "三级行业1领涨"
    assert payload["debugInfo"]["exceptions"] == []


def test_industry_selection_preserves_valid_ancestor_and_corrects_outside_top5(app_client, db_session) -> None:
    _seed_sector_overview_v2(db_session)

    valid = app_client.get(
        "/api/v1/wealth/market/sector-overview",
        params={"tradeDate": TARGET_DATE.isoformat(), "selectedIndustryCode": "BK1103", "debug": 1},
    ).json()
    assert valid["sectorOverview"]["industry"]["selection"]["level2Code"] == "BK1103.DC"
    assert valid["debugInfo"]["exceptions"] == []

    corrected = app_client.get(
        "/api/v1/wealth/market/sector-overview",
        params={"tradeDate": TARGET_DATE.isoformat(), "selectedIndustryCode": "BK9999", "debug": 1},
    ).json()
    assert corrected["sectorOverview"]["industry"]["selection"]["detailSectorCode"] == "BK1201.DC"
    assert [item["code"] for item in corrected["debugInfo"]["exceptions"]] == ["SO_SELECTION_INVALID"]


def test_concept_workspace_supports_heat_sort_history_and_member_detail(app_client, db_session) -> None:
    _seed_sector_overview_v2(db_session)

    response = app_client.get(
        "/api/v1/wealth/market/sector-overview",
        params={
            "tradeDate": TARGET_DATE.isoformat(),
            "view": "CONCEPT",
            "conceptRankMetric": "HEAT_DELTA_1D",
            "selectedConceptCode": "BK2001",
            "debug": 1,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    workspace = payload["sectorOverview"]["concept"]
    assert "industry" not in payload["sectorOverview"] and "region" not in payload["sectorOverview"]
    assert len(workspace["rows"]) == 20
    assert workspace["rows"][0]["sectorCode"] == "BK2020.DC"
    assert set(workspace["rows"][0]) == {
        "rank",
        "sectorCode",
        "sectorName",
        "changePct",
        "mainNetInflow",
        "leader",
        "heatStatus",
        "heatLevel",
        "heatTrend",
        "heatScore",
        "heatDelta1d",
        "selected",
    }
    assert workspace["rows"][0]["heatStatus"] == "VALID"
    assert workspace["rows"][0]["changePct"]["value"] == 10.0
    assert workspace["rows"][0]["mainNetInflow"]["value"] == 4_000_000_000.0
    assert workspace["selectedConceptCode"] == "BK2001.DC"
    assert len(workspace["detail"]["heatHistory"]) == 20
    assert workspace["detail"]["heatHistory"] == sorted(
        workspace["detail"]["heatHistory"], key=lambda item: item["tradeDate"]
    )
    assert any(item.get("heatScore") is None for item in workspace["detail"]["heatHistory"])
    assert len(workspace["detail"]["members"]) == 5


def test_region_workspace_returns_exact_production_enumeration_without_heat_or_hierarchy(app_client, db_session) -> None:
    _seed_sector_overview_v2(db_session)

    response = app_client.get(
        "/api/v1/wealth/market/sector-overview",
        params={
            "tradeDate": TARGET_DATE.isoformat(),
            "view": "REGION",
            "regionRankMetric": "UP_COUNT",
            "selectedRegionCode": "BK3005.DC",
        },
    )
    assert response.status_code == 200
    panel = response.json()["sectorOverview"]
    workspace = panel["region"]
    assert len(workspace["rows"]) == 31
    assert workspace["selectedRegionCode"] == "BK3005.DC"
    assert workspace["rows"][0]["sectorCode"] == "BK3001.DC"
    assert set(workspace["rows"][0]) == {
        "rank",
        "sectorCode",
        "sectorName",
        "changePct",
        "mainNetInflow",
        "memberCount",
        "upCount",
        "leader",
        "selected",
    }
    assert workspace["rows"][0]["changePct"]["value"] == 39.0
    assert workspace["rows"][0]["mainNetInflow"]["value"] == 7_900_000_000.0
    assert workspace["rows"][0]["memberCount"] == 6
    assert workspace["rows"][0]["upCount"] == 79
    assert "hierarchyPath" not in workspace["detail"]
    assert "heatHistory" not in workspace["detail"]


def test_concept_heat_not_ready_does_not_fallback_to_change_ranking(app_client, db_session) -> None:
    _seed_sector_overview_v2(db_session)
    db_session.query(WealthSectorHeatDaily).delete()
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/sector-overview",
        params={"tradeDate": TARGET_DATE.isoformat(), "view": "CONCEPT", "debug": 1},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["sectorOverview"]["status"] == "PARTIAL"
    assert payload["sectorOverview"]["concept"]["rows"] == []
    assert [item["code"] for item in payload["debugInfo"]["exceptions"]] == ["SO_HEAT_NOT_READY"]


def test_one_invalid_concept_heat_row_keeps_usable_rows_but_marks_partial(app_client, db_session) -> None:
    _seed_sector_overview_v2(db_session)
    db_session.query(WealthSectorHeatDaily).filter(
        WealthSectorHeatDaily.trade_date == TARGET_DATE,
        WealthSectorHeatDaily.sector_code == "BK2020.DC",
    ).update(
        {
            WealthSectorHeatDaily.heat_status: "INVALID",
            WealthSectorHeatDaily.invalid_reason: "FEATURE_MISSING",
            WealthSectorHeatDaily.heat_score: None,
            WealthSectorHeatDaily.heat_rank: None,
            WealthSectorHeatDaily.heat_level: "NONE",
            WealthSectorHeatDaily.heat_delta_1d: None,
            WealthSectorHeatDaily.heat_trend: "UNKNOWN",
            WealthSectorHeatDaily.raw_heat_trend: "UNKNOWN",
        },
        synchronize_session=False,
    )
    db_session.commit()

    payload = app_client.get(
        "/api/v1/wealth/market/sector-overview",
        params={"tradeDate": TARGET_DATE.isoformat(), "view": "CONCEPT", "debug": 1},
    ).json()

    assert payload["sectorOverview"]["status"] == "PARTIAL"
    assert len(payload["sectorOverview"]["concept"]["rows"]) == 19
    assert [item["code"] for item in payload["debugInfo"]["exceptions"]] == ["SO_HEAT_NOT_READY"]


def test_sector_overview_rejects_unknown_irrelevant_or_invalid_parameters(app_client, db_session) -> None:
    _seed_sector_overview_v2(db_session)
    cases = [
        {"market": "US"},
        {"view": "INDUSTRY", "conceptRankMetric": "HEAT_SCORE"},
        {"view": "REGION", "selectedRegionCode": "bad-code"},
        {"level": "2"},
        {"tradeDate": "2026/04/28"},
        {"debug": "true"},
    ]
    for params in cases:
        response = app_client.get("/api/v1/wealth/market/sector-overview", params=params)
        assert response.status_code == 400, params
        assert response.json()["code"] == "400001"


def test_explicit_non_trading_or_missing_date_returns_empty_without_fallback(app_client, db_session) -> None:
    _seed_sector_overview_v2(db_session)

    response = app_client.get(
        "/api/v1/wealth/market/sector-overview",
        params={"tradeDate": "2026-04-27", "debug": 1},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["sectorOverview"]["tradeDate"] == "2026-04-27"
    assert payload["sectorOverview"]["status"] == "EMPTY"
    assert payload["sectorOverview"]["industry"]["columns"][0]["rows"] == []
    assert [item["code"] for item in payload["debugInfo"]["exceptions"]] == ["SO_SOURCE_EMPTY"]


def test_explicit_trading_date_without_bundle_returns_empty_not_previous_day(app_client, db_session) -> None:
    _seed_sector_overview_v2(db_session)
    missing_date = date(2026, 4, 29)
    db_session.add(
        TradeCalendar(
            exchange="SSE",
            trade_date=missing_date,
            is_open=True,
            pretrade_date=TARGET_DATE,
        )
    )
    db_session.commit()

    payload = app_client.get(
        "/api/v1/wealth/market/sector-overview",
        params={"tradeDate": missing_date.isoformat(), "debug": 1},
    ).json()

    assert payload["sectorOverview"]["tradeDate"] == missing_date.isoformat()
    assert payload["sectorOverview"]["status"] == "EMPTY"
    assert payload["sectorOverview"]["industry"]["columns"][0]["rows"] == []
    assert [item["code"] for item in payload["debugInfo"]["exceptions"]] == ["SO_SOURCE_EMPTY"]


def test_default_date_reports_delayed_without_cross_date_join(app_client, db_session) -> None:
    _seed_sector_overview_v2(db_session)
    db_session.add(
        TradeCalendar(
            exchange="SSE",
            trade_date=date(2026, 4, 29),
            is_open=True,
            pretrade_date=TARGET_DATE,
        )
    )
    db_session.commit()

    response = app_client.get("/api/v1/wealth/market/sector-overview", params={"debug": 1})
    assert response.status_code == 200
    payload = response.json()
    assert payload["tradingDay"]["tradeDate"] == "2026-04-29"
    assert payload["tradingDay"]["isTradingDay"] is True
    assert payload["sectorOverview"]["tradeDate"] == TARGET_DATE.isoformat()
    assert payload["sectorOverview"]["status"] == "DELAYED"
    assert [item["code"] for item in payload["debugInfo"]["exceptions"]] == ["SO_SOURCE_DELAYED"]


def test_rank_null_rules_filter_industry_and_concept_before_topn_but_keep_all_regions(
    app_client,
    db_session,
) -> None:
    _seed_sector_overview_v2(db_session)
    db_session.query(DcDaily).filter(
        DcDaily.trade_date == TARGET_DATE,
        DcDaily.ts_code.in_(("BK1001.DC", "BK2001.DC", "BK3001.DC")),
    ).update({DcDaily.pct_change: None}, synchronize_session=False)
    db_session.commit()

    industry = app_client.get(
        "/api/v1/wealth/market/sector-overview",
        params={"tradeDate": TARGET_DATE.isoformat(), "view": "INDUSTRY"},
    ).json()["sectorOverview"]["industry"]["columns"][0]["rows"]
    concept = app_client.get(
        "/api/v1/wealth/market/sector-overview",
        params={
            "tradeDate": TARGET_DATE.isoformat(),
            "view": "CONCEPT",
            "conceptRankMetric": "CHANGE_PCT",
        },
    ).json()["sectorOverview"]["concept"]["rows"]
    region = app_client.get(
        "/api/v1/wealth/market/sector-overview",
        params={
            "tradeDate": TARGET_DATE.isoformat(),
            "view": "REGION",
            "regionRankMetric": "CHANGE_PCT",
        },
    ).json()["sectorOverview"]["region"]["rows"]

    assert len(industry) == 4
    assert "BK1001.DC" not in {row["sectorCode"] for row in industry}
    assert len(concept) == 19
    assert "BK2001.DC" not in {row["sectorCode"] for row in concept}
    assert len(region) == 31
    assert region[-1]["sectorCode"] == "BK3001.DC"
    assert region[-1]["changePct"]["value"] is None


def test_required_moneyflow_and_member_gaps_are_partial_with_explicit_issues(app_client, db_session) -> None:
    _seed_sector_overview_v2(db_session)
    db_session.query(BoardMoneyflowDc).filter(
        BoardMoneyflowDc.trade_date == TARGET_DATE,
        BoardMoneyflowDc.ts_code == "BK1001.DC",
    ).delete(synchronize_session=False)
    db_session.query(DcMember).filter(
        DcMember.trade_date == TARGET_DATE,
        DcMember.ts_code == "BK1201.DC",
    ).delete(synchronize_session=False)
    db_session.commit()

    payload = app_client.get(
        "/api/v1/wealth/market/sector-overview",
        params={"tradeDate": TARGET_DATE.isoformat(), "debug": 1},
    ).json()

    assert payload["sectorOverview"]["status"] == "PARTIAL"
    assert payload["sectorOverview"]["industry"]["columns"][0]["rows"]
    assert payload["sectorOverview"]["industry"]["detail"]["metrics"]["sourceMemberCount"] == 0
    assert {item["code"] for item in payload["debugInfo"]["exceptions"]} == {
        "SO_MONEYFLOW_MISSING",
        "SO_MEMBER_SOURCE_EMPTY",
    }


def test_required_daily_gap_is_partial_and_keeps_other_rows(app_client, db_session) -> None:
    _seed_sector_overview_v2(db_session)
    db_session.query(DcDaily).filter(
        DcDaily.trade_date == TARGET_DATE,
        DcDaily.ts_code == "BK1002.DC",
    ).delete(synchronize_session=False)
    db_session.commit()

    payload = app_client.get(
        "/api/v1/wealth/market/sector-overview",
        params={"tradeDate": TARGET_DATE.isoformat(), "debug": 1},
    ).json()

    assert payload["sectorOverview"]["status"] == "PARTIAL"
    assert payload["sectorOverview"]["industry"]["columns"][0]["rows"]
    assert [item["code"] for item in payload["debugInfo"]["exceptions"]] == ["SO_DAILY_MISSING"]


def test_missing_index_row_is_partial_but_missing_leader_fields_are_not(app_client, db_session) -> None:
    _seed_sector_overview_v2(db_session)
    db_session.query(DcIndex).filter(
        DcIndex.trade_date == TARGET_DATE,
        DcIndex.ts_code == "BK1002.DC",
    ).delete(synchronize_session=False)
    db_session.commit()

    payload = app_client.get(
        "/api/v1/wealth/market/sector-overview",
        params={"tradeDate": TARGET_DATE.isoformat(), "debug": 1},
    ).json()

    assert payload["sectorOverview"]["status"] == "PARTIAL"
    assert [item["code"] for item in payload["debugInfo"]["exceptions"]] == ["SO_INDEX_MISSING"]


def test_legal_missing_leader_remains_ready_and_returns_null(app_client, db_session) -> None:
    _seed_sector_overview_v2(db_session)
    db_session.query(DcIndex).filter(
        DcIndex.trade_date == TARGET_DATE,
        DcIndex.ts_code == "BK1001.DC",
    ).update(
        {DcIndex.leading: None, DcIndex.leading_code: None, DcIndex.leading_pct: None},
        synchronize_session=False,
    )
    db_session.commit()

    payload = app_client.get(
        "/api/v1/wealth/market/sector-overview",
        params={"tradeDate": TARGET_DATE.isoformat(), "debug": 1},
    ).json()

    assert payload["sectorOverview"]["status"] == "READY"
    assert payload["sectorOverview"]["industry"]["columns"][0]["rows"][0]["leader"] is None
    assert payload["debugInfo"]["exceptions"] == []


def test_industry_hierarchy_unavailable_is_stable_error(app_client, db_session) -> None:
    _seed_sector_overview_v2(db_session)
    db_session.query(WealthSectorHierarchy).delete()
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/sector-overview",
        params={"tradeDate": TARGET_DATE.isoformat(), "debug": 1},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["sectorOverview"]["status"] == "ERROR"
    assert payload["sectorOverview"]["industry"]["selection"]["detailSectorCode"] is None
    assert [item["code"] for item in payload["debugInfo"]["exceptions"]] == ["SO_HIERARCHY_UNAVAILABLE"]


def test_page_status_contract_rejects_unknown_backend_values() -> None:
    with pytest.raises(ValidationError):
        PageStatusDto(status="UNKNOWN", displayText="未知状态")  # type: ignore[arg-type]


def test_all_frozen_rank_metrics_are_accepted_per_workspace(app_client, db_session) -> None:
    _seed_sector_overview_v2(db_session)
    matrix = {
        "INDUSTRY": ("industryRankMetric", ("CHANGE_PCT", "MAIN_NET_INFLOW", "UP_COUNT")),
        "CONCEPT": (
            "conceptRankMetric",
            ("HEAT_SCORE", "HEAT_DELTA_1D", "CHANGE_PCT", "MAIN_NET_INFLOW"),
        ),
        "REGION": ("regionRankMetric", ("CHANGE_PCT", "MAIN_NET_INFLOW", "UP_COUNT")),
    }
    for view, (param_name, metrics) in matrix.items():
        for metric in metrics:
            response = app_client.get(
                "/api/v1/wealth/market/sector-overview",
                params={"tradeDate": TARGET_DATE.isoformat(), "view": view, param_name: metric},
            )
            assert response.status_code == 200, (view, metric)
            workspace = response.json()["sectorOverview"][view.lower()]
            assert workspace["rankMetric"] == metric
