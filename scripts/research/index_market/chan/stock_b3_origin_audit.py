"""Section 33: capture actual B3 producer centers; no new exit simulation."""
from __future__ import annotations

import argparse
from collections import Counter
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
from scripts.research.index_market.chan import stock_exit_structure_review as review
from scripts.research.index_market.chan import stock_sell_linkage_study as shared
from scripts.research.index_market.chan import stock_signal_chain_audit as audit
from scripts.research.index_market.chan.minute_replay import replay
from scripts.research.index_market.chan.minute_variant_a import VARIANT_A
from scripts.research.index_market.chan.run_m0 import expanded
from scripts.research.index_market.chan.stock_opportunity import safe_output, sha
from scripts.research.index_market.chan.stock_research_store import StockResearchStore


@dataclass(frozen=True)
class OriginSpec:
    counts: tuple = tuple(zip(review.SPEC.codes, (6,7,9,6,8,10,9,3), strict=True))
    paths: tuple = (('3a','treat_bsp3_after','zs','next_seg'), ('3b','treat_bsp3_before','cmp_zs','seg'))
    max_origins: int = 8
    cases: tuple = (('300263.SZ','2024-04-10 15:00:00'), ('688069.SH','2025-05-23 11:30:00'))


SPEC = OriginSpec()


def distance(price, level):
    if price <= 0:
        raise ValueError('nonpositive price')
    return (price-level)/price


def source_names(raw_type, caller_name):
    matches = [x for x in SPEC.paths if x[0] == raw_type and x[1] == caller_name]
    if len(matches) != 1:
        raise ValueError('unexpected B3 producer path')
    return matches[0][2:]


def pack(facts, **refs):
    return dict(refs=refs, objects={k:json.loads(v) for k,v in facts.objects.items()})


def origin_snapshot(rows, index, bi, center, segment, config):
    facts=audit.Facts(rows); facts.now=index
    return dict(index=index, time=rows[index]['time'], **pack(facts,
        line=facts.line(bi), center=facts.center(center), segment=facts.line(segment),
        config=facts.value(config)))


def remember(records, point, raw, index, source, center, segment):
    """Object identity matters: a cleared/rebuilt BSP cannot inherit old provenance."""
    bucket=records.setdefault(point,{})
    if raw not in bucket or bucket[raw]['index'] != index:
        bucket[raw]=dict(index=index, alternatives=[])
    alternatives=bucket[raw]['alternatives']
    if not any(x['source']==source for x in alternatives):
        alternatives.append(dict(source=source,center=center,segment=segment))
    if len(alternatives)>SPEC.max_origins:
        raise ValueError('origin multiplicity budget')


def freeze_origins(rows, event, snapshot, origins, kl):
    objects=snapshot['objects']; refs=snapshot['refs']
    line=objects[refs['point']['line']]
    raw_types=sorted(set(event['types']) & {'3a','3b'})
    frozen=[]; missing=[]
    for raw in raw_types:
        if raw not in origins:
            missing.append(raw); continue
        for item in origins[raw]['alternatives']:
            source=item['source']; center=item['center']; segment=item['segment']
            facts=audit.Facts(rows); facts.now=event['signal_index']
            current=pack(facts, center=facts.center(center),segment=facts.line(segment))
            original=source['objects'][source['refs']['center']]
            actual=current['objects'][current['refs']['center']]
            source_line=source['objects'][source['refs']['line']]
            audit.equal(source['index']<=event['signal_index'], True, 'origin as of')
            if source_line['end_value'] < original['high']:
                raise ValueError('source B3 pullback violates actual center')
            context=objects[refs['latest_sure_center']] if refs['latest_sure_center'] else None
            frozen.append(dict(raw_type=raw, source=source,current=current,
                center_in_current_list=any(z is center for z in kl.zs_list.zs_lst),
                boundary_changed=(original['low'],original['high']) != (actual['low'],actual['high']),
                line_changed=source_line != line,
                same_as_latest_sure_center=context == actual,
                center_sure=bool(actual['sure']), segment_sure=bool(segment.is_sure),
                geometry_at_confirmation=line['end_value'] >= actual['high'],
                close_to_center=distance(snapshot['close'],actual['high']),
                close_to_pullback=distance(snapshot['close'],line['end_value'])))
    ambiguous=len(frozen)>len(raw_types)
    return dict(event=event,snapshot=snapshot,origins=frozen,missing_types=missing,
                status='missing' if missing else 'ambiguous' if ambiguous else 'unique')


class OriginObserver:
    def __init__(self, rows, targets, add_code):
        self.rows=rows;self.targets={e['event_id']:e for e in targets};self.add_code=add_code
        if len(self.targets)!=len(targets): raise ValueError('duplicate targets')
        self.indices={e['bi_index'] for e in targets};self.last=max(e['signal_index'] for e in targets)
        self.records={};self.frozen={};self.captured_calls=0

    def trace(self, frame, event, arg):
        if event=='call' and frame.f_code is self.add_code:
            frame.f_trace_lines=False
            return self.trace
        if event!='return' or frame.f_code is not self.add_code:
            return None
        local=frame.f_locals; bi=local['bi']; raw=local['bs_type'].value
        if raw not in {'3a','3b'} or type(bi).__name__!='CBi' or bi.dir.name!='DOWN' or bi.idx not in self.indices:
            return None
        root=frame.f_back
        while root is not None and root.f_code is not replay.__code__:
            root=root.f_back
        if root is None:
            raise ValueError('B3 call outside original replay')
        state=root.f_locals;index=state['i'];kl=state['kl']
        if index>self.last or local['self'] is not kl.bs_point_lst:
            return None
        point=local['self'].bsp_store_flat_dict.get(bi.idx)
        if point is None or raw not in {t.value for t in point.type}:
            return None  # A rejected attempt is not an origin.
        parent=frame.f_back;args=parent.f_locals
        center_name,segment_name=source_names(raw,parent.f_code.co_name)
        center,segment=args[center_name],args[segment_name]
        source=origin_snapshot(self.rows,index,bi,center,segment,args['BSP_CONF'])
        source.update(raw_type=raw,function=parent.f_code.co_name,line=parent.f_lineno)
        remember(self.records,point,raw,index,source,center,segment)
        self.captured_calls+=1
        return None

    def __call__(self, changes):
        frame=sys._getframe(1)
        if frame.f_code is not replay.__code__:
            raise ValueError('unexpected replay callback')
        state=frame.f_locals;kl=state['kl']
        for e in state['new']:
            if e['event_id'] not in self.targets: continue
            audit.equal(e,self.targets[e['event_id']],'first confirmation identity')
            point=kl.bs_point_lst.bsp_store_flat_dict[e['bi_index']]
            snap=review.snapshot(kl,self.rows,e)
            self.frozen[e['event_id']]=freeze_origins(self.rows,e,snap,self.records.get(point,{}),kl)
        active=set(kl.bs_point_lst.bsp_store_flat_dict.values())
        self.records={p:r for p,r in self.records.items() if p in active}


def observe(rows, code, targets, spec):
    from BuySellPoint.BSPointList import CBSPointList
    if sys.gettrace() is not None:
        raise ValueError('existing tracer must not be replaced')
    observer=OriginObserver(rows,targets,CBSPointList.add_bs.__code__)
    try:
        sys.settrace(observer.trace)
        events=replay(rows,code,60,spec,sink=observer)
    finally:
        sys.settrace(None)
    audit.equal(set(observer.frozen),set(observer.targets),'all 58 target identities')
    return events,observer.frozen,observer.captured_calls


def select_targets(data, code):
    ids={k for p in data['cases'] for k in p['event_ids']}
    targets=[e for e in data['events'] if e['event_id'] in ids and e['group']=='B3']
    if len(targets)!=dict(SPEC.counts)[code] or any(not e['buy'] for e in targets):
        raise ValueError('frozen B3 scope')
    return targets


def case_ids(targets):
    selected=[]
    for raw in ('3a','3b'):
        pool=[e for e in targets if raw in e['types']]
        if not pool:raise ValueError('required B3 path missing')
        selected.append(min(pool,key=lambda e:(e['signal_time'],e['code']))['event_id'])
    for code,timestamp in SPEC.cases:
        matches=[e['event_id'] for e in targets if e['code']==code and e['signal_time']==timestamp]
        if len(matches)!=1:raise ValueError('previous illustrative case missing')
        selected.extend(matches)
    return list(dict.fromkeys(selected))


def worker(code, expected_ids, sender):
    started=time.monotonic()
    try:
        source=audit.source_gate()
        from ChanConfig import CChanConfig
        policy.require_original_a(expanded(CChanConfig(VARIANT_A.chan_config())),source['expanded_config'])
        store=StockResearchStore();header=cohort.load_header(store);data=cohort.load_stock(store,header,code)
        targets=select_targets(data,code);audit.equal([e['event_id'] for e in targets],expected_ids,'frozen selection')
        spec=replace(VARIANT_A,codes=(code,),frequencies=(60,),replay_seconds=shared.SPEC.stock_seconds)
        events,origins,calls=observe(data['structure'],code,targets,spec)
        audit.equal(events,data['events'],'original full ledger')
        cutoff=max(e['signal_index'] for e in targets)
        pe,po,_=observe(data['structure'][:cutoff+1],code,targets,spec)
        audit.equal(pe,[e for e in events if e['signal_index']<=cutoff],'prefix events')
        audit.equal(po,origins,'prefix provenance')
        future=[dict(r,**{k:r[k]*shared.SPEC.future_multiplier for k in ('open','high','low','close')})
                if i>cutoff else dict(r) for i,r in enumerate(data['structure'])]
        fe,fo,_=observe(future,code,targets,spec)
        audit.equal([e for e in fe if e['signal_index']<=cutoff],pe,'future events')
        audit.equal(fo,origins,'future provenance')
        # Execution observations are deliberately attached AFTER as-of provenance checks.
        cases={p['signal_time']:p for p in data['cases']}
        for obj in origins.values():
            entry=cases[obj['event']['signal_time']]['arms']['sell']
            obj['execution_observation']=dict(time=entry['entry_bar'],price=entry['entry_price'],
                distances=[dict(raw_type=o['raw_type'],
                    to_center=distance(entry['entry_price'],o['current']['objects'][o['current']['refs']['center']]['high']),
                    to_pullback=distance(entry['entry_price'],obj['snapshot']['objects'][obj['snapshot']['refs']['point']['line']]['end_value']))
                    for o in obj['origins']])
        store.verify_unchanged();audit.equal(audit.source_gate(),source,'source unchanged')
        result=dict(origins=origins,event_count=len(events),captured_calls=calls,
            checks=dict(full_ledger=True,prefix=True,future=True,cutoff=data['structure'][cutoff]['time']),
            consumed_records=store.consumed,seconds=time.monotonic()-started,
            rss_bytes=audit.budget(started,started,shared.SPEC))
        if len(audit.encoded(result))>shared.SPEC.output_bytes:raise ValueError('unit evidence budget')
        sender.send(dict(status='complete',result=result))
    except Exception as exc:
        sender.send(dict(status='failed',error=f'{type(exc).__name__}: {exc}'))
    finally:sender.close()


def run_process(code, ids, started):
    ctx=multiprocessing.get_context('spawn');receiver,sender=ctx.Pipe(duplex=False)
    process=ctx.Process(target=worker,args=(code,ids,sender));stock_start=time.monotonic()
    process.start();sender.close()
    try:
        while not receiver.poll(10):
            audit.budget(stock_start,started,shared.SPEC)
            if not process.is_alive():raise RuntimeError('worker exited without evidence')
            print(f'{code}: provenance replay {time.monotonic()-stock_start:.0f}s',flush=True)
        payload=receiver.recv();process.join(timeout=2)
        if process.is_alive() or process.exitcode!=0 or payload['status']!='complete':
            raise RuntimeError(payload.get('error','worker incomplete'))
        audit.budget(stock_start,started,shared.SPEC)
        return payload['result']
    finally:
        if process.is_alive():process.terminate();process.join(timeout=2)
        receiver.close()


def summary(results):
    all_rows=[o for r in results.values() for o in r['origins'].values()]
    sources=[s for o in all_rows for s in o['origins']]
    return dict(n=len(all_rows),status=dict(Counter(o['status'] for o in all_rows)),
        source_n=len(sources),paths=dict(Counter(s['raw_type'] for s in sources)),
        center_sure=sum(s['center_sure'] for s in sources),segment_sure=sum(s['segment_sure'] for s in sources),
        boundary_changed=sum(s['boundary_changed'] for s in sources),line_changed=sum(s['line_changed'] for s in sources),
        center_detached=sum(not s['center_in_current_list'] for s in sources),
        same_as_latest=sum(s['same_as_latest_sure_center'] for s in sources),
        geometry_false=sum(not s['geometry_at_confirmation'] for s in sources),
        generated_before_confirmation=sum(s['source']['time']<o['event']['signal_time'] for o in all_rows for s in o['origins']),
        close_below_center=sum(s['close_to_center']<0 for s in sources),
        entry_at_or_below_center=sum(d['to_center']<=0 for o in all_rows for d in o['execution_observation']['distances']))


def report(results,selection,names):
    stats=summary(results);objects={k:o for r in results.values() for k,o in r['origins'].items()}
    lines=['# B3买入依据追溯：阶段性可行性审计','',
        '2026-09-14。原八股133次共同机会中58次含B3，其余75次不在本次追溯范围；未按成绩筛选。输入2021-09-09—2026-09-08、评估2022-09-22起；60分钟原A、前复权。存续股票/共同闭合选择偏差仍在。','',
        f'来源状态：{stats["status"]}；共{stats["source_n"]}条来源。3a/3b分别来自真实add_bs调用帧，不是事后最近中枢。','',
        f'实际中枢已确认{stats["center_sure"]}条；绑定段已确认{stats["segment_sure"]}条；与最近已确认中枢完全同一上下文{stats["same_as_latest"]}条。', '',
        f'生成早于首次确认{stats["generated_before_confirmation"]}条，期间中枢边界变化{stats["boundary_changed"]}条、笔快照变化{stats["line_changed"]}条；确认时中枢对象不在当前表{stats["center_detached"]}条。', '',
        f'确认时低点不回来源中枢条件不成立{stats["geometry_false"]}条；确认收盘低于上沿{stats["close_below_center"]}条；次执行柱开盘不高于上沿{stats["entry_at_or_below_center"]}条。后者是次柱观察，未放入首次确认特征。', '',
        '## 逐股覆盖','', '| 股票 | B3事件 | 唯一 | 缺失 | 多义 |', '| --- | ---: | ---: | ---: | ---: |']
    for code,result in results.items():
        counts=Counter(o['status'] for o in result['origins'].values())
        lines.append(f'| {code} {names[code]} | {len(result["origins"])} | {counts["unique"]} | {counts["missing"]} | {counts["ambiguous"]} |')
    for raw in ('3a','3b'):
        ss=[s for o in objects.values() for s in o['origins'] if s['raw_type']==raw]
        if not ss:continue
        lines+=['',f'## {raw} 距离（只描述，不按距离筛选）','']
        for key,title in [('close_to_center','确认收盘到中枢上沿'),('close_to_pullback','确认收盘到回踩低点')]:
            vs=[s[key] for s in ss]
            lines.append(f'- {title}：最小{min(vs):.2%}、中位{median(vs):.2%}、最大{max(vs):.2%}；n={len(vs)}。')
    for key in selection['cases']:
        o=objects[key];e=o['event'];snap=o['snapshot'];entry=o['execution_observation']
        lines+=['',f'## 案例：{names[e["code"]]} {e["signal_time"]}','',
            f'原始类型 {"/".join(e["types"])}；首次确认收盘{snap["close"]:.4f}；下一执行柱{entry["time"]}开盘{entry["price"]:.4f}。来源状态{o["status"]}。','']
        for s in o['origins']:
            z=s['current']['objects'][s['current']['refs']['center']]
            line=snap['objects'][snap['refs']['point']['line']]
            lines.append(f'- {s["raw_type"]}真实来源：{s["source"]["function"]}，最后生成{s["source"]["time"]}。中枢区间[{z["low"]:.4f}, {z["high"]:.4f}]，范围{z["begin"]["time"]}—{z["end"]["time"]}，中枢已确认={s["center_sure"]}，绑定段已确认={s["segment_sure"]}。')
            lines.append(f'- 回踩低点{line["end_value"]:.4f}（{line["end"]["time"]}）；确认价到中枢上沿距离{s["close_to_center"]:.2%}、到回踩低点{s["close_to_pullback"]:.2%}；与最近已确认中枢相同={s["same_as_latest_sure_center"]}。')
    lines+=['','## 阶段结论与停止条件','',
        '已证实的只是来源绑定与当前算法口径，不能称收益有效。此前取消卖点编号配对的后期失败结论不变；不能因追溯成功就自动启动回测。','',
        '中枢上沿与回踩低点是不同的失效假设，须分开讨论。未确认结构必须说明固定哪个时刻；来源多义/缺失/确认前变化必须先解释，不能用最低或最高线补齐。', '',
        '本轮未计算未来破位退出成绩、费用或股数账户。所有58条来源在ZIP中；全事件、前缀及未来扰动验证只证明工程时序一致，不是样本外有效性。']
    return '\n'.join(lines)+'\n'


def execute(output):
    output=safe_output(output);started=time.monotonic();source=audit.source_gate()
    store=StockResearchStore();header=cohort.load_header(store)
    paths=sorted(Path(__file__).parent.glob('*.py'));hashes={str(p):sha(p) for p in paths}
    targets=[];pairs=[];by_stock={}
    for code,_ in SPEC.counts:
        audit.budget(started,started,shared.SPEC)
        data=cohort.load_stock(store,header,code);ts=select_targets(data,code);targets.extend(ts)
        by_stock[code]=[e['event_id'] for e in ts]
        pairs.extend(policy.compare(data['cases'],data['events'],data['structure'],data['times'],data['rows'],data['diagnostics']))
        del data
    audit.equal(audit.sha(audit.encoded(pairs)),review.SPEC.pairs_sha256,'133 frozen pairs')
    selection=dict(targets=targets,by_stock=by_stock,cases=case_ids(targets),all_opportunities=133,b3_opportunities=len(targets))
    del pairs
    output.mkdir(parents=True);audit.write_json(output/'selection.json',selection)
    manifest=dict(status='running',source=source,spec=asdict(SPEC),code_sha256=hashes,
        consumed_records=store.consumed,input_store=store.receipt,plan_design_sha256=sha(audit.PLAN),
        selection_sha256=sha(output/'selection.json'),completed=[],
        limits={k:getattr(shared.SPEC,k) for k in ('stock_seconds','total_seconds','memory_bytes','output_bytes','max_files')})
    results={};shared.checkpoint(output,manifest,results)
    try:
        for i,(code,_) in enumerate(SPEC.counts):
            print(f'{i+1}/8 {code} {header["names"][code]}',flush=True)
            result=run_process(code,by_stock[code],started)
            for k,h in result.pop('consumed_records').items():audit.equal(store.consumed[k],h,'worker inputs')
            results[code]=result;manifest['completed'].append(code);shared.checkpoint(output,manifest,results)
            print(f'{i+1}/8 complete: {len(result["origins"])} B3, {result["seconds"]:.2f}s',flush=True)
        store.verify_unchanged();audit.equal(audit.source_gate(),source,'source unchanged')
        audit.equal({str(p):sha(p) for p in paths},hashes,'code unchanged')
        stats=summary(results);audit.equal(stats['n'],58,'full B3 denominator')
        manifest.update(status='complete',summary=stats,seconds=time.monotonic()-started,
                        checks=dict(store_unchanged=True,code_unchanged=True,source_unchanged=True))
        (output/'report.md').write_text(report(results,selection,header['names']))
        manifest['report_sha256']=sha(output/'report.md');shared.checkpoint(output,manifest,results)
        with ZipFile(output/'evidence.zip') as z:
            audit.equal(z.testzip(),None,'ZIP CRC')
            for code,result in results.items():audit.equal(json.loads(z.read(code+'.json')),result,'ZIP readback')
        print(json.dumps(stats,ensure_ascii=False),flush=True)
    except Exception as exc:
        manifest.update(status='failed',error=f'{type(exc).__name__}: {exc}')
        shared.checkpoint(output,manifest,results)
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    execute(parser.parse_args().output)
