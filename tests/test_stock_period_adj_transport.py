"""Real loopback HTTP -> bounded child -> Decimal/source contract.
The network is replaced by a task-owned HTTP fixture; no platform request is made.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import multiprocessing
import threading
import time
from decimal import Decimal
import pytest
from src.foundation.clients.bounded_tushare_call import call_bounded, BoundedTushareError
from src.foundation.ingestion.run_errors import IngestionCanceledError


@pytest.fixture
def period_http():
    # Keep the real fixture's numeric JSON lexemes. No binary float serializer.
    raw=Path('tests/fixtures/stock_period_adj_month_202002.json').read_text()
    import json
    sample=json.loads(raw,parse_float=Decimal)
    fields=sample['provenance']['fields']
    def lexeme(value):
        return str(value) if isinstance(value,(int,Decimal)) else json.dumps(value)
    full='{"code":0,"msg":"","data":{"fields":'+json.dumps(fields)+',"items":['+','.join(
        '['+','.join(lexeme(row[key]) for key in fields)+']' for row in sample['rows'])+']}}'
    class Handler(BaseHTTPRequestHandler):
        hits=0
        def log_message(self,*args): pass
        def do_POST(self):
            Handler.hits+=1
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(302 if self.path=='/redirect' else 200)
            if self.path=='/redirect': self.send_header('Location','/formal')
            self.end_headers()
            try:
                if self.path=='/slow':
                    for _ in range(200): self.wfile.write(b' '); self.wfile.flush(); time.sleep(.05)
                elif self.path=='/readiness':
                    self.wfile.write(b'{"code":0,"msg":"","data":{"fields":["ts_code","trade_date","end_date"],"items":[["000001.SZ","20261130","20261113"]]}}')
                elif self.path=='/malformed': self.wfile.write(b'not-json')
                else: self.wfile.write(full.encode())
            except (BrokenPipeError,ConnectionResetError): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    yield f'http://127.0.0.1:{server.server_port}',Handler
    server.shutdown();server.server_close();thread.join()


def call(url,**kwargs):
    return call_bounded(base_url=url,payload={'api_name':'stk_week_month_adj','token':'test-placeholder','params':{'freq':'month'}},
        maximum=8*1024*1024,timeout=kwargs.pop('timeout',20),check=kwargs.pop('check',lambda:None),tick=lambda:None,
        response_contract=kwargs.pop('response_contract','stock_period_adj/v1'),**kwargs)


def test_decimal_and_three_field_contract_through_real_transport(period_http):
    url,_=period_http
    kind,rows=call(url+'/formal')
    assert kind=='rows' and len(rows)==2
    assert rows[0]['close_qfq']==Decimal('11.14') and rows[1]['close_qfq']==Decimal('12.01')
    assert isinstance(rows[0]['open_hfq'],Decimal)
    kind,rows=call(url+'/readiness',response_contract='stock_period_adj_readiness/v1')
    assert kind=='rows' and set(rows[0])=={'ts_code','trade_date','end_date'}
    assert call(url+'/readiness')[:2]==('bounded_error','stock_period_adj.source_schema_invalid')


def test_transport_no_redirect_retry_and_malformed_is_not_empty_success(period_http):
    url,handler=period_http
    assert call(url+'/redirect')[:2]==('bounded_error','source_http_error')
    assert call(url+'/malformed')[:2]==('bounded_error','stock_period_adj.source_schema_invalid')
    assert handler.hits==2


def test_real_deadline_and_cancel_clean_child_without_retry(period_http):
    url,handler=period_http
    baseline={p.pid for p in multiprocessing.active_children()}
    with pytest.raises(BoundedTushareError,match='总期限'): call(url+'/slow',timeout=1)
    started=time.monotonic()
    def cancel():
        if time.monotonic()-started>.5: raise IngestionCanceledError('deliberate transport cancel')
    with pytest.raises(IngestionCanceledError): call(url+'/slow',check=cancel)
    assert handler.hits==2 and {p.pid for p in multiprocessing.active_children()}==baseline
