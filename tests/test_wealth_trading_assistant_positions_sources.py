"""Bounded real source reads: no inferred calendar or mixed industry dates."""
from datetime import date, datetime, timezone

from sqlalchemy import insert
from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.trading_assistant.positions_cutoff import resolve_positions_cutoff
from src.biz.queries.wealth.market.trading_assistant.positions_industry import PositionsIndustryQuery
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.market_facts import MarketFactsReader
from src.foundation.models.core_serving.dc_index import DcIndex
from src.foundation.models.core_serving.dc_member import DcMember
from tests.wealth_trading_assistant_browser_fixture import seed, NOW
from tests.wealth_trading_assistant_fixture_support import fixed_fixture_clock
from tests.wealth_watchlist_postgres_support import isolated_postgres


def test_industry_requires_exact_date_type_and_level(tmp_path):
    with isolated_postgres(tmp_path) as database:
        seed(database)
        with database.begin() as connection:
            for board, day, level, kind in (
                ("UPPER", 11, "东财二级行业", "行业板块"),
                ("CONCEPT", 11, "东财三级行业", "概念板块"),
                ("FUTURE", 14, "东财三级行业", "行业板块"),
                ("MISMATCH", 10, "东财三级行业", "行业板块"),
                ("CONFLICT", 11, "东财三级行业", "行业板块"),
            ):
                connection.execute(insert(DcIndex), dict(ts_code=board, trade_date=date(2026, 9, day), name=board, level=level, idx_type=kind))
                connection.execute(insert(DcMember), dict(ts_code=board, trade_date=date(2026, 9, 14 if board == "FUTURE" else 11),
                    con_code="000101.SZ" if board == "CONFLICT" else "000001.SZ"))
        with Session(database) as session:
            result = PositionsIndustryQuery(TradingAssistantExecutionPolicyV1(page_rows=1)).read(session,
                codes=["000001.SZ", "000101.SZ", "000102.SZ"], trade_date=date(2026, 9, 11), deadline=Deadline.after_ms(5000))
            assert result["000001.SZ"].name is None and result["000001.SZ"].reason is None
            assert result["000101.SZ"].name is None and "多重归属" in result["000101.SZ"].reason
            assert result["000102.SZ"].name == "测试三级行业"


def test_cutoff_uses_real_calendar_and_stable_business_phase(tmp_path):
    with isolated_postgres(tmp_path) as database:
        seed(database)
        clock = [NOW]
        policy = TradingAssistantExecutionPolicyV1()
        with fixed_fixture_clock(database, clock), Session(database) as session:
            def read(day, hour, minute=0):
                clock[0] = datetime(2026, 9, day, hour, minute, tzinfo=timezone.utc)
                return resolve_positions_cutoff(session, market=MarketFactsReader(policy), deadline=Deadline.after_ms(5000))
            morning, noon = read(11, 2), read(11, 4)
            assert morning.through == noon.through
            assert morning.valuation_date == date(2026, 9, 10)
            closing = read(11, 7)
            assert closing.valuation_date == date(2026, 9, 11) and closing.through != morning.through
            weekend = read(12, 8)
            assert weekend.is_open is False and weekend.valuation_date == date(2026, 9, 11)
            assert weekend.through != closing.through
            missing = read(15, 8)
            assert missing.is_open is None and missing.valuation_date is None and missing.reason
