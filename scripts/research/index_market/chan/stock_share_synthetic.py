"""Run/verify a fixed synthetic share-account example. No real data is accepted."""
import argparse
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path

from scripts.research.index_market.chan.stock_share_account import Account
from scripts.research.index_market.chan.stock_share_audit import audit, metrics
from scripts.research.index_market.chan.stock_share_model import D, RawBar, Signal, StockShareBacktestSpec, TradingRule


REPORTS = Path(__file__).resolve().parents[4]/'reports'
MODULES = ('stock_share_model.py', 'stock_share_account.py', 'stock_share_audit.py', 'stock_share_synthetic.py')


def jsonable(value):
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, (D, date, datetime)):
        return str(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def encode(value):
    return (json.dumps(jsonable(value), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()


def golden_inputs():
    spec = StockShareBacktestSpec(initial_cash=D(120000), warmup_days=0,
                                slippage=D(0), commission_rate=D(0), minimum_commission=D(0))
    rule = TradingRule(date(2026, 1, 1), date(2026, 12, 31), 100, 100, 100, 100, True,
                       D('.01'), D(0), D(0), 'SYNTHETIC: not an exchange rule citation')
    bars, signals = [], []
    # The signal close is 12; 120000/12 freezes Q=10000 without a test-only Q override.
    for i, price in enumerate((12, 10, 11, 12, 13, 12, 11)):
        start = datetime(2026, 1, 5, 9, 30)+timedelta(days=i)
        bar = RawBar('000001.SZ', 30, start, start+timedelta(minutes=30), D(price), D(price),
                     1000000, None, None, True, rule, 'SYNTHETIC: calendar not real')
        bars.append(bar)
        group = ('B1', 'B2', 'B3', 'S1', 'S2', 'S3', None)[i]
        signals.append([Signal(str(i), bar.code, 30, bar.end, group)] if group else [])
    return spec, bars, signals


def run_golden():
    spec, bars, signals = golden_inputs()
    account = Account(bars[0].code, spec=spec)
    for bar, events in zip(bars, signals, strict=True):
        account.step(bar, events)
    result = account.result()
    expected = [(2000, 2000, D(100000)), (3000, 5000, D(67000)), (5000, 10000, D(7000)),
                (5000, 5000, D(72000)), (3000, 2000, D(108000)), (2000, 0, D(130000))]
    actual = [(f['quantity'], f['shares'], f['cash']) for f in result['fills']]
    if actual != expected:
        raise ValueError('literal plan example differs')
    return dict(inputs=dict(spec=spec, bars=bars, signals=signals), account=result,
                audit=audit(result), metrics=metrics(result), literal_expected=expected)


def code_hashes():
    return {name: sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in MODULES}


def execute(output):
    output = output.resolve()
    if output.parent != REPORTS.resolve() or output.exists():
        raise ValueError('new direct child of repository reports required')
    data = run_golden()
    raw = encode(data)
    report = ('# 按股数缠论账户：P1合成算例\n\n'
              '只验证账本，不是真实股票回测，不证明缠论有效。\n\n'
              '方案金样本：买2000/3000/5000股，卖5000/3000/2000股。'
              '本金120000元，期末130000元，净增加10000元，收益8.3333%。'
              '本例费用及滑点为零；有成本和不可成交的反例见主题测试。\n\n'
              '逐笔账、原始合成输入和独立审计在example.json。'
              '缺少真实名单、来源核验和完整公司行为，不能启动五年真实回测。\n')
    payloads = {'example.json': raw, 'report.md': report.encode()}
    manifest = dict(status='synthetic_example_passed', real_backtest=False,
                    spec=asdict(data['inputs']['spec']),
                    code_sha256=code_hashes(),
                    artifacts_sha256={k: sha256(v).hexdigest() for k, v in payloads.items()})
    output.mkdir(parents=False, exist_ok=False)
    for name, content in payloads.items():
        with (output/name).open('xb') as stream:
            stream.write(content)
    with (output/'manifest.json').open('xb') as stream:
        stream.write(encode(manifest))
    return manifest


def verify(output):
    output = output.resolve(strict=True)
    if output.parent != REPORTS.resolve():
        raise ValueError('repository report scope required')
    paths = [output/name for name in ('manifest.json', 'example.json', 'report.md')]
    if any(p.is_symlink() or not p.is_file() or p.stat().st_size > 2*1024*1024 for p in paths):
        raise ValueError('report artifact type/size budget')
    manifest = json.loads(paths[0].read_bytes())
    if (manifest.get('status') != 'synthetic_example_passed' or manifest.get('real_backtest') is not False
            or manifest.get('spec') != jsonable(golden_inputs()[0])
            or manifest.get('code_sha256') != code_hashes()
            or set(manifest.get('artifacts_sha256', {})) != {'example.json', 'report.md'}):
        raise ValueError('report scope/code changed')
    for name, expected in manifest['artifacts_sha256'].items():
        if sha256((output/name).read_bytes()).hexdigest() != expected:
            raise ValueError('artifact changed')
    # Recompute, rather than only trusting saved success booleans or checksums.
    if (output/'example.json').read_bytes() != encode(run_golden()):
        raise ValueError('synthetic replay differs')
    return dict(status='synthetic_replay_verified', real_backtest=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--output', type=Path, help='new reports/<name>, synthetic inputs only')
    group.add_argument('--verify', type=Path, help='read-only artifact and deterministic replay audit')
    args = parser.parse_args()
    print(json.dumps(jsonable(execute(args.output) if args.output else verify(args.verify)), ensure_ascii=False))


if __name__ == '__main__':
    main()
