"""Frozen A contrast: disable buy-side B3 linkage, reuse authenticated input."""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import statistics
import time

from scripts.research.index_market.chan.event_ledger import canonical
from scripts.research.index_market.chan.m0_data import REPO, digest, safe_output
from scripts.research.index_market.chan.minute_data import MINUTE, MinuteSpec
from scripts.research.index_market.chan.minute_replay import replay
from scripts.research.index_market.chan.minute_score import label_rows, summarize
from scripts.research.index_market.chan.run_m0 import expanded, save, verify_source
from scripts.research.index_market.chan.run_minute import run
from scripts.research.index_market.chan.verify_minute import audit


@dataclass(frozen=True)
class VariantASpec(MinuteSpec):
    variant: str = 'A-buy-B3-no-follow1'
    bsp3_follow_1_buy: bool = False
    baseline: str = 'reports/chan_minute_5y_20260909'
    baseline_manifest_sha256: str = '69f15a64ed34475c2c0002b3ee6f64b3e4e0fc95ed6de54a84a62c282c9a4f83'

    def chan_config(self):
        return dict(super().chan_config(), **{'bsp3_follow_1-buy':self.bsp3_follow_1_buy})


VARIANT_A = VariantASpec()
REUSED_CODE = ('minute_data.py','minute_replay.py','minute_score.py','m0_data.py',
               'event_ledger.py','run_m0.py')


def require_single_change(base, changed):
    expected = deepcopy(base)
    if expected['bs_point_conf']['b_conf']['bsp3_follow_1'] is not True:
        raise ValueError('baseline buy B3 linkage is not true')
    expected['bs_point_conf']['b_conf']['bsp3_follow_1'] = False
    if canonical(changed)!=canonical(expected):
        raise ValueError('configuration must differ only at buy-side B3 linkage')


def require_scope(spec):
    for key,value in asdict(MINUTE).items():
        if getattr(spec,key)!=value:
            raise ValueError(f'baseline scope changed: {key}')
    if asdict(spec)!=asdict(VARIANT_A):
        raise ValueError('unapproved A variant identity or settings')


def read_baseline(spec=VARIANT_A):
    require_scope(spec)
    folder = (REPO/spec.baseline).resolve(strict=True)
    manifest_bytes = (folder/'manifest.json').read_bytes()
    if digest(manifest_bytes)!=spec.baseline_manifest_sha256:
        raise ValueError('baseline manifest fingerprint mismatch')
    manifest = json.loads(manifest_bytes)
    if manifest['status']!='complete' or manifest['spec']!=json.loads(canonical(asdict(MINUTE))):
        raise ValueError('baseline incomplete or different scope')
    paths = [(folder/name).resolve(strict=True) for name in manifest['artifacts_sha256']]
    if (len(paths)>100 or any(not p.is_relative_to(folder) for p in paths)
            or sum(p.stat().st_size for p in paths)>spec.max_output_bytes):
        raise ValueError('baseline artifact path or byte budget')
    check = audit(folder)
    code_folder = Path(__file__).parent
    for name in REUSED_CODE:
        if digest((code_folder/name).read_bytes())!=manifest['code_sha256'][name]:
            raise ValueError(f'reused algorithm changed: {name}')
    # Read only payloads authenticated in the fixed historical manifest.
    payloads = {}
    for name in ('source.json','calendar.json','source_files.json','input_quality.json','metrics.json'):
        data = (folder/name).read_bytes()
        if digest(data)!=manifest['artifacts_sha256'][name]:
            raise ValueError(f'baseline payload changed: {name}')
        payloads[name] = json.loads(data)
    if len(payloads['source.json'])>spec.max_rows or len(payloads['calendar.json'])>spec.max_calendar_rows:
        raise ValueError('baseline row budget')
    return folder,manifest,payloads,check


def verify_variant_source(source, spec=VARIANT_A):
    require_scope(spec)
    base = verify_source(source,MINUTE)
    from ChanConfig import CChanConfig

    actual = expanded(CChanConfig(spec.chan_config()))
    require_single_change(base['expanded_config'],actual)
    return dict(base,expanded_config=actual,
        single_config_change={'bs_point_conf.b_conf.bsp3_follow_1':[True,False]},
        baseline_manifest_sha256=spec.baseline_manifest_sha256)


def event_diff(before,after):
    old,new = {e['event_id']:e for e in before},{e['event_id']:e for e in after}
    common = sorted(old.keys() & new.keys())
    shifted = [k for k in common if (old[k]['signal_time'],old[k]['anchor_index']) !=
               (new[k]['signal_time'],new[k]['anchor_index'])]
    return dict(added=sorted(new.keys()-old.keys()),removed=sorted(old.keys()-new.keys()),
                timing_or_anchor_changed=shifted,unchanged=len(common)-len(shifted))


def risk_summary(events,rows):
    if not events:
        return dict(n=0)
    rises = [rows[e['signal_index']]['close']/rows[e['anchor_index']]['low']-1 for e in events]
    lags = [e['lag_bars'] for e in events]
    return dict(n=len(events),median_anchor_to_signal_rise=statistics.median(rises),
                mean_anchor_to_signal_rise=statistics.mean(rises),
                median_lag_bars=statistics.median(lags),max_lag_bars=max(lags))


def comparison(output,baseline,payloads,spec=VARIANT_A):
    new_metrics = json.loads((output/'metrics.json').read_text())
    results = []
    for old,now in zip(payloads['metrics.json'],new_metrics,strict=True):
        code,freq = old['code'],old['frequency']
        if (now['code'],now['frequency'])!=(code,freq):
            raise ValueError('comparison cell misalignment')
        name = f'{code}_{freq}'
        before = json.loads((baseline/name/'events.json').read_text())
        after = json.loads((output/name/'events.json').read_text())
        old_buy = [e for e in before if e['evaluation'] and e['group']=='B3']
        new_buy = [e for e in after if e['evaluation'] and e['group']=='B3']
        diff = event_diff(old_buy,new_buy)
        bars = [r for r in payloads['source.json'] if r['code']==code and r['frequency']==freq]
        labels = label_rows(bars,payloads['calendar.json'],1,spec)
        added = [e for e in new_buy if e['event_id'] in diff['added']]
        other = {group:event_diff([e for e in before if e['evaluation'] and e['group']==group],
                                  [e for e in after if e['evaluation'] and e['group']==group])
                 for group in ('B1','B2','S1','S2','S3')}
        def cooled_ids(folder):
            return {r['event_id'] for r in json.loads((folder/name/'next_day_scored.json').read_text())
                    if r['group']=='B3' and r['mode']=='cooldown'}
        old_cool,new_cool = cooled_ids(baseline),cooled_ids(output)
        results.append(dict(code=code,frequency=freq,events=diff,other_groups=other,
            cooldown_replacement=dict(added=sorted(new_cool-old_cool),removed=sorted(old_cool-new_cool)),
            before=old['scores']['B3'],after=now['scores']['B3'],
            newly_added_next_day=summarize(added,labels)[0],
            risk_before=risk_summary(old_buy,bars),risk_after=risk_summary(new_buy,bars),
            intervals_after=now['intervals'],sample_gate_after=now['sample_gate']))
    save(output/'comparison.json',results)
    def pct(v):
        return '—' if v is None else f'{v*100:.2f}%'
    lines = ['# 试验A：仅关闭买入三买的前置关联','',
        '对照为原五年30/60分钟结果；输入投影相同，初始化及预测/冷却口径不变。',
        'Q=下一根完整K线开盘到下一交易日收盘的无成本指数价格代理收益；不是账户回测。','',
        '## 主结果（20交易日冷却）','',
        '|指数|分钟|原始数 原→A|冷却后有效N 原→A|上涨率 原→A|平均Q 原→A|A基线Q|A中位Q|A平均MAE|',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for c in results:
        old,new = c['before']['cooldown']['1'],c['after']['cooldown']['1']
        lines.append(f"|{c['code']}|{c['frequency']}|{c['risk_before']['n']}→{c['risk_after']['n']}|"
            f"{old['n']}→{new['n']}|{pct(old['up'])}→{pct(new['up'])}|{pct(old['q'])}→{pct(new['q'])}|"
            f"{pct(new['baseline_q'])}|{pct(new['median_q'])}|{pct(new['mae'])}|")
    lines += ['', '## 原始口径与新增事件诊断','',
        '新增事件只按身份集合差确定，不按收益筛选；冷却样本可能被更早新增信号替换。', '',
        '|指数|分钟|原始平均Q 原→A|新增事件N|新增事件平均Q|A低点至触发反弹中位数|A确认滞后中位数(根)|',
        '|---|---:|---:|---:|---:|---:|---:|']
    for c in results:
        a = c['newly_added_next_day']
        lines.append(f"|{c['code']}|{c['frequency']}|{pct(c['before']['raw']['1']['q'])}→{pct(c['after']['raw']['1']['q'])}|"
            f"{a['n']}|{pct(a['q'])}|{pct(c['risk_after'].get('median_anchor_to_signal_rise'))}|{c['risk_after'].get('median_lag_bars','—')}|")
    lines += ['', '## 解读边界','',
        '- 单变量配置比较覆盖全部展开参数，不只是核对一个布尔值；旧配置六组回放与原事件逐条一致。',
        '- 相同历史的探索性对照，未对版本间收益差做显著性检验；不能把均值变高直接称为显著改善。',
        '- A相对匹配基线的区块区间、年度分项、全部h和去重口径在原始metrics及comparison.json中；不挑最优周期。',
        '- 第13节样本门槛继续适用，当前家族区间不涵盖历次选型的全部多重尝试。',
        '- 仅笔确认，不保证线段/中枢稳定；没有新增量价过滤、止损或实际交易限制。',
        '- 本轮不重新访问Lake；原Gold质量检查为历史事实，本轮只核验冻结投影/原代码与事件。', '']
    (output/'comparison.md').write_text('\n'.join(lines))
    return results


def execute(source,output,spec=VARIANT_A):
    started = time.monotonic()
    output = safe_output(output)
    baseline,manifest,payloads,check = read_baseline(spec)
    source_info = verify_variant_source(source,spec)
    require_single_change(manifest['source']['expanded_config'],source_info['expanded_config'])
    if source_info['tracked_python_sha256']!=manifest['source']['tracked_python_sha256']:
        raise ValueError('third-party source differs from baseline')
    # Six original-config replays on exactly the saved projection before variant work.
    for code in spec.codes:
        for freq in spec.frequencies:
            bars = [r for r in payloads['source.json'] if r['code']==code and r['frequency']==freq]
            observed = replay(bars,code,freq,MINUTE)
            saved = json.loads((baseline/f'{code}_{freq}'/'events.json').read_text())
            if observed!=saved:
                raise ValueError('original configuration no longer reproduces events')
            print(f'baseline reproduced {code}/{freq}: {len(saved)} events',flush=True)

    def loader(actual_spec):
        require_scope(actual_spec)
        # Provenance paths are historical, not sources read again in this run.
        quality = dict(payloads['input_quality.json'],seconds=0.0,files=0,bytes=0,
            input_mode='authenticated_saved_projection',lake_files_read_this_run=0,
            inherited_quality=payloads['input_quality.json'],baseline_audit=check,
            baseline=str(baseline),baseline_manifest_sha256=spec.baseline_manifest_sha256)
        return payloads['source.json'],payloads['calendar.json'],payloads['source_files.json'],quality

    def verifier(actual_source,actual_spec):
        if actual_source!=source:
            raise ValueError('source identity changed')
        require_scope(actual_spec)
        return source_info

    run(source,output,spec,source_verifier=verifier,input_loader=loader)
    comparison(output,baseline,payloads,spec)
    verification = audit(output)
    if time.monotonic()-started>spec.total_seconds:
        raise TimeoutError('variant overall budget')
    if sum(p.stat().st_size for p in output.rglob('*') if p.is_file())>spec.max_output_bytes:
        raise ValueError('variant output budget')
    save(output/'comparison_manifest.json',dict(status='complete',seconds=time.monotonic()-started,
        baseline_audit=check,original_config_replayed_cells=6,variant_audit=verification,
        base_source_sha256=manifest['artifacts_sha256']['source.json'],
        variant_source_sha256=digest((output/'source.json').read_bytes()),
        artifacts_sha256={name:digest((output/name).read_bytes())
            for name in ('manifest.json','comparison.json','comparison.md')}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chan-source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    execute(args.chan_source,args.output)


if __name__=='__main__':
    main()
