from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.foundation.clients.tushare_client import (
    _API_RATE_LIMITS,
    _RateLimiter,
    _get_rate_limiter,
    _rate_limiters,
    TushareHttpClient,
    TushareApiError,
    TushareRateLimitError,
)
from src.foundation.ingestion.error_mapper import IngestionErrorMapper
from src.foundation.models.meta.realtime_runtime_config import RealtimeRuntimeConfigRecord
from src.foundation.realtime import clear_realtime_runtime_config_cache
from tests.realtime_runtime_config_helpers import seed_realtime_runtime_config


def _runtime_config_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS foundation")
        RealtimeRuntimeConfigRecord.__table__.create(connection)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def test_tushare_http_client_builds_session_with_post_retries() -> None:
    client = TushareHttpClient(token="token")

    https_adapter = client.session.adapters["https://"]
    retry = https_adapter.max_retries

    assert retry.total == 5
    assert retry.connect == 5
    assert retry.read == 5
    assert retry.other == 3
    assert retry.allowed_methods is None


def test_tushare_http_client_uses_session_post_with_timeout_tuple(mocker) -> None:
    client = TushareHttpClient(token="token")
    response = mocker.Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "code": 0,
        "msg": "ok",
        "data": {"fields": ["ts_code"], "items": [["000001.SZ"]]},
    }
    response.raw = SimpleNamespace(retries=SimpleNamespace(history=()))
    post = mocker.patch.object(client.session, "post", return_value=response)

    rows = client.call("daily", params={"ts_code": "000001.SZ"}, fields=["ts_code"])

    assert rows == [{"ts_code": "000001.SZ"}]
    post.assert_called_once_with(
        client.base_url,
        json={
            "api_name": "daily",
            "token": "token",
            "params": {"ts_code": "000001.SZ"},
            "fields": "ts_code",
        },
        timeout=(5, 30),
    )


def test_tushare_http_client_logs_and_reraises_request_exception(mocker) -> None:
    client = TushareHttpClient(token="token")
    mocker.patch.object(
        client.session,
        "post",
        side_effect=requests.exceptions.SSLError("boom"),
    )
    logger = mocker.patch.object(client, "logger")

    with pytest.raises(requests.exceptions.SSLError):
        client.call("daily", params={"ts_code": "000001.SZ", "trade_date": "20260324"})

    logger.warning.assert_called_once()


def test_tushare_http_client_logs_retry_success(mocker) -> None:
    client = TushareHttpClient(token="token")
    response = mocker.Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "code": 0,
        "msg": "ok",
        "data": {"fields": ["ts_code"], "items": [["000001.SZ"]]},
    }
    response.raw = SimpleNamespace(retries=SimpleNamespace(history=(object(), object())))
    mocker.patch.object(client.session, "post", return_value=response)
    logger = mocker.patch.object(client, "logger")

    client.call("daily", params={"ts_code": "000001.SZ"})

    logger.info.assert_called_once()


def test_tushare_index_daily_rate_limit_keeps_safety_margin() -> None:
    assert _API_RATE_LIMITS["index_daily"] == 420
    assert _API_RATE_LIMITS["index_daily"] < 500


def test_tushare_etf_mins_uses_documented_endpoint_limit() -> None:
    assert _API_RATE_LIMITS["etf_mins"] == 500


def test_tushare_realtime_rate_limits_use_runtime_config(monkeypatch) -> None:
    session = _runtime_config_session()
    seed_realtime_runtime_config(
        session,
        daily={"max_calls_per_minute": 11},
        minute={"max_calls_per_minute": 13},
        etf={"max_calls_per_minute": 17},
    )
    monkeypatch.setattr("src.db.SessionLocal", lambda: session)
    clear_realtime_runtime_config_cache()
    _rate_limiters.clear()

    assert _get_rate_limiter("rt_k").max_calls == 11
    assert _get_rate_limiter("rt_min").max_calls == 13
    assert _get_rate_limiter("rt_etf_k").max_calls == 17
    clear_realtime_runtime_config_cache()


def test_tushare_rate_limiter_initialization_is_shared_across_threads(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.foundation.realtime.runtime_config.get_realtime_tushare_max_calls_per_minute",
        lambda api_name: None,
    )
    _rate_limiters.clear()

    with ThreadPoolExecutor(max_workers=2) as executor:
        limiters = list(executor.map(lambda _index: _get_rate_limiter("stk_mins"), range(20)))

    assert len({id(limiter) for limiter in limiters}) == 1
    assert _rate_limiters["stk_mins"].max_calls == 500


def test_tushare_rate_limiter_spaces_calls_evenly(mocker) -> None:
    limiter = _RateLimiter(max_calls_per_minute=120)
    current_time = [100.0]
    sleeps: list[float] = []

    mocker.patch("src.foundation.clients.tushare_client.time.monotonic", side_effect=lambda: current_time[0])

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        current_time[0] += seconds

    mocker.patch("src.foundation.clients.tushare_client.time.sleep", side_effect=fake_sleep)

    limiter.acquire()
    limiter.acquire()

    assert sleeps == [pytest.approx(0.5)]


def test_tushare_http_client_raises_rate_limit_error_for_business_quota_response(mocker) -> None:
    client = TushareHttpClient(token="token")
    response = mocker.Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "code": -2002,
        "msg": "抱歉，您访问接口(index_daily)频率超限(500次/分钟)",
        "data": None,
    }
    response.raw = SimpleNamespace(retries=SimpleNamespace(history=()))
    mocker.patch.object(client.session, "post", return_value=response)

    with pytest.raises(TushareRateLimitError) as exc_info:
        client.call("index_daily", params={"ts_code": "000001.SH", "trade_date": "20260424"})

    assert exc_info.value.api_name == "index_daily"
    assert "频率超限" in str(exc_info.value)


def test_tushare_http_client_preserves_full_nonzero_source_response_json(mocker) -> None:
    client = TushareHttpClient(token="token")
    raw_response_json = {
        "code": 50101,
        "msg": "查询数据失败，请确认参数！可以反馈管理员协助您排查问题",
        "data": None,
        "provider_diagnostic": "x" * 40_000,
    }
    response = mocker.Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = raw_response_json
    response.raw = SimpleNamespace(retries=SimpleNamespace(history=()))
    mocker.patch.object(client.session, "post", return_value=response)

    with pytest.raises(TushareApiError) as exc_info:
        client.call("stk_mins", params={"ts_code": "000001.SZ", "freq": "5min"})

    assert exc_info.value.api_name == "stk_mins"
    assert exc_info.value.code == 50101
    assert exc_info.value.raw_response_json == raw_response_json


def test_ingestion_error_mapper_preserves_full_tushare_source_response_json() -> None:
    raw_response_json = {
        "code": 50101,
        "msg": "查询数据失败，请确认参数！可以反馈管理员协助您排查问题",
        "data": None,
        "provider_diagnostic": "x" * 40_000,
    }

    structured = IngestionErrorMapper().map_exception(
        exc=TushareApiError(
            api_name="stk_mins",
            message="查询数据失败，请确认参数！可以反馈管理员协助您排查问题",
            code=50101,
            raw_response_json=raw_response_json,
        ),
        phase="source_client",
        unit_id="stk_mins:000001.SZ:5min",
    )

    assert structured.details == {
        "api_name": "stk_mins",
        "source_code": 50101,
        "source_response_json": raw_response_json,
    }


@pytest.mark.parametrize('details, message', [
    ({'exception_type': 'ReadTimeout', 'failure_stage': 'request'}, '等待Tushare响应超时'),
    ({'exception_type': 'ConnectionError', 'cause_types': ['ReadTimeoutError'],
      'failure_stage': 'response_body'}, '读取Tushare响应超时'),
    ({'exception_type': 'ConnectTimeout'}, 'Tushare连接超时'),
    ({'exception_type': 'HTTPError', 'http_status': 503}, 'Tushare返回HTTP 503'),
    ({'exception_type': 'HTTPError', 'http_status': 401}, 'Tushare返回HTTP 401'),
    ({'exception_type': 'TypeError'}, '源调用异常（TypeError）'),
])
def test_bounded_client_preserves_transport_diagnostics_and_safe_log(mocker, details, message):
    from src.foundation.clients.bounded_tushare_call import BoundedTushareError
    mocker.patch('src.foundation.clients.tushare_client._get_rate_limiter')
    worker = mocker.patch('src.foundation.clients.bounded_tushare_call.call_bounded',
        return_value=('transport_error', details))
    client = TushareHttpClient(token='secret-token', base_url='https://secret:credential@example.invalid')
    logger = mocker.patch.object(client, 'logger')
    before = mocker.Mock()
    params = {'start_date': '20260101', 'end_date': '20260101', 'limit': 2000, 'offset': 0,
        'token': 'secret-token'}
    with pytest.raises(BoundedTushareError) as error:
        client.call_bounded(api_name='anns_d', params=params, fields=('ann_date',), maximum=65536,
            timeout=25, check=lambda: None, tick=lambda: None, before_request=before)
    assert error.value.code == 'source_connection_failed' and str(error.value) == message
    assert error.value.details == {**details, 'api_name': 'anns_d',
        'request_params': {k: v for k, v in params.items() if k != 'token'}}
    before.assert_called_once()
    worker.assert_called_once()
    logger.warning.assert_called_once()
    assert 'secret' not in str(logger.warning.call_args) and 'credential' not in str(logger.warning.call_args)
    client.session.close()


@pytest.mark.parametrize('from_parent', [False, True])
def test_bounded_client_keeps_named_errors_when_diagnostic_logging_fails(mocker, from_parent):
    from src.foundation.clients.bounded_tushare_call import BoundedTushareError
    details = {'exception_type': 'TimeoutError', 'failure_stage': 'ipc_wait', 'total_timeout_seconds': 20}
    code, message = 'weekly_adj.source_deadline_exceeded', '源调用超过总期限'
    mocker.patch('src.foundation.clients.tushare_client._get_rate_limiter')
    worker = mocker.patch('src.foundation.clients.bounded_tushare_call.call_bounded')
    if from_parent:
        worker.side_effect = BoundedTushareError(code, message, details)
    else:
        worker.return_value = ('bounded_error', code, message, details)
    from src.foundation.datasets.stock_weekly_adj_contracts import SOURCE_FIELDS
    client = TushareHttpClient(token='secret-token')
    mocker.patch.object(client.logger, 'warning', side_effect=RuntimeError('log offline'))
    with pytest.raises(BoundedTushareError) as error:
        client.call_bounded(api_name='stk_week_month_adj', params={'freq': 'week', 'trade_date': '20190607'},
            fields=SOURCE_FIELDS, maximum=8388608, timeout=20, check=lambda: None,
            tick=lambda: None, before_request=lambda: None, response_contract='stock_weekly_adj/v1')
    assert error.value.code == code and str(error.value) == message
    assert error.value.details['failure_stage'] == 'ipc_wait'
    assert error.value.details['api_name'] == 'stk_week_month_adj'
    worker.assert_called_once()
    client.session.close()


@pytest.mark.parametrize('packet, expected', [
    (('rows', [{'ann_date': '20260101'}]), [{'ann_date': '20260101'}]),
    (('rate_limit', -2002, '频率超限'), TushareRateLimitError),
    (('api_error', 50101, '查询数据失败'), TushareApiError),
])
def test_bounded_success_and_api_errors_keep_existing_semantics(mocker, packet, expected):
    mocker.patch('src.foundation.clients.tushare_client._get_rate_limiter')
    mocker.patch('src.foundation.clients.bounded_tushare_call.call_bounded', return_value=packet)
    client = TushareHttpClient(token='test-placeholder')
    call = dict(api_name='anns_d', params={}, fields=('ann_date',), maximum=65536, timeout=25,
        check=lambda: None, tick=lambda: None, before_request=lambda: None)
    if isinstance(expected, list):
        assert client.call_bounded(**call) == expected
    else:
        with pytest.raises(expected) as error:
            client.call_bounded(**call)
        assert error.value.code == packet[1]
    client.session.close()
