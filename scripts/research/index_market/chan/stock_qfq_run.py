"""Fixed Weilan Lithium QFQ backtest. Reads eight Lake files; writes only a new report."""
import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import time

from scripts.research.index_market.chan.m0_data import REPO, digest, safe_output
from scripts.research.index_market.chan.minute_data import slots
from scripts.research.index_market.chan.minute_replay import replay
from scripts.research.index_market.chan.minute_variant_a import VARIANT_A, verify_variant_source
from scripts.research.index_market.chan.run_m0 import save
from scripts.research.index_market.chan.stock_chan_replay_data import LAKE, Reader, SPEC as READ_SPEC
from scripts.research.index_market.chan.stock_qfq_model import SPEC, account_prefix_equal, simulate, summarize
from scripts.research.index_market.chan.stock_share_synthetic import jsonable


def load(reader, spec=SPEC):
    gold = [LAKE/f'gold/quote/stk_mins_qfq/freq=30/ts_code={spec.code}/year={y}/part-000.parquet'
            for y in range(int(spec.start[:4]), int(spec.end[:4])+1)]
    life = LAKE/'silver/basic/stock_lifecycle/full/part-000.parquet'
    cal = LAKE/'silver/calendar/trade_calendar/full/part-000.parquet'
    identities = reader.read([life], '''SELECT ts_code,name,exchange,is_cny_stock,list_date,delist_date
        FROM read_parquet(?,hive_partitioning=false) WHERE ts_code=?''', [str(life), spec.code], 1)
    if (len(identities) != 1 or not identities[0]['is_cny_stock'] or identities[0]['exchange'] != 'SZSE'
            or identities[0]['name'] != spec.name or str(identities[0]['list_date']) > spec.start
            or identities[0]['delist_date'] is not None and str(identities[0]['delist_date']) <= spec.asof):
        raise ValueError('stock lifecycle/survivorship scope mismatch')
    days = reader.read([cal], '''SELECT CAST(trade_date AS VARCHAR) AS date FROM read_parquet(?,hive_partitioning=false)
        WHERE exchange='SSE' AND is_open AND trade_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
        ORDER BY trade_date''', [str(cal), spec.start, spec.end], 2000)
    rows = reader.read(gold, '''SELECT ts_code AS code,freq AS frequency,exchange,'qfq' AS price_basis,
        CAST(trade_date AS VARCHAR) AS date,CAST(trade_time AS VARCHAR) AS time,open,high,low,close,vol,amount
        FROM read_parquet(?,hive_partitioning=false) WHERE trade_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
        ORDER BY trade_time''', [[str(p) for p in gold], spec.start, spec.end], spec.account.max_bars)
    validate_rows(rows, [d['date'] for d in days], spec)
    return rows, identities


def validate_rows(rows, days, spec=SPEC):
    import math
    expected = [f'{d} {s}' for d in days for s in slots(spec.frequency)]
    if not rows or len(rows) > spec.account.max_bars or days != sorted(set(days)):
        raise ValueError('empty/invalid calendar or bar budget')
    if [r['time'] for r in rows] != expected:
        raise ValueError('QFQ grid mismatch; no silently missing/duplicated bars')
    for r in rows:
        if (r['code'] != spec.code or r['frequency'] != spec.frequency or r['exchange'] != 'SZSE'
                or r['price_basis'] != 'qfq' or r['date'] != r['time'][:10]
                or not spec.start <= r['date'] <= spec.end
                or any(v is None or not math.isfinite(v) or v <= 0
                       for v in [r[k] for k in ('open', 'high', 'low', 'close', 'vol', 'amount')])
                or r['low'] > min(r['open'], r['close']) or r['high'] < max(r['open'], r['close'])
                or r['vol'] != int(r['vol'])):
            raise ValueError('QFQ data quality/identity/volume units')
    if len(days) <= spec.account.warmup_days:
        raise ValueError('insufficient warmup history')


def source_gate():
    folder = REPO/READ_SPEC.a_report
    raw = (folder/'manifest.json').read_bytes()
    if digest(raw) != READ_SPEC.a_manifest:
        raise ValueError('frozen A manifest changed')
    manifest = json.loads(raw)
    for name, expected in manifest['code_sha256'].items():
        if digest(Path(__file__).with_name(name).read_bytes()) != expected:
            raise ValueError(f'frozen A code changed: {name}')
    source = verify_variant_source(Path(manifest['source']['path']))
    if source != manifest['source']:
        raise ValueError('frozen Chan source/configuration changed')
    return source


def run_signals(rows, output, started, spec=SPEC):
    durations = {}
    def one(name, data):
        remaining = spec.total_seconds-(time.monotonic()-started)
        if remaining <= 0:
            raise TimeoutError('whole backtest time budget')
        config = replace(VARIANT_A, codes=(spec.code,), frequencies=(spec.frequency,),
                         replay_seconds=min(spec.replay_seconds, remaining))
        before = time.monotonic()
        print(f'{name}: {len(data)} bars', flush=True)
        result = replay(data, spec.code, spec.frequency, config)
        durations[name] = time.monotonic()-before
        save(output/f'{name}_events.json', result)
        return result
    events = one('full', rows)
    print(f'full signals: {dict(Counter(e["group"] for e in events))}', flush=True)
    prefixes, checks = {}, {}
    for year in range(2022, 2026):
        cutoff = f'{year}-12-31 23:59:59'
        data = [r for r in rows if r['time'] <= cutoff]
        if not data or len(data) == len(rows):
            continue
        pref = one(f'prefix_{year}', data)
        prefixes[year] = (data, pref)
        checks[f'prefix_{year}'] = pref == [e for e in events if e['signal_time'] <= cutoff]
    cutoff = prefixes[2024][0][-1]['time']
    future = deepcopy(rows)
    for r in future:
        if r['time'] > cutoff:
            for k in ('open', 'high', 'low', 'close'):
                r[k] *= 1.37
    changed = one('future', future)
    checks['future_isolation'] = ([e for e in changed if e['signal_time'] <= cutoff] ==
                                  [e for e in events if e['signal_time'] <= cutoff])
    scaled = [dict(r, **{k: r[k]*2 for k in ('open', 'high', 'low', 'close')}) for r in rows]
    checks['scaled'] = one('scaled', scaled) == events
    days = sorted({r['date'] for r in rows})
    shorter = [r for r in rows if r['date'] >= days[spec.account.warmup_days]]
    shorter_events = one('shorter', shorter)
    common_start = days[2*spec.account.warmup_days]
    omit = {'signal_index', 'start_index', 'end_index', 'anchor_index', 'bi_index'}
    def semantic(es):
        return [{k: v for k, v in e.items() if k not in omit} for e in es if e['signal_time'][:10] >= common_start]
    left, right = semantic(events), semantic(shorter_events)
    checks['shorter_initialization'] = left == right
    evidence = dict(checks=checks, all_passed=all(checks.values()), seconds=durations,
                    future_cutoff=cutoff, shorter_common_start=common_start,
                    shorter_full_count=len(left), shorter_count=len(right),
                    shorter_only_full=[e for e in left if e not in right][:5],
                    shorter_only_short=[e for e in right if e not in left][:5])
    save(output/'signal_checks.json', evidence)
    return events, prefixes, evidence


def report_text(summaries, checks, seconds):
    base = summaries['model_cost']
    def pct(value):
        return '不适用' if value is None else f'{float(value)*100:.2f}%'
    text = f'''# 蔚蓝锂芯：前复权缠论股数回测

范围2021-09-09—2026-09-08，30分钟；250日初始化，允许信号自{base['eligible_signal_start']}起。
仅该股自身信号，不看指数；B1/B2/B3买20/30/50，S1/S2/S3卖50/30/20，按固定股数基数。

| 模型 | 期末权益 | 累计收益 | 全范围年化 | 最大回撤 | 完整轮次 | 胜率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
'''
    for key, label in [('gross', '策略：无费用滑点'), ('model_cost', '策略：佣金+5bp滑点'),
                       ('stress', '策略：佣金+10bp滑点'), ('hold', '同股买入持有：佣金+5bp滑点')]:
        s = summaries[key]
        text += f"| {label} | {float(s['ending_equity']):,.2f} | {pct(s['total_return'])} | {pct(s['full_range_annualized'])} | {pct(s['maximum_drawdown'])} | {s['completed_cycles']} | {pct(s['win_rate'])} |\n"
    text += f'''
初始资金100万元。模型费用为佣金万分之三、每次部分成交最低5元；不计印花税/过户费，不模拟涨跌停排队。下一根K线开盘模型成交，T+1、上一柱量1%上限、100股取整；前复权数值精度8位。没有额外分红送股入账。以上不是实际券商账户净收益。

主模型允许交易区间年化：{pct(base['eligible_range_annualized'])}；平均投入比例{pct(base['average_invested_fraction'])}。
首次成交{base['first_fill']}；成交{base['fill_count']}笔；期末持股{base['end_shares']}，未完成轮次标记{base['unfinished_cycle']}。未强制期末卖出，浮动盈亏已计入权益。

允许交易期信号：{base['eligible_signals']}。信号数量不等于成交数量，同类每轮仅启用一次。

## 年度模型收益

| 年份 | 策略（佣金+5bp） | 买入持有 | 范围 |
| --- | ---: | ---: | --- |
'''
    for a, b in zip(base['annual'], summaries['hold']['annual'], strict=True):
        text += f"| {a['year']} | {pct(a['return_value'])} | {pct(b['return_value'])} | {'部分年度' if a['partial_calendar_year'] else '完整年度'} |\n"
    text += f'''
## 验证与明细

信号检查：{checks['checks']}。缩短初始化比较不删除差异；若有失败，不称为稳定性通过。
账户逐笔现金、股数、T+1、费用独立审计及年度截断检查见account_checks.json。
总耗时约{seconds:.2f}秒；生命周期、Gold与日历读取前后哈希一致。历史日历用SSE共同交易日作网格检查，不声称已认证SZSE独立日历。

- full_events.json：全部首次确认事件，包含锚点与首次可知时间。
- model_cost_account.json：主模型逐笔成交、意图、净值及完整/未完成轮次。
- summary.json：所有模型的指标及年度收益；input.json为已冻结的前复权输入。
- 只测指定股票，不据此宣称缠论普遍有效；不按收益调参或换股。
'''
    return text


def execute(output, spec=SPEC):
    if spec != SPEC:
        raise ValueError('fixed single-stock scope only')
    output = safe_output(output)
    if shutil.disk_usage(REPO).free < spec.reserve_bytes:
        raise ValueError('report disk reserve')
    started = time.monotonic()
    source = source_gate()
    reader = Reader(replace(READ_SPEC, max_files=spec.max_files, max_bytes=spec.max_bytes,
                            pilot_seconds=spec.total_seconds))
    rows, identity = load(reader, spec)
    output.mkdir(parents=True)
    save(output/'input.json', rows)
    save(output/'identity.json', jsonable(identity))
    manifest = dict(status='running', spec=jsonable(asdict(spec)), source=source,
                    created_at_utc=datetime.now(timezone.utc).isoformat(), basis='qfq_model')
    try:
        events, prefixes, signal_checks = run_signals(rows, output, started, spec)
        summaries, accounts = {}, {}
        for mode in ('model_cost', 'gross', 'stress', 'hold'):
            print(f'account {mode}: {len(rows)} bars', flush=True)
            account = simulate(rows, events, spec, 'model_cost' if mode == 'hold' else mode, hold=mode == 'hold')
            accounts[mode] = account
            summaries[mode] = summarize(account, rows, events, spec)
            save(output/f'{mode}_account.json', jsonable(account))
        checks = {}
        for year, (data, pref) in prefixes.items():
            result = simulate(data, pref, spec)
            checks[f'prefix_{year}'] = account_prefix_equal(accounts['model_cost'], result, data[-1]['time'])
        if not all(checks.values()):
            raise ValueError('account prefix discrepancy')
        checks['independent_ledger_audit'] = 'passed_all_four_accounts'
        save(output/'account_checks.json', checks)
        save(output/'summary.json', jsonable(summaries))
        manifest['read_audit'] = reader.verify_unchanged()
        seconds = time.monotonic()-started
        if seconds > spec.total_seconds:
            raise TimeoutError('whole backtest time budget')
        with (output/'report.md').open('x') as stream:
            stream.write(report_text(summaries, signal_checks, seconds))
        manifest.update(status='complete' if signal_checks['all_passed'] else 'complete_with_signal_stability_differences',
                        seconds=seconds, all_signal_checks_passed=signal_checks['all_passed'])
        return summaries
    except BaseException as exc:
        manifest.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        save(output/'queries.json', reader.queries)
        save(output/'source_hashes.json', reader.hashes)
        names = ('stock_qfq_model.py', 'stock_qfq_run.py', 'stock_share_account.py', 'stock_share_model.py',
                 'stock_share_audit.py', 'stock_share_synthetic.py', 'minute_replay.py', 'minute_variant_a.py',
                 'stock_chan_replay_data.py', 'stock_chan_rank.py', 'event_ledger.py', 'minute_data.py', 'm0_data.py', 'run_m0.py')
        manifest['code_sha256'] = {n: digest(Path(__file__).with_name(n).read_bytes()) for n in names}
        paths = [p for p in output.iterdir() if p.is_file()]
        manifest['output_bytes_before_manifest'] = sum(p.stat().st_size for p in paths)
        if manifest['output_bytes_before_manifest'] > spec.max_output_bytes:
            manifest['status'] = 'output_budget_exceeded'
        manifest['artifacts_sha256'] = {p.name: digest(p.read_bytes()) for p in paths}
        save(output/'manifest.json', manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = execute(args.output)
    print(json.dumps({k: {m: jsonable(v[m]) for m in ('total_return', 'maximum_drawdown', 'completed_cycles')}
                      for k, v in result.items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
