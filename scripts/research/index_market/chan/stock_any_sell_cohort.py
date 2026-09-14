"""Section 31: frozen ten-stock validation of the unchanged any-sell policy."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, replace
import argparse
import json
import multiprocessing
from pathlib import Path
from statistics import mean
import time
from zipfile import ZipFile

from scripts.research.index_market.chan import stock_any_sell_study as policy
from scripts.research.index_market.chan import stock_sell_linkage_study as shared
from scripts.research.index_market.chan import stock_signal_chain_audit as audit
from scripts.research.index_market.chan import stock_sell_usage_audit as usage
from scripts.research.index_market.chan import stock_exit_study as old
from scripts.research.index_market.chan.minute_variant_a import VARIANT_A
from scripts.research.index_market.chan.minute_replay import replay
from scripts.research.index_market.chan.run_m0 import expanded
from scripts.research.index_market.chan.stock_research_store import StockResearchStore
from scripts.research.index_market.chan.stock_opportunity import safe_output, sha


@dataclass(frozen=True)
class CohortSpec:
    counts: tuple = (('000731.SZ',14),('002084.SZ',22),('002225.SZ',16),('002252.SZ',16),
                    ('002587.SZ',18),('300263.SZ',11),('300407.SZ',18),('603360.SH',17),
                    ('605186.SH',20),('688069.SH',11))
    min_positive_fraction: float = .5


SPEC = CohortSpec()


def validate_roster(statuses, origin, initial):
    expected = set(dict(SPEC.counts))
    for codes in ([x['code'] for x in statuses], origin['codes'], [x['ts_code'] for x in initial['stocks']]):
        if len(codes) != len(expected) or len(set(codes)) != len(codes) or set(codes) != expected:
            raise ValueError('frozen ten-stock roster mismatch')
        if any(not c.endswith(('.SH','.SZ')) for c in codes):
            raise ValueError('non SH/SZ stock forbidden')
    names = {s['ts_code']:s['name'] for s in initial['stocks']}
    if any(s['status'] != 'complete' or s['name'] != names[s['code']] for s in statuses):
        raise ValueError('incomplete stock or changed identity')
    return names


def load_header(store):
    manifest = store.read('exits/manifest.json')
    audit.equal(manifest['status'],'complete','exits status')
    setup = store.read('exits/setup.json',manifest['setup_sha256'])
    expected = asdict(old.SPEC); expected['source'] = store.original_path(old.SPEC.source)
    audit.equal(setup['spec'],json.loads(json.dumps(expected)),'frozen execution spec')
    audit.equal(setup['periods'],{p:list(v) for p,v in old.PERIODS.items()},'frozen periods')
    origin = store.read('calendar/source.json',setup['source_sha256'])
    initial = store.read('initial/source.json',origin['previous_source_sha256'])
    for obj in (setup,origin,initial):
        for path,h in obj['code_sha256'].items():
            store.verify_code(path,h)
    names = validate_roster(store.read('calendar/status_10.json'),origin,initial)
    aggregate = store.read('exits/aggregate.json',manifest['aggregate_sha256'])
    audit.equal(next(x['n'] for x in aggregate if x['period']=='full' and x['mode']=='sell'),
                sum(dict(SPEC.counts).values()),'163 frozen opportunities')
    return dict(days=initial['days'],names=names)


def validate_common(cases, events, times, code):
    if len(cases) != dict(SPEC.counts)[code] or len({c['signal_time'] for c in cases}) != len(cases):
        raise ValueError('frozen per-stock count or duplicate case')
    emap = {e['event_id']:e for e in events}
    for c in cases:
        es = [emap[k] for k in c['event_ids']]
        if (c['code'] != code or times[c['signal_index']] != c['signal_time'] or not es
                or any(not e['buy'] or e['signal_time'] != c['signal_time'] for e in es)
                or c['types'] != sorted({e['group'] for e in es})):
            raise ValueError('frozen buy identity mismatch')


def load_stock(store, header, code):
    cm = store.read(f'exits/{code}/manifest.json')
    dm = store.read(f'calendar/{code}/manifest.json',cm['source_manifest_sha256'])
    audit.equal((cm['status'],dm['status']),('complete','complete'),'stock source status')
    paths = [f'calendar/{code}/{f}' for f in ('input_30.json','input_60.json','full_events.json')]
    if sum(store.size(p) for p in paths)+store.size(f'exits/{code}/cases.json') > usage.SPEC.input_bytes:
        raise ValueError('stock input budget')
    obs, structure, events = [store.read(p,dm['artifacts_sha256'][Path(p).name]) for p in paths]
    for rows,freq in ((obs,30),(structure,60)):
        if (not 0 < len(rows) <= audit.SPEC.max_bars or rows[0]['time'][:10] != audit.SPEC.start
                or rows[-1]['time'][:10] != audit.SPEC.end
                or any(r['code'] != code or r['frequency'] != freq or r['price_basis'] != 'qfq' for r in rows)
                or any(a['time'] >= b['time'] for a,b in zip(rows,rows[1:]))):
            raise ValueError('input scope, price basis or time order')
    usage.validate_events(events,structure,code)
    cases = store.read(f'exits/{code}/cases.json',cm['artifacts_sha256']['cases.json'])
    lo,hi = old.PERIODS['full']
    common = [c for c in cases if lo <= c['signal_time'][:10] <= hi and
              set(c['arms']) == set(old.SPEC.arms) and all(a['status']=='closed' and
              a['exit_time'][:10] <= hi for a in c['arms'].values())]
    times,rows = usage.grid(obs,header['days'])
    validate_common(common,events,times,code)
    diagnostics = [usage.diagnose(c,events,structure,times,rows,old.SPEC.max_days*old.SPEC.bars_day) for c in common]
    audit.equal(diagnostics,store.read(f'sell_usage/{code}/diagnostics.json'),'original diagnostics')
    if any(d['differences'] for d in diagnostics):
        raise ValueError('original execution inconsistent')
    return dict(cases=common, events=events, structure=structure, times=times, rows=rows,
                diagnostics=diagnostics, membership=shared.freeze_membership(common))


def stock_worker(code, sender):
    started = time.monotonic()
    try:
        source = audit.source_gate()
        from ChanConfig import CChanConfig
        policy.require_original_a(expanded(CChanConfig(VARIANT_A.chan_config())),source['expanded_config'])
        store = StockResearchStore(); header = load_header(store); data = load_stock(store,header,code)
        spec = replace(VARIANT_A,codes=(code,),frequencies=(60,),replay_seconds=shared.SPEC.stock_seconds)
        events = replay(data['structure'],code,60,spec)
        audit.equal(events,data['events'],'complete original A ledger')
        pairs = policy.compare(data['cases'],events,data['structure'],data['times'],data['rows'],data['diagnostics'])
        checks = shared.check_prefix(data['structure'],code,spec,events)
        checks['executions'] = policy.execution_prefix(data['cases'],pairs,events,data['times'],data['rows'])
        store.verify_unchanged()
        audit.equal(audit.source_gate(),source,'source unchanged')
        rss = audit.budget(started,started,shared.SPEC)
        result = dict(pairs=pairs,checks=checks,membership=data['membership'],event_count=len(events),
            event_sha256=audit.sha(audit.encoded(events)),consumed_records=store.consumed,
            source_sha256=audit.sha(audit.encoded(source)),seconds=time.monotonic()-started,rss_bytes=rss)
        if len(audit.encoded(result)) > shared.SPEC.output_bytes:
            raise ValueError('unit evidence budget')
        sender.send(dict(status='complete',result=result))
    except Exception as exc:
        sender.send(dict(status='failed',error=f'{type(exc).__name__}: {exc}'))
    finally:
        sender.close()


def run_process(code, started):
    context = multiprocessing.get_context('spawn')
    receiver,sender = context.Pipe(duplex=False)
    process = context.Process(target=stock_worker,args=(code,sender))
    stock_start = time.monotonic()
    process.start(); sender.close()
    try:
        while not receiver.poll(10):
            audit.budget(stock_start,started,shared.SPEC)
            if not process.is_alive():
                raise RuntimeError('stock process exited without evidence')
            print(f'{code}: verification running, {time.monotonic()-stock_start:.0f}s',flush=True)
        payload = receiver.recv()
        process.join(timeout=2)
        if process.is_alive() or process.exitcode != 0 or payload['status'] != 'complete':
            raise RuntimeError(payload.get('error','stock process did not complete'))
        audit.budget(stock_start,started,shared.SPEC)
        return payload['result']
    finally:
        if process.is_alive():
            process.terminate(); process.join(timeout=2)
        receiver.close()


def group_summary(results, selection, codes):
    selected = {c:results[c] for c in codes}
    summary = shared.summarize(selected,selection)
    summary['pooled'] = {kind:{p:shared.metrics([x for c in codes for x in results[c]['pairs']
        if x['signal_time'] in selection['membership'][c][kind][p]]) for p in old.PERIODS}
        for kind in ('periods','nonoverlap')}
    return summary


def screening(results, selection, codes):
    summary = group_summary(results,selection,codes)
    all_pairs = [p for c in codes for p in results[c]['pairs']]
    if not codes or not all_pairs or summary['all']['unclosed']:
        return dict(passed=False,reason='empty or unclosed cohort')
    by_stock = {c:shared.metrics(results[c]['pairs']) for c in codes}
    if any(not v['n'] or v['unclosed'] for v in by_stock.values()):
        return dict(passed=False,reason='empty or unclosed stock')
    best = max(sorted(codes),key=lambda c:by_stock[c]['delta']['mean'])
    rest = [p for c in codes if c!=best for p in results[c]['pairs']]
    without_stock = shared.metrics(rest)
    positive = sum(x['delta']['mean'] > 0 for x in by_stock.values())
    def positive_mean(m):
        return bool(m['n'] and not m['unclosed'] and m['delta']['mean'] > 0)
    gates = dict(pooled_positive=summary['all']['delta']['mean']>0,
        stock_equal_positive=mean(v['delta']['mean'] for v in by_stock.values())>0,
        at_least_half_stocks=positive>=len(codes)*SPEC.min_positive_fraction,
        nonoverlap_positive=positive_mean(summary['pooled']['nonoverlap']['full']),
        early_positive=positive_mean(summary['pooled']['periods']['early']),
        late_positive=positive_mean(summary['pooled']['periods']['late']),
        without_best_trade_positive=summary['all']['delta']['without_best'] is not None and
                                   summary['all']['delta']['without_best']>0,
        without_best_stock_positive=positive_mean(without_stock),
        mae_not_worse=summary['all']['after']['adverse']>=summary['all']['before']['adverse'])
    return dict(passed=all(gates.values()),gates=gates,positive_stocks=positive,total_stocks=len(codes),
                best_stock=best,without_best_stock=without_stock)


def report(groups, screen, names):
    lines=['# 原A取消编号配对：10股扩批', '',
        '只扩大覆盖，不改原A、买点或成交规则。输入2021-09-09—2026-09-08；评估2022-09-22起；60分钟识别、30分钟执行。', '',
        '主要观察组为其余八股133次，全10股163次作为辅助；原两股30次单列。均为已见的存续股票历史样本，不是未见样本或分仓账户。', '',
        '| 样本组 | n | 原平均毛收益 | 新平均毛收益 | 增量 | 改善/变差/不变 | 原/新卖点退出 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    def row(name,m):
        if not m['n'] or m['unclosed']:
            return f"| {name} | {m['n']} | 未闭合或空组，不能比较 | | | | |"
        b,a,d=m['before'],m['after'],m['delta']
        return f"| {name} | {m['n']} | {b['mean']:.2%} | {a['mean']:.2%} | {d['mean']*100:+.2f}pp | {d['better']}/{d['worse']}/{d['unchanged']} | {b['sell_exits']}/{a['sell_exits']} |"
    lines.extend(row(k,s['all']) for k,s in groups.items())
    primary=groups['remaining8']['all']
    if primary['n'] and not primary['unclosed']:
        b,a=primary['before'],primary['after']
        lines.extend(['',f"八股胜率{b['win']:.2%}→{a['win']:.2%}；持有{b['holding_days']:.2f}→{a['holding_days']:.2f}市场日；MAE {b['adverse']:.2%}→{a['adverse']:.2%}；MFE {b['favorable']:.2%}→{a['favorable']:.2%}。",
            f"八股股票等权原/新均值：{groups['remaining8']['stock_equal_weight_mean']['before']:.2%}/{groups['remaining8']['stock_equal_weight_mean']['after']:.2%}。固定60日机会等权参照：{primary['fixed60']['mean']:.2%}。"])
    lines.extend(['','## 逐股结果','', '| 股票 | n | 原平均毛收益 | 新平均毛收益 | 增量 | 改善/变差/不变 | 原/新卖点退出 |',
                  '| --- | ---: | ---: | ---: | ---: | ---: | ---: |'])
    lines.extend(row(f'{c} {names[c]}',v['periods']['full']) for c,v in groups['all10']['stocks'].items())
    lines.extend(['','## 八股阶段及非重叠对照','',
                  '| 子集 | n | 原平均毛收益 | 新平均毛收益 | 增量 | 改善/变差/不变 | 原/新卖点退出 |',
                  '| --- | ---: | ---: | ---: | ---: | ---: | ---: |'])
    lines.extend(row(f'{kind}/{p}',m) for kind,g in groups['remaining8']['pooled'].items() for p,m in g.items())
    lines.extend(['','## 预先声明的初筛','',f"通过：{screen['passed']}。这不是策略有效认证。",''])
    lines += [f'- {k}: {v}' for k,v in screen.get('gates',{}).items()]
    lines.extend(['','## 验证与限制','',
        '逐股原事件、原退出和独立新退出复核；冻结分母、阶段/非重叠名单及前缀/未来扰动见manifest和证据ZIP。所有逐笔改变都在ZIP内，未按表现挑案例。', '',
        'MAE是相对入场价浮亏，不是账户回撤；未扣成本、未做同持有期随机基准、未运行分仓账户。不报告IID显著性、年化或复利净值；不能以工程通过代替方法有效。',''])
    return '\n'.join(lines)


def execute(output):
    output=safe_output(output); started=time.monotonic()
    source=audit.source_gate(); store=StockResearchStore(); header=load_header(store)
    selection=dict(opportunities=[],membership={})
    for code,_ in SPEC.counts:
        data=load_stock(store,header,code)
        selection['opportunities'].extend({k:d[k] for k in audit.SELECTION_FIELDS} for d in data['diagnostics'])
        selection['membership'][code]=data['membership']
        del data
        audit.budget(started,started,shared.SPEC)
    audit.equal(Counter(x['category'] for x in selection['opportunities']),
        Counter(matched_sell_exit=29,no_sell_in_trigger_window=100,nonmatching_only=34),'original category totals')
    codes=[c for c,_ in SPEC.counts]; remaining=[c for c in codes if c not in policy.SPEC.codes]
    audit.equal((len(remaining),len(selection['opportunities'])),(8,163),'cohort denominator')
    output.mkdir(); (output/'selection.json').write_bytes(audit.encoded(selection))
    paths=sorted(Path(__file__).parent.glob('*.py')); hashes={str(p):sha(p) for p in paths}
    manifest=dict(status='running',spec=asdict(SPEC),primary_codes=remaining,source=source,
        validation_limits={k:getattr(shared.SPEC,k) for k in ('cutoffs','future_multiplier','stock_seconds',
            'total_seconds','memory_bytes','output_bytes','max_files')},
        code_sha256=hashes,input_store=store.receipt,consumed_records=store.consumed,completed=[],
        plan_design_sha256=sha(audit.PLAN),selection_sha256=sha(output/'selection.json'))
    results={}; shared.checkpoint(output,manifest,results)
    try:
        for i,code in enumerate(codes):
            print(f'{i+1}/10 {code} {header["names"][code]}',flush=True)
            result=run_process(code,started)
            audit.equal(result.pop('membership'),selection['membership'][code],'preselected subgroups')
            audit.equal(result['source_sha256'],audit.sha(audit.encoded(source)),'worker source')
            for key,h in result.pop('consumed_records').items():
                audit.equal(h,store.consumed[key],'worker inputs')
            results[code]=result; manifest['completed'].append(code)
            shared.checkpoint(output,manifest,results)
            print(f'{i+1}/10 complete: {len(result["pairs"])} opportunities, {result["seconds"]:.2f}s',flush=True)
        store.verify_unchanged(); audit.equal(audit.source_gate(),source,'source unchanged')
        audit.equal({str(p):sha(p) for p in paths},hashes,'code unchanged')
        groups={name:group_summary(results,selection,cs) for name,cs in
                (('remaining8',remaining),('all10',codes),('previous2',list(policy.SPEC.codes)))}
        screen=screening(results,selection,remaining)
        manifest.update(status='complete',seconds=time.monotonic()-started,summary=groups,screening=screen,
                        checks=dict(source_unchanged=True,store_unchanged=True,code_unchanged=True))
        (output/'report.md').write_text(report(groups,screen,header['names']))
        manifest['report_sha256']=sha(output/'report.md'); shared.checkpoint(output,manifest,results)
        with ZipFile(output/'evidence.zip') as z:
            audit.equal(z.testzip(),None,'ZIP CRC')
            for code in codes: audit.equal(json.loads(z.read(code+'.json')),results[code],'readback')
        print(json.dumps(dict(primary=groups['remaining8']['all'],screening=screen),ensure_ascii=False),flush=True)
    except Exception as exc:
        manifest.update(status='failed',error=f'{type(exc).__name__}: {exc}',seconds=time.monotonic()-started)
        shared.checkpoint(output,manifest,results)
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    execute(parser.parse_args().output)
