"""Index-detail routes select storage from the backend environment."""
from datetime import datetime
import importlib
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
import pytest

from src.app.auth.dependencies import require_quote_access
from src.app.dependencies import get_db_session
from src.app.exceptions import WebAppError, install_exception_handlers
from src.foundation.config.settings import Settings, get_settings
from src.foundation.config.local_minute_capability import LocalMinuteCapability, LocalMinuteCapabilityError

PATH = '/api/v1/wealth/market/index-detail/'
NAMES = ('xxm-signals', 'xxm-key-point-forecast', 'daily-waves', 'minute-xxm-signals')


def settings(**kwargs):
    return Settings(_env_file=None, WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED=False, **kwargs)


@pytest.mark.parametrize('value', [None, '', 'prod', 'test', 'unknown', 'DEV ', ' local', 'dev', 'local'])
def test_explicit_environment_and_once_only_registration(monkeypatch, value):
    assembly = importlib.import_module("src.app.api.v1.router")
    # None must genuinely omit the env even in configured_web_env's test process.
    monkeypatch.delenv('APP_ENV', raising=False)
    supplied = settings(**({} if value is None else {'APP_ENV': value}))
    calls = []
    def capability(actual):
        assert actual is supplied
        calls.append(actual)
        return LocalMinuteCapability(True, Path('/Volumes/datasource/data_lake'), None)
    monkeypatch.setattr(assembly, 'resolve_index_minute_capability', capability)
    target = APIRouter(prefix='/api/v1')
    assembly._include_local_xxm_routers(target, supplied)
    enabled = value is not None and value.strip().lower() in ('dev', 'local')
    paths = [r.path for r in target.routes]
    for name in NAMES:
        assert paths.count(PATH+name) == int(enabled)
    assert len(calls) == int(enabled)


def test_unconfigured_minutes_do_not_block_dg_daily_query_or_auth(monkeypatch, tmp_path):
    assembly = importlib.import_module("src.app.api.v1.router")
    supplied = settings(APP_ENV='local', GOLDENSHARE_LAKE_ROOT=str(tmp_path))
    monkeypatch.setattr(assembly, 'FORMAL_LAKE_ROOT', tmp_path)
    # DG Silver uses DATE and DOUBLE and publishes one factor file per trade date.
    calendar = tmp_path / 'silver/calendar/trade_calendar/full/part-000.parquet'
    calendar.parent.mkdir(parents=True)
    identity = tmp_path / 'silver/index_basic/full/part-000.parquet'
    identity.parent.mkdir(parents=True)
    today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
    with duckdb.connect(':memory:') as connection:
        connection.execute(f"""
            COPY (SELECT '000001.SH' AS ts_code, '上证指数' AS name,
                         'SSE' AS market, 'SSE' AS publisher, '综合' AS category)
            TO '{identity}' (FORMAT PARQUET)
        """)
        connection.execute(f"""
            COPY (
                WITH days AS (
                    SELECT CAST(day AS DATE) AS trade_date, dayofweek(day) BETWEEN 1 AND 5 AS is_open
                    FROM generate_series(DATE '2010-01-04', DATE '{today.isoformat()}', INTERVAL 1 DAY) AS t(day)
                )
                SELECT 'SSE' AS exchange, trade_date, is_open,
                       max(trade_date) FILTER (WHERE is_open) OVER (
                           ORDER BY trade_date ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                       ) AS pretrade_date
                FROM days
            ) TO '{calendar}' (FORMAT PARQUET)
        """)
        for day, close in (('2020-01-06', 100.0), ('2020-01-07', 101.0), ('2020-01-08', 102.0)):
            part = tmp_path / f'silver/index/index_factor_pro/trade_date={day}/part-000.parquet'
            part.parent.mkdir(parents=True)
            connection.execute(f"""
                COPY (
                    SELECT '000001.SH' AS ts_code, DATE '{day}' AS trade_date,
                           {close - 0.5}::DOUBLE AS open, {close + 1}::DOUBLE AS high,
                           {close - 1}::DOUBLE AS low, {close}::DOUBLE AS close,
                           {close - 1}::DOUBLE AS pre_close, 1.0::DOUBLE AS change,
                           1.0::DOUBLE AS pct_change, 200.0::DOUBLE AS vol, 2000.0::DOUBLE AS amount,
                           100.0::DOUBLE AS ma_bfq_5, 100.0::DOUBLE AS ma_bfq_10,
                           100.0::DOUBLE AS ma_bfq_20, 100.0::DOUBLE AS ma_bfq_30,
                           100.0::DOUBLE AS ma_bfq_60, 100.0::DOUBLE AS ma_bfq_90,
                           100.0::DOUBLE AS ma_bfq_250, 104.0::DOUBLE AS boll_upper_bfq,
                           100.0::DOUBLE AS boll_mid_bfq, 96.0::DOUBLE AS boll_lower_bfq,
                           1.0::DOUBLE AS macd_dif_bfq, 0.5::DOUBLE AS macd_dea_bfq,
                           1.0::DOUBLE AS macd_bfq, 50.0::DOUBLE AS kdj_k_bfq,
                           50.0::DOUBLE AS kdj_d_bfq, 50.0::DOUBLE AS kdj_bfq
                ) TO '{part}' (FORMAT PARQUET)
            """)
    app = FastAPI(); install_exception_handlers(app)
    daily_lake = assembly._resolve_index_daily_lake(supplied)
    target = APIRouter(prefix='/api/v1')
    target.include_router(assembly.wealth_market_index_detail.build_router(daily_lake=daily_lake))
    assembly._include_local_xxm_routers(target, supplied, daily_lake=daily_lake)
    app.include_router(target)
    app.dependency_overrides[get_db_session] = lambda: None
    import src.app.auth.dependencies as auth
    from types import SimpleNamespace
    monkeypatch.setattr(auth, 'get_web_settings', lambda: SimpleNamespace(quote_api_auth_required=True))
    with TestClient(app) as client:
        assert client.get(PATH+'xxm-signals?tsCode=000001.SH').status_code == 401
        app.dependency_overrides[require_quote_access] = lambda: None
        result = client.get(PATH+'xxm-signals?tsCode=000001.SH&endDate=2020-01-08&limit=8')
        assert result.status_code == 200
        assert [point['close'] for point in result.json()['points']] == [100.0, 101.0, 102.0]
        chart = client.get(PATH+'kline?tsCode=000001.SH&endDate=2020-01-08&limit=501')
        assert chart.status_code == 200
        assert [bar['close'] for bar in chart.json()['bars']] == [100.0, 101.0, 102.0]
        day_forecast = client.get(PATH+'xxm-key-point-forecast?tsCode=000001.SH&period=day&asOf=2020-01-08')
        assert day_forecast.status_code == 200
        assert day_forecast.json()['computedThrough'] == '2020-01-08'
        assert client.get(PATH+'minute-xxm-signals?tsCode=000001.SH&freq=60').status_code == 404
        forecast = client.get(PATH+'xxm-key-point-forecast?tsCode=000001.SH&period=m60')
        assert forecast.status_code == 404 and forecast.json()['code'] == 'XXMF_NOT_SUPPORTED'
        def denied(): raise WebAppError(status_code=403, code='FORBIDDEN', message='denied')
        app.dependency_overrides[require_quote_access] = denied
        assert client.get(PATH+'xxm-signals?tsCode=000001.SH').status_code == 403


def test_invalid_enabled_root_is_not_hidden(monkeypatch):
    assembly = importlib.import_module("src.app.api.v1.router")
    def invalid(s): raise LocalMinuteCapabilityError(code='SM_LOCAL_LAKE_NOT_CONFIGURED', message='invalid')
    monkeypatch.setattr(assembly, 'resolve_index_minute_capability', invalid)
    with pytest.raises(LocalMinuteCapabilityError):
        assembly._include_local_xxm_routers(APIRouter(), settings(APP_ENV='dev'))


def test_production_full_api_aggregation_has_no_r4_routes_or_source_calls(monkeypatch):
    import src.foundation.config.settings as config
    v1 = importlib.import_module("src.app.api.v1.router")
    api = importlib.import_module("src.app.api.router")
    original = config.get_settings
    # Full /api -> /v1 includes; no lifespan or production IO.
    try:
        monkeypatch.setattr(config, 'get_settings', lambda: settings(APP_ENV='prod'))
        importlib.reload(v1); importlib.reload(api)
        assert v1._index_daily_lake is None
        app = FastAPI(); app.include_router(api.router)
        def forbidden(): raise AssertionError('production r4 reached database')
        app.dependency_overrides[get_db_session] = forbidden
        app.dependency_overrides[require_quote_access] = forbidden
        with TestClient(app) as client:
            from src.biz.services.wealth.market.index_detail.index_detail_universe import IndexDetailUniverseService
            codes = IndexDetailUniverseService().load_universe().ordered_codes
            assert len(codes) == 10 and '899050.BJ' in codes
            for code in codes:
                for period in ('day','m30','m60','m90','m120'):
                    params = {'tsCode':code,'debug':'1'}
                    if period == 'day':
                        signals = 'xxm-signals'
                        params['period'] = 'day'
                    else:
                        signals = 'minute-xxm-signals'
                        params['freq'] = period[1:]
                    assert client.get(PATH+signals,params=params).status_code == 404
                    assert client.get(PATH+'xxm-key-point-forecast',params={
                        'tsCode':code,'period':period,'debug':'1'}).status_code == 404
            assert client.get(PATH+'daily-waves?tsCode=000001.SH&debug=1').status_code == 404
            schema = client.get('/openapi.json').json()
            assert all(PATH+name not in schema['paths'] for name in NAMES)
            assert PATH+'kline' in schema['paths']
    finally:
        monkeypatch.setattr(config, 'get_settings', original)
        importlib.reload(v1); importlib.reload(api)


def test_existing_file_priority_and_missing_default_do_not_enable(monkeypatch, tmp_path):
    from src.app.api.v1.router import _xxm_local_environment_enabled
    env = tmp_path/'config.env'; env.write_text('APP_ENV=prod\n')
    monkeypatch.setenv('GOLDENSHARE_ENV_FILE', str(env)); monkeypatch.setenv('APP_ENV', 'local')
    get_settings.cache_clear()
    try:
        assert not _xxm_local_environment_enabled(get_settings())
        env.write_text('APP_ENV=local\n'); get_settings.cache_clear()
        assert _xxm_local_environment_enabled(get_settings())
        env.write_text(''); monkeypatch.delenv('APP_ENV'); get_settings.cache_clear()
        supplied = get_settings()
        assert supplied.app_env == 'dev' and not _xxm_local_environment_enabled(supplied)
    finally: get_settings.cache_clear()


def test_existing_kline_debug_contract_is_preserved(app_client, db_session):
    # Real ordinary producer/ORM fixture; r4 assembly must not change its query contract.
    from tests.web.test_wealth_index_detail_api import _seed_full_data
    _seed_full_data(db_session)
    params = {'tsCode':'000001.SH','endDate':'2026-08-10','limit':'501'}
    for debug in (None,'0','1'):
        response = app_client.get(PATH+'kline',params={**params,**({'debug':debug} if debug is not None else {})})
        assert response.status_code == 200
        assert [bar['tradeDate'] for bar in response.json()['bars']] == ['2026-08-07','2026-08-10']
        assert response.json()['bars'][-1]['close'] == 105.0
    for extra in ('debug=2','debug=0&debug=1'):
        response = app_client.get(PATH+'kline?tsCode=000001.SH&'+extra)
        assert response.status_code == 400 and response.json()['code'] == 'ID_REQUEST_INVALID'
