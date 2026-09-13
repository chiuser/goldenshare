"""Section 30: unchanged A ledger, any numbered sell exits frozen entries."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import time
from zipfile import ZipFile

from scripts.research.index_market.chan import stock_sell_linkage_study as shared
from scripts.research.index_market.chan import stock_signal_chain_audit as audit
from scripts.research.index_market.chan import stock_sell_usage_audit as usage
from scripts.research.index_market.chan import stock_exit_study as old
from scripts.research.index_market.chan.minute_variant_a import VARIANT_A
from scripts.research.index_market.chan.minute_replay import replay
from scripts.research.index_market.chan.run_m0 import expanded
from scripts.research.index_market.chan.stock_opportunity import safe_output, sha


@dataclass(frozen=True)
class AnySellSpec:
    codes: tuple = audit.SPEC.codes
    exit_groups: tuple = ('S1', 'S2', 'S3')


SPEC = AnySellSpec()


def require_original_a(actual, frozen):
    audit.equal(actual, frozen, 'unchanged expanded A configuration')
    if actual['bs_point_conf']['s_conf']['bsp3_follow_1'] is not True:
        raise ValueError('section 29 sell configuration is forbidden')


def sell_triggers(events, indices):
    return {indices[e['signal_time']] for e in events
            if not e['buy'] and e['group'] in SPEC.exit_groups}


def independent(case, arm, events, structure, times, rows):
    if arm['status'] != 'closed':
        return None
    # Eligibility projection ONLY: the archived buy event and case are untouched.
    projection = dict(case, types=['B'+g[1:] for g in SPEC.exit_groups],
                      arms=dict(case['arms'], sell=arm))
    result = usage.diagnose(projection, events, structure, times, rows,
                            old.SPEC.max_days*old.SPEC.bars_day)
    result.update(types=list(case['types']), eligible_sell_groups=list(SPEC.exit_groups))
    if result['differences']:
        raise ValueError('independent any-sell execution mismatch')
    return result


def compare(cases, events, structure, times, rows, previous):
    indices = {t: i for i, t in enumerate(times)}
    all_sells = sell_triggers(events, indices)
    categories = {d['signal_time']: d['category'] for d in previous}
    pairs = []
    for c in cases:
        before = old.simulate(times, rows, c['signal_index'], 'sell', shared.triggers(c, events, indices))
        audit.equal(before, c['arms']['sell'], 'original execution all fields')
        after = old.simulate(times, rows, c['signal_index'], 'sell', all_sells)
        diagnosis = independent(c, after, events, structure, times, rows)
        category = categories[c['signal_time']]
        if category == audit.NO_SELL:
            audit.equal(after, before, 'no-sell window cannot change')
        used = [e['event_id'] for e in events if not e['buy'] and e['group'] in SPEC.exit_groups
                and e['signal_time'] == after.get('trigger_time')]
        pairs.append(dict(code=c['code'], signal_time=c['signal_time'], types=c['types'],
            event_ids=c['event_ids'], before=before, after=after, fixed60=c['arms']['fixed60'],
            old_category=category, new_category=diagnosis['category'] if diagnosis else 'unclosed',
            independent=diagnosis, used_sell_event_ids=used,
            delta=after['return_value']-before['return_value'] if after['status']=='closed' else None))
    audit.equal(len(pairs), len(cases), 'unchanged denominator')
    return pairs


def execution_prefix(cases, pairs, events, times, rows):
    checks = []
    for day in shared.SPEC.cutoffs:
        n = sum(t[:10] <= day for t in times)
        index = {t: i for i, t in enumerate(times[:n])}
        triggers = sell_triggers([e for e in events if e['signal_time'][:10] <= day], index)
        checked = []
        for c, p in zip(cases, pairs, strict=True):
            audit.equal(c['signal_time'], p['signal_time'], 'prefix pair identity')
            if (c['signal_index']+old.SPEC.max_days*old.SPEC.bars_day >= n or
                    p['after']['status'] != 'closed' or p['after']['exit_index'] >= n):
                continue
            truncated = old.simulate(times[:n], rows[:n], c['signal_index'], 'sell', triggers)
            audit.equal(truncated, p['after'], 'execution prefix')
            checked.append(c['signal_time'])
        checks.append(dict(cutoff=day, checked=checked, not_checked=len(cases)-len(checked),
                           exclusion='original full horizon or exit not within prefix'))
    return checks


def report(summary, results):
    lines = ['# 原A识别不变：取消卖点编号配对', '',
        '输入2021-09-09—2026-09-08；评估2022-09-22起；60分钟识别、30分钟执行。', '',
        '只把对应卖类改成S1/S2/S3均可退出；三卖前置条件仍True，原买卖事件零变化。固定两股30次机会，不是分仓账户收益。', '',
        '| 股票/子集/阶段 | n | 原毛收益 | 新毛收益 | 增量 | 原/新卖点退出 | 改善/变差/不变 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    table = [('全部/机会等权/full', summary['all'])]
    for code, stock in summary['stocks'].items():
        for kind in ('periods','nonoverlap'):
            table.extend((f'{code}/{kind}/{p}', m) for p, m in stock[kind].items())
    for name, m in table:
        if not m['n'] or m['unclosed']:
            lines.append(f"| {name} | {m['n']} | 不可比较：未闭合{m['unclosed']} | | | | |")
            continue
        b, a, d = m['before'], m['after'], m['delta']
        lines.append(f"| {name} | {m['n']} | {b['mean']:.2%} | {a['mean']:.2%} | {d['mean']*100:+.2f}pp | {b['sell_exits']}/{a['sell_exits']} | {d['better']}/{d['worse']}/{d['unchanged']} |")
    m = summary['all']
    if m['n'] and not m['unclosed']:
        lines.extend(['', f"胜率：{m['before']['win']:.2%}→{m['after']['win']:.2%}；平均持有：{m['before']['holding_days']:.2f}→{m['after']['holding_days']:.2f}市场日；平均MAE：{m['before']['adverse']:.2%}→{m['after']['adverse']:.2%}。",
            f"固定60日参照均值{m['fixed60']['mean']:.2%}。剔除最大改善后的平均增量：{m['delta']['without_best']*100:+.4f}个百分点。", ''])
    lines.extend(['## 窗口分类转移', ''])
    lines += [f'- {key}: {n}' for key, n in sorted(summary['categories'].items())]
    lines.extend(['', '## 所有退出发生变化的案例', '',
        '| 股票/买点确认/买类 | 新采用卖点确认/卖类 | 新退出柱开盘 | 原退出 | 原/新收益 |',
        '| --- | --- | --- | --- | ---: |'])
    for code, r in results.items():
        for p in r['pairs']:
            if p['after'] == p['before']:
                continue
            if p['after']['status'] != 'closed':
                lines.append(f"| {code}/{p['signal_time']} | 未闭合 | | | |")
                continue
            types = sorted({key.rsplit('|',1)[1] for key in p['used_sell_event_ids']})
            lines.append(f"| {code}/{p['signal_time']}/{','.join(p['types'])} | {p['after']['trigger_time']}/{','.join(types)} | {p['after']['exit_time']} | {p['before']['exit_time']} | {p['before']['return_value']:.2%}/{p['after']['return_value']:.2%} |")
    lines.extend(['', '## 核验与限制', '',
        '完整A配置、原事件、基线执行均核验不变；新退出由独立事件优先诊断复核。固定分母、代码/数据指纹及前缀核验见manifest.json，逐笔诊断及执行前缀明细见evidence.zip。', '',
        '两股按无卖点问题选择且已被研究过，未代表全市场；原四臂共同闭合与存续股票选择亦有限制。机会有重叠，不计算IID显著性、年化或复利净值。MAE不是账户回撤；未扣费、未做同持有期随机基准或分仓账户。', '',
        '结论只用于判定本轮是否值得扩大验证；结果少不能解释为全市场无效，工程核验通过也不代表策略有效。', ''])
    return '\n'.join(lines)


def execute(output):
    output = safe_output(output)
    started = time.monotonic()
    source = audit.source_gate()
    from ChanConfig import CChanConfig
    actual = expanded(CChanConfig(VARIANT_A.chan_config()))
    require_original_a(actual, source['expanded_config'])
    store = audit.StockResearchStore()
    stocks, selection = audit.load_inputs(store)
    audit.equal(tuple(stocks), SPEC.codes, 'frozen two-stock scope')
    cases = {c: shared.frozen_cases(store, c, selection) for c in SPEC.codes}
    selection['membership'] = {c: shared.freeze_membership(cs) for c, cs in cases.items()}
    output.mkdir()
    (output/'selection.json').write_bytes(audit.encoded(selection))
    paths = sorted(Path(__file__).parent.glob('*.py'))
    hashes = {str(p):sha(p) for p in paths}
    limits = {k:getattr(shared.SPEC,k) for k in ('cutoffs','future_multiplier','stock_seconds',
        'total_seconds','memory_bytes','output_bytes','max_files')}
    manifest = dict(status='running', spec=asdict(SPEC), validation_limits=limits,
        source=source, expanded_config=actual, periods=old.PERIODS, input_store=store.receipt,
        code_sha256=hashes, plan_design_sha256=sha(audit.PLAN),
        selection_sha256=sha(output/'selection.json'), consumed_records=store.consumed, completed=[])
    results = {}
    shared.checkpoint(output, manifest, results)
    try:
        days = store.read('initial/source.json')['days']
        for code in SPEC.codes:
            stock_start = time.monotonic()
            audit.budget(stock_start, started, shared.SPEC)
            print(f'{code}: frozen A replay and any-sell execution', flush=True)
            data = stocks[code]
            spec = replace(VARIANT_A, codes=(code,), frequencies=(60,), replay_seconds=shared.SPEC.stock_seconds)
            events = replay(data['rows'], code, 60, spec)
            audit.equal(events, data['events'], 'all original buy/sell events and order')
            obs = store.read(f'calendar/{code}/input_30.json')
            times, rows = usage.grid(obs, days)
            pairs = compare(cases[code], events, data['rows'], times, rows, data['diagnostics'])
            checks = shared.check_prefix(data['rows'], code, spec, events)
            checks['executions'] = execution_prefix(cases[code], pairs, events, times, rows)
            rss = audit.budget(stock_start, started, shared.SPEC)
            results[code] = dict(pairs=pairs, checks=checks, event_count=len(events),
                event_sha256=audit.sha(audit.encoded(events)), seconds=time.monotonic()-stock_start, rss_bytes=rss)
            manifest['completed'].append(code)
            manifest['consumed_records'] = store.consumed
            shared.checkpoint(output, manifest, results)
        store.verify_unchanged()
        audit.equal(audit.source_gate(), source, 'source unchanged')
        audit.equal({str(p):sha(p) for p in paths}, hashes, 'code unchanged')
        manifest.update(status='complete', seconds=time.monotonic()-started,
            summary=shared.summarize(results,selection),
            checks=dict(source_unchanged=True,store_unchanged=True,code_unchanged=True))
        (output/'report.md').write_text(report(manifest['summary'],results))
        manifest['report_sha256'] = sha(output/'report.md')
        shared.checkpoint(output,manifest,results)
        with ZipFile(output/'evidence.zip') as archive:
            audit.equal(archive.testzip(),None,'ZIP CRC')
            for code in SPEC.codes:
                audit.equal(json.loads(archive.read(code+'.json')), results[code], 'evidence readback')
        print(json.dumps(manifest['summary']['all'],ensure_ascii=False),flush=True)
    except Exception as exc:
        manifest.update(status='failed', error=f'{type(exc).__name__}: {exc}', seconds=time.monotonic()-started)
        shared.checkpoint(output,manifest,results)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    execute(parser.parse_args().output)


if __name__ == '__main__':
    main()
