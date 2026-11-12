"""Integration LLD literals and substitutes; never read/write historical reports.

Only indicator calculation, Control, and the PG-only resource boundary are
replaced. SQLite queries, DTOs, Admission, workers, encoding and sending are real.
These values test field mapping, not the numerical indicator algorithms.
"""
from contextlib import contextmanager
import json

from sqlalchemy.orm import sessionmaker

from tests.app.technical_indicators.test_admission import FakeControl, make_config
from src.app.dependencies import stock_daily_technical_indicators as wiring
from src.app.runtime.technical_indicators import execution
from src.app.runtime.technical_indicators.admission import AdmissionController
from src.app.runtime.technical_indicators.composition import TechnicalIndicatorRuntime
from src.foundation.config.settings import Settings
from goldenshare_technical_indicators.calculation.indicators import create_builtin_registry
from goldenshare_technical_indicators.contracts import (
    CalculationResult, CalculationStatistics, CalculationValues, OutputRange,
    PriceAdjustmentResult, RequestedRange, SeriesDescription, SourceResult,
)


def make_runtime(**changes):
    config = make_config(**changes)
    return TechnicalIndicatorRuntime(config, create_builtin_registry(), object(), AdmissionController(config))


@contextmanager
def controlled_controls(monkeypatch, record_property):
    created = []
    first = len(FakeControl.instances)

    def create(*, config, arrived_at=None, **kwargs):
        control = FakeControl(config=config, arrived_at=arrived_at, **kwargs)
        created.append(control)
        return control

    monkeypatch.setattr(execution, "ExecutionControl", create)
    try:
        yield create, created
    finally:
        record_property("stock_daily_step3_metrics", json.dumps({
            "fake_controls": len(created), "real_controls": 0,
            "real_calculate_calls": 0, "source_rows": 0, "indicator_sql_rows": 0,
        }))
        created.clear()
        del FakeControl.instances[first:]


def result_for(ts_code, days, overrides=None):
    days = tuple(days)
    overrides = overrides or {}
    definitions = (
        *((f"ma{n}", "ma", "1.0.0", (("period", n),), ("value",))
          for n in (5, 10, 20, 30, 60, 90, 250)),
        ("boll", "boll", "1.0.0", (("period", 20), ("multiplier", 2)), ("middle", "upper", "lower")),
        ("macd", "macd", "2.0.0", (("fast", 12), ("slow", 26), ("signal", 9)), ("dif", "dea", "hist")),
        ("kdj", "kdj", "2.0.0", (("window", 9), ("k_period", 3), ("d_period", 3)), ("k", "d", "j")),
    )
    calculations = tuple(CalculationValues(identity, kind, version, parameters, tuple(
        (name, tuple(overrides.get((identity, name), 10.0) for _ in days)) for name in fields
    )) for identity, kind, version, parameters, fields in definitions)
    return CalculationResult(
        "2.0.0", SeriesDescription("stock", ts_code, "day", "qfq", "Asia/Shanghai", "CNY", "share", "CNY"),
        RequestedRange(days[0] if days else None, days[-1] if days else None, None, len(days)),
        SourceResult("literal", "1", "none", None, None, None, None),
        PriceAdjustmentResult(None, None, None, None, False, "1"), days, None, calculations,
        OutputRange(days[0] if days else None, days[-1] if days else None, len(days)),
        CalculationStatistics(0, 0, 0, 0, 0, 0, 0), "",
    )


@contextmanager
def sqlite_session(factory, control):
    control.check_active()
    session = factory()
    try:
        control.check_active()
        yield session
        control.check_active()
    finally:
        session.close()


@contextmanager
def backend_for_client(client, monkeypatch, engine, record_property, *, overrides=None):
    """Build Admission on TestClient's loop, and a new Session in each worker."""
    import threading
    from src.biz.api.wealth.market.stock_detail_dependencies import get_stock_daily_kline_backend
    from src.biz.queries.wealth.market.stock_detail.stock_detail_query import StockDetailQuery
    from src.biz.queries.wealth.market.context.market_page_context_query import MarketPageContextQuery

    async def start():
        return make_runtime()

    with controlled_controls(monkeypatch, record_property) as (_, controls):
        rt = client.portal.call(start)
        factory = sessionmaker(bind=engine, autoflush=False)
        backend = wiring.StockDailyKlineAppBackend(
            rt, lambda: factory, settings=Settings(_env_file=None, APP_ENV="prod"),
        )
        calls, reads, other_rows = [], [], []
        original_query = StockDetailQuery.load_kline_rows
        original_security = StockDetailQuery.load_security
        original_context = MarketPageContextQuery.resolve_context

        def query(self, session, **kwargs):
            rows = original_query(self, session, **kwargs)
            reads.append(len(rows))
            return rows

        def security(self, session, **kwargs):
            result = original_security(self, session, **kwargs)
            other_rows.append(int(result is not None))
            return result

        def context(self, session, **kwargs):
            result = original_context(self, session, **kwargs)
            other_rows.append(1)
            return result

        def calculate(service, request):
            assert len(request.calculations) == 10
            assert threading.get_ident() != threading.main_thread().ident
            calls.append(request)
            days = tuple(day for day in available_days if request.start <= day <= request.end)
            return result_for(request.ts_code, days, overrides)

        # Available dates come from this test's temporary DB, not product calculation.
        from sqlalchemy import select
        from src.foundation.models.core.equity_factor_pro import EquityFactorPro
        with factory() as session:
            available_days = tuple(session.scalars(select(EquityFactorPro.trade_date)
                                                   .distinct().order_by(EquityFactorPro.trade_date)))
        monkeypatch.setattr(StockDetailQuery, "load_kline_rows", query)
        monkeypatch.setattr(StockDetailQuery, "load_security", security)
        monkeypatch.setattr(MarketPageContextQuery, "resolve_context", context)
        monkeypatch.setattr(wiring, "open_stock_daily_read_session", sqlite_session)
        monkeypatch.setattr(execution.TechnicalIndicatorService, "calculate", calculate)
        previous = client.app.dependency_overrides.get(get_stock_daily_kline_backend)
        client.app.dependency_overrides[get_stock_daily_kline_backend] = lambda: backend
        try:
            yield backend, calls, controls
        finally:
            client.portal.call(rt.aclose)
            assert not rt.admission.active_leases and not rt.admission.waiters
            if previous is None:
                client.app.dependency_overrides.pop(get_stock_daily_kline_backend, None)
            else:
                client.app.dependency_overrides[get_stock_daily_kline_backend] = previous
            record_property("stock_daily_sqlite_rows", sum(reads) + sum(other_rows) + len(available_days))
