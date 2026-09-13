"""Frozen single-stock opportunity event study; no Lake access or signal tuning."""
import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from statistics import mean, median

from scripts.research.index_market.chan.m0_data import REPO, safe_output


@dataclass(frozen=True)
class OpportunitySpec:
    source: str = 'reports/stock_qfq_002245_30m_20260912'
    warmup_days: int = 250
    bars_per_day: int = 8
    horizons: tuple = (5, 10, 20)
    barrier: float = .05
    rally_days: int = 20
    rally_return: float = .10
    early_days: int = 5
    max_source_bytes: int = 64*1024**2
    max_bars: int = 10000


SPEC = OpportunitySpec()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def outcome(rows, signal_index, bars, barrier=SPEC.barrier):
    start, end = signal_index+1, signal_index+bars
    if end >= len(rows):
        return None
    price = rows[start]['open']
    window = rows[start:end+1]
    first = 'neither'
    for r in window:
        up, down = r['high'] >= price*(1+barrier), r['low'] <= price*(1-barrier)
        if up or down:
            first = 'ambiguous' if up and down else 'up' if up else 'down'
            break
    return dict(index=signal_index, entry_index=start, exit_index=end,
                signal_time=rows[signal_index]['time'], entry_bar=rows[start]['time'],
                exit_time=rows[end]['time'], entry_price=price,
                return_value=rows[end]['close']/price-1,
                favorable=max(0, max(r['high'] for r in window)/price-1),
                adverse=min(0, min(r['low'] for r in window)/price-1), first=first)


def aggregate(items):
    if not items:
        return dict(n=0)
    return dict(n=len(items), mean=mean(x['return_value'] for x in items),
                median=median(x['return_value'] for x in items),
                win=mean(x['return_value'] > 0 for x in items),
                favorable=mean(x['favorable'] for x in items),
                adverse=mean(x['adverse'] for x in items),
                **{f'first_{k}': mean(x['first'] == k for x in items)
                   for k in ('up', 'down', 'ambiguous', 'neither')})


def nonoverlap(items):
    result, last = [], -1
    for x in sorted(items, key=lambda x: x['entry_index']):
        if x['entry_index'] > last:
            result.append(x)
            last = x['exit_index']
    return result


def evaluate(rows, events, spec=SPEC):
    times = {r['time']: i for i, r in enumerate(rows)}
    days = sorted({r['date'] for r in rows})
    day_index = {d: i for i, d in enumerate(days)}
    start = next(i for i, r in enumerate(rows) if r['date'] == days[spec.warmup_days])
    groups = {g: set() for g in ('B1', 'B2', 'B3', 'ALL')}
    for e in events:
        if e['group'] not in groups or e['group'] == 'ALL':
            continue
        i = times[e['signal_time']]
        if i != e['signal_index'] or not e['sure'] or not e['buy']:
            raise ValueError('invalid confirmed buy event')
        if i >= start:
            groups[e['group']].add(i)
            groups['ALL'].add(i)
    summary, details = [], []
    for horizon in spec.horizons:
        bars = horizon*spec.bars_per_day
        ordinary = [outcome(rows, i, bars) for i in range(start, len(rows)-bars)]
        pools = defaultdict(list)
        for x in ordinary:
            pools[(x['signal_time'][:4], x['signal_time'][11:])].append(x)
        pool_stats = {k: aggregate(v) for k, v in pools.items()}
        lookup = {x['index']: x for x in ordinary}
        for group, indices in groups.items():
            items = [dict(lookup[i], group=group, horizon=horizon) for i in sorted(indices) if i in lookup]
            matched = [pool_stats[(x['signal_time'][:4], x['signal_time'][11:])] for x in items]
            matched_mean = {k: mean(x[k] for x in matched) for k in matched[0] if k != 'n'} if matched else {}
            summary.append(dict(group=group, horizon=horizon, total=len(indices),
                                censored=len(indices)-len(items), signals=aggregate(items),
                                ordinary=aggregate(ordinary), matched=matched_mean,
                                nonoverlap=aggregate(nonoverlap(items))))
            details.extend(items)
    # Daily forward-return labels: disjoint, chronological, not hindsight-selected bottoms.
    available = sorted(i+1 for i in groups['ALL'] if i+1 < len(rows))
    candidates = []
    for i in range(start+1, len(rows)):
        if rows[i]['date'] == rows[i-1]['date']:
            continue
        x = outcome(rows, i-1, spec.rally_days*spec.bars_per_day)
        if x is None:
            continue
        d = day_index[rows[i]['date']]
        early = [j for j in available if abs(day_index[rows[j]['date']]-d) <= spec.early_days]
        during = [j for j in available if i <= j <= x['exit_index']]
        first = during[0] if during else None
        x.update(early=bool(early), early_bars=[rows[j]['time'] for j in early],
                 first_signal_bar=rows[first]['time'] if first is not None else None,
                 delay_days=day_index[rows[first]['date']]-d if first is not None else None,
                 already_risen=rows[first]['open']/rows[i]['open']-1 if first is not None else None)
        candidates.append(x)
    rallies = nonoverlap([x for x in candidates if x['return_value'] >= spec.rally_return])
    recall = dict(n=len(rallies), early_count=sum(x['early'] for x in rallies),
                  ordinary_dates=len(candidates), ordinary_early_rate=mean(x['early'] for x in candidates),
                  rallies=rallies)
    return dict(summary=summary, events=details, recall=recall, eligible_start=rows[start]['time'])


def render(result):
    text = '''# 蔚蓝锂芯：买点发现机会评估

冻结2021-09-09—2026-09-08的30分钟前复权数据，250日初始化。只评价首次确认后的价格表现，不评价仓位与卖点。确认后下一柱开盘至40/80/160柱收盘，毛收益无费用，无成交保证。

| 买点 | 交易日 | 有效/尾部不足 | 上涨率 | 匹配普通上涨率 | 平均收益 | 匹配普通收益 | 中位收益 | 平均最大不利偏移 | 不重叠样本/均值 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
'''
    for s in result['summary']:
        a, b, n = s['signals'], s['matched'], s['nonoverlap']
        text += (f"| {s['group']} | {s['horizon']} | {a['n']}/{s['censored']} | {a.get('win',0):.1%} | "
                 f"{b.get('win',0):.1%} | {a.get('mean',0):.2%} | {b.get('mean',0):.2%} | "
                 f"{a.get('median',0):.2%} | {a.get('adverse',0):.2%} | {n['n']}/{n.get('mean',0):.2%} |\n")
    r = result['recall']
    text += f'''
## 大涨区间有没有提前提示

事后标签：每日首柱开盘至第20日收盘涨幅≥10%，按时间保留互不重叠区间，不是精确底顶。共{r['n']}段，其中{r['early_count']}段在起点前后5个交易日存在已确认且可下一柱入场的买点。普通日期相同窗口的提示覆盖率{r['ordinary_early_rate']:.1%}。这衡量早期覆盖，不等于预测准确率或独立检验。

| 区间起始柱（结束时间） | 区间结束 | 涨幅 | 前后5日提示 | 区间内首次提示可入场柱 | 延迟交易日 | 此时已涨 |
| --- | --- | ---: | --- | --- | ---: | ---: |
'''
    for x in r['rallies']:
        risen = f"{x['already_risen']:.2%}" if x['already_risen'] is not None else '无'
        text += f"| {x['entry_bar']} | {x['exit_time']} | {x['return_value']:.2%} | {x['early']} | {x['first_signal_bar']} | {x['delay_days']} | {risen} |\n"
    text += '''
## 解读与验证边界

普通时点包含信号时点，是随机选时参考，不是独立无信号控制组。匹配采用同年、同盘中时段，每个信号等权；未控制波动、趋势等特征，不能解释为因果优势。ALL同柱去重，各类型分别去重，跨类型不相加。非重叠列按组/周期分别保留最早信号，不称独立样本。

summary.json含普通全时点、匹配基准、±5%先触及比例（同柱双触未知）、最大有利/不利偏移。events.json保留逐个买点、窗口及收益，recall.json保留全部选定区间。时间字段entry_bar是成交柱的结束时间，实际假设入场为该柱开盘，非收盘。

此为已看过单股收益后的探索性评估；样本小、窗口重叠、多类型多周期、单只存续股票，不能宣称统计显著或普遍有效。事后大涨标签不进入买点生成；起点前后5日不是精确抓底。报告无图，不存在坐标缩放问题。验证结论为附限制分享。
'''
    return text


def execute(output):
    source = REPO/SPEC.source
    manifest_path = source/'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if manifest['status'] != 'complete' or not manifest['all_signal_checks_passed']:
        raise ValueError('source run not verified complete')
    paths = [source/n for n in manifest['artifacts_sha256']]
    if sum(p.stat().st_size for p in paths) > SPEC.max_source_bytes:
        raise ValueError('source budget exceeded')
    for p in paths:
        if sha(p) != manifest['artifacts_sha256'][p.name]:
            raise ValueError(f'source artifact changed: {p.name}')
    rows = json.loads((source/'input.json').read_text())
    events = json.loads((source/'full_events.json').read_text())
    if not 0 < len(rows) <= SPEC.max_bars:
        raise ValueError('bar budget')
    result = evaluate(rows, events)
    output = safe_output(output)
    output.mkdir()
    for name, value in [('summary', result['summary']), ('events', result['events']), ('recall', result['recall'])]:
        (output/f'{name}.json').write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    (output/'report.md').write_text(render(result))
    receipt = dict(status='complete', spec=asdict(SPEC), source_manifest_sha256=sha(manifest_path),
                   code_sha256=sha(Path(__file__)), eligible_start=result['eligible_start'],
                   artifacts_sha256={p.name: sha(p) for p in output.iterdir()})
    (output/'manifest.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result['summary'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    execute(parser.parse_args().output)
