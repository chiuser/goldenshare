"""Representative M3 multi-instance work plus real isolated ASGI reads/writes."""
import asyncio
import tracemalloc
from datetime import datetime, timedelta
from time import monotonic
from unittest.mock import Mock
from uuid import UUID, uuid4

from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy import event, select, func, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from tests.test_wealth_trading_assistant_calculation_work import database, migrated, publication_db, interruptions_db, cutoff_db, DAY
from tests.test_wealth_trading_assistant_runtime_acceptance import fixed_clock, OBSERVED
from tests import test_wealth_trading_assistant_account_acceptance as acceptance
from src.app.runtime.trading_assistant_lifespan import trading_assistant_lifespan
from src.app.runtime.trading_assistant_execution_resource import TradingAssistantExecutionResource
from src.biz.api.wealth.market.trading_assistant.router import create_trading_assistant_router
from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, Recalculation
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from src.biz.models.wealth.trading_assistant.publication import PublicationDay, AccountSnapshot
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar


def test_long_history_backlog_two_resources_and_concurrent_http(cutoff_db, monkeypatch):
    monkeypatch.setattr(acceptance, "NOW", OBSERVED)
    start, stock = DAY-timedelta(days=28), "601088.SH"
    identities = []
    for positions in ([dict(clientRowId="long", tsCode=stock, openedOn=start.isoformat(),
            quantity=100, availableQuantity=100, costPrice="10.00")], [], []):
        _, _, saved = acceptance.create(cutoff_db, acceptance.create_command(positions))
        identities.append(UUID(saved.receipt["result"]["account"]["accountId"]))
    long_account, bulk_account, short_account = identities
    count, prefix = 5001, str(uuid4())
    with cutoff_db.begin() as conn:
        EquityDailyBar.__table__.create(conn, checkfirst=True)
        previous_open = start-timedelta(days=1)
        for offset in range(29):
            day = start+timedelta(days=offset)
            conn.execute(insert(TradeCalendar).values(exchange="SSE", trade_date=day,
                is_open=day.weekday() < 5, pretrade_date=previous_open).on_conflict_do_nothing())
            if day.weekday() < 5:
                conn.execute(insert(EquityDailyBar).values(ts_code=stock, trade_date=day,
                    close="11.00", source="tushare"))
                previous_open = day
        params = dict(account=bulk_account, prefix=prefix, count=count, day=DAY)
        conn.execute(text("""INSERT INTO app.wealth_ta_ledger (ledger_id,account_id,kind,created_at)
            SELECT md5(:prefix || n::text)::uuid,:account,'CASH_FLOW',now()
            FROM generate_series(1,:count) n"""), params)
        conn.execute(text("""INSERT INTO app.wealth_ta_ledger_revision
            (ledger_id,account_id,kind,revision,accepted_fact_version,occurred_on,accepted_at,status,direction,cash_amount,net_cash_change)
            SELECT md5(:prefix || n::text)::uuid,:account,'CASH_FLOW',1,n+1,:day,now(),'ACTIVE','IN',1,1
            FROM generate_series(1,:count) n"""), params)
        conn.execute(text("UPDATE app.wealth_ta_account SET fact_version=:version WHERE account_id=:account"),
            dict(account=bulk_account, version=count+1))
        conn.execute(text("ANALYZE app.wealth_ta_ledger_revision"))

    # Measure existing resource budgets, not new user-facing capacity limits.
    waits, units, sql_times = [], [], []
    failures = []
    from src.biz.services.wealth.market.trading_assistant.calculation_failures import classify_calculation_failure
    def capture_failure(error):
        import traceback
        failures.append("".join(traceback.format_exception(error)))
        return classify_calculation_failure(error)
    for module in ("calculation_work", "generation_execution"):
        monkeypatch.setattr(f"src.biz.services.wealth.market.trading_assistant.{module}.classify_calculation_failure",
            capture_failure)
    class MeasuredResource(TradingAssistantExecutionResource):
        async def _execute(self, kind):
            self.started = monotonic()
            return await super()._execute(kind)
        def _unit(self, sessions, kind):
            waits.append(monotonic()-self.started)
            began = monotonic()
            try:
                return super()._unit(sessions, kind)
            finally:
                units.append(monotonic()-began)
    monkeypatch.setattr("src.app.runtime.trading_assistant_lifespan.TradingAssistantExecutionResource", MeasuredResource)
    clock_start = monotonic()
    class AppClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return (OBSERVED+timedelta(seconds=monotonic()-clock_start)).astimezone(tz)
    monkeypatch.setattr("src.app.runtime.trading_assistant_lifespan.datetime", AppClock)
    def clock(conn, cursor, statement, parameters, context, executemany):
        context._ta_capacity_started = monotonic()
        return fixed_clock(OBSERVED+timedelta(seconds=monotonic()-clock_start))(
            conn, cursor, statement, parameters, context, executemany)
    def sql_done(conn, cursor, statement, parameters, context, executemany):
        sql_times.append(monotonic()-context._ta_capacity_started)
    event.listen(Engine, "before_cursor_execute", clock, retval=True)
    event.listen(Engine, "after_cursor_execute", sql_done)
    async def run():
        apps = [FastAPI(), FastAPI()]
        latencies, published_at, last_progress, longest_gap = [], {}, {}, 0.0
        started = monotonic()
        tracemalloc.start()
        try:
            async with trading_assistant_lifespan(apps[0], database_url=cutoff_db.url, logger=Mock()), \
                    trading_assistant_lifespan(apps[1], database_url=cutoff_db.url, logger=Mock()):
                for app in apps:
                    def dependency_for(application):
                        def dependency():
                            return application.state.trading_assistant
                        return dependency
                    app.include_router(create_trading_assistant_router(auth_dependency=lambda: 1,
                        dependencies_dependency=dependency_for(app)))
                root = "/wealth/market/trading-assistant"
                async with AsyncClient(transport=ASGITransport(app=apps[0]), base_url="http://isolated") as client:
                    command = dict(requestId=str(uuid4()), attemptId=str(uuid4()), direction="IN",
                        occurredOn=DAY.isoformat(), amount="2.00")
                    saved = await client.post(root+f"/accounts/{short_account}/cash-flows", json=command)
                    assert saved.status_code in (200, 201), saved.text
                    async def read():
                        begin = monotonic()
                        response = await client.get(root+"/accounts")
                        latencies.append(monotonic()-begin)
                        assert response.status_code == 200, response.text
                    while monotonic()-started < 180:
                        await asyncio.gather(read(), read(), read())
                        with Session(cutoff_db) as session:
                            accounts = session.scalars(select(Account).where(Account.account_id.in_(identities))).all()
                            for account in accounts:
                                if account.published_generation_id is not None:
                                    published_at.setdefault(account.account_id, monotonic()-started)
                            generations = session.scalars(select(CalculationGeneration).where(
                                CalculationGeneration.account_id.in_(identities))).all()
                            for generation in generations:
                                assert generation.stage not in ("FAILED", "WAITING_DATA"), (
                                    generation.account_id, generation.stage, generation.reason, failures)
                                value = (generation.stage, generation.completed_trade_date_count)
                                before = last_progress.get(generation.account_id)
                                if before is None or before[0] != value:
                                    if before:
                                        longest_gap = max(longest_gap, monotonic()-before[1])
                                    last_progress[generation.account_id] = (value, monotonic())
                            pending = session.scalar(select(func.count()).select_from(Recalculation).where(
                                Recalculation.account_id.in_(identities)))
                            if not pending and len(published_at) == 3:
                                break
                        await asyncio.sleep(.02)
                    else:
                        with Session(cutoff_db) as session:
                            detail = [(str(r.account_id), r.target_version, r.next_attempt_at, r.executor_id)
                                for r in session.scalars(select(Recalculation))]
                        raise AssertionError(f"Representative backlog did not complete: {detail}")
                    replay = await client.post(root+f"/accounts/{short_account}/cash-flows", json=command)
                    assert replay.json() == saved.json()
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert published_at[short_account] < published_at[long_account]
        assert max(latencies) < 5 and max(units) < 2 and max(waits) < 2 and max(sql_times) < 1
        assert longest_gap < 30 and peak < 64*1024*1024
        p95 = sorted(latencies)[int((len(latencies)-1)*.95)]
        print(f"M3 backlog accounts=3 resources=2 days=29 cash_rows={count} "
            f"elapsed={monotonic()-started:.3f}s http_n={len(latencies)} p95={p95:.4f}s "
            f"http_max={max(latencies):.4f}s connect_max={max(waits):.4f}s "
            f"unit_max={max(units):.4f}s sql_max={max(sql_times):.4f}s "
            f"day_progress_gap_max={longest_gap:.4f}s python_peak_bytes={peak}")
    try:
        asyncio.run(run())
    finally:
        event.remove(Engine, "before_cursor_execute", clock)
        event.remove(Engine, "after_cursor_execute", sql_done)
    with Session(cutoff_db) as session:
        for identity, cash, days in ((long_account, 0, 21), (bulk_account, count, 1), (short_account, 2, 1)):
            account = session.get(Account, identity)
            rows = session.scalars(select(AccountSnapshot).join(PublicationDay,
                PublicationDay.day_result_id == AccountSnapshot.day_result_id).where(
                    PublicationDay.account_id == identity, PublicationDay.generation_id == account.published_generation_id)
                .order_by(PublicationDay.trade_date)).all()
            assert len(rows) == days and rows[-1].cash_amount == cash
            assert session.get(CalculationGeneration, account.published_generation_id).through_date == DAY
        pages = session.scalars(select(CalculationBatch).where(CalculationBatch.account_id == bulk_account,
            CalculationBatch.stage == "ACCOUNT_CASH")).all()
        assert len(pages) == 12 and sum(page.row_count for page in pages) == count
        assert max(page.row_count for page in pages) == 500
