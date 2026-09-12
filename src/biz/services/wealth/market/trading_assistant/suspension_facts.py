"""Bounded read-only suspension evidence, PRD §7.6 (2026-09-12 decision).

The accepted factor/event checks are not a complete corporate-action engine.
No synthetic daily market rows are written or returned as same-day prices.
"""
import json

from sqlalchemy import text

from .market_facts import apply_sql_budget, facts_digest


def read_suspension_carries(session, codes, day, policy, deadline):
    """One stock page; SQL aggregates history without loading it into Python."""
    if not codes:
        return {}
    if len(codes) > policy.page_rows or len(set(codes)) != len(codes):
        raise ValueError("Expected a bounded unique stock page")
    apply_sql_budget(session, deadline, policy)
    rows = session.execute(text("""
        WITH prices AS MATERIALIZED (
          SELECT s.code, p.trade_date, p.close, p.source
          FROM unnest(CAST(:codes AS text[])) AS s(code)
          JOIN LATERAL (
            SELECT trade_date, close, source FROM core_serving.equity_daily_bar
            WHERE ts_code = s.code AND trade_date < :day
            ORDER BY trade_date DESC LIMIT 1
          ) p ON true
        ), events AS MATERIALIZED (
          SELECT d.ts_code, d.ex_date, d.pay_date, d.div_listdate
          FROM core_serving.equity_dividend d
          WHERE d.ts_code = ANY(CAST(:codes AS text[])) AND d.div_proc = '实施' AND (
            d.ex_date BETWEEN (SELECT min(trade_date) FROM prices) AND :day OR
            d.pay_date BETWEEN (SELECT min(trade_date) FROM prices) AND :day OR
            d.div_listdate BETWEEN (SELECT min(trade_date) FROM prices) AND :day)
        )
        SELECT p.code, p.trade_date AS price_date, p.close, p.source,
               c.calendar_count, c.open_count, c.factor_count, c.factor_min, c.factor_max,
               c.suspended_count,
               EXISTS (
                 SELECT 1 FROM events d
                 WHERE d.ts_code = p.code AND (
                   (d.ex_date > p.trade_date AND d.ex_date <= :day) OR
                   (d.pay_date > p.trade_date AND d.pay_date <= :day) OR
                   (d.div_listdate > p.trade_date AND d.div_listdate <= :day))
               ) AS has_event
        FROM prices p
        CROSS JOIN LATERAL (
          SELECT count(*) AS calendar_count,
                 count(*) FILTER (WHERE cal.is_open) AS open_count,
                 count(a.adj_factor) FILTER (WHERE cal.is_open) AS factor_count,
                 min(a.adj_factor) FILTER (WHERE cal.is_open) AS factor_min,
                 max(a.adj_factor) FILTER (WHERE cal.is_open) AS factor_max,
                 count(*) FILTER (WHERE cal.is_open AND cal.trade_date > p.trade_date AND
                   EXISTS (SELECT 1 FROM core_serving.equity_suspend_d sus
                           WHERE sus.ts_code = p.code AND sus.trade_date = cal.trade_date
                             AND sus.suspend_type = 'S' AND sus.suspend_timing IS NULL) AND
                   NOT EXISTS (SELECT 1 FROM core_serving.equity_suspend_d sus
                           WHERE sus.ts_code = p.code AND sus.trade_date = cal.trade_date
                             AND (sus.suspend_type IS DISTINCT FROM 'S' OR sus.suspend_timing IS NOT NULL))
                 ) AS suspended_count,
                 bool_or(cal.trade_date = p.trade_date AND cal.is_open) AS price_open,
                 bool_or(cal.trade_date = :day AND cal.is_open) AS target_open
          FROM core_serving.trade_calendar cal LEFT JOIN core.equity_adj_factor a
            ON a.ts_code = p.code AND a.trade_date = cal.trade_date
          WHERE cal.exchange = 'SSE' AND cal.trade_date BETWEEN p.trade_date AND :day
        ) c
        WHERE c.price_open AND c.target_open
        ORDER BY p.code
    """), {"codes": list(codes), "day": day}).mappings().all()
    deadline.remaining_ms()
    found = {}
    for row in rows:
        price, factor = row["close"], row["factor_min"]
        if (price is None or not price.is_finite() or price <= 0 or row["source"] != "tushare"
                or row["calendar_count"] != (day-row["price_date"]).days+1
                or row["open_count"] < 2 or row["factor_count"] != row["open_count"]
                or factor is None or not factor.is_finite() or factor <= 0
                or factor != row["factor_max"] or row["suspended_count"] != row["open_count"]-1
                or row["has_event"]):
            continue
        proof = dict(rule="TA_SUSPENSION_V1", tsCode=row["code"],
            priceDate=row["price_date"].isoformat(), valuationDate=day.isoformat(),
            calendarDays=row["calendar_count"], tradingDays=row["open_count"],
            factorDays=row["factor_count"], factor=format(factor, "f"),
            suspendedDays=row["suspended_count"], hasEffectiveDividend=False,
            sources=["core_serving.trade_calendar", "core.equity_adj_factor",
                     "core_serving.equity_suspend_d", "core_serving.equity_dividend"])
        evidence = json.dumps(proof, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        price_text = format(price, "f")
        found[row["code"]] = (row["price_date"], price_text, evidence,
            facts_digest(dict(evidence=proof, price=price_text, source="tushare")))
    return found
