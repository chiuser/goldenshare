"""One HTTP attempt with bounded wire bytes and a terminable total deadline."""
import multiprocessing
import time
import json
from decimal import Decimal
import queue
import threading
import math
import re
import requests
from requests.adapters import HTTPAdapter
from src.foundation.schemas import TushareEnvelope
from src.foundation.datasets.stock_weekly_adj_contracts import WeeklyAdjContractError, validate_weekly_response


def safe_diagnostics(details):
    """Project finite diagnostic facts; never stringify arbitrary exception/payload objects."""
    details = details if isinstance(details, dict) else {}
    result = {}
    for key in ('exception_type', 'api_name', 'dataset_key'):
        value = details.get(key)
        if isinstance(value, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*', value[:96]):
            result[key] = value[:96]
    causes = details.get('cause_types')
    if isinstance(causes, (list, tuple)):
        result['cause_types'] = [name[:96] for name in causes[:4]
            if isinstance(name, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*', name[:96])]
    stage = details.get('failure_stage')
    if stage in ('request', 'response_body', 'decode', 'validate', 'ipc_wait', 'ipc_receive'):
        result['failure_stage'] = stage
    for key in ('http_status', 'elapsed_ms', 'connect_timeout_seconds', 'read_timeout_seconds',
                'total_timeout_seconds', 'worker_exit_code', 'page_number', 'offset', 'attempt_number'):
        value = details.get(key)
        if value is None and key in details:
            result[key] = None
        elif type(value) in (int, float) and abs(value) <= 2**63 - 1 and math.isfinite(value):
            result[key] = value
    params = details.get('request_params')
    if isinstance(params, dict):
        selected = {}
        for key in ('trade_date', 'ann_date', 'start_date', 'end_date', 'ts_code', 'freq', 'limit', 'offset'):
            value = params.get(key)
            if key in ('limit', 'offset'):
                if type(value) is int and 0 <= value <= 2**63 - 1:
                    selected[key] = value
            elif isinstance(value, str):
                pattern = (r'\d{8}|\d{4}-\d{2}-\d{2}' if key.endswith('date') else
                           r'[A-Za-z0-9]+\.[A-Za-z]+' if key == 'ts_code' else r'[A-Za-z]+')
                if len(value) <= 96 and re.fullmatch(pattern, value):
                    selected[key] = value
        result['request_params'] = selected
    # Fixed field/count/string bounds above normally keep this well below 8 KiB.
    while len(json.dumps(result, ensure_ascii=True).encode()) > 8192:
        result.pop(next(reversed(result)))
    return result


def request_diagnostics(details, *, api_name, params, **context):
    return safe_diagnostics({**details, **context, 'api_name': api_name, 'request_params': params})


def _failure_details(exc, *, stage, started, timeout, status=None):
    causes, seen = [], {id(exc)}
    cause = exc.__cause__ or exc.__context__
    while cause is not None and id(cause) not in seen and len(causes) < 4:
        seen.add(id(cause))
        causes.append(type(cause).__name__)
        cause = cause.__cause__ or cause.__context__
    return safe_diagnostics({
        'exception_type': type(exc).__name__, 'cause_types': causes, 'failure_stage': stage,
        'http_status': status, 'elapsed_ms': max(0, int((time.monotonic() - started) * 1000)),
        'connect_timeout_seconds': min(5, timeout), 'read_timeout_seconds': min(5, timeout),
        'total_timeout_seconds': timeout,
    })


def source_failure_message(details):
    details = safe_diagnostics(details)
    kinds = {details.get('exception_type'), *details.get('cause_types', [])}
    if kinds & {'ConnectTimeout', 'ConnectTimeoutError'}:
        return 'Tushare连接超时'
    if kinds & {'ReadTimeout', 'ReadTimeoutError'}:
        return ('读取Tushare响应超时' if details.get('failure_stage') == 'response_body'
                else '等待Tushare响应超时')
    if 'HTTPError' in kinds and details.get('http_status') is not None:
        return f"Tushare返回HTTP {details['http_status']}"
    name = details.get('exception_type')
    return f'源调用异常（{name}）' if name else 'Tushare源单次传输失败'


class BoundedTushareError(RuntimeError):
    def __init__(self, code, message, details=None):
        self.code = code
        self.details = safe_diagnostics(details)
        super().__init__(message)


def _attempt(send, base_url, payload, maximum, timeout, response_contract=None):
    prefix = 'weekly_adj' if response_contract == 'stock_weekly_adj/v1' else 'anns_d'
    started, stage, status = time.monotonic(), 'request', None
    try:
        with requests.Session() as session:
            # Exactly one real attempt: neither adapter retries nor redirects are permitted.
            session.mount('http://', HTTPAdapter(max_retries=0))
            session.mount('https://', HTTPAdapter(max_retries=0))
            with session.post(base_url, json=payload, stream=True, allow_redirects=False,
                              headers={'Accept-Encoding': 'identity'}, timeout=(min(5,timeout), min(5,timeout))) as response:
                status = response.status_code
                response.raise_for_status()
                if 300 <= response.status_code < 400:
                    raise BoundedTushareError('source_http_error', '源请求重定向不允许绕过预算')
                if response.headers.get('Content-Encoding', 'identity').lower() not in ('identity', ''):
                    raise BoundedTushareError(f'{prefix}.response_size_exceeded', '源响应压缩编码不符合有界读取合同')
                stage = 'response_body'
                data = bytearray()
                for block in response.iter_content(chunk_size=65536):
                    if len(data) + len(block) > maximum:
                        raise BoundedTushareError(f'{prefix}.response_size_exceeded', '源响应超过字节预算')
                    data.extend(block)
                try:
                    stage = 'decode'
                    # Weekly prices must reach normalization without a binary float round trip.
                    original = json.loads(data, parse_float=Decimal) if response_contract == 'stock_weekly_adj/v1' else json.loads(data)
                    stage = 'validate'
                    envelope = TushareEnvelope.model_validate(original)
                except (ValueError, TypeError):
                    if response_contract == 'stock_weekly_adj/v1':
                        raise BoundedTushareError('weekly_adj.source_payload_invalid', '周线响应JSON或数据结构无效') from None
                    raise
                if envelope.code != 0:
                    message = str(envelope.msg or '')
                    limited = '频率超限' in message or '次/分钟' in message
                    send.send(('rate_limit' if limited else 'api_error', envelope.code, message))
                else:
                    if response_contract == 'stock_weekly_adj/v1':
                        try:
                            rows = validate_weekly_response(original)
                        except WeeklyAdjContractError as exc:
                            raise BoundedTushareError(exc.code, str(exc)) from None
                        send.send(('rows', rows))
                        return
                    rows = []
                    if envelope.data is not None:
                        fields = envelope.data.fields
                        if len(fields) != len(set(fields)) or any(len(item) != len(fields) for item in envelope.data.items):
                            raise BoundedTushareError('anns_d.source_payload_invalid', '公告源字段重复或字段值数量不匹配，不能丢弃源值')
                        rows = [dict(zip(fields, item, strict=True)) for item in envelope.data.items]
                    send.send(('rows', rows))
    except BoundedTushareError as exc:
        send.send(('bounded_error', exc.code, str(exc), _failure_details(
            exc, stage=stage, started=started, timeout=timeout, status=status)))
    except Exception as exc:
        # Do not serialize token, response body, query or session exceptions across the boundary.
        send.send(('transport_error', _failure_details(
            exc, stage=stage, started=started, timeout=timeout, status=status)))
    finally:
        send.close()


def call_bounded(*, base_url, payload, maximum, timeout, check, tick, response_contract=None):
    if response_contract not in (None, 'stock_weekly_adj/v1'):
        raise BoundedTushareError('weekly_adj.delivery_contract_mismatch', '未知有界响应合同')
    prefix = 'weekly_adj' if response_contract == 'stock_weekly_adj/v1' else 'anns_d'
    ctx = multiprocessing.get_context('spawn')
    receive, send = ctx.Pipe(duplex=False)
    worker = ctx.Process(target=_attempt, args=(send,base_url,payload,maximum,timeout,response_contract), daemon=True)
    started_at = time.monotonic()
    deadline = started_at + timeout
    check()
    results = queue.Queue(maxsize=1)
    def receive_result():
        try:
            results.put(receive.recv())
        except (EOFError, OSError) as exc:
            details = _failure_details(exc, stage='ipc_receive', started=started_at, timeout=timeout)
            # Read before cleanup; a supervisor's terminate/kill is not the original fault.
            details['worker_exit_code'] = worker.exitcode
            results.put(('bounded_error', 'source_connection_failed', '源调用进程未返回结果', details))
    started = False
    try:
        worker.start()
        started = True
        send.close()
        # Reading/unpickling a large result must not block cancellation/deadline checks.
        reader = threading.Thread(target=receive_result, daemon=True)
        reader.start()
        while True:
            check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BoundedTushareError(f'{prefix}.source_deadline_exceeded', '源调用超过总期限',
                    _failure_details(TimeoutError(), stage='ipc_wait', started=started_at, timeout=timeout))
            try:
                result = results.get(timeout=min(remaining,0.2))
            except queue.Empty:
                tick()
                continue
            else:
                if time.monotonic() > deadline:
                    raise BoundedTushareError(f'{prefix}.source_deadline_exceeded', '源响应解码超过总期限',
                        _failure_details(TimeoutError(), stage='ipc_receive', started=started_at, timeout=timeout))
                check()
                return result
    finally:
        send.close()
        if started and worker.is_alive():
            worker.terminate()
        if started:
            worker.join(timeout=1)
            if worker.is_alive():
                worker.kill()
                worker.join(timeout=1)
        receive.close()
