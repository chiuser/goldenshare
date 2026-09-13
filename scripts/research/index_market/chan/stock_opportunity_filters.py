"""Four predeclared filters over frozen confirmed Chan events, no new signal replay."""
import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from statistics import mean
import time

from scripts.research.index_market.chan import stock_opportunity as base


@dataclass(frozen=True)
class FilterSpec:
    ma: int = 40
    slope: int = 5
    atr: int = 20
    distance_atr: float = 2.0
    variants: tuple = ('original', 'trend', 'near', 'both')
    previous: str = 'reports/stock_opportunity_002245_30m_20260912'
    plan: str = 'docs/product/stock-chan-share-position-backtest-plan-v1.md'
    seconds: int = 60
    output_bytes: int = 32*1024**2


SPEC = FilterSpec()


def features(rows, event, spec=SPEC):
    i, anchor = event['signal_index'], event['anchor_index']
    if not 0 <= anchor <= i < len(rows) or rows[i]['time'] != event['signal_time']:
        raise ValueError('future anchor or invalid confirmation index')
    result = dict(event_id=event['event_id'], group=event['group'], index=i, anchor=anchor,
                  time=event['signal_time'], trend=False, near=False, reason='insufficient_history')
    if i < max(spec.ma+spec.slope-1, spec.atr):
        return result
    ma = mean(r['close'] for r in rows[i-spec.ma+1:i+1])
    previous_ma = mean(r['close'] for r in rows[i-spec.slope-spec.ma+1:i-spec.slope+1])
    atr = mean(max(rows[j]['high']-rows[j]['low'],
                   abs(rows[j]['high']-rows[j-1]['close']),
                   abs(rows[j]['low']-rows[j-1]['close'])) for j in range(i-spec.atr+1, i+1))
    distance = rows[i]['close']-rows[anchor]['low']
    result.update(ma=ma, previous_ma=previous_ma, atr=atr, close=rows[i]['close'],
                  anchor_low=rows[anchor]['low'], distance=distance,
                  trend=rows[i]['close'] > ma > previous_ma,
                  near=atr > 0 and 0 <= distance <= spec.distance_atr*atr,
                  reason='zero_atr' if atr <= 0 else 'negative_distance' if distance < 0 else 'evaluated')
    return result


def passes(feature, variant):
    if variant not in SPEC.variants:
        raise ValueError('unapproved variant')
    return {'original': True, 'trend': feature['trend'], 'near': feature['near'],
            'both': feature['trend'] and feature['near']}[variant]


def enrich(rows, result):
    days = sorted({r['date'] for r in rows})
    start = next(i for i,r in enumerate(rows) if r['date'] == days[base.SPEC.warmup_days])
    pools = {}
    for horizon in base.SPEC.horizons:
        groups = defaultdict(list)
        for i in range(start, len(rows)-horizon*base.SPEC.bars_per_day):
            x = base.outcome(rows, i, horizon*base.SPEC.bars_per_day)
            groups[(x['signal_time'][:4], x['signal_time'][11:])].append(x)
        pools[horizon] = {key: base.aggregate(value) for key,value in groups.items()}
    def stats(items, horizon):
        a = base.aggregate(items)
        if not items:
            return dict(signals=a, matched_mean=None, excess=None, without_best=None)
        b = mean(pools[horizon][(x['signal_time'][:4], x['signal_time'][11:])]['mean'] for x in items)
        values = sorted(x['return_value'] for x in items)
        return dict(signals=a, matched_mean=b, excess=a['mean']-b,
                    without_best=mean(values[:-1]) if len(values)>1 else None)
    for s in result['summary']:
        items = [x for x in result['events'] if x['group']==s['group'] and x['horizon']==s['horizon']]
        s['nonoverlap_comparison'] = stats(base.nonoverlap(items), s['horizon'])
        s['without_best'] = stats(items, s['horizon'])['without_best']
        s['annual'] = {year: stats([x for x in items if x['signal_time'][:4]==year], s['horizon'])
                       for year in sorted({r['date'][:4] for r in rows[start:]})}


def checked_report(folder):
    manifest = json.loads((folder/'manifest.json').read_text())
    if manifest['status'] != 'complete':
        raise ValueError('incomplete source')
    paths = [folder/name for name in manifest['artifacts_sha256']]
    if sum(p.stat().st_size for p in paths) > base.SPEC.max_source_bytes:
        raise ValueError('source byte budget')
    for p in paths:
        if base.sha(p) != manifest['artifacts_sha256'][p.name]:
            raise ValueError(f'source hash mismatch: {p}')
    return manifest


def render(results):
    labels = dict(original='原买点', trend='仅顺势', near='仅不追高', both='两者同时')
    text = '''# 蔚蓝锂芯30分钟：买点过滤四组对照

2021-09-09—2026-09-08前复权，250日初始化；10交易日为主窗口。先写方案再计算，未搜索参数。仅评价下一柱开盘后的毛价格收益，不是持仓策略净收益。

顺势=C>MA40且MA40>5柱前MA40；不追高=0≤C-首次确认锚点柱low≤2×ATR20，ATR用20柱TR简单平均。过滤不延迟发信号；先过滤结构事件再同柱去重。

## 主窗口：合并买点，同柱去重

| 组 | 样本 | 上涨率 | 平均收益 | 匹配普通收益 | 中位数 | 先+5% | 先-5% | 大涨区间早期覆盖 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
'''
    def pct(v):
        return '无样本' if v is None else f'{v:.2%}'
    for name,r in results.items():
        s = next(x for x in r['summary'] if x['group']=='ALL' and x['horizon']==10)
        a=s['signals']
        text += f"| {labels[name]} | {a['n']} | {pct(a.get('win'))} | {pct(a.get('mean'))} | {pct(s['matched'].get('mean'))} | {pct(a.get('median'))} | {pct(a.get('first_up'))} | {pct(a.get('first_down'))} | {r['recall']['early_count']}/{r['recall']['n']} |\n"
    for name,r in results.items():
        text += f'\n## {labels[name]}：全部类型及窗口\n\n'
        text += '| 类型 | 天数 | 留下/尾部不足 | 均值 | 匹配均值 | 非重叠数/均值/超额 | 去掉最高一例均值 |\n| --- | ---: | ---: | ---: | ---: | --- | ---: |\n'
        for s in r['summary']:
            n=s['nonoverlap_comparison']
            text += f"| {s['group']} | {s['horizon']} | {s['total']}/{s['censored']} | {pct(s['signals'].get('mean'))} | {pct(s['matched'].get('mean'))} | {n['signals']['n']}/{pct(n['signals'].get('mean'))}/{pct(n['excess'])} | {pct(s['without_best'])} |\n"
        text += '\n主窗口逐年（确认年份，2022/2026为部分年）：\n\n| 类型 | 年 | 样本 | 均值 | 匹配超额 |\n| --- | --- | ---: | ---: | ---: |\n'
        for s in r['summary']:
            if s['horizon']==10:
                for year,a in s['annual'].items():
                    text += f"| {s['group']} | {year} | {a['signals']['n']} | {pct(a['signals'].get('mean'))} | {pct(a['excess'])} |\n"
    text += '''
## 证据与限制

features.json逐事件保存当时MA/ATR/锚点价格和过滤结果；各组JSON含逐信号收益、剔除数量、所有周期逐年和非重叠结果、固定24个区间的覆盖。所有组普通时点按各自信号同年/同盘中时段重新匹配；非重叠子集再次匹配。不是同趋势状态的对照，不能分离趋势过滤与缠论自身的因果贡献。

覆盖使用原24个事后20日涨≥10%且互不重叠区间，提示窗口起点前后5交易日；未重新选区间。窗口重叠、单股小样本、多组比较，本股数据已经看过，不给统计显著性或普遍有效结论。5/20日为敏感性，不择优替代10日。过滤组为零时空值不写0%收益。先触±5%不模拟T+1可卖，属于价格路径指标；同柱双触列入未知。

验证：原组复现上轮所有汇总/信号/区间，逐事件前缀与未来扰动过滤一致；工程通过不代表策略有效。报告可以附上述限制分享，无产品/正式数据变更。
'''
    return text


def execute(output):
    started=time.monotonic()
    output=base.safe_output(output)
    source=base.REPO/base.SPEC.source
    previous=base.REPO/SPEC.previous
    checked_report(source)
    old_manifest=checked_report(previous)
    if old_manifest['code_sha256'] != base.sha(Path(base.__file__)):
        raise ValueError('frozen evaluator changed')
    rows=json.loads((source/'input.json').read_text())
    events=json.loads((source/'full_events.json').read_text())
    if not 0<len(rows)<=base.SPEC.max_bars:
        raise ValueError('bar budget')
    buys=[e for e in events if e['group'] in ('B1','B2','B3')]
    fs=[features(rows,e) for e in buys]
    for e,f in zip(buys,fs,strict=True):
        if features(rows[:e['signal_index']+1],e)!=f:
            raise ValueError('prefix mismatch')
    cutoff=len(rows)//2
    altered=[dict(r, **{k:r[k]*1.5 for k in ('open','high','low','close')}) if i>cutoff else r
             for i,r in enumerate(rows)]
    if any(features(altered,e)!=f for e,f in zip(buys,fs,strict=True) if e['signal_index']<=cutoff):
        raise ValueError('future isolation failure')
    receipt=dict(status='running', spec=asdict(SPEC), base_spec=asdict(base.SPEC),
                 plan_sha256_at_start=base.sha(base.REPO/SPEC.plan),
                 source_manifests={str(p):base.sha(p/'manifest.json') for p in (source,previous)},
                 code_sha256={str(p):base.sha(p) for p in (Path(__file__),Path(base.__file__))},
                 checks={'prefix':True,'future_isolation':True})
    output.mkdir()
    def save(name,data):
        (output/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    results={}
    try:
        save('features.json',fs)
        for variant in SPEC.variants:
            if time.monotonic()-started>SPEC.seconds:
                raise TimeoutError('filter experiment time budget')
            selected=[e for e,f in zip(buys,fs,strict=True) if passes(f,variant)]
            r=base.evaluate(rows,selected)
            old_recall=json.loads((previous/'recall.json').read_text())
            if variant=='original':
                for name,key in [('summary.json','summary'),('events.json','events'),('recall.json','recall')]:
                    if r[key]!=json.loads((previous/name).read_text()):
                        raise ValueError(f'original result mismatch: {name}')
                receipt['checks']['original_exact']=True
            if [(x['entry_index'],x['exit_index']) for x in r['recall']['rallies']] != [(x['entry_index'],x['exit_index']) for x in old_recall['rallies']]:
                raise ValueError('rally population changed')
            enrich(rows,r)
            for s in r['summary']:
                original=next(x for x in (r if variant=='original' else results['original'])['summary']
                              if x['group']==s['group'] and x['horizon']==s['horizon'])
                s['removed']=original['total']-s['total']
            results[variant]=r
            save(f'{variant}.json',r)
            print(f'{variant}: completed',flush=True)
        (output/'report.md').write_text(render(results))
        receipt.update(status='complete',seconds=time.monotonic()-started)
        if receipt['seconds']>SPEC.seconds or sum(p.stat().st_size for p in output.iterdir())>SPEC.output_bytes:
            raise ValueError('time/output budget')
    except BaseException as exc:
        receipt.update(status='failed',error=str(exc))
        raise
    finally:
        receipt['artifacts_sha256']={p.name:base.sha(p) for p in output.iterdir()}
        save('manifest.json',receipt)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    execute(parser.parse_args().output)
