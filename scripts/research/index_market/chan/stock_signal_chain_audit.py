"""Section 28: read-only tracing of the frozen two-stock signal chain.

Never patches the engine or the frozen replay. Evidence is content addressed;
indices in the timeline refer to the authenticated 60-minute input, not clocks.
"""
from __future__ import annotations

import argparse
import ast
from bisect import bisect_right
from collections import Counter
from dataclasses import asdict, dataclass, replace
from enum import Enum
import gc
import hashlib
import html
import json
import math
from pathlib import Path
import resource
import sys
import time
from zipfile import ZipFile, ZIP_DEFLATED

from scripts.research.index_market.chan import minute_replay as engine
from scripts.research.index_market.chan import stock_sell_usage_audit as usage
from scripts.research.index_market.chan.event_ledger import groups
from scripts.research.index_market.chan.minute_variant_a import VARIANT_A
from scripts.research.index_market.chan.stock_qfq_run import source_gate
from scripts.research.index_market.chan.stock_research_store import StockResearchStore


@dataclass(frozen=True)
class SignalChainAuditSpec:
    codes: tuple = ('000731.SZ', '002225.SZ')
    start: str = '2021-09-09'
    end: str = '2026-09-08'
    evaluation_start: str = '2022-09-22'
    max_bars: int = 10000
    stock_seconds: int = 240
    total_seconds: int = 600
    memory_bytes: int = 256 * 1024**2
    output_bytes: int = 16 * 1024**2
    max_files: int = 5
    progress_seconds: int = 25


SPEC = SignalChainAuditSpec()
REPO = Path(__file__).resolve().parents[4]
PLAN = REPO/'docs/product/stock-chan-share-position-backtest-plan-v1.md'
NO_SELL = 'no_sell_in_trigger_window'
SELECTION_FIELDS = ('code', 'signal_time', 'types', 'entry_bar', 'deadline', 'category')


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                      allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def equal(actual, expected, label):
    if actual != expected:
        raise ValueError(f'inconsistent: {label}')


def select_cases(opportunities):
    chosen = []
    for code, category, n in ((SPEC.codes[0], NO_SELL, 2),
                              (SPEC.codes[0], 'nonmatching_only', 1),
                              (SPEC.codes[0], 'matched_sell_exit', 1),
                              (SPEC.codes[1], NO_SELL, 2)):
        pool = sorted((d for d in opportunities if d['code'] == code and d['category'] == category),
                      key=lambda d: (d['signal_time'], d['types']))
        if len(pool) < n:
            raise ValueError('fixed case category missing')
        chosen.extend(pool[:n])
    return chosen


def budget(stock_start, total_start, spec=SPEC):
    now = time.monotonic()
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != 'darwin':
        rss *= 1024
    if rss > spec.memory_bytes:
        raise MemoryError(f'audit RSS budget: {rss}')
    if now-stock_start > spec.stock_seconds or now-total_start > spec.total_seconds:
        raise TimeoutError('audit runtime budget')
    return rss


class Facts:
    """Copies plain attributes only; engine cached getters are forbidden here."""
    def __init__(self, rows, retain=True):
        self.rows, self.now, self.objects = rows, -1, {}
        self.retain = retain

    def put(self, value):
        data = encoded(value)
        key = sys.intern(sha(data))
        if self.retain:
            self.objects.setdefault(key, data)
        return key

    def get(self, ref):
        return json.loads(self.objects[ref])

    def endpoint(self, unit):
        i = unit.idx
        if not 0 <= i <= self.now < len(self.rows):
            raise ValueError('future structure reference')
        return {'index': i, 'time': self.rows[i]['time']}

    def ends(self, line):
        if type(line).__name__ == 'CSeg':
            return self.ends(line.start_bi)[0], self.ends(line.end_bi)[1]
        if type(line).__name__ != 'CBi':
            raise ValueError('unknown structural line')
        up = line.dir.name == 'UP'
        result = []
        for klc, field in ((line.begin_klc, 'low' if up else 'high'),
                           (line.end_klc, 'high' if up else 'low')):
            peak = getattr(klc, field)
            unit = next(u for u in reversed(klc.lst) if getattr(u, field) == peak)
            result.append((unit, peak))
        return result

    def line(self, line):
        if line is None:
            return None
        (begin, bv), (end, ev) = self.ends(line)
        level = ('bi' if type(line).__name__ == 'CBi' else
                 'segment' if type(line.start_bi).__name__ == 'CBi' else 'higher_segment')
        b, e = self.endpoint(begin), self.endpoint(end)
        value = dict(kind='line', level=level, index=line.idx, direction=line.dir.name,
                     sure=bool(line.is_sure), begin=b, end=e, begin_value=bv, end_value=ev,
                     identity=f"{level}|{line.dir.name}|{b['time']}|{e['time']}",
                     seg_idx=line.seg_idx)
        if level != 'bi':
            value['members'] = [self.line(x) for x in line.bi_list]
        return self.put(value)

    def center(self, z):
        return self.put(dict(kind='center', begin=self.endpoint(z.begin), end=self.endpoint(z.end),
            low=z.low, high=z.high, peak_low=z.peak_low, peak_high=z.peak_high,
            sure=bool(z.is_sure), incoming=self.line(z.bi_in), outgoing=self.line(z.bi_out),
            begin_line=self.line(z.begin_bi), end_line=self.line(z.end_bi),
            members=[self.line(b) for b in z.bi_lst]))

    def point(self, p):
        line = self.line(p.bi)
        return dict(line=line, buy=bool(p.is_buy), sure=bool(p.bi.is_sure),
                    types=sorted({t.value for t in p.type}), anchor=self.endpoint(p.klu),
                    predecessor=self.line(p.relate_bsp1.bi) if p.relate_bsp1 else None)

    def value(self, v):
        if v is None or isinstance(v, (str, bool, int)):
            return v
        if isinstance(v, float):
            return v if math.isfinite(v) else str(v)
        if isinstance(v, Enum):
            return v.value
        kind = type(v).__name__
        if kind in ('CBi', 'CSeg'):
            return {'ref': self.line(v)}
        if kind == 'CZS':
            return {'ref': self.center(v)}
        if kind == 'CBS_Point':
            return self.point(v)
        if kind == 'CPointConfig':
            return {k: self.value(x) for k, x in vars(v).items()}
        if isinstance(v, (tuple, list)):
            return [self.value(x) for x in v]
        if isinstance(v, dict):
            return {str(k): self.value(x) for k, x in v.items()}
        raise TypeError(f'unsupported observer value: {kind}')

    def scene(self, kl):
        return self.put(dict(kind='scene', index=self.now,
            strokes=[self.line(b) for b in kl.bi_list],
            segments=[self.line(s) for s in kl.seg_list],
            higher_segments=[self.line(s) for s in kl.segseg_list],
            centers=[self.center(z) for z in kl.zs_list.zs_lst],
            higher_centers=[self.center(z) for z in kl.segzs_list.zs_lst]))


def branch_catalog(path):
    """Source locations for executed control transfers, never eval predicates."""
    source = path.read_text()
    result = {}

    def walk(node, guards=()):
        if isinstance(node, ast.If):
            condition = ast.get_source_segment(source, node.test)
            for child in node.body:
                walk(child, guards+((condition, True),))
            for child in node.orelse:
                walk(child, guards+((condition, False),))
            return
        reject = (isinstance(node, (ast.Return, ast.Break, ast.Continue)) or
                  isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and
                  t.id == 'is_target_bsp' for t in node.targets))
        if reject:
            result[node.lineno] = dict(statement=ast.get_source_segment(source, node), guards=guards)
        for child in ast.iter_child_nodes(node):
            walk(child, guards)
    walk(ast.parse(source))
    return result


class Observer:
    def __init__(self, rows, code, diagnostics, cases, source_path, stock_start, total_start, retain=True):
        self.rows, self.code = rows, code
        self.diagnostics, self.cases = diagnostics, cases
        self.facts = Facts(rows, retain)
        self.stock_start, self.total_start = stock_start, total_start
        self.source_path = Path(source_path)
        self.paths = [self.source_path/'BuySellPoint/BSPointList.py', self.source_path/'ZS/ZS.py']
        self.catalog = {str(p): branch_catalog(p) for p in self.paths}
        self.root_code = engine.replay.__code__
        lines = Path(engine.__file__).read_text().splitlines()
        self.before = next(i+1 for i, x in enumerate(lines) if x.strip() == 'kl.add_single_klu(unit)')
        self.after = next(i+1 for i, x in enumerate(lines) if x.strip() == 'events.extend(new)')
        self.timeline, self.changes, self.coverage, self.snapshots = [], [], [], {}
        self.timeline_digest, self.timeline_hashes = hashlib.sha256(), {}
        self.previous = {'bi': {}, 'segment': {}}
        self.kl, self.i, self.in_window, self.cal_counts = None, -1, False, Counter()
        self.last_progress = time.monotonic()
        self.first_candidates, self.first_rejects = {}, {}
        self.call_number, self.calls = 0, {}
        times = [r['time'] for r in rows]
        self.fixed = set()
        for c in cases:
            self.fixed.add(bisect_right(times, c['signal_time'])-1)
            self.fixed.add(bisect_right(times, c['recorded_exit']['exit_time'])-1)

    def level(self, frame):
        while frame and frame.f_code is not self.root_code:
            obj = frame.f_locals.get('self')
            if obj is self.kl.bs_point_lst:
                return 'bi'
            if obj is self.kl.seg_bs_point_lst:
                return 'segment'
            frame = frame.f_back
        return 'unknown'

    def capture(self, frame, event, arg):
        local = frame.f_locals
        values = {}
        for k, v in local.items():
            if k in ('self', 'bi_list', 'seg_list'):
                continue
            if v is None or isinstance(v, (str, bool, int, float, Enum)) or type(v).__name__ in (
                    'CBi', 'CSeg', 'CZS', 'CBS_Point', 'CPointConfig') or k == 'feature_dict':
                values[k] = self.facts.value(v)
        obj = local.get('self')
        if type(obj).__name__ == 'CZS':
            values['center'] = {'ref': self.facts.center(obj)}
        if type(obj).__name__ == 'CBSPointList':
            values['last_sure_pos'] = obj.last_sure_pos
            predecessor = local.get('bsp1_bi')
            if 'bsp1_bi' in local:
                values['predecessor_in_target_store'] = (predecessor is not None and
                                                         predecessor.idx in obj.bsp_store_flat_dict)
            bi = local.get('bi')
            if bi is not None and frame.f_code.co_name == 'add_bs':
                point = obj.bsp_store_flat_dict.get(bi.idx)
                values['target_store_point'] = self.facts.point(point) if point else None
                values['bsp1_store_member'] = bi.idx in obj.bsp1_dict
        conf = local.get('BSP_CONF', local.get('config'))
        owner = frame
        while owner and type(owner.f_locals.get('self')).__name__ != 'CBSPointList':
            owner = owner.f_back
        side = None
        if owner and conf is not None:
            cfg = owner.f_locals['self'].config
            side = 'buy' if conf is cfg.b_conf else 'sell' if conf is cfg.s_conf else None
        if frame.f_code.co_name == 'cal_seg_bs3point' and 'bsp3_follow_1' not in str(
                self.catalog[frame.f_code.co_filename].get(frame.f_lineno, {})):
            side = None  # Loop locals can belong to the previous segment.
        if side is None and 'is_buy' in local:
            side = 'buy' if local['is_buy'] else 'sell'
        if side is None and frame.f_code.co_name == 'add_bs':
            side = 'buy' if local['bi'].dir.name == 'DOWN' else 'sell'
        if side is None and owner and owner is not frame:
            # A helper inherits the actual caller-side configuration, not a price guess.
            parent_conf = owner.f_locals.get('BSP_CONF')
            if parent_conf is not None:
                side = 'buy' if parent_conf is owner.f_locals['self'].config.b_conf else 'sell'
        location = self.catalog[frame.f_code.co_filename].get(frame.f_lineno, {})
        payload = dict(function=frame.f_code.co_name, file=str(Path(frame.f_code.co_filename).relative_to(self.source_path)),
                       line=frame.f_lineno, phase=event, level=self.level(frame), side=side,
                       location=location, values=values)
        if event == 'return':
            payload['result'] = self.facts.value(arg)
        ref = self.facts.put(payload)
        item = [self.i, self.calls.get(id(frame)), ref]
        self.timeline_digest.update(encoded(item)+b'\n')
        if self.facts.retain:
            self.timeline.append(item)
        if is_rejection(payload) and side == 'sell' and payload['level'] == 'bi':
            for c in self.cases:
                if c['entry_bar'] <= self.rows[self.i]['time'] < c['deadline']:
                    self.first_rejects.setdefault(c['signal_time'], self.i)

    def trace(self, frame, event, arg):
        if event == 'call':
            if frame.f_code is self.root_code:
                return self.trace
            path, name = frame.f_code.co_filename, frame.f_code.co_name
            if self.kl is None or path not in self.catalog:
                return None
            if path == str(self.paths[1]) and name not in ('is_divergence', 'end_bi_break', 'out_bi_is_peak'):
                return None
            if path == str(self.paths[0]) and not (name.startswith(('cal_', 'treat_', 'bsp')) or
                                                  name in ('cal', 'seg_need_cal', 'add_bs')):
                return None
            if name == 'cal':
                self.cal_counts[self.level(frame)] += 1
            if not self.in_window:
                return None
            self.call_number += 1
            self.calls[id(frame)] = self.call_number
            self.capture(frame, 'call', None)
            return self.trace
        if frame.f_code is self.root_code:
            if event == 'line' and frame.f_lineno == self.before:
                self.i, self.kl = frame.f_locals['i'], frame.f_locals['kl']
                self.facts.now = self.i
                stamp = self.rows[self.i]['time']
                self.in_window = any(d['entry_bar'] <= stamp < d['deadline'] for d in self.diagnostics)
                self.cal_counts.clear()
                budget(self.stock_start, self.total_start)
                if time.monotonic()-self.last_progress >= SPEC.progress_seconds:
                    print(f'observer {self.code} {self.i+1}/{len(self.rows)} {stamp}', flush=True)
                    self.last_progress = time.monotonic()
            elif event == 'line' and frame.f_lineno == self.after:
                self.bar_end(frame.f_locals)
            return self.trace
        if event == 'line' and frame.f_lineno in self.catalog[frame.f_code.co_filename]:
            self.capture(frame, event, arg)
        elif event == 'return':
            self.capture(frame, event, arg)
            self.calls.pop(id(frame), None)
        return self.trace

    def bar_end(self, local):
        stamp = self.rows[self.i]['time']
        self.timeline_hashes[self.i] = self.timeline_digest.hexdigest()
        for level, store in (('bi', self.kl.bs_point_lst), ('segment', self.kl.seg_bs_point_lst)):
            current = {}
            for p in store.bsp_store_flat_dict.values():
                value = self.facts.point(p)
                start = self.facts.endpoint(self.facts.ends(p.bi)[0][0])['time']
                key = f"{self.code}|{level}|{'buy' if p.is_buy else 'sell'}|{start}"
                current[key] = value
                if not p.is_buy and level == 'bi':
                    for c in self.cases:
                        if c['entry_bar'] <= stamp < c['deadline']:
                            self.first_candidates.setdefault(c['signal_time'], self.i)
            before = self.previous[level]
            for key in sorted(before.keys() | current.keys()):
                if before.get(key) != current.get(key):
                    self.changes.append(dict(index=self.i, level=level, candidate_id=key,
                                             before=before.get(key), after=current.get(key)))
            self.previous[level] = current
        if self.in_window:
            self.coverage.append(dict(index=self.i, calculations=dict(self.cal_counts),
                                      strokes=len(self.kl.bi_list), segments=len(self.kl.seg_list),
                                      centers=len(self.kl.zs_list.zs_lst)))
        if self.i in self.fixed or self.i in self.first_candidates.values() or self.i in self.first_rejects.values():
            self.snapshots[self.i] = self.facts.scene(self.kl)

    def run(self):
        if sys.gettrace() is not None:
            raise RuntimeError('another tracer is active')
        try:
            sys.settrace(self.trace)
            events = engine.replay(self.rows, self.code, 60, replace(VARIANT_A, codes=(self.code,),
                                   frequencies=(60,), replay_seconds=SPEC.stock_seconds))
        finally:
            sys.settrace(None)
            self.kl = None
        return events

    def prefix(self, cutoff):
        return dict(timeline_sha256=self.timeline_hashes[cutoff],
                    changes=[x for x in self.changes if x['index'] <= cutoff],
                    coverage=[x for x in self.coverage if x['index'] <= cutoff],
                    snapshots={i: h for i, h in self.snapshots.items() if i <= cutoff})


def is_rejection(p):
    location = p.get('location', {})
    return (p['phase'] == 'line' and bool(location.get('guards')) and
            p['function'].startswith(('treat_', 'cal_seg_')) and
            location.get('statement') in ('return', 'continue', 'break', 'is_target_bsp = False'))


def load_inputs(store):
    manifest = store.read('exits/manifest.json')
    equal(manifest['status'], 'complete', 'source status')
    setup = store.read('exits/setup.json', manifest['setup_sha256'])
    expected = asdict(usage.old.SPEC)
    expected['source'] = store.original_path(usage.old.SPEC.source)
    equal(setup['spec'], json.loads(json.dumps(expected)), 'exit configuration')
    equal(setup['periods']['full'], [SPEC.evaluation_start, SPEC.end], 'evaluation range')
    for path, h in setup['code_sha256'].items():
        store.verify_code(path, h)
    origin = store.read('calendar/source.json', setup['source_sha256'])
    for path, h in origin['code_sha256'].items():
        store.verify_code(path, h)
    days = store.read('initial/source.json', origin['previous_source_sha256'])['days']
    stocks, opportunities = {}, []
    for code in SPEC.codes:
        cm = store.read(f'exits/{code}/manifest.json')
        dm = store.read(f'calendar/{code}/manifest.json', cm['source_manifest_sha256'])
        equal((cm['status'], dm['status']), ('complete', 'complete'), 'stock status')
        rows30, rows60, events = [store.read(f'calendar/{code}/{name}', dm['artifacts_sha256'][name])
                               for name in ('input_30.json', 'input_60.json', 'full_events.json')]
        for rows, freq in ((rows30, 30), (rows60, 60)):
            if not 0 < len(rows) <= SPEC.max_bars:
                raise ValueError('input bar budget')
            if (rows[0]['time'][:10] != SPEC.start or rows[-1]['time'][:10] != SPEC.end or
                    any(r['code'] != code or r['frequency'] != freq for r in rows) or
                    any(a['time'] >= b['time'] for a, b in zip(rows, rows[1:]))):
                raise ValueError('frozen input identity or dates')
        usage.validate_events(events, rows60, code)
        cases = store.read(f'exits/{code}/cases.json', cm['artifacts_sha256']['cases.json'])
        times, gridrows = usage.grid(rows30, days)
        common = [c for c in cases if SPEC.evaluation_start <= c['signal_time'][:10] <= SPEC.end
                  and len(c['arms']) == 4 and all(a['status'] == 'closed' and
                  a['exit_time'][:10] <= SPEC.end for a in c['arms'].values())]
        emap = {e['event_id']: e for e in events}
        for c in common:
            es = [emap[e] for e in c['event_ids']]
            if (c['code'] != code or times[c['signal_index']] != c['signal_time'] or
                    any(not e['buy'] or e['signal_time'] != c['signal_time'] for e in es) or
                    c['types'] != sorted({e['group'] for e in es})):
                raise ValueError('buy identity mismatch')
        diagnostics = [usage.diagnose(c, events, rows60, times, gridrows,
                       setup['spec']['max_days']*setup['spec']['bars_day']) for c in common]
        equal(diagnostics, store.read(f'sell_usage/{code}/diagnostics.json'), 'archived diagnostics')
        if any(d['differences'] for d in diagnostics):
            raise ValueError('inconsistent: original execution')
        opportunities.extend({k: d[k] for k in SELECTION_FIELDS} for d in diagnostics)
        stocks[code] = dict(rows=rows60, events=events, diagnostics=diagnostics)
    equal(Counter(d['category'] for d in opportunities),
          Counter({NO_SELL: 27, 'nonmatching_only': 2, 'matched_sell_exit': 1}), '1/27/2 categories')
    equal(Counter(d['code'] for d in opportunities), Counter(dict(zip(SPEC.codes, (14, 16)))), '30 opportunities')
    selection = dict(opportunities=opportunities, cases=select_cases(opportunities))
    return stocks, selection


def explain(observer, events):
    """Link overlapping windows to the same candidate/branch records, not copies."""
    result = []
    objects, rows = observer.facts.get, observer.rows
    sell_changes = [x for x in observer.changes if x['level'] == 'bi' and
                    '|sell|' in x['candidate_id']]
    for d in observer.diagnostics:
        lo, hi = d['entry_bar'], d['deadline']
        relevant, confirmed, excluded, reused, outside, versions = set(), set(), set(), set(), set(), set()
        latest = {}
        # Changes before entry establish the actual state carried into the window.
        for ch in sell_changes:
            t, key = rows[ch['index']]['time'], ch['candidate_id']
            if t < lo:
                latest[key] = ch
        observations = list(latest.values()) + [x for x in sell_changes if lo <= rows[x['index']]['time'] < hi]
        for ch in observations:
            p, key = ch['after'], ch['candidate_id']
            if not p:
                continue
            relevant.add(key)
            versions.add(sha(encoded(p)))
            mapped = groups(p['types'], False)
            if p['sure']:
                confirmed.add(key)
                if not mapped:
                    excluded.add(key)
                event_key = key.replace('|bi|', '|K_60M|')
                if any(e['event_id'].startswith(event_key+'|') and e['signal_time'] < lo
                       for e in events):
                    reused.add(key)
        first_sure = {}
        for ch in sell_changes:
            p = ch['after']
            if p and p['sure']:
                first_sure.setdefault(ch['candidate_id'], ch)
        for ch in first_sure.values():
            p = ch['after']
            if rows[ch['index']]['time'] >= hi and lo <= p['anchor']['time'] < hi:
                outside.add(ch['candidate_id'])
        refs = [j for j, (i, _, ref) in enumerate(observer.timeline)
                if lo <= rows[i]['time'] < hi and objects(ref)['level'] == 'bi'
                and objects(ref)['side'] == 'sell']
        rejects = [j for j in refs if is_rejection(objects(observer.timeline[j][2]))]
        # One main rejection per invocation and actual candidate/structural alternative.
        first = {}
        for j in rejects:
            i, call, ref = observer.timeline[j]
            p = objects(ref)
            v = p['values']
            subject = next((v[k] for k in ('bsp3_bi', 'bsp2s_bi', 'bsp2_bi', 'last_bi', 'bsp1_bi', 'seg')
                            if v.get(k) is not None), None)
            first.setdefault((call, sha(encoded(subject))), j)
        reasons = Counter()
        for j in first.values():
            p = objects(observer.timeline[j][2])
            reasons[f"{p['file']}:{p['line']} {p['location']['statement']}"] += 1
        cov = [x for x in observer.coverage if lo <= rows[x['index']]['time'] < hi]
        expected = sum(lo <= r['time'] < hi for r in rows)
        equal(len(cov), expected, 'window trace coverage')
        result.append(dict(**{k: d[k] for k in SELECTION_FIELDS},
            raw_candidates=sorted(relevant), candidate_versions=len(versions),
            confirmed_candidates=sorted(confirmed), mapping_excluded=sorted(excluded),
            prior_ledger_identity=sorted(reused), outside_confirmation=sorted(outside),
            sell_evidence_indices=refs, first_rejection_indices=list(first.values()),
            primary_branch_counts=dict(reasons), observed_bars=len(cov),
            recalculation_bars=sum(x['calculations'].get('bi', 0) > 0 for x in cov),
            execution_evidence=d, unknown=[]))
    return result


def write_json(path, value):
    data = encoded(value)
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_bytes(data)
    equal(json.loads(temp.read_bytes()), json.loads(data), 'JSON readback')
    temp.replace(path)


def checkpoint(output, code, evidence, manifest, completed=True, check_budget=None):
    target, temp = output/'evidence.zip', output/'evidence.zip.tmp'
    with ZipFile(temp, 'w', ZIP_DEFLATED) as new:
        if target.exists():
            with ZipFile(target) as old:
                if old.testzip() is not None:
                    raise ValueError('existing evidence CRC')
                for info in old.infolist():
                    if info.filename == code+'.json':
                        raise ValueError('completed stock overwrite')
                    with old.open(info) as src, new.open(info.filename, 'w') as dst:
                        while chunk := src.read(1024**2):
                            dst.write(chunk)
        digest = hashlib.sha256()
        encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                   default=lambda value: json.loads(value) if isinstance(value, bytes) else
                                   (_ for _ in ()).throw(TypeError('unsupported evidence value')))
        with new.open(code+'.json', 'w') as dst:
            buffer = bytearray()
            for chunk in encoder.iterencode(evidence):
                buffer.extend(chunk.encode())
                if len(buffer) >= 65536:
                    if check_budget:
                        check_budget()
                    digest.update(buffer)
                    dst.write(buffer)
                    buffer.clear()
            digest.update(buffer)
            dst.write(buffer)
    with ZipFile(temp) as check:
        readback = hashlib.sha256()
        with check.open(code+'.json') as src:
            while chunk := src.read(1024**2):
                readback.update(chunk)
        if check.testzip() is not None or readback.digest() != digest.digest():
            raise ValueError('evidence readback')
    if temp.stat().st_size > SPEC.output_bytes:
        raise ValueError('compressed evidence budget')
    temp.replace(target)
    manifest.setdefault('observed_units', []).append(code)
    if completed:
        manifest['completed_units'].append(code)
    manifest['evidence_sha256'] = sha(target.read_bytes())
    write_json(output/'manifest.json', manifest)


def case_cutoffs(observer, c):
    times = [r['time'] for r in observer.rows]
    middle = observer.first_candidates.get(c['signal_time'], observer.first_rejects.get(c['signal_time']))
    cutoffs = [(bisect_right(times, c['signal_time'])-1, '买点确认'),
               (middle, '首个原始卖方候选' if c['signal_time'] in observer.first_candidates else '首个卖方拒绝分支'),
               (bisect_right(times, c['recorded_exit']['exit_time'])-1, '原退出/截止前最后完成60分钟柱')]
    result = {}
    for i, label in cutoffs:
        if i is not None:
            result.setdefault(i, []).append(label)
    return result


def diagram(observer, index):
    scene = observer.facts.get(observer.snapshots[index])
    objects = observer.facts.get
    # The picture is deliberately bounded; full dependencies remain in the ZIP.
    lo = max(0, index-160)
    rows = observer.rows[lo:index+1]
    low, high = min(r['low'] for r in rows), max(r['high'] for r in rows)
    x = lambda i: 50 + 900*(i-lo)/max(1, index-lo)
    y = lambda v: 260 - 220*(v-low)/max(1e-9, high-low)
    svg = ['<svg viewBox="0 0 1000 310" role="img" aria-label="截至当前柱的价格、笔、线段与中枢">',
           '<defs><clipPath id="plot"><rect x="50" y="20" width="900" height="250"/></clipPath></defs>',
           '<g clip-path="url(#plot)">']
    for ref in scene['centers']:
        z = objects(ref)
        if z['end']['index'] < lo:
            continue
        a, b = max(lo, z['begin']['index']), min(index, z['end']['index'])
        svg.append(f'<rect x="{x(a):.2f}" y="{y(z["high"]):.2f}" width="{max(1,x(b)-x(a)):.2f}" '
                   f'height="{max(1,y(z["low"])-y(z["high"])):.2f}" fill="#c99a32" opacity=".17"/>')
    points = ' '.join(f'{x(lo+i):.2f},{y(r["close"]):.2f}' for i, r in enumerate(rows))
    svg.append(f'<polyline points="{points}" fill="none" stroke="#a6adb8" stroke-width="1"/>')
    for key, color, width in (('strokes', '#288797', 1.5), ('segments', '#b44b5e', 2.5)):
        for ref in scene[key]:
            line = objects(ref)
            a, b = line['begin']['index'], line['end']['index']
            if b < lo:
                continue
            dash = '' if line['sure'] else ' stroke-dasharray="5 4"'
            svg.append(f'<line x1="{x(a):.2f}" y1="{y(line["begin_value"]):.2f}" '
                       f'x2="{x(b):.2f}" y2="{y(line["end_value"]):.2f}" stroke="{color}" '
                       f'stroke-width="{width}"{dash}/>')
    svg.extend(['</g>', f'<text x="50" y="290">{rows[0]["time"]}</text>',
                f'<text x="720" y="290">{rows[-1]["time"]}</text>',
                f'<text x="5" y="35">{high:.2f}</text><text x="5" y="260">{low:.2f}</text>', '</svg>'])
    return ''.join(svg)


def render_cases(observer, explanations):
    parts = []
    for c in observer.cases:
        detail = next(d for d in explanations if d['signal_time'] == c['signal_time'])
        parts.append(f'<section><h2>{c["code"]} · {c["signal_time"]} · {"/".join(c["types"])}</h2>')
        parts.append(f'<p>入场 {c["entry_bar"]}；截止 {c["deadline"]}；原退出 '
                     f'{c["recorded_exit"]["exit_time"]}（{c["recorded_exit"]["reason"]}）。</p>')
        parts.append(f'<p>窗口内不同原始卖候选 {len(detail["raw_candidates"])}；确认过 '
                     f'{len(detail["confirmed_candidates"])}；确认但仅1p/2s而未映射 '
                     f'{len(detail["mapping_excluded"])}。这些集合可重叠，不是独立交易数。</p>')
        parts.append('<table><tr><th>首次出现</th><th>当时锚点</th><th>首次确认及细类</th></tr>')
        for key in detail['raw_candidates']:
            history = [x for x in observer.changes if x['candidate_id'] == key and x['after']]
            first = history[0]
            sure = next((x for x in history if x['after']['sure']), None)
            sure_text = (f'{observer.rows[sure["index"]]["time"]} / {"+".join(sure["after"]["types"])}'
                         if sure else '完整封存期内未确认')
            parts.append(f'<tr><td>{observer.rows[first["index"]]["time"]}</td>'
                         f'<td>{first["after"]["anchor"]["time"]}</td><td>{sure_text}</td></tr>')
        parts.append('</table><p>表中首次确认若晚于当前截面/观察窗口，只作为事后核验，不回填当时信号。</p>')
        for i, labels in case_cutoffs(observer, c).items():
            parts.append(f'<h3>{" / ".join(labels)} · {observer.rows[i]["time"]}</h3>')
            parts.append(diagram(observer, i))
            parts.append(f'<small>截面引用 {observer.snapshots[i]}；只画最后161柱，完整结构见证据包。</small>')
        parts.append('<details><summary>实际经过的首个卖方拒绝分支与数值（非推测原因）</summary>')
        for j in detail['first_rejection_indices'][:1]:
            i, call, ref = observer.timeline[j]
            payload = observer.facts.get(ref)
            parts.append(f'<p>{observer.rows[i]["time"]}，调用 {call}，证据 {ref}</p><pre>'+
                         html.escape(json.dumps(display_facts(payload, observer.facts), ensure_ascii=False, indent=2))+'</pre>')
        metric = next((j for j in detail['sell_evidence_indices'] if
                       'in_metric' in observer.facts.get(observer.timeline[j][2])['values'] and
                       'out_metric' in observer.facts.get(observer.timeline[j][2])['values']), None)
        if metric is not None:
            i, call, ref = observer.timeline[metric]
            parts.append(f'<h4>实际动能比较：{observer.rows[i]["time"]}，调用{call}</h4><pre>'+
                         html.escape(json.dumps(display_facts(observer.facts.get(ref), observer.facts),
                                               ensure_ascii=False, indent=2))+'</pre>')
        else:
            parts.append('<p>本窗口未观测到卖方两段动能均已计算的证据，不补算或推测背驰。</p>')
        parts.append('</details><p>判定：原事件和原执行复现一致；候选出现不等于可成交。'
                     '本页不计算新策略收益，未运行的后续条件不推断通过。</p></section>')
    return ''.join(parts)


def display_facts(value, facts):
    """Expand endpoint/threshold references for humans, not entire recursive graphs."""
    if isinstance(value, dict) and set(value) == {'ref'}:
        obj = facts.get(value['ref'])
        if obj.get('kind') == 'line':
            return {k: obj[k] for k in ('kind', 'level', 'direction', 'sure', 'begin', 'end',
                                       'begin_value', 'end_value')}
        if obj.get('kind') == 'center':
            return dict(kind='center', begin=obj['begin'], end=obj['end'], low=obj['low'], high=obj['high'],
                        incoming=display_facts({'ref': obj['incoming']}, facts) if obj['incoming'] else None,
                        outgoing=display_facts({'ref': obj['outgoing']}, facts) if obj['outgoing'] else None)
    if isinstance(value, dict):
        return {k: display_facts(v, facts) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [display_facts(v, facts) for v in value]
    return value


def stock_process(data, cases, source, output, manifest, total_start, connection):
    """One serial stock per fresh process; no heap is carried into the next stock."""
    code = data['diagnostics'][0]['code']
    stock_start = time.monotonic()
    try:
        equal(source_gate(), source, 'child source/configuration')
        manifest.update(stage='baseline', current_stock=code)
        write_json(output/'manifest.json', manifest)
        rows, frozen, diagnostics = data['rows'], data['events'], data['diagnostics']
        print(f'baseline {code}: {len(rows)} bars', flush=True)
        reference = engine.replay(rows, code, 60, replace(VARIANT_A, codes=(code,),
                                  frequencies=(60,), replay_seconds=SPEC.stock_seconds))
        equal(reference, frozen, 'baseline versus frozen all event fields/order')
        baseline_seconds = time.monotonic()-stock_start
        manifest['stage'] = 'observer'
        write_json(output/'manifest.json', manifest)
        observer = Observer(rows, code, diagnostics, cases, source['path'], stock_start, total_start)
        observed = observer.run()
        equal(observed, reference, 'observer changed events')
        observed_seconds = time.monotonic()-stock_start-baseline_seconds
        explanations = explain(observer, observed)
        rendered = render_cases(observer, explanations)
        checkpoint(output, code, dict(objects=observer.facts.objects, timeline=observer.timeline,
            changes=observer.changes, coverage=observer.coverage, snapshots=observer.snapshots,
            explanations=explanations, source_lines={str(p.relative_to(Path(source['path']))):
            observer.catalog[str(p)] for p in observer.paths}), manifest, completed=False,
            check_budget=lambda: budget(stock_start, total_start))
        cutoffs = sorted({i for c in cases for i in case_cutoffs(observer, c)})
        checks = []
        manifest['stage'] = 'prefix_checks'
        write_json(output/'manifest.json', manifest)
        for cutoff in cutoffs:
            print(f'prefix {code}: {cutoff+1}/{len(rows)}', flush=True)
            small = Observer(rows[:cutoff+1], code, diagnostics, cases, source['path'], stock_start, total_start,
                             retain=False)
            equal(small.run(), [e for e in observed if e['signal_index'] <= cutoff], 'prefix events')
            # Snapshot schedules depend on full case times; compare only real requested cutoffs.
            equal({k: v for k, v in small.prefix(cutoff).items() if k != 'snapshots'},
                  {k: v for k, v in observer.prefix(cutoff).items() if k != 'snapshots'}, 'prefix diagnostics')
            equal(small.snapshots[cutoff], observer.snapshots[cutoff], 'prefix structure')
            del small
            gc.collect()
            checks.append(dict(cutoff=rows[cutoff]['time'], events_equal=True, diagnostics_equal=True))
        # A separate full replay modifies only OHLC strictly AFTER the latest checked cutoff.
        latest = max(cutoffs)
        manifest['stage'] = 'future_perturbation'
        write_json(output/'manifest.json', manifest)
        mutated = [dict(r, **{k: r[k]*1.013 for k in ('open', 'high', 'low', 'close')})
                   if i > latest else r for i, r in enumerate(rows)]
        perturb = Observer(mutated, code, diagnostics, cases, source['path'], stock_start, total_start,
                           retain=False)
        perturbed_events = perturb.run()
        equal([e for e in perturbed_events if e['signal_index'] <= latest],
              [e for e in observed if e['signal_index'] <= latest], 'future perturbation events')
        equal(perturb.prefix(latest), observer.prefix(latest), 'future perturbation diagnostics')
        del perturb, mutated
        rss = budget(stock_start, total_start)
        summary = dict(code=code, opportunities=len(diagnostics), events=len(observed),
            baseline_seconds=round(baseline_seconds, 3), observer_seconds=round(observed_seconds, 3),
            total_seconds=round(time.monotonic()-stock_start, 3), rss_bytes=rss,
            prefix_checks=checks, future_perturbation_equal=True, event_differences=0, execution_differences=0,
            changes=len(observer.changes), branch_observations=len(observer.timeline),
            labels={k: sum(bool(d[k]) for d in explanations if d['category'] == NO_SELL)
                    for k in ('raw_candidates', 'confirmed_candidates', 'mapping_excluded',
                              'prior_ledger_identity', 'outside_confirmation')})
        manifest['stocks'][code] = summary
        manifest['completed_units'].append(code)
        write_json(output/'manifest.json', manifest)
        del observer, data, rows, observed, reference, frozen, explanations
        gc.collect()
        connection.send(dict(summary=summary, html=rendered, manifest=manifest))
    except BaseException as exc:
        connection.send(dict(error=f'{type(exc).__name__}: {exc}', inconsistent=str(exc).startswith('inconsistent:')))
    finally:
        connection.close()


def execute(output):
    from scripts.research.index_market.chan.m0_data import safe_output
    output = safe_output(Path(output))
    source = source_gate()
    total_start = time.monotonic()
    store = StockResearchStore()
    stocks, selection = load_inputs(store)
    output.mkdir()
    write_json(output/'selection.json', selection)  # Frozen before any candidate inspection.
    manifest = dict(status='running', stage='baseline', spec=asdict(SPEC), source=source,
                    plan_sha256=sha(PLAN.read_bytes()), code_sha256=sha(Path(__file__).read_bytes()),
                    input_store=store.receipt, inputs=dict(store.consumed), completed_units=[], stocks={})
    write_json(output/'manifest.json', manifest)
    case_html, summaries = [], []
    try:
        import multiprocessing
        context = multiprocessing.get_context('spawn')
        for code in SPEC.codes:
            data = stocks.pop(code)
            cases = [d for s in selection['cases'] for d in data['diagnostics'] if
                     d['code'] == s['code'] and d['signal_time'] == s['signal_time']]
            receiver, sender = context.Pipe(duplex=False)
            process = context.Process(target=stock_process,
                args=(data, cases, source, output, manifest, total_start, sender))
            process.start()
            sender.close()
            parent_stock_start = time.monotonic()
            try:
                while not receiver.poll(1):
                    budget(parent_stock_start, total_start)
                    if not process.is_alive():
                        raise RuntimeError(f'stock process exited: {process.exitcode}')
                    if time.monotonic()-total_start > SPEC.total_seconds:
                        raise TimeoutError('total process budget')
                message = receiver.recv()
                process.join(5)
                if process.is_alive():
                    raise RuntimeError('stock process did not exit')
            finally:
                if process.is_alive():
                    process.terminate()
                    process.join(5)
                receiver.close()
            # A failed child may already have persisted an observed unit.
            manifest = json.loads((output/'manifest.json').read_bytes())
            if 'error' in message:
                prefix = 'inconsistent: ' if message.get('inconsistent') else ''
                raise RuntimeError(prefix+message['error'])
            equal(process.exitcode, 0, 'stock process exit')
            manifest = message['manifest']
            summaries.append(message['summary'])
            case_html.append(message['html'])
            del data, message, process
            gc.collect()
        store.verify_unchanged()
        equal(source_gate(), source, 'source/configuration changed during audit')
        equal(sha(Path(__file__).read_bytes()), manifest['code_sha256'], 'observer source changed during run')
        manifest.update(status='complete', stage='28.8_verified', total_seconds=round(time.monotonic()-total_start, 3))
    except BaseException as exc:
        manifest = json.loads((output/'manifest.json').read_bytes())
        manifest.update(status='inconsistent' if str(exc).startswith('inconsistent:') else 'partial',
                        error=f'{type(exc).__name__}: {exc}')
        write_json(output/'manifest.json', manifest)
        (output/'report.md').write_text(f'# 识别链审计：{manifest["status"]}\n\n已完成单元：'
                                      f'{manifest["completed_units"]}。已保存观测单元：{manifest.get("observed_units", [])}。'
                                      f'停止原因：{manifest["error"]}。'
                                      '\n\n未改变算法或历史结果，未完成条件不能推断为通过。\n')
        raise
    (output/'cases.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<title>两股识别链：六笔固定案例</title><style>body{max-width:1100px;margin:30px auto;'
        'font:16px/1.6 system-ui;color:#243044;padding:20px}section{border-top:1px solid #ccd;'
        'margin-top:35px}pre{white-space:pre-wrap;font-size:12px}svg{width:100%}small{overflow-wrap:anywhere}</style>'
        '<h1>六笔固定案例 · 60分钟识别链</h1><p>灰线为收盘价，蓝线为笔，红线为线段，黄色为中枢；'
        '虚线表示当时未确认。没有画入截面之后的行情。图仅辅助定位，完整数值与分支在evidence.zip。</p>'+
        ''.join(case_html)+'</html>')
    lines = ['# 两股识别链审计（第28节）', '', '范围：四川美丰、濮耐股份，冻结五年60分钟识别；'
             '30分钟只核对旧执行。不是新收益回测。', '', '原30次机会：1次匹配退出、27次无账本卖点、'
             '2次只有不匹配卖点。带/不带观测与封存事件逐字段一致，原执行零差异。', '',
             '| 股票 | 原事件 | 无卖点机会中有原始候选 | 确认过 | 有仅1p/2s被映射排除 |',
             '| --- | ---: | ---: | ---: | ---: |']
    for s in summaries:
        labels = s['labels']
        lines.append(f'| {s["code"]} | {s["events"]} | {labels["raw_candidates"]} | '
                     f'{labels["confirmed_candidates"]} | {labels["mapping_excluded"]} |')
    lines += ['', '这些是可重叠的机会标签，不是互斥原因，也不是新增可交易卖点。'
              '原始候选按笔/线段分开；只有原笔级映射进入交易账本。', '',
              '[六笔案例](cases.html) · [固定样本](selection.json) · [校验与用时](manifest.json) · [机器证据](evidence.zip)', '',
              '证据包每股一个JSON：objects按内容去重，timeline为[60分钟输入下标,调用号,对象哈希]；'
              'explanations引用判定索引与原执行。分支只记录实际执行；未执行的后续条件未评估。'
              '首次拒绝按函数调用计，不把同一窗口多次尝试当成独立交易。', '',
              '前缀截断、未来OHLC扰动、源码/展开配置及Store前后校验通过。规则是否值得改动仍需单变量对照；'
              '本轮不证明放开1p/2s或取消配对能够增加收益。']
    (output/'report.md').write_text('\n'.join(lines)+'\n')
    manifest['artifacts_sha256'] = {p.name: sha(p.read_bytes()) for p in output.iterdir() if p.name != 'manifest.json'}
    write_json(output/'manifest.json', manifest)
    files = list(output.iterdir())
    if len(files) > SPEC.max_files or sum(p.stat().st_size for p in files) > SPEC.output_bytes:
        manifest.update(status='partial', error='final output budget exceeded')
        write_json(output/'manifest.json', manifest)
        raise ValueError(manifest['error'])
    print(json.dumps(summaries, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    execute(args.output)


if __name__ == '__main__':
    main()
