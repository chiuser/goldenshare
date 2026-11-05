"""P4 bounded, read-only HTTP audit with the real TypeScript clients.

Only selected periods/modes; summaries stay in memory/stdout. No lifespan,
source warm-up, account writes, source replacement, results or recovery files.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import date, datetime
import hashlib
import json
import math
import os
import re
from pathlib import Path
import selectors
import shutil
import signal
import socket
import subprocess
import sys
from threading import Event, RLock, Thread, local
import time
from types import SimpleNamespace
from urllib.parse import parse_qs
from unittest.mock import patch
import uuid

from src.biz.services.wealth.market.index_detail_xxm.runtime import BUDGET

PERIODS = ('day', 'm60', 'm90', 'm120')
_REQUEST_ID = ContextVar('p4_request_id', default=None)
_LOAD_ID = ContextVar('p4_load_id', default=None)
_REQUEST_FIELDS = frozenset('''groupId requestId tabId sequence round endpointKind period debug requestedAsOf
startedMs finishedMs httpStatus bodyBytes httpSeconds clientSeconds computedThrough dataStatus responseRows
sourceInputId calendarInputId indicatorVersion prefixRows windowStart windowEnd computeSeconds publicDigest
forecastCacheRead forecastCacheReadCalls forecastCacheWrite forecastCacheWriteCalls loadIds errorCode terminal'''.split())
_LOAD_FIELDS = frozenset('''loadId flightKeyDigest period startedMs finishedMs terminal pairCalls barsCalls
indicatorCalls signatureChecks seriesCacheRead seriesCacheReadCalls'''.split())
_CLIENT_FIELDS = frozenset('''requestId httpSeconds clientSeconds terminal httpStatus bodyBytes
computedThrough responseRows windowStart windowEnd'''.split())


@dataclass(frozen=True)
class AuditGroupSpec:
    groupId: str
    tool: str
    scenario: str
    period: str
    mode: str
    requestedAsOf: str | None
    samples: int
    startedAt: float
    workDeadline: float
    deadline: float


@dataclass
class AuditApp:
    app: object
    baseUrl: str
    collector: 'AuditCollector'
    stopRequested: Event


class AuditGroupFailure(RuntimeError):
    def __init__(self, stage, *, error_type='RuntimeError', summary=None, client_records=()):
        super().__init__(f'Audit group failed: {stage}')
        self.stage, self.error_type, self.summary = stage, error_type, summary
        self.client_records = client_records


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False, default=lambda v: v.isoformat() if isinstance(v, (date, datetime)) else str(v)).encode()).hexdigest()


def _settings_identity(settings):
    return _digest(dict(app_env=settings.app_env, explicit='app_env' in settings.model_fields_set,
                        minutes=settings.wealth_local_lake_minute_api_enabled,
                        root=settings.goldenshare_lake_root, database=settings.database_url))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--periods', nargs='+', choices=PERIODS, required=True)
    parser.add_argument('--as-of')
    parser.add_argument('--mode', choices=('normal', 'debug', 'both'), default='normal')
    parser.add_argument('--samples', type=int, choices=(1, 20), default=1)
    args = parser.parse_args(argv)
    if len(set(args.periods)) != len(args.periods):
        parser.error('--periods must be unique')
    if args.as_of is not None:
        try:
            if date.fromisoformat(args.as_of).isoformat() != args.as_of:
                raise ValueError()
        except ValueError:
            parser.error('--as-of must be YYYY-MM-DD')
    return args


def planned_groups(args, tool):
    modes = ('normal', 'debug') if args.mode == 'both' else (args.mode,)
    return [(period, mode, scenario) for period in args.periods for mode in modes
            for scenario in (('forecast_series',) if tool == 'forecast' else
                             ('mixed_single', 'mixed_two') if args.samples == 1 else
                             ('kline_series',) if period == 'day' else ('kline_series', 'indicator_series'))]


def _new_group(args, tool, period, mode, scenario):
    started = time.monotonic()
    return AuditGroupSpec(uuid.uuid4().hex, tool, scenario, period, mode, args.as_of,
                          args.samples, started, started + 50, started + 60)


def _group_from_json(raw):
    if not isinstance(raw, dict) or set(raw) != set(AuditGroupSpec.__dataclass_fields__):
        raise ValueError('Invalid group fields')
    group = AuditGroupSpec(**raw)
    if (not isinstance(group.groupId, str) or len(group.groupId) != 32
            or any(c not in '0123456789abcdef' for c in group.groupId)
            or group.tool not in ('page', 'forecast') or group.period not in PERIODS
            or group.mode not in ('normal', 'debug') or type(group.samples) is not int or group.samples not in (1, 20)
            or group.scenario not in ('mixed_single', 'mixed_two', 'forecast_series', 'kline_series', 'indicator_series')
            or any(type(v) not in (int, float) or not math.isfinite(v)
                   for v in (group.startedAt, group.workDeadline, group.deadline))
            or group.workDeadline != group.startedAt + 50 or group.deadline != group.startedAt + 60):
        raise ValueError('Invalid group values')
    argv = ['--periods', group.period, '--mode', group.mode, '--samples', str(group.samples)]
    if group.requestedAsOf is not None:
        argv += ['--as-of', group.requestedAsOf]
    args = parse_args(argv)
    if (group.period, group.mode, group.scenario) not in planned_groups(args, group.tool):
        raise ValueError('Group does not match selected scenario')
    return group


class AuditCollector:
    def __init__(self, group):
        self.group = group
        self.lock = RLock()
        self.requests = {}
        self.loads = {}
        self.active = 0
        self.workers = 0
        self._entries = {}
        self._flights = {}
        self._pair_owners = {}

    def offset(self):
        return (time.monotonic() - self.group.startedAt) * 1000

    def request(self):
        identity = _REQUEST_ID.get()
        if identity not in self.requests:
            raise ValueError('Observation outside an active audit request')
        return self.requests[identity]

    def start(self, scope):
        from urllib.parse import parse_qs
        headers = [value.decode() for key, value in scope['headers'] if key.lower() == b'x-request-id']
        if len(headers) != 1:
            raise ValueError('Missing request identity')
        identity = headers[0]
        parts = identity.split(':')
        if len(parts) != 5 or parts[:2] != [self.group.groupId, self.group.scenario]:
            raise ValueError('Wrong group request identity')
        round_, tab, seq = parts[2:]
        if (not round_.isdigit() or not seq.isdigit() or str(int(round_)) != round_
                or str(int(seq)) != seq or not 1 <= int(round_) <= self.group.samples
                or int(seq) < 1 or tab not in ('1', '2')
                or (tab == '2' and self.group.scenario != 'mixed_two')):
            raise ValueError('Invalid round/tab/sequence')
        params = parse_qs(scope['query_string'].decode(), keep_blank_values=True)
        endpoint = scope['path'].rsplit('/', 1)[-1]
        kind = {'kline': 'kline', 'minutes': 'kline', 'minute-indicators': 'indicators',
                'nine-turn': 'nineTurn', 'minute-nine-turn': 'nineTurn',
                'xxm-signals': 'signals', 'minute-xxm-signals': 'signals',
                'xxm-key-point-forecast': 'forecast'}.get(endpoint)
        # The actual minute path is checked against the producer below as well.
        if kind is None or params.get('tsCode') != ['000001.SH']:
            raise ValueError('Unselected endpoint or object')
        period = params.get('period', ['day' if endpoint == 'nine-turn' else None])[0]
        if 'freq' in params:
            period = 'm' + params['freq'][0]
        elif kind == 'nineTurn' and period != 'day':
            period = 'm' + str(period)
        if period != self.group.period:
            raise ValueError('Unselected period')
        debug = params.get('debug', [None])[0]
        expected = '1' if kind in ('signals', 'forecast') and self.group.mode == 'debug' else None
        if debug != expected:
            raise ValueError('Unexpected transmitted debug')
        row = dict(groupId=self.group.groupId, requestId=identity, tabId=tab, sequence=int(seq), round=int(round_),
                   endpointKind=kind, period=period, debug=int(debug) if debug is not None else None,
                   requestedAsOf=params.get('asOf' if kind == 'forecast' else 'endDate', [None])[0],
                   startedMs=self.offset(), finishedMs=None, httpStatus=None, bodyBytes=0,
                   httpSeconds=None, clientSeconds=None, computedThrough=None, dataStatus=None, responseRows=None,
                   sourceInputId=None, calendarInputId=None, indicatorVersion=None, prefixRows=None,
                   windowStart=None, windowEnd=None, computeSeconds=None, publicDigest=None,
                   forecastCacheRead='not_called' if kind == 'forecast' else 'not_applicable', forecastCacheReadCalls=0,
                   forecastCacheWrite='not_called' if kind == 'forecast' else 'not_applicable', forecastCacheWriteCalls=0,
                   loadIds=[], errorCode=None, terminal=None)
        with self.lock:
            if identity in self.requests or any(r['tabId'] == tab and r['sequence'] == int(seq) for r in self.requests.values()):
                raise ValueError('Duplicate audit request')
            max_requests = expected_requests(self.group)
            if len(self.requests) >= max_requests:
                raise ValueError('Too many requests')
            self.requests[identity] = row
            self.active += 1
        return identity

    def projected(self, internal, public, kind):
        with self.lock:
            row = self.request()
            entry = self._entries.get(_REQUEST_ID.get())
            if entry is None:
                raise ValueError('Projection without actual source entry')
            if kind == 'signals':
                through = internal.source.computedThrough
                row.update(computedThrough=through, sourceInputId=internal.source.inputId,
                           indicatorVersion=internal.source.indicatorVersion, dataStatus=internal.dataStatus.status,
                           responseRows=internal.meta.count, windowStart=internal.meta.responseStart, windowEnd=internal.meta.responseEnd)
            else:
                through = internal.computedThrough
                row.update(computedThrough=through, sourceInputId=internal.sourceInputId,
                           calendarInputId=internal.calendarInputId, dataStatus=internal.dataStatus,
                           indicatorVersion=None if internal.period == 'day' else int(entry.calculator.source_identity.split('|')[-1]))
            count = bisect_right([b.time for b in entry.processed], through) if through else 0
            row['prefixRows'] = count
            if kind == 'forecast':
                row.update(windowStart=entry.processed[0].time if count else None, windowEnd=through)
            row['publicDigest'] = _digest(public.model_dump(mode='json', exclude={'debug'}))

    def metrics(self, cache):
        with self.lock, cache.lock:
            return dict(groupId=self.group.groupId, requests=[dict(self.requests[k]) for k in sorted(self.requests)],
                        loads=[dict(self.loads[k]) for k in sorted(self.loads)], activeRequests=self.active,
                        cacheBytes=sum(size for _, size in cache.entries.values()), cacheEntries=len(cache.entries),
                        cleanupStatus='pending')


def expected_requests(group):
    if group.scenario in ('mixed_single', 'mixed_two'):
        return (4 if group.period == 'day' else 5) * (2 if group.scenario == 'mixed_two' else 1)
    return group.samples


class _RequestMiddleware:
    def __init__(self, app, *, collector, stop):
        self.app, self.collector, self.stop = app, collector, stop

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['path'].startswith('/__audit__/'):
            return await self.app(scope, receive, send)
        if self.stop.is_set() or time.monotonic() >= self.collector.group.workDeadline:
            raise TimeoutError('Group work deadline')
        identity = self.collector.start(scope)
        token = _REQUEST_ID.set(identity)
        row = self.collector.requests[identity]
        async def observed(message):
            if message['type'] == 'http.response.start':
                row['httpStatus'] = message['status']
                message = {**message, 'headers': [(k,v) for k,v in message.get('headers', []) if k.lower() != b'x-request-id'] + [(b'x-request-id', identity.encode())]}
            elif message['type'] == 'http.response.body':
                body = message.get('body', b'')
                row['bodyBytes'] += len(body)
                if row['httpStatus'] >= 400 and len(body) <= 32768:
                    try: row['errorCode'] = json.loads(body).get('code')
                    except (ValueError, AttributeError): pass
                if not message.get('more_body', False):
                    row['finishedMs'] = self.collector.offset()
                    row['terminal'] = 'success' if row['httpStatus'] < 400 else 'error'
            await send(message)
        try:
            await self.app(scope, receive, observed)
        except BaseException:
            row['terminal'] = 'cancelled' if self.stop.is_set() else 'error'
            raise
        finally:
            with self.collector.lock:
                self.collector.active -= 1
                if row['terminal'] is None: row['terminal'] = 'error'
                if row['finishedMs'] is None: row['finishedMs'] = self.collector.offset()
            _REQUEST_ID.reset(token)


@contextmanager
def _observe(collector):
    """Observe originals exactly once. All patches are worker-local and reversed last."""
    from src.biz.queries.wealth.market.index_detail_xxm import query_service as q, forecast_query_service as fq
    from src.biz.services.wealth.market.index_detail_xxm import response_projection as projection
    from src.foundation.clients.local_lake.major_index_mins_reader import MajorIndexMinsLakeReader as Reader
    original_cache = q._CACHE
    cache = q.XxmCache()
    clocks = local()
    with ExitStack() as stack:
        stack.enter_context(patch.object(q, '_CACHE', cache))
        original_signal_build = q.IndexDetailXxmQueryService.build
        def signal_build(self, *a, **kw):
            with collector.lock: collector.workers += 1
            try: return original_signal_build(self, *a, **kw)
            finally:
                with collector.lock: collector.workers -= 1
        stack.enter_context(patch.object(q.IndexDetailXxmQueryService, 'build', signal_build))
        original_load_entry = q.IndexDetailXxmQueryService.load_entry
        @contextmanager
        def load_entry(self, *a, **kw):
            with original_load_entry(self, *a, **kw) as result:
                identity = _REQUEST_ID.get()
                if identity is not None:
                    with collector.lock: collector._entries[identity] = result[0]
                try: yield result
                finally:
                    with collector.lock: collector._entries.pop(identity, None)
        stack.enter_context(patch.object(q.IndexDetailXxmQueryService, 'load_entry', load_entry))
        for module, name, kind in ((projection, 'project_xxm_response', 'signals'), (fq, 'project_forecast_response', 'forecast')):
            original = getattr(module, name)
            def project(internal, *a, _original=original, _kind=kind, **kw):
                value = _original(internal, *a, **kw)
                if _REQUEST_ID.get() is not None: collector.projected(internal, value, _kind)
                return value
            stack.enter_context(patch.object(module, name, project))
        original_shared = cache.loads.load
        def shared(key, loader, remaining):
            with collector.lock:
                flight = collector._flights.setdefault(key, {'active': 0, 'objects': []})
                flight['active'] += 1
            def observed_loader():
                with collector.lock:
                    load_id = f'load-{len(collector.loads)+1}'
                    collector.loads[load_id] = dict(loadId=load_id, flightKeyDigest=_digest(key), period=key[2],
                        startedMs=collector.offset(), finishedMs=None, terminal=None, pairCalls=0, barsCalls=0,
                        indicatorCalls=0, signatureChecks=0, seriesCacheRead='not_called', seriesCacheReadCalls=0)
                token = _LOAD_ID.set(load_id)
                try:
                    value = loader()
                except BaseException as error:
                    with collector.lock:
                        flight['objects'].append((error, load_id))
                        collector.loads[load_id].update(terminal='error', finishedMs=collector.offset())
                    raise
                else:
                    with collector.lock:
                        flight['objects'].append((value, load_id))
                        collector.loads[load_id].update(terminal='success', finishedMs=collector.offset())
                    return value
                finally: _LOAD_ID.reset(token)
            def associate(value):
                with collector.lock:
                    matches = [load_id for obj, load_id in flight['objects'] if obj is value]
                    if len(matches) == 1 and _REQUEST_ID.get() is not None:
                        collector.request()['loadIds'].append(matches[0])
            try:
                value = original_shared(key, observed_loader, remaining)
                associate(value)
                return value
            except BaseException as error:
                associate(error)
                raise
            finally:
                with collector.lock:
                    flight['active'] -= 1
                    if not flight['active']:
                        del collector._flights[key]
        stack.enter_context(patch.object(cache.loads, 'load', shared))
        for name, field, calls in (('get', 'seriesCacheRead', 'seriesCacheReadCalls'),
                                  ('get_forecast', 'forecastCacheRead', 'forecastCacheReadCalls'),
                                  ('put_forecast', 'forecastCacheWrite', 'forecastCacheWriteCalls')):
            original = getattr(q.XxmCache, name)
            def observed(self, *a, _original=original, _field=field, _calls=calls, **kw):
                row = None
                if self is cache:
                    with collector.lock:
                        if _field == 'seriesCacheRead' and _LOAD_ID.get() in collector.loads:
                            row = collector.loads[_LOAD_ID.get()]
                        elif _field != 'seriesCacheRead' and _REQUEST_ID.get() in collector.requests:
                            row = collector.request()
                        if row is not None: row[_calls] += 1
                try: value = _original(self, *a, **kw)
                except BaseException:
                    if row is not None:
                        with collector.lock: row[_field] = 'error'
                    raise
                if row is not None:
                    with collector.lock: row[_field] = 'stored' if _field == 'forecastCacheWrite' else 'miss' if value is None else 'hit'
                return value
            stack.enter_context(patch.object(q.XxmCache, name, observed))
        original_pair = Reader.read_complete_history_pair
        def pair(self, request, **kwargs):
            load_id = _LOAD_ID.get()
            if load_id is None: return original_pair(self, request, **kwargs)
            key = (id(self), request.freq, request.start_date, request.end_date)
            with collector.lock:
                if key in collector._pair_owners: raise ValueError('Overlapping pair ownership')
                collector._pair_owners[key] = load_id
                collector.loads[load_id]['pairCalls'] += 1
            try: return original_pair(self, request, **kwargs)
            finally:
                with collector.lock: del collector._pair_owners[key]
        stack.enter_context(patch.object(Reader, 'read_complete_history_pair', pair))
        original_read, original_signature = Reader._read_complete_history, Reader.history_source_signature
        def read(self, request, **kwargs):
            key = (id(self), request.freq, request.start_date, request.end_date)
            with collector.lock:
                load_id = collector._pair_owners.get(key)
                if load_id is None: raise ValueError('History read without paired load owner')
                field = 'barsCalls' if kwargs['dataset'] == 'bars' else 'indicatorCalls'
                collector.loads[load_id][field] += 1
            return original_read(self, request, **kwargs)
        def signature(self, *a, **kw):
            if _LOAD_ID.get() is not None:
                with collector.lock: collector.loads[_LOAD_ID.get()]['signatureChecks'] += 1
            return original_signature(self, *a, **kw)
        stack.enter_context(patch.object(Reader, '_read_complete_history', read))
        stack.enter_context(patch.object(Reader, 'history_source_signature', signature))
        original_build, original_time = fq.IndexDetailXxmForecastQueryService.build, fq.time
        def clock():
            value = original_time.perf_counter()
            if getattr(clocks, 'building', False) and clocks.started is None:
                clocks.started = value
            return value
        stack.enter_context(patch.object(fq, 'time', SimpleNamespace(perf_counter=clock)))
        def build(self, *a, **kw):
            clocks.started = None; clocks.building = True
            with collector.lock: collector.workers += 1
            try: return original_build(self, *a, **kw)
            finally:
                duration = original_time.perf_counter() - clocks.started if clocks.started is not None else None
                if _REQUEST_ID.get() is not None:
                    with collector.lock: collector.request()['computeSeconds'] = duration
                clocks.building = False; clocks.started = None
                with collector.lock: collector.workers -= 1
        stack.enter_context(patch.object(fq.IndexDetailXxmForecastQueryService, 'build', build))
        yield cache
        # Only isolated_app may exit this context, after all real threads stop.
        if collector.active or collector.workers or collector._entries or collector._flights or collector._pair_owners:
            raise RuntimeError('Observation still active at cleanup')
    assert q._CACHE is original_cache


@contextmanager
def isolated_app(settings, *, group):
    """One disposable worker owns the App, source pool, patches and socket."""
    import uvicorn
    from fastapi import APIRouter, Depends, FastAPI
    from src.app.api.v1.router import (
        _include_local_xxm_routers,
        _resolve_index_daily_lake,
        _xxm_local_environment_enabled,
    )
    from src.app.auth.dependencies import require_quote_access
    from src.app.dependencies import get_db_session
    from src.app.exceptions import install_exception_handlers
    from src.biz.api.wealth.market import index_detail, index_detail_nine_turn
    from src.biz.queries.wealth.market.context.market_page_context_query import MarketPageContextQuery
    from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
    from src.biz.services.wealth.market.index_detail_xxm.forecast_spec import FORECAST_SPEC
    from sqlalchemy import text
    from src.db import get_engine, get_session_factory
    if not _xxm_local_environment_enabled(settings): raise ValueError('Explicit local environment required')
    collector, stop = AuditCollector(group), Event()
    stack = ExitStack()
    server = thread = sock = None
    try:
        cache = stack.enter_context(_observe(collector))
        app = FastAPI(); install_exception_handlers(app)
        def readonly_session():
            with get_session_factory()() as session:
                session.execute(text('SET TRANSACTION READ ONLY'))
                yield session
        app.dependency_overrides[get_db_session] = readonly_session
        target = APIRouter(prefix='/api/v1')
        daily_lake = _resolve_index_daily_lake(settings)
        _include_local_xxm_routers(target, settings, daily_lake=daily_lake)
        target.include_router(index_detail.build_router(daily_lake=daily_lake))
        target.include_router(index_detail_nine_turn.router)
        if group.period != 'day':
            from src.foundation.config.local_minute_capability import resolve_index_minute_capability, resolve_index_nine_turn_minute_capability
            if not resolve_index_minute_capability(settings).enabled or not resolve_index_nine_turn_minute_capability(settings).enabled:
                raise ValueError('Selected minute source not available')
            from src.biz.api.wealth.market import index_detail_minutes, index_detail_minute_nine_turn
            target.include_router(index_detail_minutes.router)
            target.include_router(index_detail_minute_nine_turn.router)
        app.include_router(target)
        from src.app.web.middleware.request_id import RequestIdMiddleware
        app.add_middleware(RequestIdMiddleware)
        app.add_middleware(_RequestMiddleware, collector=collector, stop=stop)
        @app.get('/__audit__/context')
        def context(_user=Depends(require_quote_access), session=Depends(readonly_session)):
            value = MarketPageContextQuery().resolve_context(session, market='CN_A', requested_trade_date=None)
            return dict(groupId=group.groupId, period=group.period, mode=group.mode, requestedAsOf=group.requestedAsOf,
                        businessDate=value.trade_date.isoformat(), generatedAt=value.generated_at.isoformat(),
                        algorithmVersion=MAIN_SPEC.algorithm_version, specHash=MAIN_SPEC.spec_hash,
                        forecastVersion=FORECAST_SPEC.forecast_version, forecastSpecHash=FORECAST_SPEC.spec_hash)
        @app.get('/__audit__/reset')
        def reset(_user=Depends(require_quote_access)):
            with collector.lock, cache.lock:
                if collector.active: raise ValueError('Cannot reset active group')
                cache.entries.clear(); collector.requests.clear(); collector.loads.clear()
            return dict(groupId=group.groupId, ok=True)
        @app.get('/__audit__/metrics')
        def metrics(_user=Depends(require_quote_access)):
            while collector.active or collector.workers:
                if time.monotonic() >= group.workDeadline:
                    raise TimeoutError('Metrics cleanup deadline')
                time.sleep(.01)
            return collector.metrics(cache)
        sock = socket.socket(); sock.bind(('127.0.0.1', 0)); sock.listen(32)
        server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False, lifespan='off', timeout_graceful_shutdown=1))
        thread = Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True); thread.start()
        while not server.started:
            if not thread.is_alive(): raise RuntimeError('Audit server did not start')
            if time.monotonic() >= group.workDeadline: raise TimeoutError('App startup deadline')
            time.sleep(.01)
        yield AuditApp(app, f'http://127.0.0.1:{sock.getsockname()[1]}', collector, stop)
    finally:
        stop.set()
        if server is not None: server.should_exit = True
        # Never unwind patches under an executing request/thread. The parent
        # kills only this worker's process group at the original 58/59s limits.
        while (thread is not None and thread.is_alive()) or collector.active or collector.workers:
            if thread is not None: thread.join(.02)
            else: time.sleep(.02)
        if sock is not None: sock.close()
        if get_engine.cache_info().currsize:
            get_engine().dispose()
            get_session_factory.cache_clear(); get_engine.cache_clear()
        stack.close()


def _validate_minute_r4_prefix(row):
    if row['period'] not in ('m60', 'm90', 'm120') or row['endpointKind'] not in ('signals', 'forecast'):
        return
    if row['dataStatus'] != 'READY':
        raise ValueError('Minute source is not READY')
    prefix = row['prefixRows']
    if type(prefix) is not int or not 0 < prefix <= BUDGET.response_default_minute + BUDGET.source_extra_rows:
        raise ValueError('Minute prefix rows exceeded or invalid')
    if any(not isinstance(row[key], str) or not row[key] for key in ('sourceInputId', 'computedThrough')):
        raise ValueError('Missing minute source identity or completed endpoint')
    if row['endpointKind'] == 'signals':
        count = row['responseRows']
        if type(count) is not int or not 0 < count <= min(BUDGET.response_default_minute, prefix):
            raise ValueError('Minute response rows exceeded or invalid')
    else:
        duration = row['computeSeconds']
        if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 <= duration <= .4:
            raise ValueError('Missing or invalid minute forecast compute time')


def validate_summary(group, summary):
    if not isinstance(summary, dict) or summary.get('groupId') != group.groupId or summary.get('cleanupStatus') != 'cleaned':
        raise ValueError('Missing completed cleanup')
    rows = summary.get('requests')
    if not isinstance(rows, list) or len(rows) != expected_requests(group): raise ValueError('Wrong completed request count')
    ids = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != _REQUEST_FIELDS:
            raise ValueError('Unexpected request fields')
        if row['requestId'] in ids or row['groupId'] != group.groupId or row['period'] != group.period:
            raise ValueError('Request identity mismatch')
        ids.add(row['requestId'])
        if (row['terminal'] != 'success' or row['httpStatus'] != 200 or type(row['httpSeconds']) not in (int, float)
                or not math.isfinite(row['httpSeconds']) or row['httpSeconds'] < 0):
            raise ValueError('Unsuccessful request')
        if row['endpointKind'] in ('signals', 'forecast'):
            if row['httpSeconds'] > 4 or row['clientSeconds'] is None or not 0 <= row['clientSeconds'] < 5:
                raise ValueError('HTTP/client budget exceeded')
            if row['bodyBytes'] > (32768 if row['endpointKind'] == 'forecast' else BUDGET.max_response_bytes):
                raise ValueError('Response bytes exceeded')
        _validate_minute_r4_prefix(row)
        if row['computeSeconds'] is not None and not 0 <= row['computeSeconds'] <= .4:
            raise ValueError('Compute budget exceeded')
        if row['forecastCacheReadCalls'] > 1 or row['forecastCacheWriteCalls'] > 1:
            raise ValueError('Duplicate forecast cache access')
    loads = {row['loadId']: row for row in summary['loads']}
    for row in rows:
        if any(value not in loads for value in row['loadIds']): raise ValueError('Unknown source load')
    for row in loads.values():
        if set(row) != _LOAD_FIELDS: raise ValueError('Unexpected source load fields')
        if row['seriesCacheReadCalls'] > 1 or row['pairCalls'] > 1 or row['barsCalls'] > 1 or row['indicatorCalls'] > 1:
            raise ValueError('Duplicate source read')
    if summary['cacheBytes'] > BUDGET.cache_max_bytes or summary['cacheEntries'] > BUDGET.cache_max_series or summary['activeRequests']:
        raise ValueError('Cache/active request budget')
    if group.samples == 20:
        summary['p95HttpSeconds'] = sorted(row['httpSeconds'] for row in rows)[18]
        if group.scenario == 'kline_series' and group.period == 'day' and summary['p95HttpSeconds'] > .8:
            raise ValueError('Daily Kline P95 exceeded')
    else: summary['p95HttpSeconds'] = None
    summary['forecastCacheHitCoverage'] = ('verified' if any(r['endpointKind'] == 'forecast' and r['forecastCacheRead'] == 'hit' for r in rows)
                                           else 'not_verified' if group.scenario == 'forecast_series' and group.samples == 20 else 'not_required')
    summary['sharedLoadCoverage'] = ('verified' if any(sum(load in r['loadIds'] for r in rows) > 1 for load in loads)
                                     else 'not_verified' if group.scenario == 'mixed_two' else 'not_required')
    return summary


def _validate_failure(group, message):
    for key in ('stage', 'errorType'):
        if not isinstance(message[key], str) or not re.fullmatch(r'[A-Za-z0-9_]{1,64}', message[key]):
            raise ValueError('Invalid failure type')
    if message['cleanupStatus'] != 'failed' or (message['errorCode'] is not None and
            (not isinstance(message['errorCode'], str) or not re.fullmatch(r'[A-Za-z0-9_]{1,128}', message['errorCode']))):
        raise ValueError('Invalid failure status/code')
    value = message['summary']
    if value is None: return
    if (not isinstance(value, dict) or set(value) != {'groupId','requests','loads','activeRequests','cacheBytes','cacheEntries','cleanupStatus'}
            or value['groupId'] != group.groupId or value['cleanupStatus'] != 'failed'
            or not isinstance(value['requests'], list) or len(value['requests']) > expected_requests(group)
            or not isinstance(value['loads'], list) or len(value['loads']) > expected_requests(group)):
        raise ValueError('Invalid failure summary')
    ids = set()
    for row in value['requests']:
        if (not isinstance(row, dict) or set(row) != _REQUEST_FIELDS or row['groupId'] != group.groupId
                or row['requestId'] in ids or row['period'] != group.period
                or not row['requestId'].startswith(group.groupId + ':' + group.scenario + ':')):
            raise ValueError('Invalid failed request identity/fields')
        ids.add(row['requestId'])
        for key, item in row.items():
            if key == 'loadIds':
                if not isinstance(item, list) or any(not isinstance(v, str) or not re.fullmatch(r'load-[0-9]+', v) for v in item):
                    raise ValueError('Invalid failed load references')
            elif item is not None and (type(item) not in (str, int, float) or
                    isinstance(item, str) and len(item) > 256 or type(item) in (int, float) and not math.isfinite(item)):
                raise ValueError('Invalid failure value')
    for row in value['loads']:
        if not isinstance(row, dict) or set(row) != _LOAD_FIELDS or row['period'] != group.period:
            raise ValueError('Invalid failed load fields')
        if any(item is not None and (type(item) not in (str, int, float) or
               isinstance(item, str) and len(item) > 256 or type(item) in (int, float) and not math.isfinite(item)) for item in row.values()):
            raise ValueError('Invalid failed load value')
    for key in ('activeRequests', 'cacheBytes', 'cacheEntries'):
        if type(value[key]) is not int or value[key] < 0: raise ValueError('Invalid failure counter')


def compare_modes(previous, current):
    """Compare only equal actual prefix/window/calendar identities; never replay."""
    pairs = []
    for row in current['requests']:
        if row['endpointKind'] not in ('signals', 'forecast'): continue
        candidates = [old for old in previous['requests'] if all(old[k] == row[k] for k in
            ('endpointKind', 'period', 'requestedAsOf', 'computedThrough', 'sourceInputId', 'calendarInputId',
             'indicatorVersion', 'windowStart', 'windowEnd', 'round', 'tabId'))]
        if len(candidates) != 1:
            pairs.append(dict(requestId=row['requestId'], status='not_comparable'))
        else:
            if candidates[0]['publicDigest'] != row['publicDigest']: raise ValueError('Same-source public results differ')
            pairs.append(dict(requestId=row['requestId'], status='equal'))
    return pairs


def _send_message(message):
    raw = json.dumps(message, separators=(',', ':'), allow_nan=False).encode() + b'\n'
    if len(raw) > BUDGET.max_response_bytes: raise ValueError('Worker message too large')
    sys.stdout.buffer.write(raw); sys.stdout.buffer.flush()


def _run_node(audit, group):
    node = shutil.which('node')
    if node is None: raise RuntimeError('Existing Node is required')
    command = [node, str(Path(__file__).with_suffix('.mjs')), audit.baseUrl, json.dumps(asdict(group), separators=(',', ':'))]
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
    try:
        selector = selectors.DefaultSelector()
        output = bytearray(); errors = bytearray(); total = 0
        try:
            for pipe in (child.stdout, child.stderr):
                os.set_blocking(pipe.fileno(), False); selector.register(pipe, selectors.EVENT_READ)
            while selector.get_map():
                left = group.workDeadline-time.monotonic()
                if left <= 0: raise TimeoutError('Node work deadline')
                for key, _ in selector.select(timeout=min(.05, left)):
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data: selector.unregister(key.fileobj); continue
                    total += len(data)
                    if total > BUDGET.max_response_bytes: raise ValueError('Node summary too large')
                    if key.fileobj is child.stdout: output.extend(data)
                    else: errors.extend(data)
            child.wait(timeout=max(.01, group.workDeadline-time.monotonic()))
        finally:
            selector.close()
        if child.returncode != 0:
            try:
                error = json.loads(errors)
                if (set(error) != {'stage','errorType','sentRequests','requests'} or error['stage'] != 'client'
                        or not isinstance(error['errorType'], str) or not re.fullmatch(r'[A-Za-z0-9_]{1,64}', error['errorType'])
                        or type(error['sentRequests']) is not int or not 0 <= error['sentRequests'] <= expected_requests(group)):
                    raise ValueError()
                _validate_client_records(group, error['requests'], error['sentRequests'])
            except (ValueError, TypeError, KeyError):
                raise AuditGroupFailure('client_communication') from None
            raise AuditGroupFailure('client', error_type=error['errorType'], client_records=error['requests'])
        value = json.loads(output)
        if not isinstance(value, dict) or value.get('groupId') != group.groupId: raise ValueError('Wrong Node group')
        return value
    finally:
        if child.poll() is None:
            child.terminate()
            try: child.wait(timeout=max(.01, min(1, group.deadline-time.monotonic())))
            except subprocess.TimeoutExpired:
                child.kill(); child.wait(timeout=max(.01, min(1, group.deadline-time.monotonic())))
        child.stdout.close(); child.stderr.close()


def _validate_client_records(group, records, count):
    if not isinstance(records, list) or len(records) != count:
        raise ValueError('Invalid client record count')
    ids = set()
    for row in records:
        if (not isinstance(row, dict) or set(row) != _CLIENT_FIELDS or not isinstance(row['requestId'], str)
                or not row['requestId'].startswith(group.groupId + ':' + group.scenario + ':')
                or row['requestId'] in ids or row['terminal'] not in ('success', 'error', 'cancelled')):
            raise ValueError('Invalid client record')
        ids.add(row['requestId'])
        for item in row.values():
            if item is not None and (type(item) not in (str, int, float) or
                    isinstance(item, str) and len(item) > 256 or type(item) in (int, float) and not math.isfinite(item)):
                raise ValueError('Invalid client value')


def _failure_summary(collector, cache, error, returned):
    value = collector.metrics(cache)
    records = error.client_records if isinstance(error, AuditGroupFailure) else ()
    if returned is not None:
        records = [{key: row[key] for key in _CLIENT_FIELDS} for row in returned['requests']]
    by_id = {row['requestId']: row for row in records}
    for row in value['requests']:
        client = by_id.get(row['requestId'])
        if client is None: continue
        row['httpSeconds'], row['clientSeconds'] = client['httpSeconds'], client['clientSeconds']
        if client['terminal'] != 'success': row['terminal'] = client['terminal']
        if row['endpointKind'] not in ('signals', 'forecast'):
            for key in ('computedThrough', 'responseRows', 'windowStart', 'windowEnd'): row[key] = client[key]
    value['cleanupStatus'] = 'failed'
    return value


def _run_audit_group_worker():
    group = None
    audit = own_cache = summary = None
    try:
        # Started is emitted before configuration/App imports and only for our
        # own process group, never for a pid supplied by a message.
        raw = sys.stdin.buffer.read(4097)
        if len(raw) > 4096: raise ValueError('Worker input exceeds limit')
        payload = json.loads(raw)
        if set(payload) != {'group', 'settingsIdentity'}: raise ValueError('Worker input fields')
        group = _group_from_json(payload['group'])
        _send_message(dict(type='started', groupId=group.groupId, pid=os.getpid(), processGroupId=os.getpgrp()))
        from src.foundation.config.settings import get_settings
        settings = get_settings()
        if _settings_identity(settings) != payload['settingsIdentity']: raise ValueError('Settings identity differs')
        if time.monotonic() >= group.workDeadline: raise TimeoutError('Worker startup deadline')
        with isolated_app(settings, group=group) as audit:
            from src.biz.queries.wealth.market.index_detail_xxm import query_service as q
            own_cache = q._CACHE
            summary = _run_node(audit, group)
        summary['cleanupStatus'] = 'cleaned'
        validate_summary(group, summary)
        _send_message(dict(type='result', groupId=group.groupId, summary=summary))
    except BaseException as error:
        if group is not None:
            if audit is not None and own_cache is not None:
                summary = _failure_summary(audit.collector, own_cache, error, summary)
            codes = {r['errorCode'] for r in summary['requests'] if r['errorCode']} if summary else set()
            _send_message(dict(type='failed', groupId=group.groupId,
                               stage=error.stage if isinstance(error, AuditGroupFailure) else 'worker',
                               errorType=error.error_type if isinstance(error, AuditGroupFailure) else type(error).__name__,
                               errorCode=next(iter(codes)) if len(codes) == 1 else None,
                               cleanupStatus='failed', summary=summary))
        raise SystemExit(1) from None


def _group_alive(pid):
    try: os.killpg(pid, 0)
    except ProcessLookupError: return False
    except PermissionError: return True  # Absence is not proven; never report clean.
    return True


def _supervise(command, payload, group):
    """No App/patch/source in this parent; bounded nonblocking pipes and own pgrp."""
    raw = json.dumps(payload, separators=(',', ':')).encode()
    if len(raw) > 4096: raise ValueError('Worker input exceeds limit')
    child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             shell=False, start_new_session=True, close_fds=True)
    selector = selectors.DefaultSelector()
    buffers = {'stdout': bytearray(), 'stderr': bytearray()}
    total = 0; sent = 0; started = False; terminal = None; failure = None
    signalled = set()
    for stream, name, events in ((child.stdin, 'stdin', selectors.EVENT_WRITE),
                                  (child.stdout, 'stdout', selectors.EVENT_READ), (child.stderr, 'stderr', selectors.EVENT_READ)):
        os.set_blocking(stream.fileno(), False); selector.register(stream, events, name)
    def send(sig):
        nonlocal failure
        try: os.killpg(child.pid, sig)
        except ProcessLookupError: pass
        except PermissionError: failure = failure or 'signal_permission'
    try:
        while True:
            now = time.monotonic()
            for limit, sig in ((group.workDeadline, signal.SIGINT), (group.startedAt+58, signal.SIGTERM), (group.startedAt+59, signal.SIGKILL)):
                if now >= limit and sig not in signalled:
                    failure = failure or 'group_deadline'; send(sig); signalled.add(sig)
            if now >= group.deadline: failure = failure or 'cleanup_deadline'; break
            if failure and signal.SIGINT not in signalled:
                send(signal.SIGINT); signalled.add(signal.SIGINT)
            if child.poll() is not None and not selector.get_map() and not _group_alive(child.pid): break
            for key, _ in selector.select(timeout=min(.05, max(0, group.deadline-now))):
                stream, name = key.fileobj, key.data
                if name == 'stdin':
                    try: sent += os.write(stream.fileno(), raw[sent:])
                    except (BrokenPipeError, OSError): failure = failure or 'stdin_failed'; sent = len(raw)
                    if sent == len(raw): selector.unregister(stream); stream.close()
                    continue
                data = os.read(stream.fileno(), 65536)
                if not data:
                    selector.unregister(stream); stream.close()
                    if name == 'stdout' and buffers[name]: failure = failure or 'incomplete_json'
                    continue
                total += len(data)
                if total > BUDGET.max_response_bytes:
                    failure = failure or 'communication_limit'
                    continue
                if name == 'stderr': continue  # Bounded count only; never print credentials from tracebacks.
                buffers[name].extend(data)
                while b'\n' in buffers[name]:
                    line, _, rest = buffers[name].partition(b'\n'); buffers[name] = bytearray(rest)
                    try:
                        message = json.loads(line)
                        if message.get('groupId') != group.groupId: raise ValueError()
                        if message.get('type') == 'started' and not started and terminal is None:
                            if set(message) != {'type','groupId','pid','processGroupId'} or message['pid'] != child.pid or message['processGroupId'] != child.pid: raise ValueError()
                            started = True
                        elif message.get('type') in ('result', 'failed') and started and terminal is None:
                            expected = {'type','groupId','summary'} if message['type'] == 'result' else {'type','groupId','stage','errorType','errorCode','cleanupStatus','summary'}
                            if set(message) != expected: raise ValueError()
                            terminal = message
                        else: raise ValueError()
                    except (ValueError, TypeError, AttributeError): failure = failure or 'invalid_worker_message'
            if child.poll() is not None and not _group_alive(child.pid) and not selector.get_map(): break
    except KeyboardInterrupt:
        failure = 'cancelled'; send(signal.SIGINT)
        # Continue cleanup through the same original deadline; never start another group.
        while time.monotonic() < group.deadline and _group_alive(child.pid):
            now = time.monotonic()
            if now >= group.startedAt+59: send(signal.SIGKILL)
            elif now >= group.startedAt+58: send(signal.SIGTERM)
            child.poll(); time.sleep(.01)
    finally:
        selector.close()
        if _group_alive(child.pid): send(signal.SIGKILL)
        try: child.wait(timeout=max(0, min(.2, group.deadline-time.monotonic())))
        except subprocess.TimeoutExpired: failure = failure or 'not_reaped'
        for stream in (child.stdin, child.stdout, child.stderr):
            if not stream.closed: stream.close()
    if (terminal is not None and terminal['type'] == 'failed' and failure is None
            and child.returncode is not None and not _group_alive(child.pid)):
        _validate_failure(group, terminal)
        raise AuditGroupFailure(terminal['stage'], error_type=terminal['errorType'], summary=terminal['summary'])
    if failure or child.returncode != 0 or not started or terminal is None or terminal['type'] != 'result' or _group_alive(child.pid):
        raise RuntimeError(f'Audit group failed: {failure or "incomplete_cleanup"}')
    return validate_summary(group, terminal['summary'])


def run_audit_group(group, settings):
    command = [sys.executable, '-B', '-c',
               'from scripts.research.index_market.xxm_page_request_audit import _run_audit_group_worker; _run_audit_group_worker()']
    return _supervise(command, dict(group=asdict(group), settingsIdentity=_settings_identity(settings)), group)


def run(args, tool):
    from src.foundation.config.settings import get_settings
    settings = get_settings()
    previous = {}
    for period, mode, scenario in planned_groups(args, tool):
        group = _new_group(args, tool, period, mode, scenario)
        try:
            summary = run_audit_group(group, settings)
        except AuditGroupFailure as error:
            print(json.dumps(dict(groupId=group.groupId, status='failed', stage=error.stage,
                                  errorType=error.error_type, summary=error.summary), ensure_ascii=False, allow_nan=False), flush=True)
            raise SystemExit(1) from None
        key = (period, scenario)
        if mode == 'debug' and key in previous:
            summary['normalDebugComparison'] = compare_modes(previous.pop(key), summary)
        elif mode == 'normal': previous[key] = summary
        print(json.dumps(summary, ensure_ascii=False, allow_nan=False), flush=True)


def main(argv=None):
    run(parse_args(argv), 'page')


if __name__ == '__main__':
    main()
