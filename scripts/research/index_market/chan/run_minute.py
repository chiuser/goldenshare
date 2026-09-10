"""Run the frozen six-cell minute prediction experiment, never an account backtest."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from pathlib import Path
import shutil
import time

import duckdb

from scripts.research.index_market.chan.event_ledger import canonical
from scripts.research.index_market.chan.m0_data import REPO, digest, safe_output
from scripts.research.index_market.chan.minute_data import MINUTE, load_input
from scripts.research.index_market.chan.minute_replay import replay
from scripts.research.index_market.chan.minute_score import (
    block_intervals, label_rows, select_events, summarize,
)
from scripts.research.index_market.chan.run_m0 import save, verify_source


def independent_score_check(rows, scored):
    """Separate SQL forward-index and day alignment, no label_rows reuse."""
    if not scored:
        return True
    # In-memory JSON relations; no external reads or writes.
    with duckdb.connect(':memory:') as con:
        con.execute('CREATE TEMP TABLE raw AS SELECT unnest(CAST(? AS JSON[])) AS j',
                    [[canonical(r) for r in rows]])
        con.execute('''CREATE TEMP TABLE p AS SELECT row_number() OVER(ORDER BY j->>'time')-1 AS idx,
            j->>'date' AS d,j->>'time' AS t,CAST(j->>'open' AS DOUBLE) AS o,
            CAST(j->>'close' AS DOUBLE) AS c,CAST(j->>'low' AS DOUBLE) AS l,
            CAST(j->>'high' AS DOUBLE) AS h FROM raw''')
        con.execute('CREATE TEMP TABLE ev AS SELECT unnest(CAST(? AS JSON[])) AS j',
                    [[canonical(r) for r in scored]])
        errors = con.execute('''WITH days AS (SELECT d,dense_rank() OVER(ORDER BY d) AS dn,
            arg_max(c,t) AS c,max(idx) AS idx FROM p GROUP BY d),
            e AS (SELECT j->>'event_id' AS id,CAST(j->>'index' AS BIGINT) AS idx,
                CAST(j->>'r' AS DOUBLE) AS r,CAST(j->>'q' AS DOUBLE) AS q,
                CAST(j->>'mae' AS DOUBLE) AS mae,CAST(j->>'mfe' AS DOUBLE) AS mfe FROM ev),
            computed AS (SELECT e.id,e.r,e.q,e.mae,e.mfe,
                target.c/now.c-1 AS actual_r,target.c/entry.o-1 AS actual_q,
                min(path.l)/entry.o-1 AS actual_mae,max(path.h)/entry.o-1 AS actual_mfe
                FROM e JOIN p now ON now.idx=e.idx JOIN p entry ON entry.idx=e.idx+1
                JOIN days origin ON origin.d=now.d JOIN days target ON target.dn=origin.dn+1
                JOIN p path ON path.idx BETWEEN e.idx+1 AND target.idx
                GROUP BY e.id,e.r,e.q,e.mae,e.mfe,target.c,now.c,entry.o)
            SELECT count(*) FILTER(WHERE abs(r-actual_r)>1e-12 OR abs(q-actual_q)>1e-12
                OR abs(mae-actual_mae)>1e-12 OR abs(mfe-actual_mfe)>1e-12),count(*) FROM computed''').fetchone()
    if errors != (0,len(scored)):
        raise ValueError(f'independent SQL scoring mismatch {errors}')
    return True


def report(metrics, quality):
    lines = ['# 五年30/60分钟缠论买点预判测试','',
        '数据：2021-09-09—2026-09-08，2021年窗口内数据仅初始化；评分2022年起。',
        f"实测{quality['open_days']}交易日、{quality['rows']}根K线。这里只是A预判测试，不是B买卖账户回测。",'',
        '## 下一交易日：主去重口径','',
        '同指数同组冷却20交易日；上涨率从识别柱收盘算，Q从下一根完整柱开盘算，均到下一交易日收盘。',
        '基线按同年份和收盘时刻匹配；所有数字是历史频率，不是已校准的未来概率。','',
        '|指数|分钟|组|原始/冷却后有效N|上涨率|基线上涨率|平均Q|基线Q|中位Q|平均MAE|',
        '|---|---:|---|---:|---:|---:|---:|---:|---:|---:|']
    def pct(x):
        return '—' if x is None else f'{x*100:.2f}%'
    for cell in metrics:
        for group in ('B3','B2','B1'):
            a = cell['scores'][group]['cooldown']['1']
            n = cell['scores'][group]['raw']['1']['n']
            lines.append(f"|{cell['code']}|{cell['frequency']}|{group}|{n}/{a['n']}|"+
                '|'.join(pct(a[k]) for k in ('up','baseline_up','q','baseline_q','median_q','mae'))+'|')
    lines += ['', '## B3不确定性与样本门槛','',
        '主检验12项，使用99.5833%同时区间；不同区块长度作敏感性。不达50个/5个信号年份，不宣布有效。', '',
        '|指数|分钟|60日块上涨率差区间|60日块Q收益差区间|样本门槛|',
        '|---|---:|---|---|---|']
    for cell in metrics:
        a = cell['scores']['B3']['cooldown']['1']
        ci = cell['intervals'].get('60',{})
        def span(key):
            v = ci.get(key)
            return '不足以估计' if v is None else ' ～ '.join(pct(x) for x in v['simultaneous'])
        lines.append(f"|{cell['code']}|{cell['frequency']}|{span('lift_up')}|{span('lift_q')}|{cell['sample_gate']}（N={a['n']}）|")
    lines += ['', '## 完整明细与限制','',
        '- 每个组合的 `events.json` 保存首次事件；`changes.jsonl` 保存后续修改/撤回；`next_day_scored.json` 保存逐事件入场代理价、目标时点、收益和路径。',
        '- `metrics.json` 包含全部1/3/5/10/20交易日、原始及冷却口径、年度分项与区块敏感性，不挑最好周期报成绩。',
        '- `verification.json` 保存冷启动前缀、未来扰动及独立DuckDB评分复核。`source.json`和manifest提供复现输入及哈希。',
        '- 信号只有笔确认，线段/中枢可能仍变化；未使用多级别联立或量价过滤。此限制与日线相同，换频率不自动修复。',
        '- 指数不可直接买卖；Q不含费用、滑点、跟踪误差、T+1限制和资金占用，不能当成实盘盈利。',
        '- 使用当前湖中历史修订版，不是逐日归档原始快照；逐根防未来只证明算法不读后续柱，不消除源历史修订风险。',
        '- 五年窗口和频率由已有研究后选择，结果属于探索性复测，不是完全独立样本外验证。', '']
    return '\n'.join(lines)


def run(source, output, spec=MINUTE, *, source_verifier=verify_source, input_loader=load_input):
    started = time.monotonic()
    output = safe_output(output)
    if shutil.disk_usage(REPO).free < spec.reserve_bytes:
        raise ValueError('disk reserve')
    source_info = source_verifier(source,spec)
    output.mkdir(parents=True,exist_ok=False)
    manifest = dict(status='running',spec=asdict(spec),source=source_info,
        plan_sha256=digest((REPO/'docs/product/chan-signal-prediction-and-profit-experiment-plan-v1.md').read_bytes()),
        code_sha256={p.name:digest(p.read_bytes()) for p in Path(__file__).parent.glob('*.py')})
    save(output/'started.json',manifest)
    try:
        rows,days,facts,quality = input_loader(spec)
        save(output/'source.json',rows)
        save(output/'calendar.json',days)
        save(output/'source_files.json',facts)
        save(output/'input_quality.json',quality)
        print(f"input {len(rows)} rows, {quality['seconds']:.3f}s",flush=True)
        metrics,checks = [],[]
        for code in spec.codes:
            for freq in spec.frequencies:
                if time.monotonic()-started>spec.total_seconds:
                    raise TimeoutError('total time budget')
                cell_start = time.monotonic()
                bars = [r for r in rows if r['code']==code and r['frequency']==freq]
                folder = output/f'{code}_{freq}'
                folder.mkdir()
                with (folder/'changes.jsonl').open('x') as handle:
                    def sink(changes):
                        handle.write(''.join(canonical(c)+'\n' for c in changes))
                    events = replay(bars,code,freq,spec,sink)
                save(folder/'events.json',events)
                # Exact temporal prefixes selected before observing signal outcomes.
                prefix_checks = []
                for cutoff in ('2022-12-31','2024-12-31'):
                    prefix = [r for r in bars if r['date']<=cutoff]
                    observed = replay(prefix,code,freq,spec)
                    if observed != [e for e in events if e['signal_time'][:10]<=cutoff]:
                        raise ValueError('prefix replay mismatch')
                    prefix_checks.append(cutoff)
                # Alter all future OHLC; only compare earlier events, not future output.
                cutoff = '2024-12-31'
                altered = [dict(r,**{k:r[k]*(1.1 if r['date']>cutoff else 1)
                           for k in ('open','high','low','close')}) for r in bars]
                changed = replay(altered,code,freq,spec)
                if [e for e in changed if e['signal_time'][:10]<=cutoff] != [e for e in events if e['signal_time'][:10]<=cutoff]:
                    raise ValueError('future perturbation mismatch')
                cell = dict(code=code,frequency=freq,bars=len(bars),
                    evaluation_bars=sum(r['date']>=spec.evaluation_start for r in bars),
                    events=dict(Counter(e['group'] for e in events if e['evaluation'])),scores={})
                label_map = {h:label_rows(bars,days,h,spec) for h in spec.horizons}
                scored_save = []
                for group in ('B1','B2','B3'):
                    cell['scores'][group] = {}
                    for mode in ('raw','cooldown'):
                        selected = select_events(events,days,group,mode=='cooldown',spec)
                        result = {}
                        for h in spec.horizons:
                            summary,scored = summarize(selected,label_map[h])
                            result[str(h)] = summary
                            if h==1:
                                independent_score_check(bars,scored)
                                scored_save.extend(dict(group=group,mode=mode,**r) for r in scored)
                            if group=='B3' and mode=='cooldown' and h==1:
                                main_scored = scored
                        cell['scores'][group][mode] = result
                print(f'{code}/{freq}: scoring complete; block bootstrap',flush=True)
                cell['intervals'] = block_intervals(main_scored,label_map[1],days,spec)
                main = cell['scores']['B3']['cooldown']['1']
                cell['sample_gate'] = ('通过' if main['n']>=spec.min_events
                    and len(main['year_counts'])>=spec.min_years else '不足')
                cell['seconds'] = time.monotonic()-cell_start
                save(folder/'next_day_scored.json',scored_save)
                save(folder/'metrics.json',cell)
                metrics.append(cell)
                checks.append(dict(code=code,frequency=freq,prefix=prefix_checks,
                    future_perturbation=True,independent_duckdb_next_day=True))
                print(f"complete {code}/{freq}: {cell['events']}, {cell['seconds']:.2f}s",flush=True)
                if sum(p.stat().st_size for p in output.rglob('*') if p.is_file())>spec.max_output_bytes:
                    raise ValueError('output budget')
        if time.monotonic()-started>spec.total_seconds:
            raise TimeoutError('total time budget')
        save(output/'metrics.json',metrics)
        save(output/'verification.json',checks)
        (output/'report.md').write_text(report(metrics,quality))
        manifest.update(status='complete',seconds=time.monotonic()-started,
            artifacts_sha256={str(p.relative_to(output)):digest(p.read_bytes())
                for p in output.rglob('*') if p.is_file()})
        save(output/'manifest.json',manifest)
    except Exception as exc:
        save(output/'failure.json',dict(error=repr(exc),seconds=time.monotonic()-started))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chan-source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    run(args.chan_source,args.output)


if __name__=='__main__':
    main()
