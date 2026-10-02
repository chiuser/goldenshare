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
            self.send_response(302 if self.path=='/redirect' else 200)
            if self.path=='/redirect':self.send_header('Location','/ok')
            self.end_headers()
            try:
                if self.path=='/slow':
                    for _ in range(100):self.wfile.write(b' ');self.wfile.flush();time.sleep(.05)
                elif self.path=='/large':self.wfile.write(b'x'*200000)
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
