"""Section 32: as-of structure review; no new trading policy or threshold search."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
import json
import multiprocessing
from pathlib import Path
from statistics import median
import sys
import time
from zipfile import ZipFile

from scripts.research.index_market.chan import stock_any_sell_cohort as cohort
from scripts.research.index_market.chan import stock_any_sell_study as policy
from scripts.research.index_market.chan import stock_sell_linkage_study as shared
from scripts.research.index_market.chan import stock_signal_chain_audit as audit
from scripts.research.index_market.chan.minute_replay import replay
from scripts.research.index_market.chan.minute_variant_a import VARIANT_A
from scripts.research.index_market.chan.run_m0 import expanded
from scripts.research.index_market.chan.stock_opportunity import safe_output, sha
from scripts.research.index_market.chan.stock_research_store import StockResearchStore


@dataclass(frozen=True)
class ReviewSpec:
    codes: tuple = tuple(c for c, _ in cohort.SPEC.counts if c not in policy.SPEC.codes)
    # Canonical JSON of the 133 full pairs from section 31, in code/time order.
    pairs_sha256: str = '0f7a53ba2a3e093f3b5aa2fd90317c497fc37bd310f44bce3d4b90f5b39995a9'
    selection_rule: str = 'each sign: largest absolute delta, lower median rank, earliest remaining'
    recent_segments: int = 3
    recent_centers: int = 2


SPEC = ReviewSpec()


def identity(p):
    return p['code'] + '|' + p['signal_time']


def label(p):
    return 'better' if p['delta'] > 0 else 'worse' if p['delta'] < 0 else 'unchanged'


def select_cases(pairs):
    if len({identity(p) for p in pairs}) != len(pairs):
        raise ValueError('duplicate opportunities')
    selected = []
    for group in ('better', 'worse'):
        pool = sorted((p for p in pairs if label(p) == group), key=lambda p: (abs(p['delta']), identity(p)))
        if len(pool) < 3:
            raise ValueError('insufficient illustrative cases')
        chosen = [pool[-1], pool[(len(pool)-1)//2]]
        chosen.append(min((p for p in pool if identity(p) not in {identity(c) for c in chosen}),
                          key=lambda p: (p['signal_time'], p['code'])))
        selected.extend(dict(case_id=identity(p), label=group, reason=reason) for p, reason in
                        zip(chosen, ('extreme', 'lower_median', 'earliest_remaining'), strict=True))
    return selected


def position(price, center):
    if center is None:
        return 'missing'
    return 'above' if price > center['high'] else 'below' if price < center['low'] else 'inside'


def s2_geometry(line, previous, close):
    if previous is None or previous['index'] != line['index']-1:
        return None
    denominator = abs(previous['end_value']-previous['begin_value'])
    if not denominator:
        return None
    return dict(retrace=abs(line['end_value']-line['begin_value'])/denominator,
                rebound_below_prior_high=line['end_value'] < previous['begin_value'],
                confirm_below_prior_low=close < previous['end_value'])


def snapshot(kl, rows, event):
    """Only already computed attributes; never calls engine metric/cached getters."""
    facts = audit.Facts(rows); facts.now = event['signal_index']
    points = [p for p in kl.bs_point_lst.bsp_store_flat_dict.values() if
              p.bi.idx == event['bi_index'] and bool(p.is_buy) == event['buy']]
    if len(points) != 1:
        raise ValueError('event point not found uniquely at first confirmation')
    point = points[0]; bi = point.bi
    copied = facts.point(point); line = facts.get(copied['line'])
    audit.equal(copied['sure'], True, 'confirmed point')
    audit.equal(copied['types'], event['types'], 'original types')
    audit.equal((line['begin']['index'], line['end']['index'], copied['anchor']['index']),
                (event['start_index'], event['end_index'], event['anchor_index']), 'original endpoints')
    parent = bi.parent_seg
    if parent is not None and not any(b is bi for b in parent.bi_list):
        raise ValueError('parent membership mismatch')
    segments = list(kl.seg_list)
    centers = list(kl.zs_list.zs_lst)
    sure_segments = [s for s in segments if s.is_sure]
    sure_centers = [z for z in centers if z.is_sure and z.begin_bi.idx < z.end_bi.idx]
    latest_center = max(sure_centers, key=lambda z: (z.end.idx, z.begin.idx), default=None)
    previous = next((b for b in kl.bi_list if b.idx == bi.idx-1), None)
    next_bi = next((b for b in kl.bi_list if b.idx == bi.idx+1), None)
    refs = dict(point=copied, previous=facts.line(previous), next=facts.line(next_bi),
                parent=facts.line(parent), parent_centers=[facts.center(z) for z in parent.zs_lst] if parent else [],
                recent_segments=[facts.line(s) for s in segments[-SPEC.recent_segments:]],
                recent_centers=[facts.center(z) for z in centers[-SPEC.recent_centers:]],
                latest_sure_segment=facts.line(sure_segments[-1]) if sure_segments else None,
                latest_sure_center=facts.center(latest_center) if latest_center else None)
    close = rows[facts.now]['close']
    center = facts.get(refs['latest_sure_center']) if refs['latest_sure_center'] else None
    geometry = s2_geometry(line, facts.get(refs['previous']) if refs['previous'] else None, close) if event['group']=='S2' else None
    features = dict(group=event['group'], lag_bars=event['lag_bars'],
        parent_state=f'{parent.dir.name}/{"sure" if parent.is_sure else "tentative"}' if parent else 'missing',
        latest_sure_segment=sure_segments[-1].dir.name if sure_segments else 'missing',
        center_position=position(close, center), s2=geometry)
    return dict(event=event, as_of=rows[facts.now]['time'], close=close, refs=refs, features=features,
                objects={k:json.loads(v) for k,v in facts.objects.items()})


class SnapshotSink:
    def __init__(self, rows, targets):
        self.rows = rows; self.targets = defaultdict(list); self.snapshots = {}
        ids = [e['event_id'] for e in targets]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate snapshot targets')
        for e in targets:
            self.targets[e['signal_index']].append(e)

    def __call__(self, changes):
        frame = sys._getframe(1)
        if frame.f_code is not replay.__code__:
            raise ValueError('unexpected replay callback frame')
        state = frame.f_locals
        for event in self.targets.get(state['i'], []):
            if event not in state['new']:
                raise ValueError('target not a first-confirmed event')
            self.snapshots[event['event_id']] = snapshot(state['kl'], self.rows, event)

    def finish(self):
        expected = {e['event_id'] for es in self.targets.values() for e in es}
        audit.equal(set(self.snapshots), expected, 'all snapshot targets')
        return self.snapshots


def observe(rows, code, spec, targets):
    sink = SnapshotSink(rows, targets)
    events = replay(rows, code, 60, spec, sink=sink)
    return events, sink.finish()


def targets_for(data, changed, selected):
    ids = {k for p in changed for k in p['used_sell_event_ids']}
    ids.update(k for p in changed if identity(p) in selected for k in p['event_ids'])
    result = [e for e in data['events'] if e['event_id'] in ids]
    audit.equal({e['event_id'] for e in result}, ids, 'target identities')
    if not result:
        raise ValueError('empty stock targets')
    return result


def stock_worker(code, selected, expected_pairs_sha, sender):
    started = time.monotonic()
    try:
        source = audit.source_gate()
        from ChanConfig import CChanConfig
        policy.require_original_a(expanded(CChanConfig(VARIANT_A.chan_config())), source['expanded_config'])
        store = StockResearchStore(); header = cohort.load_header(store); data = cohort.load_stock(store, header, code)
        pairs = policy.compare(data['cases'], data['events'], data['structure'], data['times'], data['rows'], data['diagnostics'])
        audit.equal(audit.sha(audit.encoded(pairs)), expected_pairs_sha, 'preselected stock pairs')
        changed = [p for p in pairs if p['delta'] != 0]
        targets = targets_for(data, changed, selected)
        spec = replace(VARIANT_A, codes=(code,), frequencies=(60,), replay_seconds=shared.SPEC.stock_seconds)
        events, snapshots = observe(data['structure'], code, spec, targets)
        audit.equal(events, data['events'], 'full original A events')
        cutoff = max(e['signal_index'] for e in targets)
        prefix_events, prefix_snaps = observe(data['structure'][:cutoff+1], code, spec, targets)
        audit.equal(prefix_events, [e for e in events if e['signal_index'] <= cutoff], 'prefix events')
        audit.equal(prefix_snaps, snapshots, 'prefix snapshots')
        changed_rows = [dict(r, **{k:r[k]*shared.SPEC.future_multiplier for k in ('open','high','low','close')})
                        if i > cutoff else dict(r) for i,r in enumerate(data['structure'])]
        future_events, future_snaps = observe(changed_rows, code, spec, targets)
        audit.equal([e for e in future_events if e['signal_index'] <= cutoff], prefix_events, 'future events')
        audit.equal(future_snaps, snapshots, 'future snapshots')
        store.verify_unchanged(); audit.equal(audit.source_gate(), source, 'source unchanged')
        rss = audit.budget(started, started, shared.SPEC)
        result = dict(pairs=changed, snapshots=snapshots, original_events=len(events),
                      checks=dict(prefix_cutoff=data['structure'][cutoff]['time'], prefix_events=len(prefix_events),
                                  snapshots=len(snapshots), full_ledger=True, prefix=True, future=True),
                      seconds=time.monotonic()-started, rss_bytes=rss, consumed_records=store.consumed)
        if len(audit.encoded(result)) > shared.SPEC.output_bytes:
            raise ValueError('unit evidence budget')
        sender.send(dict(status='complete', result=result))
    except Exception as exc:
        sender.send(dict(status='failed', error=f'{type(exc).__name__}: {exc}'))
    finally:
        sender.close()


def run_process(code, selected, digest, started):
    context = multiprocessing.get_context('spawn'); receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=stock_worker, args=(code,selected,digest,sender))
    stock_start = time.monotonic(); process.start(); sender.close()
    try:
        while not receiver.poll(10):
            audit.budget(stock_start,started,shared.SPEC)
            if not process.is_alive():
                raise RuntimeError('worker exited without evidence')
            print(f'{code}: structure review {time.monotonic()-stock_start:.0f}s',flush=True)
        payload = receiver.recv(); process.join(timeout=2)
        if process.is_alive() or process.exitcode != 0 or payload['status'] != 'complete':
            raise RuntimeError(payload.get('error','worker not complete'))
        audit.budget(stock_start,started,shared.SPEC)
        return payload['result']
    finally:
        if process.is_alive():
            process.terminate(); process.join(timeout=2)
        receiver.close()


def feature_rows(results):
    rows = []
    for code, result in results.items():
        for pair in result['pairs']:
            snaps = [result['snapshots'][k] for k in pair['used_sell_event_ids']]
            # A simultaneous multi-type event stays one opportunity, not extra observations.
            features = {k: '|'.join(sorted({str(s['features'][k]) for s in snaps})) for k in
                        ('group','parent_state','latest_sure_segment','center_position')}
            rows.append(dict(case_id=identity(pair), label=label(pair), delta=pair['delta'], **features))
    return rows


def descriptive(rows):
    tables = {}
    for field in ('group','parent_state','latest_sure_segment','center_position'):
        groups = defaultdict(Counter)
        for r in rows:
            groups[r[field]][r['label']] += 1
        audit.equal(sum(sum(c.values()) for c in groups.values()), len(rows), 'feature denominator')
        tables[field] = {k:dict(v) for k,v in sorted(groups.items())}
    return tables


def report(results, selection, names):
    rows = feature_rows(results); tables = descriptive(rows)
    lines = ['# 退出改善与卖早：当时可见结构审阅', '',
        '2026-09-13；原八股133次机会，47次收益改变（26改善/21变差），86次不变。60分钟原A识别、30分钟执行；输入2021-09-09—2026-09-08，评估2022-09-22起。', '',
        '这是按结果分组的回顾解释，不是预测、策略胜率或分仓账户收益；改善可能仍亏损，变差可能仍盈利。样本为此前筛选的存续沪深股，带幸存者/共同闭合选择偏差。', '',
        '结构只取首次确认回调的实时对象。父线段/中枢是同一60分钟图的结构层次，不是日线共振；中枢位置使用最近已确认多笔中枢上下文，不冒充买卖点生成依据。', '',
        '## 全47次的结构分组', '', '| 字段 | 当时状态 | 改善 | 变差 |', '| --- | --- | ---: | ---: |']
    for field, groups in tables.items():
        lines.extend(f'| {field} | {k} | {v.get("better",0)} | {v.get("worse",0)} |' for k,v in groups.items())
    for group in ('better','worse'):
        observations = [results[p['code']]['snapshots'][k]['features'] for result in results.values()
                        for p in result['pairs'] if label(p)==group for k in p['used_sell_event_ids']]
        for field, values in (('确认滞后（60分钟柱）',[x['lag_bars'] for x in observations]),
                              ('S2反弹/前跌幅度',[x['s2']['retrace'] for x in observations if x['s2']])):
            if values:
                lines += ['', f'{group} / {field}：n={len(values)}，最小{min(values):.4f}、中位{median(values):.4f}、最大{max(values):.4f}。这里是事件引用数，若同一卖点服务多个机会会重复，不是独立事件样本。']
    index = {identity(p):(result,p) for result in results.values() for p in result['pairs']}
    for selected in selection['cases']:
        result,p = index[selected['case_id']]; b,a = p['before'],p['after']
        lines += ['', f'## {names[p["code"]]} {p["code"]}：{selected["label"]}/{selected["reason"]}', '',
            f'买点确认 {p["signal_time"]}（{"/".join(p["types"])}）；入场柱 {a["entry_bar"]}，前复权开盘 {a["entry_price"]:.4f}。', '',
            f'新退出 {a["exit_time"]}，{a["exit_phase"]}价{a["exit_price"]:.4f}，毛收益{a["return_value"]:.2%}；原退出 {b["exit_time"]}（{b["reason"]}），价{b["exit_price"]:.4f}，毛收益{b["return_value"]:.2%}。差{p["delta"]*100:+.2f}个百分点。', '',
            f'原→新持有{b["holding_days"]:.2f}→{a["holding_days"]:.2f}市场日；MAE {b["adverse"]:.2%}→{a["adverse"]:.2%}；MFE {b["favorable"]:.2%}→{a["favorable"]:.2%}。', '',
            '| 截面 | 确认时刻 | 笔端点时刻/价格 | 父线段方向/状态 | 最近确认线段 | 确认收盘/中枢 |',
            '| --- | --- | --- | --- | --- | --- |']
        for key in p['event_ids']+p['used_sell_event_ids']:
            s = result['snapshots'][key]; f=s['features']; refs=s['refs']; objs=s['objects']
            ln=objs[refs['point']['line']]; z=objs[refs['latest_sure_center']] if refs['latest_sure_center'] else None
            lines.append(f'| {s["event"]["group"]} | {s["as_of"]} | {ln["begin"]["time"]} {ln["begin_value"]:.4f} → {ln["end"]["time"]} {ln["end_value"]:.4f} | {f["parent_state"]} | {f["latest_sure_segment"]} | {s["close"]:.4f} / {f["center_position"]} '+(f'[{z["low"]:.4f}, {z["high"]:.4f}]' if z else '缺失')+' |')
            if f['s2']:
                g=f['s2']; prev=objs[refs['previous']]
                lines += ['', f'S2：前跌笔 {prev["begin_value"]:.4f}→{prev["end_value"]:.4f}，反弹幅度/前跌幅度={g["retrace"]:.4f}；反弹高点低于前高={g["rebound_below_prior_high"]}，确认收盘跌破前跌低点={g["confirm_below_prior_low"]}；锚点后{f["lag_bars"]}根才首次确认。', '']
    lines += ['', '## 验证与限制', '',
        '133次旧对照摘要精确一致；8股全事件零变化，全部目标截面找到；每股目标末时刻截断和未来OHLC扰动均通过。来源/Store/研究代码读前后检查及ZIP读回见manifest。', '',
        '6例按已知收益差挑选（每类极值、下中位、最早），只解释机制，不代表总体概率。中枢位置、父结构若两类都有，不能硬解释为可靠过滤条件。未调整阈值、运行新退出政策或加入费用/分仓账户。缺少独立样本和同持有期基准。', '']
    return '\n'.join(lines)


def execute(output):
    output=safe_output(output)
    started=time.monotonic(); source=audit.source_gate()
    store=StockResearchStore(); header=cohort.load_header(store)
    paths=sorted(Path(__file__).parent.glob('*.py')); hashes={str(p):sha(p) for p in paths}
    all_pairs=[]; per_stock={}
    for code in SPEC.codes:
        audit.budget(started,started,shared.SPEC)
        data=cohort.load_stock(store,header,code)
        pairs=policy.compare(data['cases'],data['events'],data['structure'],data['times'],data['rows'],data['diagnostics'])
        per_stock[code]=audit.sha(audit.encoded(pairs)); all_pairs.extend(pairs)
        del data
    audit.equal(audit.sha(audit.encoded(all_pairs)), SPEC.pairs_sha256, '133 frozen pairs')
    audit.equal(Counter(label(p) for p in all_pairs),Counter(better=26,worse=21,unchanged=86),'frozen outcome counts')
    selection=dict(cases=select_cases(all_pairs), changed=[identity(p) for p in all_pairs if p['delta']!=0],
                   all_n=len(all_pairs), per_stock_sha256=per_stock, spec=asdict(SPEC))
    del all_pairs
    output.mkdir(parents=True); audit.write_json(output/'selection.json',selection)
    manifest=dict(status='running',spec=asdict(SPEC),source=source,code_sha256=hashes,
        plan_design_sha256=sha(audit.PLAN), selection_sha256=sha(output/'selection.json'),
        input_store=store.receipt,consumed_records=store.consumed,completed=[],
        limits={k:getattr(shared.SPEC,k) for k in ('stock_seconds','total_seconds','memory_bytes','output_bytes','max_files')})
    results={}; shared.checkpoint(output,manifest,results)
    try:
        selected={p['case_id'] for p in selection['cases']}
        for i,code in enumerate(SPEC.codes):
            print(f'{i+1}/8 {code} {header["names"][code]}',flush=True)
            result=run_process(code,selected,per_stock[code],started)
            for k,h in result.pop('consumed_records').items():
                audit.equal(store.consumed[k],h,'worker source record')
            results[code]=result; manifest['completed'].append(code)
            shared.checkpoint(output,manifest,results)
            print(f'{i+1}/8 complete, {len(result["snapshots"])} snapshots, {result["seconds"]:.2f}s',flush=True)
        audit.equal(sorted(r['case_id'] for r in feature_rows(results)), sorted(selection['changed']), '47 covered opportunities')
        store.verify_unchanged(); audit.equal(audit.source_gate(),source,'source unchanged')
        audit.equal({str(p):sha(p) for p in paths},hashes,'code unchanged')
        manifest.update(status='complete',seconds=time.monotonic()-started,summary=descriptive(feature_rows(results)),
                        checks=dict(source_unchanged=True,store_unchanged=True,code_unchanged=True))
        (output/'report.md').write_text(report(results,selection,header['names']))
        manifest['report_sha256']=sha(output/'report.md'); shared.checkpoint(output,manifest,results)
        with ZipFile(output/'evidence.zip') as archive:
            audit.equal(archive.testzip(),None,'ZIP CRC')
            for code,result in results.items():
                audit.equal(json.loads(archive.read(code+'.json')),result,'ZIP readback')
        print(json.dumps(manifest['summary'],ensure_ascii=False),flush=True)
    except Exception as exc:
        manifest.update(status='failed',error=f'{type(exc).__name__}: {exc}')
        shared.checkpoint(output,manifest,results)
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    execute(parser.parse_args().output)
