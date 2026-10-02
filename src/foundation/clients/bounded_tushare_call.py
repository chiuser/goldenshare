"""One HTTP attempt with bounded wire bytes and a terminable total deadline."""
import multiprocessing
import time
import json
import queue
import threading
import requests
from requests.adapters import HTTPAdapter
from src.foundation.schemas import TushareEnvelope


class BoundedTushareError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _attempt(send, base_url, payload, maximum, timeout):
    try:
        with requests.Session() as session:
            # Exactly one real attempt: neither adapter retries nor redirects are permitted.
            session.mount('http://', HTTPAdapter(max_retries=0))
            session.mount('https://', HTTPAdapter(max_retries=0))
            with session.post(base_url, json=payload, stream=True, allow_redirects=False,
                              headers={'Accept-Encoding': 'identity'}, timeout=(min(5,timeout), min(5,timeout))) as response:
                response.raise_for_status()
                if 300 <= response.status_code < 400:
                    raise BoundedTushareError('source_http_error', '源请求重定向不允许绕过预算')
                if response.headers.get('Content-Encoding', 'identity').lower() not in ('identity', ''):
                    raise BoundedTushareError('anns_d.response_size_exceeded', '源响应压缩编码不符合有界读取合同')
                data = bytearray()
                for block in response.iter_content(chunk_size=65536):
                    if len(data) + len(block) > maximum:
                        raise BoundedTushareError('anns_d.response_size_exceeded', '公告源响应超过字节预算')
                    data.extend(block)
                envelope = TushareEnvelope.model_validate(json.loads(data))
                if envelope.code != 0:
                    message = str(envelope.msg or '')
                    limited = '频率超限' in message or '次/分钟' in message
                    send.send(('rate_limit' if limited else 'api_error', envelope.code, message))
                else:
                    rows = []
                    if envelope.data is not None:
                        fields = envelope.data.fields
                        if len(fields) != len(set(fields)) or any(len(item) != len(fields) for item in envelope.data.items):
                            raise BoundedTushareError('anns_d.source_payload_invalid', '公告源字段重复或字段值数量不匹配，不能丢弃源值')
                        rows = [dict(zip(fields, item, strict=True)) for item in envelope.data.items]
                    send.send(('rows', rows))
    except BoundedTushareError as exc:
        send.send(('bounded_error', exc.code, str(exc)))
    except Exception as exc:
        # Do not serialize token, response body, query or session exceptions across the boundary.
        send.send(('transport_error', type(exc).__name__))
    finally:
        send.close()


def call_bounded(*, base_url, payload, maximum, timeout, check, tick):
    ctx = multiprocessing.get_context('spawn')
    receive, send = ctx.Pipe(duplex=False)
    worker = ctx.Process(target=_attempt, args=(send,base_url,payload,maximum,timeout), daemon=True)
    deadline = time.monotonic() + timeout
    check()
    results = queue.Queue(maxsize=1)
    def receive_result():
        try:
            results.put(receive.recv())
        except (EOFError, OSError):
            results.put(('bounded_error', 'source_connection_failed', '公告单次源调用未返回结果'))
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
                raise BoundedTushareError('anns_d.source_deadline_exceeded', '公告源调用超过总期限')
            try:
                result = results.get(timeout=min(remaining,0.2))
            except queue.Empty:
                tick()
                continue
            else:
                if time.monotonic() > deadline:
                    raise BoundedTushareError('anns_d.source_deadline_exceeded', '公告响应解码超过总期限')
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
