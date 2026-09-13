"""Section 29: one sell-side configuration change on 30 frozen opportunities."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
from statistics import mean, median
import time
from zipfile import ZIP_DEFLATED, ZipFile

from scripts.research.index_market.chan import stock_signal_chain_audit as audit
from scripts.research.index_market.chan import stock_exit_study as old
from scripts.research.index_market.chan import stock_sell_usage_audit as usage
from scripts.research.index_market.chan.minute_variant_a import VARIANT_A, VariantASpec
from scripts.research.index_market.chan.minute_replay import replay
from scripts.research.index_market.chan.run_m0 import expanded
from scripts.research.index_market.chan.stock_opportunity import safe_output, sha


@dataclass(frozen=True)
class LinkageSpec:
    codes: tuple = audit.SPEC.codes
    cutoffs: tuple = ('2024-08-31', '2026-06-30')
    future_multiplier: float = 1.1
    bsp3_follow_1_sell: bool = False
    stock_seconds: int = 240
    total_seconds: int = 600
    memory_bytes: int = 256 * 1024**2
    output_bytes: int = 16 * 1024**2
    max_files: int = 4


SPEC = LinkageSpec()


@dataclass(frozen=True)
class SymmetricSpec(VariantASpec):
    def chan_config(self):
        return dict(super().chan_config(), **{'bsp3_follow_1-sell': SPEC.bsp3_follow_1_sell})


def require_single_change(before, after):
    expected = deepcopy(before)
    audit.equal(expected['bs_point_conf']['s_conf']['bsp3_follow_1'], True, 'baseline sell gate')
    expected['bs_point_conf']['s_conf']['bsp3_follow_1'] = SPEC.bsp3_follow_1_sell
    audit.equal(after, expected, 'only bi sell bsp3_follow_1 may change')


def event_difference(before, after):
    audit.equal([e for e in after if e['buy']], [e for e in before if e['buy']], 'buy ledger')
    b, a = ({e['event_id']: e for e in xs} for xs in (before, after))
    if len(b) != len(before) or len(a) != len(after):
        raise ValueError('duplicate event id')
    return dict(added=[a[k] for k in sorted(a.keys()-b.keys())],
                removed=[b[k] for k in sorted(b.keys()-a.keys())],
                changed=[dict(event_id=k, fields={f: dict(before=b[k].get(f), after=a[k].get(f))
                    for f in sorted(b[k].keys() | a[k].keys()) if b[k].get(f) != a[k].get(f)})
                    for k in sorted(a.keys() & b.keys()) if a[k] != b[k]])


def frozen_cases(store, code, selection):
    cm = store.read(f'exits/{code}/manifest.json')
    cases = store.read(f'exits/{code}/cases.json', cm['artifacts_sha256']['cases.json'])
    selected = [s for s in selection['opportunities'] if s['code'] == code]
    keys = {s['signal_time'] for s in selected}
    result = [c for c in cases if c['signal_time'] in keys]
    audit.equal(len(result), len(keys), 'frozen opportunities unique')
    audit.equal([(c['signal_time'], c['types']) for c in result],
                [(s['signal_time'], s['types']) for s in selected], 'frozen order and buy types')
    return result


def freeze_membership(cases):
    """Decide every subgroup from old arms, before treatment is observed."""
    periods = {p: [c['signal_time'] for c in old.paired(cases, *bounds)]
               for p, bounds in old.PERIODS.items()}
    nonoverlap = {p: [c['signal_time'] for c in old.disjoint(
        [c for c in cases if c['signal_time'] in keys])] for p, keys in periods.items()}
    return dict(periods=periods, nonoverlap=nonoverlap)


def triggers(case, events, indices):
    wanted = {'S'+g[1:] for g in case['types']}
    return {indices[e['signal_time']] for e in events if not e['buy'] and e['group'] in wanted}


def compare_cases(cases, before, after, structure, times, rows, previous):
    indices = {t: i for i, t in enumerate(times)}
    output = []
    categories = {d['signal_time']: d['category'] for d in previous}
    for case in cases:
        b = old.simulate(times, rows, case['signal_index'], 'sell', triggers(case, before, indices))
        audit.equal(b, case['arms']['sell'], 'original sell execution all fields')
        a = old.simulate(times, rows, case['signal_index'], 'sell', triggers(case, after, indices))
        newcase = dict(case, arms=dict(case['arms'], sell=a))
        # The independent reconstruction expects closed arms. Preserve unclosed
        # opportunities, block performance claims, and record the missing check.
        diagnosis = (usage.diagnose(newcase, after, structure, times, rows,
                     old.SPEC.max_days*old.SPEC.bars_day) if a['status'] == 'closed' else None)
        if diagnosis and diagnosis['differences']:
            raise ValueError('independent execution mismatch')
        output.append(dict(code=case['code'], signal_time=case['signal_time'], types=case['types'],
            event_ids=case['event_ids'], before=b, after=a, fixed60=case['arms']['fixed60'],
            old_category=categories[case['signal_time']],
            new_category=diagnosis['category'] if diagnosis else 'unclosed',
            independent=diagnosis, delta=(a['return_value']-b['return_value']
                if a['status'] == 'closed' else None)))
    audit.equal(len(output), len(cases), 'unchanged denominator')
    return output


def check_prefix(rows, code, spec, full_events, replay_fn=replay):
    checks = []
    for day in SPEC.cutoffs:
        n = sum(r['time'][:10] <= day for r in rows)
        if not 0 < n < len(rows):
            raise ValueError('prefix cutoff outside input')
        expected = [e for e in full_events if e['signal_index'] < n]
        actual = replay_fn(rows[:n], code, 60, spec)
        audit.equal(actual, expected, 'truncated treatment prefix')
        checks.append(dict(cutoff=day, bars=n, events=len(expected), sha256=audit.sha(audit.encoded(expected))))
    day = SPEC.cutoffs[-1]
    changed = [dict(r, **{f: r[f]*SPEC.future_multiplier for f in ('open', 'high', 'low', 'close')})
               if r['time'][:10] > day else dict(r) for r in rows]
    actual = replay_fn(changed, code, 60, spec)
    audit.equal([e for e in actual if e['signal_time'][:10] <= day],
                [e for e in full_events if e['signal_time'][:10] <= day], 'future perturbation prefix')
    return dict(truncated=checks, future_perturbation=dict(cutoff=day, multiplier=SPEC.future_multiplier, passed=True))


def metrics(pairs):
    out = dict(n=len(pairs), unclosed=sum(p['after']['status'] != 'closed' for p in pairs))
    if not pairs or out['unclosed']:
        return out
    for arm in ('before', 'after', 'fixed60'):
        xs = [p[arm] for p in pairs]
        out[arm] = dict(mean=mean(x['return_value'] for x in xs),
            median=median(x['return_value'] for x in xs), win=mean(x['return_value'] > 0 for x in xs),
            holding_days=mean(x['holding_days'] for x in xs),
            adverse=mean(x['adverse'] for x in xs), favorable=mean(x['favorable'] for x in xs),
            sell_exits=sum(x['reason'] == 'sell' for x in xs))
    ds = [p['delta'] for p in pairs]
    out['delta'] = dict(mean=mean(ds), median=median(ds), better=sum(d > 0 for d in ds),
        worse=sum(d < 0 for d in ds), unchanged=sum(d == 0 for d in ds),
        without_best=mean(sorted(ds)[:-1]) if len(ds) > 1 else None)
    return out


def summarize(results, selection):
    pairs = [p for r in results.values() for p in r['pairs']]
    output = dict(all=metrics(pairs), stocks={}, categories=dict(Counter(
        p['old_category']+' -> '+p['new_category'] for p in pairs)))
    for code, result in results.items():
        membership = selection['membership'][code]
        output['stocks'][code] = {kind: {period: metrics([p for p in result['pairs'] if p['signal_time'] in keys])
            for period, keys in groups.items()} for kind, groups in membership.items()}
        output['stocks'][code]['period_overrun'] = {period: sum(
            p['after']['status'] != 'closed' or p['after']['exit_time'][:10] > old.PERIODS[period][1]
            for p in result['pairs'] if p['signal_time'] in keys)
            for period, keys in membership['periods'].items()}
    complete = [v['periods']['full'] for v in output['stocks'].values()]
    if complete and all(v['n'] and not v['unclosed'] for v in complete):
        output['stock_equal_weight_mean'] = {arm: mean(v[arm]['mean'] for v in complete)
                                             for arm in ('before', 'after', 'fixed60')}
    return output


def report(summary, results):
    lines = ['# 三卖前置条件对称：两股单变量验证', '',
        '输入截至2026-09-08；60分钟识别、30分钟执行；评估2022-09-22起。只有笔级卖方bsp3_follow_1从True改False。', '',
        '以下是固定30次机会的毛收益，不是分批股数账户收益。两个已见、按诊断选出的股票不能证明普适性。', '',
        '| 股票 | 原/新全期事件 | 新增S3 | 删除/字段变化事件 | 原/新实际卖出 | 原/新均值 | 均值差 | 原/新MAE | 原/新持有日 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for code, r in results.items():
        m = summary['stocks'][code]['periods']['full']
        d = r['event_diff']
        if m.get('unclosed'):
            lines.append(f'| {code} | 未闭合，收益比较停止 | | | | | | | |')
            continue
        b, a = m['before'], m['after']
        lines.append(f"| {code}（n={m['n']}） | {r['baseline_events']}/{len(r['events'])} | {sum(e['group']=='S3' for e in d['added'])} | {len(d['removed'])}/{len(d['changed'])} | {b['sell_exits']}/{a['sell_exits']} | {b['mean']:.2%}/{a['mean']:.2%} | {m['delta']['mean']*100:+.2f}pp | {b['adverse']:.2%}/{a['adverse']:.2%} | {b['holding_days']:.2f}/{a['holding_days']:.2f} |")
    lines.extend(['', '## 固定子集（名单在处理前冻结）', '',
        '| 股票/子集/阶段 | n | 原均值 | 新均值 | 差值 | 改善/变差/不变 |',
        '| --- | ---: | ---: | ---: | ---: | ---: |'])
    for code, stock in summary['stocks'].items():
        for kind in ('periods', 'nonoverlap'):
            for period, m in stock[kind].items():
                if not m['n'] or m['unclosed']:
                    lines.append(f"| {code}/{kind}/{period} | {m['n']} | 不可比较 | | | |")
                else:
                    d = m['delta']
                    lines.append(f"| {code}/{kind}/{period} | {m['n']} | {m['before']['mean']:.2%} | {m['after']['mean']:.2%} | {d['mean']*100:+.2f}pp | {d['better']}/{d['worse']}/{d['unchanged']} |")
    lines.extend(['', '## 原窗口分类转移', ''])
    lines += [f'- {key}: {n}' for key, n in sorted(summary['categories'].items())]
    lines.extend(['', '## 每笔发生收益变化的机会', '',
        '| 股票/买点确认 | 买类 | 原退出 | 新退出 | 原收益 | 新收益 | 差值 |',
        '| --- | --- | --- | --- | ---: | ---: | ---: |'])
    for r in results.values():
        for p in r['pairs']:
            if p['delta'] is not None and p['delta'] != 0:
                lines.append(f"| {p['code']}/{p['signal_time']} | {','.join(p['types'])} | {p['before']['exit_time']} | {p['after']['exit_time']} | {p['before']['return_value']:.2%} | {p['after']['return_value']:.2%} | {p['delta']*100:+.2f}pp |")
    lines.extend(['', '## 验证及边界', '',
        '源码、输入、配置、旧事件与执行逐项校验；新买点零变化，新退出独立重建，四次截断与两次未来扰动通过。完整指标、事件差异和逐笔证据见manifest.json及evidence.zip。', '',
        'MAE是相对入场价的最差浮亏，不是账户最大回撤。fixed60和持有日用于参照，尚未做同持有期随机基准。样本重叠、当前存续股票筛选、曾用于研究及原四臂共同闭合筛选均限制外推；不做IID显著性、年化或复利净值。未扣费用，未重跑分仓账户。', '',
        '数据验证结论：带限制可分享；只用于检验这个门槛是否值得继续，不能作为投资建议或可靠参数认证。', ''])
    return '\n'.join(lines)


def checkpoint(output, manifest, results):
    if results:
        temporary = output/'evidence.zip.tmp'
        with ZipFile(temporary, 'x', compression=ZIP_DEFLATED) as archive:
            for code, result in results.items():
                archive.writestr(code+'.json', audit.encoded(result))
        if temporary.stat().st_size > SPEC.output_bytes:
            raise ValueError('output budget')
        temporary.replace(output/'evidence.zip')
        manifest['evidence_sha256'] = sha(output/'evidence.zip')
    manifest['consumed_records'] = dict(manifest['consumed_records'])
    temporary = output/'manifest.json.tmp'
    temporary.write_bytes(audit.encoded(manifest))
    temporary.replace(output/'manifest.json')
    files = list(output.iterdir())
    if len(files) > SPEC.max_files or sum(p.stat().st_size for p in files) > SPEC.output_bytes:
        raise ValueError('output file/byte budget')


def execute(output):
    output = safe_output(output)
    started = time.monotonic()
    source = audit.source_gate()
    from ChanConfig import CChanConfig
    new_config = expanded(CChanConfig(SymmetricSpec().chan_config()))
    require_single_change(source['expanded_config'], new_config)
    store = audit.StockResearchStore()
    stocks, selection = audit.load_inputs(store)
    cases = {code: frozen_cases(store, code, selection) for code in SPEC.codes}
    selection['membership'] = {code: freeze_membership(cs) for code, cs in cases.items()}
    audit.equal(sum(len(cs) for cs in cases.values()), 30, '30 frozen cases')
    output.mkdir()
    (output/'selection.json').write_bytes(audit.encoded(selection))
    paths = {Path(__file__), *(Path(m.__file__) for m in (audit, old, usage))}
    # Hash all local research Python dependencies, without importing/running them.
    paths.update(Path(__file__).parent.glob('*.py'))
    code_hashes = {str(p): sha(p) for p in sorted(paths)}
    manifest = dict(status='running', spec=asdict(SPEC), source=source, expanded_config=new_config,
        periods=old.PERIODS, selection_sha256=sha(output/'selection.json'),
        plan_design_sha256=sha(audit.PLAN), code_sha256=code_hashes,
        input_store=store.receipt, consumed_records=store.consumed, completed=[])
    results = {}
    checkpoint(output, manifest, results)
    try:
        days = store.read('initial/source.json')['days']
        for code in SPEC.codes:
            stock_start = time.monotonic()
            print(f'{code}: baseline, treatment, execution and prefix checks', flush=True)
            data = stocks[code]
            spec = replace(VARIANT_A, codes=(code,), frequencies=(60,), replay_seconds=SPEC.stock_seconds)
            before = replay(data['rows'], code, 60, spec)
            audit.equal(before, data['events'], 'full baseline events')
            after_spec = SymmetricSpec(**asdict(spec))
            after = replay(data['rows'], code, 60, after_spec)
            usage.validate_events(after, data['rows'], code)
            diff = event_difference(before, after)
            obs = store.read(f'calendar/{code}/input_30.json')
            times, rows = usage.grid(obs, days)
            pairs = compare_cases(cases[code], before, after, data['rows'], times, rows, data['diagnostics'])
            checks = check_prefix(data['rows'], code, after_spec, after)
            rss = audit.budget(stock_start, started, SPEC)
            results[code] = dict(events=after, event_diff=diff, baseline_events=len(before),
                pairs=pairs, checks=checks, seconds=time.monotonic()-stock_start, rss_bytes=rss)
            manifest['completed'].append(code)
            manifest['consumed_records'] = store.consumed
            checkpoint(output, manifest, results)
            print(f'{code}: complete, {len(before)} -> {len(after)} events', flush=True)
        store.verify_unchanged()
        audit.equal(audit.source_gate(), source, 'source unchanged')
        audit.equal({str(p): sha(p) for p in sorted(paths)}, code_hashes, 'code unchanged')
        manifest.update(status='complete', seconds=time.monotonic()-started, summary=summarize(results, selection),
                        checks=dict(source_unchanged=True, store_unchanged=True, code_unchanged=True))
        (output/'report.md').write_text(report(manifest['summary'], results))
        manifest['report_sha256'] = sha(output/'report.md')
        checkpoint(output, manifest, results)
        with ZipFile(output/'evidence.zip') as archive:
            audit.equal(archive.testzip(), None, 'evidence CRC')
            for code in SPEC.codes:
                audit.equal(json.loads(archive.read(code+'.json')), results[code], 'evidence readback')
        print(json.dumps(manifest['summary']['all'], ensure_ascii=False), flush=True)
    except Exception as exc:
        manifest.update(status='failed', error=f'{type(exc).__name__}: {exc}', seconds=time.monotonic()-started)
        checkpoint(output, manifest, results)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    execute(parser.parse_args().output)


if __name__ == '__main__':
    main()
