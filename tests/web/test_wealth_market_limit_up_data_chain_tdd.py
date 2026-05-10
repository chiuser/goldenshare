from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Integer, cast, func, select

from src.foundation.models.core.equity_limit_list import EquityLimitList
from src.foundation.models.core.equity_stock_st import EquityStockSt
from src.foundation.models.core.limit_cpt_list import LimitCptList
from src.foundation.models.core.limit_list_ths import LimitListThs
from src.foundation.models.core.ths_member import ThsMember
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar


def _ensure_limit_up_tables(db_session) -> None:
    bind = db_session.get_bind()
    for table in [
        LimitListThs.__table__,
        EquityLimitList.__table__,
        LimitCptList.__table__,
        ThsMember.__table__,
        EquityStockSt.__table__,
        EquityDailyBar.__table__,
    ]:
        table.create(bind, checkfirst=True)


@dataclass(frozen=True)
class ParsedUpStat:
    n: int
    t: int
    ratio: float


def _parse_up_stat(value: str | None) -> ParsedUpStat | None:
    if not value:
        return None
    match = re.search(r"(?P<n>\d+)\s*/\s*(?P<t>\d+)", value)
    if not match:
        return None
    n = int(match.group("n"))
    t = int(match.group("t"))
    if t <= 0:
        return None
    return ParsedUpStat(n=n, t=t, ratio=n / t)


def _build_limit_stats(db_session, *, trade_date: date) -> dict[str, int]:
    def _count(limit_type: str) -> int:
        return int(
            db_session.scalar(
                select(func.count())
                .select_from(
                    select(LimitListThs.ts_code)
                    .where(
                        LimitListThs.trade_date == trade_date,
                        LimitListThs.limit_type == limit_type,
                    )
                    .distinct()
                    .subquery()
                )
            )
            or 0
        )

    up_pool_codes = set(
        db_session.scalars(
            select(LimitListThs.ts_code).where(
                LimitListThs.trade_date == trade_date,
                LimitListThs.limit_type == "涨停池",
            )
        ).all()
    )
    down_pool_codes = set(
        db_session.scalars(
            select(LimitListThs.ts_code).where(
                LimitListThs.trade_date == trade_date,
                LimitListThs.limit_type == "跌停池",
            )
        ).all()
    )
    broken_pool_codes = set(
        db_session.scalars(
            select(LimitListThs.ts_code).where(
                LimitListThs.trade_date == trade_date,
                LimitListThs.limit_type == "炸板池",
            )
        ).all()
    )
    st_codes = set(
        db_session.scalars(
            select(EquityStockSt.ts_code).where(
                EquityStockSt.trade_date == trade_date,
            )
        ).all()
    )

    up_total = _count("涨停池")
    down_total = _count("跌停池")
    broken_total = _count("炸板池")
    up_st = len(up_pool_codes & st_codes)
    down_st = len(down_pool_codes & st_codes)
    broken_st = len(broken_pool_codes & st_codes)

    non_st_up = up_total - up_st
    non_st_broken = broken_total - broken_st
    touch = non_st_up + non_st_broken
    sealing_rate = float(non_st_up / touch) if touch > 0 else None

    return {
        "up_total": up_total,
        "down_total": down_total,
        "broken_total": broken_total,
        "up_st": up_st,
        "down_st": down_st,
        "broken_st": broken_st,
        "non_st_up": non_st_up,
        "non_st_broken": non_st_broken,
        "sealing_rate_non_st": sealing_rate,
    }


def _load_sector_top5(db_session, *, trade_date: date) -> list[dict]:
    rows = db_session.execute(
        select(
            LimitCptList.ts_code,
            LimitCptList.name,
            LimitCptList.up_nums,
            LimitCptList.rank,
            LimitCptList.up_stat,
            LimitCptList.cons_nums,
        )
        .where(LimitCptList.trade_date == trade_date)
        .order_by(
            cast(LimitCptList.rank, Integer).asc(),
            LimitCptList.up_nums.desc(),
            LimitCptList.ts_code.asc(),
        )
        .limit(5)
    ).all()
    return [
        {
            "sector_code": row.ts_code,
            "sector_name": row.name,
            "limit_up_count": int(row.up_nums or 0),
            "rank": row.rank,
            "up_stat": row.up_stat,
            "cons_nums": int(row.cons_nums or 0),
        }
        for row in rows
    ]


def _load_effective_members(db_session, *, trade_date: date, sector_code: str) -> set[str]:
    member_rows = db_session.execute(
        select(ThsMember.con_code).where(
            ThsMember.ts_code == sector_code,
            ThsMember.in_date.is_not(None),
            ThsMember.in_date <= trade_date,
            (ThsMember.out_date.is_(None)) | (ThsMember.out_date >= trade_date),
        )
    ).all()
    return {row.con_code for row in member_rows}


def _load_limit_list_d_metrics(db_session, *, trade_date: date) -> dict[str, dict]:
    rows = db_session.execute(
        select(
            EquityLimitList.ts_code,
            EquityLimitList.name,
            EquityLimitList.limit_times,
            EquityLimitList.up_stat,
            EquityLimitList.pct_chg,
        ).where(
            EquityLimitList.trade_date == trade_date,
            EquityLimitList.limit_type == "U",
        )
    ).all()
    metrics: dict[str, dict] = {}
    for row in rows:
        parsed = _parse_up_stat(row.up_stat)
        metrics[row.ts_code] = {
            "stock_name": row.name,
            "limit_times": int(row.limit_times or 0),
            "up_stat": row.up_stat,
            "up_stat_n": parsed.n if parsed else 0,
            "up_stat_t": parsed.t if parsed else 0,
            "up_stat_ratio": parsed.ratio if parsed else -1.0,
            "pct_chg": float(row.pct_chg) if row.pct_chg is not None else None,
        }
    return metrics


def _load_today_limit_up_codes(db_session, *, trade_date: date) -> set[str]:
    return set(
        db_session.scalars(
            select(LimitListThs.ts_code).where(
                LimitListThs.trade_date == trade_date,
                LimitListThs.limit_type == "涨停池",
            )
        ).all()
    )


def _load_price_change_map(db_session, *, trade_date: date) -> dict[str, dict]:
    rows = db_session.execute(
        select(
            EquityDailyBar.ts_code,
            EquityDailyBar.close,
            EquityDailyBar.pct_chg,
        ).where(EquityDailyBar.trade_date == trade_date)
    ).all()
    return {
        row.ts_code: {
            "latest_price": float(row.close) if row.close is not None else None,
            "change_pct": float(row.pct_chg) if row.pct_chg is not None else None,
        }
        for row in rows
    }


def _build_sector_leaders(
    db_session,
    *,
    trade_date: date,
    sector_code: str,
    top_n: int = 3,
) -> list[dict]:
    members = _load_effective_members(db_session, trade_date=trade_date, sector_code=sector_code)
    if not members:
        return []

    today_limit_up_codes = _load_today_limit_up_codes(db_session, trade_date=trade_date)
    metrics_map = _load_limit_list_d_metrics(db_session, trade_date=trade_date)
    price_map = _load_price_change_map(db_session, trade_date=trade_date)

    def _row_for(code: str, *, is_fallback: bool) -> dict:
        metrics = metrics_map.get(code, {})
        prices = price_map.get(code, {})
        return {
            "stock_code": code,
            "stock_name": metrics.get("stock_name"),
            "limit_times": int(metrics.get("limit_times", 0)),
            "up_stat": metrics.get("up_stat"),
            "up_stat_n": int(metrics.get("up_stat_n", 0)),
            "up_stat_t": int(metrics.get("up_stat_t", 0)),
            "up_stat_ratio": float(metrics.get("up_stat_ratio", -1.0)),
            "pct_chg": prices.get("change_pct"),
            "latest_price": prices.get("latest_price"),
            "is_fallback": is_fallback,
        }

    def _sort_key(item: dict) -> tuple:
        pct = item["pct_chg"]
        pct_sort = pct if pct is not None else float("-inf")
        return (
            -item["limit_times"],
            -item["up_stat_n"],
            -item["up_stat_ratio"],
            -pct_sort,
            item["stock_code"],
        )

    strict_codes = members & today_limit_up_codes
    fallback_codes = members - strict_codes

    strict_rows = sorted((_row_for(code, is_fallback=False) for code in strict_codes), key=_sort_key)
    fallback_rows = sorted((_row_for(code, is_fallback=True) for code in fallback_codes), key=_sort_key)

    merged = strict_rows + fallback_rows
    return merged[:top_n]


def test_limit_up_hybrid_data_chain_tdd(db_session) -> None:
    """
    TDD 探针测试（非 mock）：
    - 先验证数据链路与口径可行性；
    - 再把通过的口径迁移进正式 API/query。
    """

    _ensure_limit_up_tables(db_session)

    trade_date = date(2026, 4, 28)

    db_session.add_all(
        [
            LimitCptList(
                ts_code="885001.TI",
                trade_date=trade_date,
                name="机器人",
                days=8,
                up_stat="9天7板",
                cons_nums=12,
                up_nums=12,
                pct_chg=Decimal("3.2100"),
                rank="1",
            ),
            LimitCptList(
                ts_code="885002.TI",
                trade_date=trade_date,
                name="固态电池",
                days=5,
                up_stat="7天5板",
                cons_nums=9,
                up_nums=9,
                pct_chg=Decimal("2.1100"),
                rank="2",
            ),
        ]
    )

    db_session.add_all(
        [
            ThsMember(
                ts_code="885001.TI",
                con_code="000001.SZ",
                con_name="龙头一号",
                in_date=date(2025, 1, 1),
                out_date=None,
                is_new="Y",
            ),
            ThsMember(
                ts_code="885001.TI",
                con_code="000002.SZ",
                con_name="龙头二号",
                in_date=date(2025, 1, 1),
                out_date=None,
                is_new="Y",
            ),
            ThsMember(
                ts_code="885001.TI",
                con_code="000006.SZ",
                con_name="回退补齐股",
                in_date=date(2025, 1, 1),
                out_date=None,
                is_new="Y",
            ),
            ThsMember(
                ts_code="885001.TI",
                con_code="000007.SZ",
                con_name="过期成分股",
                in_date=date(2025, 1, 1),
                out_date=date(2026, 4, 1),
                is_new="N",
            ),
            ThsMember(
                ts_code="885002.TI",
                con_code="000003.SZ",
                con_name="电池一号",
                in_date=date(2025, 1, 1),
                out_date=None,
                is_new="Y",
            ),
            ThsMember(
                ts_code="885002.TI",
                con_code="000004.SZ",
                con_name="电池二号",
                in_date=date(2025, 1, 1),
                out_date=None,
                is_new="Y",
            ),
        ]
    )

    db_session.add_all(
        [
            LimitListThs(
                trade_date=trade_date,
                ts_code="000001.SZ",
                query_limit_type="涨停池",
                query_market="HS",
                name="龙头一号",
                price=Decimal("18.6600"),
                pct_chg=Decimal("10.0100"),
                open_num=0,
                limit_type="涨停池",
                first_lu_time="09:32:10",
                last_lu_time="14:55:01",
                first_ld_time=None,
                last_ld_time=None,
                limit_amount=Decimal("580000000.0000"),
            ),
            LimitListThs(
                trade_date=trade_date,
                ts_code="000002.SZ",
                query_limit_type="涨停池",
                query_market="HS",
                name="龙头二号",
                price=Decimal("11.2400"),
                pct_chg=Decimal("10.0000"),
                open_num=2,
                limit_type="涨停池",
                first_lu_time="09:42:10",
                last_lu_time="14:10:25",
                first_ld_time=None,
                last_ld_time=None,
                limit_amount=Decimal("210000000.0000"),
            ),
            LimitListThs(
                trade_date=trade_date,
                ts_code="000003.SZ",
                query_limit_type="涨停池",
                query_market="HS",
                name="电池一号",
                price=Decimal("23.5800"),
                pct_chg=Decimal("9.9900"),
                open_num=1,
                limit_type="涨停池",
                first_lu_time="10:01:11",
                last_lu_time="14:50:00",
                first_ld_time=None,
                last_ld_time=None,
                limit_amount=Decimal("398000000.0000"),
            ),
            LimitListThs(
                trade_date=trade_date,
                ts_code="000004.SZ",
                query_limit_type="炸板池",
                query_market="HS",
                name="电池二号",
                price=Decimal("15.1100"),
                pct_chg=Decimal("7.8800"),
                open_num=5,
                limit_type="炸板池",
                first_lu_time="09:35:00",
                last_lu_time="11:20:00",
                first_ld_time=None,
                last_ld_time="14:57:30",
                limit_amount=Decimal("120000000.0000"),
            ),
            LimitListThs(
                trade_date=trade_date,
                ts_code="000005.SZ",
                query_limit_type="跌停池",
                query_market="HS",
                name="弱势一号",
                price=Decimal("6.8800"),
                pct_chg=Decimal("-9.9500"),
                open_num=0,
                limit_type="跌停池",
                first_lu_time=None,
                last_lu_time="14:30:00",
                first_ld_time="09:36:21",
                last_ld_time="14:58:01",
                limit_amount=Decimal("98000000.0000"),
            ),
        ]
    )

    db_session.add_all(
        [
            EquityStockSt(
                ts_code="000003.SZ",
                trade_date=trade_date,
                type="ST",
                name="电池一号",
                type_name="ST",
            ),
            EquityStockSt(
                ts_code="000005.SZ",
                trade_date=trade_date,
                type="ST",
                name="弱势一号",
                type_name="ST",
            ),
        ]
    )

    db_session.add_all(
        [
            EquityLimitList(
                ts_code="000001.SZ",
                trade_date=trade_date,
                limit_type="U",
                name="龙头一号",
                pct_chg=Decimal("10.0100"),
                open_times=0,
                up_stat="4/5",
                limit_times=4,
            ),
            EquityLimitList(
                ts_code="000002.SZ",
                trade_date=trade_date,
                limit_type="U",
                name="龙头二号",
                pct_chg=Decimal("10.0000"),
                open_times=2,
                up_stat="3/10",
                limit_times=2,
            ),
            EquityLimitList(
                ts_code="000003.SZ",
                trade_date=trade_date,
                limit_type="U",
                name="电池一号",
                pct_chg=Decimal("9.9900"),
                open_times=1,
                up_stat="6/8",
                limit_times=3,
            ),
            EquityLimitList(
                ts_code="000006.SZ",
                trade_date=trade_date,
                limit_type="U",
                name="回退补齐股",
                pct_chg=Decimal("3.2100"),
                open_times=0,
                up_stat="5/10",
                limit_times=3,
            ),
        ]
    )

    db_session.add_all(
        [
            EquityDailyBar(
                ts_code="000001.SZ",
                trade_date=trade_date,
                close=Decimal("18.6600"),
                pct_chg=Decimal("10.0100"),
                source="tushare",
            ),
            EquityDailyBar(
                ts_code="000002.SZ",
                trade_date=trade_date,
                close=Decimal("11.2400"),
                pct_chg=Decimal("10.0000"),
                source="tushare",
            ),
            EquityDailyBar(
                ts_code="000003.SZ",
                trade_date=trade_date,
                close=Decimal("23.5800"),
                pct_chg=Decimal("9.9900"),
                source="tushare",
            ),
            EquityDailyBar(
                ts_code="000006.SZ",
                trade_date=trade_date,
                close=Decimal("8.8800"),
                pct_chg=Decimal("3.2100"),
                source="tushare",
            ),
        ]
    )

    db_session.commit()

    stats = _build_limit_stats(db_session, trade_date=trade_date)
    sectors = _load_sector_top5(db_session, trade_date=trade_date)
    leaders_robot = _build_sector_leaders(
        db_session,
        trade_date=trade_date,
        sector_code="885001.TI",
        top_n=3,
    )
    leaders_battery = _build_sector_leaders(
        db_session,
        trade_date=trade_date,
        sector_code="885002.TI",
        top_n=3,
    )

    print("limit_up_stats=", stats)
    print("sector_top5=", sectors)
    print("leaders_robot=", leaders_robot)
    print("leaders_battery=", leaders_battery)

    assert stats == {
        "up_total": 3,
        "down_total": 1,
        "broken_total": 1,
        "up_st": 1,
        "down_st": 1,
        "broken_st": 0,
        "non_st_up": 2,
        "non_st_broken": 1,
        "sealing_rate_non_st": 2 / 3,
    }

    assert [item["sector_code"] for item in sectors] == ["885001.TI", "885002.TI"]
    assert sectors[0]["limit_up_count"] == 12
    assert sectors[1]["limit_up_count"] == 9

    # 机器人板块：当日严格候选只有 000001/000002，不足 3 时回退补齐 000006
    assert [item["stock_code"] for item in leaders_robot] == ["000001.SZ", "000002.SZ", "000006.SZ"]
    assert [item["is_fallback"] for item in leaders_robot] == [False, False, True]
    assert leaders_robot[0]["limit_times"] == 4
    assert leaders_robot[0]["up_stat_n"] == 4
    assert leaders_robot[2]["up_stat"] == "5/10"

    # 固态电池板块：仅 000003、000004 两个成分，且只有 000003 在当日涨停池；000004 fallback
    assert [item["stock_code"] for item in leaders_battery] == ["000003.SZ", "000004.SZ"]
    assert [item["is_fallback"] for item in leaders_battery] == [False, True]

