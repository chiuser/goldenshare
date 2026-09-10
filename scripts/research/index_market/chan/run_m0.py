"""M0 only: source/data gates, streaming events, independent audit and cases."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
import csv
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from scripts.research.index_market.chan.event_ledger import EventLedger, canonical
from scripts.research.index_market.chan.m0_data import (
    REPO, SPEC, digest, file_facts, load_input, safe_output,
)


def save(path, value):
    with path.open('x') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')


def expanded(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: expanded(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [expanded(v) for v in value]
    if hasattr(value, '__dict__'):
        return expanded(vars(value))
    return value


def verify_source(path, spec=SPEC):
    path = path.resolve(strict=True)
    actual = subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(path), 'status', '--porcelain'], text=True)
    if actual != spec.commit or dirty:
        raise ValueError('third-party commit mismatch or dirty source')
    tracked = subprocess.check_output(['git', '-C', str(path), 'ls-files', '*.py'], text=True).splitlines()
    hashes = {p: digest((path / p).read_bytes()) for p in tracked}
    if not hashes:
        raise ValueError('empty third-party Python source')
    sys.path.insert(0, str(path))
    from ChanConfig import CChanConfig
    config = CChanConfig(spec.chan_config())
    full = expanded(config)
    if full['macd_config'] != {'fast': 12, 'slow': 26, 'signal': 9}:
        raise ValueError('unexpected MACD defaults')
    if not all(full['bs_point_conf'][side]['bsp3_follow_1'] for side in ('b_conf', 's_conf')):
        raise ValueError('unexpected bsp3_follow_1')
    return dict(path=str(path), commit=actual, tracked_python_sha256=hashes, expanded_config=full)


def frames(rows, spec=SPEC):
    from ChanConfig import CChanConfig
    from Common.CEnum import KL_TYPE
    from Common.CTime import CTime
    from KLine.KLine_List import CKLine_List
    from KLine.KLine_Unit import CKLine_Unit

    if not 0 < len(rows) <= spec.max_bars:
        raise ValueError('replay bar budget')
    kl = CKLine_List(KL_TYPE.K_DAY, CChanConfig(spec.chan_config()))
    previous = None
    start = time.monotonic()
    for index, row in enumerate(rows):
        if time.monotonic()-start > spec.replay_seconds:
            raise TimeoutError('replay time budget')
        if index and row['date'] <= rows[index-1]['date']:
            raise ValueError('replay dates must be unique and increasing')
        year, month, day = map(int, row['date'].split('-'))
        unit = CKLine_Unit(dict(time_key=CTime(year, month, day, 0, 0),
                               **{k: row[k] for k in ('open', 'high', 'low', 'close')}))
        unit.set_idx(index)
        unit.kl_type = KL_TYPE.K_DAY
        if previous is not None:
            unit.set_pre_klu(previous)
        kl.add_single_klu(unit)
        previous = unit
        points = []
        for bsp in kl.bs_point_lst.bsp_store_flat_dict.values():
            begin, end, anchor = bsp.bi.get_begin_klu().idx, bsp.bi.get_end_klu().idx, bsp.klu.idx
            if not 0 <= begin <= end <= index or not begin <= anchor <= index:
                raise ValueError('invalid point index')
            points.append(dict(buy=bool(bsp.is_buy), types=sorted(set(t.value for t in bsp.type)),
                               sure=bool(bsp.bi.is_sure), bi_index=bsp.bi.idx,
                               start_date=rows[begin]['date'], start_index=begin,
                               end_date=rows[end]['date'], end_index=end,
                               anchor_date=rows[anchor]['date'], anchor_index=anchor))
        yield row['date'], index, points


def replay(rows, spec=SPEC, sink=None, progress=False):
    ledger = EventLedger(spec.replay_code, spec)
    events, days = [], []
    start = time.monotonic()
    mismatch = 0
    for day, index, points in frames(rows, spec):
        mismatch += sum(p['anchor_index'] != p['end_index'] for p in points)
        changes, new_events, daily = ledger.step(day, index, points)
        events.extend(new_events)
        days.append(daily)
        if sink is not None:
            sink(changes, new_events, daily)
        if progress and ((index+1) % 250 == 0 or index+1 == len(rows)):
            print(f'replay {index+1}/{len(rows)} {day}; events={len(events)}; elapsed={time.monotonic()-start:.2f}s', flush=True)
    return dict(events=events, days=days, changes=ledger.change_count,
                anchor_end_mismatches=mismatch, seconds=time.monotonic()-start)


def audit_saved(output):
    """Rebuild each day's state and first triggers without using EventLedger."""
    def stream(name):
        with (output / name).open() as handle:
            for line in handle:
                yield json.loads(line)

    changes = iter(stream('changes.jsonl'))
    current_change = next(changes, None)
    state, triggered, rebuilt = {}, set(), []
    for daily in stream('daily.jsonl'):
        day = daily['date']
        while current_change is not None and current_change['date'] == day:
            item = current_change
            key = item['candidate_id']
            if state.get(key) != item['before']:
                raise ValueError('change before-state inconsistency')
            if item['after'] is None:
                del state[key]
            else:
                state[key] = item['after']
            current_change = next(changes, None)
        if digest(canonical(state).encode()) != daily['state_sha256']:
            raise ValueError('daily state digest mismatch')
        for key, point in sorted(state.items()):
            if not point['sure']:
                continue
            prefix = 'B' if point['buy'] else 'S'
            targets = []
            for suffix, labels in [('1', {'1'}), ('2', {'2'}), ('3', {'3a', '3b'})]:
                if labels.intersection(point['types']):
                    targets.append(prefix+suffix)
            for group in targets:
                event_id = f'{key}|{group}'
                if event_id not in triggered:
                    triggered.add(event_id)
                    rebuilt.append((event_id, day, point['anchor_date']))
    if current_change is not None:
        raise ValueError('unconsumed changes')
    saved = [(e['event_id'], e['signal_date'], e['anchor_date']) for e in stream('events.jsonl')]
    if saved != rebuilt:
        raise ValueError('first-trigger reconstruction mismatch')
    return dict(daily_state_reconstruction=True, first_trigger_reconstruction=True, events=len(saved))


def write_cases(output, events, spec=SPEC):
    changes = [json.loads(line) for line in (output / 'changes.jsonl').read_text().splitlines()]
    selected = []
    lines = ['# M0 信号核验案例', '', '按时间选每组最早两个评估期事件，不按后续涨跌选例。',
             '表格用于精确核对两个日期，不展示收益曲线；本轮没有预测评分。', '',
             '| 组 | 识别日 | 极值日 | 滞后交易日 | 首次标签 | 后续消失日 |',
             '|---|---|---|---:|---|---|']
    for group in ('B1', 'B2', 'B3', 'S1', 'S2', 'S3'):
        sample = [e for e in events if e['group'] == group and e['evaluation']][:2]
        if not sample:
            lines.append(f'| {group} | 无样本 | — | — | — | — |')
        for event in sample:
            history = [c for c in changes if c['candidate_id'] == event['candidate_id']]
            disappearance = next((c['date'] for c in history if c['change'] == 'disappeared'
                                  and c['date'] > event['signal_date']), None)
            selected.append(dict(event=event, history=history, later_disappearance=disappearance))
            lines.append(f"| {group} | {event['signal_date']} | {event['anchor_date']} | {event['lag_bars']} | {','.join(event['types'])} | {disappearance or '未观察到'} |")
    lines += ['', '## 首批反例与状态变化', '',
              '以下只说明程序行为，不预设自然数据一定出现每种边界。缺少的场景由合成测试覆盖。', '']
    predicates = {
        '笔尚未确认，不能触发': lambda c: c['after'] is not None and not c['after']['sure'],
        '仅1p/2s，不触发研究组': lambda c: c['after'] is not None and set(c['after']['types']) <= {'1p', '2s'},
        '端点移动': lambda c: c['before'] is not None and c['after'] is not None
        and c['before']['end_index'] != c['after']['end_index'],
        '消失后重新出现': lambda c: c['change'] == 'reappeared',
        '同笔序号起点变更关联': lambda c: c['same_index_previous_candidate'] is not None,
    }
    negative = {}
    for label, predicate in predicates.items():
        sample = [c for c in changes if predicate(c)][:2]
        negative[label] = sample
        lines.append(f"- {label}：" + ('；'.join(f"{c['date']} / {c['candidate_id']}" for c in sample) or '自然数据未观察到；不修改配置凑例子。'))
    save(output / 'cases.json', dict(positive=selected, negative=negative))
    (output / 'cases.md').write_text('\n'.join(lines)+'\n')


def run(source, output, spec=SPEC):
    from dataclasses import asdict

    start = time.monotonic()
    output = safe_output(output)
    if shutil.disk_usage(REPO).free < spec.reserve_bytes:
        raise ValueError('insufficient report disk reserve')
    source_info = verify_source(source, spec)
    sample_path = REPO / 'reports/chan_theory_csi300_teaching_20260908/source.json'
    sample_rows = json.loads(sample_path.read_text())
    sample = replay(sample_rows, spec)
    print(f"sample {len(sample_rows)} bars: {sample['seconds']:.3f}s", flush=True)
    output.mkdir(parents=True, exist_ok=False)
    manifest = dict(status='running', created_at=datetime.now(timezone.utc).isoformat(),
                    spec=asdict(spec), source=source_info, sample_bars=len(sample_rows),
                    sample_seconds=sample['seconds'], sample_sha256=digest(sample_path.read_bytes()),
                    plan_sha256=digest((REPO / 'docs/product/chan-signal-prediction-and-profit-experiment-plan-v1.md').read_bytes()),
                    code_sha256={p.name: digest(p.read_bytes()) for p in Path(__file__).parent.glob('*.py')})
    save(output / 'started.json', manifest)
    try:
        rows, calendar, sources, quality = load_input(spec)
        save(output / 'input_quality.json', quality)
        save(output / 'source_files.json', sources)
        save(output / 'calendar.json', calendar)
        with (output / 'source.csv').open('x', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        manifest['source_projection_sha256'] = digest((output / 'source.csv').read_bytes())
        bars = [r for r in rows if r['ts_code'] == spec.replay_code]
        with ExitStack() as stack:
            handles = [stack.enter_context((output / name).open('x'))
                       for name in ('changes.jsonl', 'events.jsonl', 'daily.jsonl')]
            bytes_written = 0

            def sink(changes, events, daily):
                nonlocal bytes_written
                if time.monotonic()-start > spec.total_seconds:
                    raise TimeoutError('overall time budget')
                for handle, records in zip(handles, (changes, events, [daily])):
                    payload = ''.join(canonical(item)+'\n' for item in records)
                    bytes_written += len(payload.encode())
                    if bytes_written > spec.max_output_bytes // 2:
                        raise ValueError('stream output budget; reserve remaining space for evidence')
                    handle.write(payload)
                    handle.flush()

            result = replay(bars, spec, sink, progress=True)
        checks = []
        for cutoff in spec.prefix_dates:
            subset = [r for r in bars if r['date'] <= cutoff]
            prefix = replay(subset, spec)
            if prefix['events'] != [e for e in result['events'] if e['signal_date'] <= cutoff]:
                raise ValueError(f'prefix event inconsistency {cutoff}')
            if prefix['days'] != [d for d in result['days'] if d['date'] <= cutoff]:
                raise ValueError(f'prefix daily inconsistency {cutoff}')
            checks.append(dict(cutoff=cutoff, bars=len(subset), events=len(prefix['events']), passed=True))
            print(f'prefix verified {cutoff}', flush=True)
            if time.monotonic()-start > spec.total_seconds:
                raise TimeoutError('overall time budget')
        cutoff = '2020-12-31'
        changed = [{**r, **({k: r[k]*1.1 for k in ('open', 'high', 'low', 'close')}
                           if r['date'] > cutoff else {})} for r in bars]
        perturbed = replay(changed, spec)
        if [d for d in perturbed['days'] if d['date'] <= cutoff] != [d for d in result['days'] if d['date'] <= cutoff]:
            raise ValueError('future perturbation changed past states')
        if [e for e in perturbed['events'] if e['signal_date'] <= cutoff] != [e for e in result['events'] if e['signal_date'] <= cutoff]:
            raise ValueError('future perturbation changed past events')
        audit = audit_saved(output)
        audit.update(prefix_checks=checks, future_perturbation_passed=True,
                     future_perturbation_cutoff=cutoff, anchor_end_mismatches=result['anchor_end_mismatches'])
        if file_facts([Path(p['path']) for p in sources]) != sources:
            raise ValueError('source changed during M0')
        if verify_source(source, spec) != source_info:
            raise ValueError('third-party source changed during M0')
        if result['anchor_end_mismatches']:
            raise ValueError('point anchor differs from current bi end; clarify semantics before M1')
        save(output / 'verification.json', audit)
        write_cases(output, result['events'], spec)
        counts = {g: sum(e['group'] == g and e['evaluation'] for e in result['events'])
                  for g in ('B1', 'B2', 'B3', 'S1', 'S2', 'S3')}
        annual = Counter((e['signal_date'][:4], e['group']) for e in result['events'] if e['evaluation'])
        save(output / 'counts.json', dict(evaluation=counts,
                                        initialization=sum(not e['evaluation'] for e in result['events']),
                                        annual=[dict(year=y, group=g, events=n) for (y, g), n in sorted(annual.items())]))
        report = ['# 缠论M0：沪深300信号账本核验', '',
                  '工程核验通过，等待人工确认；尚未计算预测成绩或区间盈利。', '',
                  f"三指数输入各{quality['open_days']}个交易日，{spec.start}—{spec.end}；2010年仅初始化。",
                  f"只回放沪深300，合计{len(result['events'])}个组别事件（含初始化）；不同组可重合，不是独立机会总数。", '',
                  '| 组 | 2011年起首次事件数（未冷却） |', '|---|---:|']
        report += [f'| {g} | {n} |' for g, n in counts.items()]
        report += ['', '## 核验与局限', '',
                   '- 数据检查覆盖研究需要的OHLC、日期、主键和完整性，不等同正式DG checks或源端对账。',
                   '- 五个固定日期的独立前缀回放与连续回放一致；改变2020年后行情不改变此前状态/事件。',
                   '- 从保存的状态变化独立重建每日摘要和首次触发，通过；事件撤回不会删除原记录。',
                   '- 当前文件可能包含历史修订；不声称具备当年发布版本，不是独立未见数据验证。',
                   '- 数量未做A实验20日冷却，不能拿本表判断是否达到正式评分样本下限。',
                   '- 这里只验证固定程序的日K笔级信号，不证明完整缠论、预判有效或可以盈利。', '',
                   '[逐例核验](cases.md) · [输入检查](input_quality.json) · [验证明细](verification.json) · [事件账本](events.jsonl)', '',
                   '下一步：人工确认首次识别口径；之后另行进入M1买点预判，不自动启动交易账户。']
        (output / 'report.md').write_text('\n'.join(report)+'\n')
        elapsed = time.monotonic()-start
        if elapsed > spec.total_seconds or sum(p.stat().st_size for p in output.iterdir()) > spec.max_output_bytes:
            raise ValueError('M0 final time/output budget')
        manifest.update(status='M0_ENGINEERING_PASSED_PENDING_REVIEW', elapsed_seconds=elapsed,
                        quality=quality, counts=counts, replay_seconds=result['seconds'], changes=result['changes'],
                        artifacts_sha256={p.name: digest(p.read_bytes()) for p in output.iterdir() if p.is_file()})
        save(output / 'manifest.json', manifest)
        print(json.dumps(dict(output=str(output), counts=counts, elapsed_seconds=elapsed), ensure_ascii=False), flush=True)
        return manifest
    except BaseException as exc:
        save(output / 'failure.json', dict(status='failed', error=repr(exc), elapsed_seconds=time.monotonic()-start))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chan-source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.chan_source, args.output)


if __name__ == '__main__':
    main()
