"""Real loopback HTTP verifies reading limits, deadlines and process cleanup."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing
import threading
import time
import pytest
from src.foundation.clients.bounded_tushare_call import call_bounded, BoundedTushareError

@pytest.fixture
def server():
    class Handler(BaseHTTPRequestHandler):
        hits=0
        def log_message(self,*args):pass
        def do_POST(self):
            Handler.hits+=1
            self.rfile.read(int(self.headers.get('Content-Length','0')))
            if self.path == '/disconnect':
                self.connection.close()
                return
            if self.path == '/header-timeout':
                time.sleep(5.5)
            status = int(self.path.rsplit('/', 1)[1]) if self.path.startswith('/status/') else 200
            self.send_response(302 if self.path=='/redirect' else status)
            if self.path=='/redirect':self.send_header('Location','/ok')
            self.end_headers()
            try:
                if self.path == '/body-timeout':
                    time.sleep(5.5)
                    self.wfile.write(b'{}')
                elif self.path == '/invalid-json':
                    self.wfile.write(b'not-json')
                elif self.path=='/slow':
                    for _ in range(100):self.wfile.write(b' ');self.wfile.flush();time.sleep(.05)
                elif self.path=='/large':self.wfile.write(b'x'*200000)
                elif self.path.startswith('/weekly-'):
                    from src.foundation.datasets.stock_weekly_adj_contracts import SOURCE_FIELDS
                    data={'fields':list(SOURCE_FIELDS),'items':[]}
                    if self.path=='/weekly-missing':data=None
                    if self.path=='/weekly-short-fields':data['fields']=list(SOURCE_FIELDS[:-1])
                    if self.path=='/weekly-duplicate-fields':data['fields']=[SOURCE_FIELDS[0]]*21
                    if self.path=='/weekly-short-row':data['items']=[['000001.SZ']]
                    if self.path=='/weekly-decimal':
                        data['items']=[['000001.SZ','20260605','20261009','week',*([1.234567]*17)]]
                    self.wfile.write(json.dumps({'code':0,'msg':'','data':data}).encode())
                elif self.path in ('/extra-values','/missing-values','/duplicate-fields'):
                    fields = ['title','title'] if self.path=='/duplicate-fields' else ['title']
                    items = [['a','b']] if self.path!='/missing-values' else [[]]
                    self.wfile.write(json.dumps({'code':0,'msg':'','data':{'fields':fields,'items':items}}).encode())
                elif self.path=='/near-cap':
                    body=json.dumps({'code':0,'msg':'','data':{'fields':['title'],'items':[['x'*32740] for _ in range(2000)]}}).encode()
                    self.wfile.write(body)
                else:self.wfile.write(json.dumps({'code':0,'msg':'','data':{'fields':['title'],'items':[['公告']]}}).encode())
            except (BrokenPipeError,ConnectionResetError):pass
    srv=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
    yield f'http://127.0.0.1:{srv.server_port}',Handler
    srv.shutdown();srv.server_close();t.join()


def invoke(url,**kw):
    return call_bounded(base_url=url,payload={'api_name':'anns_d','token':'test-placeholder','params':{}},maximum=65536,timeout=3,check=lambda:None,tick=lambda:None,**kw)


def test_real_attempt_has_no_redirect_or_hidden_retry(server):
    url,handler=server
    assert invoke(url+'/ok')==('rows',[{'title':'公告'}])
    result=invoke(url+'/redirect')
    assert result[0:2]==('bounded_error','source_http_error') and handler.hits==2


def test_wire_size_stops_before_json_decode(server):
    url,handler=server
    assert invoke(url+'/large')[0:2]==('bounded_error','anns_d.response_size_exceeded')
    assert handler.hits==1


def test_continuous_slow_response_stops_at_total_deadline(server):
    url,_=server
    baseline={p.pid for p in multiprocessing.active_children()}
    started=time.monotonic()
    with pytest.raises(BoundedTushareError,match='总期限'):
        call_bounded(base_url=url+'/slow',payload={},maximum=65536,timeout=1,
            check=lambda:None,tick=lambda:None)
    assert time.monotonic()-started<2.5
    assert {p.pid for p in multiprocessing.active_children()}==baseline


def test_cancel_during_response_terminates_attempt(server):
    url,_=server
    start=time.monotonic()
    class Canceled(Exception):pass
    def check():
        if time.monotonic()-start>.7:raise Canceled()
    with pytest.raises(Canceled):call_bounded(base_url=url+'/slow',payload={},maximum=65536,
        timeout=10,check=check,tick=lambda:None)
    assert time.monotonic()-start<2.5


def test_near_cap_decode_is_bounded_and_measured(server):
    import resource
    from pathlib import Path
    url,_=server
    started=time.monotonic()
    result=call_bounded(base_url=url+'/near-cap',payload={},maximum=67108864,timeout=25,
        check=lambda:None,tick=lambda:None)
    assert result[0]=='rows' and len(result[1])==2000
    elapsed=time.monotonic()-started
    assert elapsed<25
    evidence={'decoded_rows':2000,'title_characters_per_row':32740,'elapsed_seconds':round(elapsed,3),
        'test_parent_peak_rss_native':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'worker_peak_rss_native':resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
        'note':'near 64 MiB loopback JSON, test parent also hosts HTTP server; measured on macOS, native RSS bytes'}
    Path('/private/tmp/anns-p2-transport-performance.json').write_text(json.dumps(evidence,indent=2))


@pytest.mark.parametrize('path',['extra-values','missing-values','duplicate-fields'])
def test_source_fields_cannot_silently_drop_values(server,path):
    url,_=server
    assert invoke(url+'/'+path)[0:2]==('bounded_error','anns_d.source_payload_invalid')


@pytest.mark.parametrize('path', ['empty','missing','short-fields','duplicate-fields','short-row'])
def test_weekly_response_contract_in_real_worker(server,path):
    url,_=server
    result=invoke(url+'/weekly-'+path,response_contract='stock_weekly_adj/v1')
    if path=='empty':
        assert result==('rows',[])
    else:
        assert result[:2]==('bounded_error','weekly_adj.source_payload_invalid')


def test_weekly_contract_cannot_be_bound_to_month_or_unknown_source(mocker):
    from src.foundation.clients.tushare_client import TushareHttpClient
    from src.foundation.datasets.stock_weekly_adj_contracts import SOURCE_FIELDS
    client=TushareHttpClient(token='test-placeholder',base_url='http://invalid.local')
    worker=mocker.patch('src.foundation.clients.bounded_tushare_call.call_bounded')
    for api,freq in [('stk_week_month_adj','month'),('anns_d','week')]:
        with pytest.raises(BoundedTushareError,match='只能绑定'):
            client.call_bounded(api_name=api,params={'freq':freq},fields=SOURCE_FIELDS,
                maximum=65536,timeout=3,check=lambda:None,tick=lambda:None,
                before_request=lambda:None,response_contract='stock_weekly_adj/v1')
    worker.assert_not_called()
    client.session.close()


def test_weekly_wire_decimals_keep_source_precision_before_normalization(server):
    from decimal import Decimal
    from src.foundation.datasets.stock_weekly_adj_contracts import canonical_source_rows, WeeklyAdjExecutionPolicy, WeeklyAdjContractError
    url,_=server
    result=invoke(url+'/weekly-decimal',response_contract='stock_weekly_adj/v1')
    assert result[0]=='rows' and result[1][0]['open']==Decimal('1.234567')
    assert isinstance(result[1][0]['open'],Decimal)
    with pytest.raises(WeeklyAdjContractError,match='数据库精度'):
        canonical_source_rows(result[1],WeeklyAdjExecutionPolicy())


@pytest.mark.parametrize('status', [401, 503])
def test_real_http_error_preserves_status_without_retry(server, status):
    url, handler = server
    result = invoke(url + f'/status/{status}')
    assert result[0] == 'transport_error'
    assert result[1]['exception_type'] == 'HTTPError'
    assert result[1]['http_status'] == status
    assert result[1]['failure_stage'] == 'request'
    assert result[1]['total_timeout_seconds'] == 3
    assert result[1]['connect_timeout_seconds'] == result[1]['read_timeout_seconds'] == 3
    assert result[1]['elapsed_ms'] >= 0 and handler.hits == 1


@pytest.mark.parametrize('path, stage, message', [
    ('header-timeout', 'request', '等待Tushare响应超时'),
    ('body-timeout', 'response_body', '读取Tushare响应超时'),
])
def test_real_read_timeout_preserves_wrapped_cause_and_phase(server, path, stage, message):
    from src.foundation.clients.bounded_tushare_call import source_failure_message
    url, handler = server
    result = call_bounded(base_url=url + '/' + path, payload={}, maximum=65536, timeout=8,
        check=lambda: None, tick=lambda: None)
    assert result[0] == 'transport_error' and handler.hits == 1
    details = result[1]
    assert details['failure_stage'] == stage and details['read_timeout_seconds'] == 5
    assert details['total_timeout_seconds'] == 8
    assert {'ReadTimeout', 'ReadTimeoutError'} & {details['exception_type'], *details['cause_types']}
    assert source_failure_message(details) == message


def test_real_disconnect_and_decode_failure_are_distinct(server):
    url, handler = server
    disconnected = invoke(url + '/disconnect')
    decoded = invoke(url + '/invalid-json')
    assert disconnected[0] == decoded[0] == 'transport_error'
    assert disconnected[1]['exception_type'] == 'ConnectionError'
    assert disconnected[1]['failure_stage'] == 'request'
    assert disconnected[1]['http_status'] is None
    assert decoded[1]['exception_type'] == 'JSONDecodeError'
    assert decoded[1]['failure_stage'] == 'decode' and decoded[1]['http_status'] == 200
    assert handler.hits == 2


def _exit_without_result(send, *args):
    import os
    os._exit(17)


def test_worker_exit_is_reported_as_ipc_failure_before_supervisor_cleanup(monkeypatch):
    monkeypatch.setattr('src.foundation.clients.bounded_tushare_call._attempt', _exit_without_result)
    baseline = {p.pid for p in multiprocessing.active_children()}
    result = invoke('http://unused.invalid')
    assert result[:3] == ('bounded_error', 'source_connection_failed', '源调用进程未返回结果')
    assert result[3]['exception_type'] == 'EOFError'
    assert result[3]['failure_stage'] == 'ipc_receive'
    assert result[3]['worker_exit_code'] in (None, 17)
    assert {p.pid for p in multiprocessing.active_children()} == baseline


def test_parent_deadline_records_only_observable_ipc_phase(server):
    url, _ = server
    with pytest.raises(BoundedTushareError) as error:
        call_bounded(base_url=url + '/slow', payload={}, maximum=65536, timeout=1,
            check=lambda: None, tick=lambda: None)
    assert error.value.code == 'anns_d.source_deadline_exceeded'
    assert error.value.details['failure_stage'] == 'ipc_wait'
    assert error.value.details['total_timeout_seconds'] == 1
    assert error.value.details['elapsed_ms'] >= 1000


@pytest.mark.parametrize('kind', ['connect', 'unexpected'])
def test_attempt_projects_types_without_exception_text_or_credentials(mocker, kind):
    import requests
    from src.foundation.clients.bounded_tushare_call import _attempt, source_failure_message
    secret = 'credential-in-url-or-body'
    exc = requests.exceptions.ConnectTimeout(secret) if kind == 'connect' else TypeError(secret * 10000)
    session = mocker.MagicMock()
    session.__enter__.return_value = session
    session.post.side_effect = exc
    mocker.patch('src.foundation.clients.bounded_tushare_call.requests.Session', return_value=session)
    sender = mocker.Mock()
    _attempt(sender, 'https://user:credential-in-url-or-body@example.invalid',
        {'token': secret}, 65536, 20)
    packet = sender.send.call_args.args[0]
    assert packet[0] == 'transport_error'
    assert secret not in json.dumps(packet)
    assert packet[1]['exception_type'] == type(exc).__name__
    assert source_failure_message(packet[1]) == ('Tushare连接超时' if kind == 'connect' else '源调用异常（TypeError）')
    assert session.post.call_args.kwargs['timeout'] == (5, 5)
    assert session.post.call_args.kwargs['allow_redirects'] is False
    assert all(call.args[1].max_retries.total == 0 for call in session.mount.call_args_list)


def test_diagnostics_reject_objects_secrets_and_unbounded_cause_chains():
    from src.foundation.clients.bounded_tushare_call import safe_diagnostics, _failure_details
    class NeverStringify:
        def __str__(self):
            pytest.fail('diagnostics must not stringify arbitrary objects')
    exc = TypeError('secret')
    tail = exc
    for _ in range(10):
        tail.__cause__ = ValueError('secret')
        tail = tail.__cause__
    tail.__cause__ = exc
    details = _failure_details(exc, stage='decode', started=time.monotonic(), timeout=20)
    assert details['cause_types'] == ['ValueError'] * 4
    details.update(token='secret', response_body='secret', exception=NeverStringify(), url='secret',
        request_params={'token': 'secret', 'start_date': '20260101', 'end_date': '2026-01-02',
            'ts_code': 'https://user:secret@example.invalid', 'freq': 'week', 'offset': 0, 'limit': 6000},
        api_name='stk_week_month_adj', exception_type='X' * 10000, cause_types=['X' * 10000] * 10000,
        elapsed_ms=float('nan'), page_number=10**10000)
    safe = safe_diagnostics(details)
    encoded = json.dumps(safe)
    assert 'secret' not in encoded and len(encoded.encode()) <= 8192
    assert len(safe['cause_types']) == 4 and len(safe['exception_type']) == 96
    assert 'elapsed_ms' not in safe and 'page_number' not in safe
    assert safe['request_params'] == {'start_date': '20260101', 'end_date': '2026-01-02',
        'freq': 'week', 'limit': 6000, 'offset': 0}


def test_known_payload_failure_keeps_code_message_and_diagnostics(server):
    url, _ = server
    result = invoke(url + '/weekly-short-row', response_contract='stock_weekly_adj/v1')
    assert result[:2] == ('bounded_error', 'weekly_adj.source_payload_invalid')
    assert result[3]['failure_stage'] == 'validate' and result[3]['http_status'] == 200
