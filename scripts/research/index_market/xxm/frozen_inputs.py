from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar


def load_frozen_inputs(root: Path) -> tuple[dict[int, list[XxmBar]], dict]:
    manifest = json.loads((root / "historical_withdrawal_full_timeline_20261013.json").read_text())
    merged: dict[int, dict[str, dict]] = {60: {}, 90: {}, 120: {}}
    for relative, sha in manifest["frozen_definitions"]["inputs"].items():
        path = root / relative
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise ValueError(f"Frozen input hash changed: {relative}")
        prefix = path.stem.split("_")[0]
        freq = int(prefix) if prefix.isdigit() else int(path.stem.split("_")[-1])
        with path.open(newline="") as stream:
            for row in csv.DictReader(stream):
                stamp = row.get("trade_time") or row.get("time")
                if not stamp:
                    raise ValueError("Frozen minute endpoint missing")
                previous = merged[freq].get(stamp)
                if previous is not None:
                    if float(previous["close"]) != float(row["close"]) or any(
                        abs(float(previous[key]) - float(row[key])) >= 1e-8 for key in ("dif", "hist")
                    ):
                        raise ValueError("Frozen source overlap differs")
                else:
                    merged[freq][stamp] = row
    series = {}
    for freq, rows in merged.items():
        series[freq] = [XxmBar(stamp.replace(" ", "T") + "+08:00", float(row["close"]), float(row["dif"]),
                              float(row.get("dea") or (float(row["dif"]) - float(row["hist"]) / 2)), float(row["hist"]))
                        for stamp, row in sorted(rows.items())]
    return series, manifest


# Independently prepared before r2 product edits. This identity is an evidence
# pointer, not a configurable product rule or a new calculator.
EXPECTATIONS = Path(__file__).resolve().parents[4] / 'reports/xxm_top_activation_expectations_20261018_01'
EXPECTED_MANIFEST_SHA = '83e86164dc95b44b492311d8ba38ef255bcc20d70ca40338a58a79f6d7a6688f'


def expected_unit(name: str):
    from .cross_index_daily import read_unit
    if hashlib.sha256((EXPECTATIONS/'manifest.json').read_bytes()).hexdigest() != EXPECTED_MANIFEST_SHA:
        raise ValueError('Independent expected manifest changed')
    value = read_unit(EXPECTATIONS, name)
    if value is None:
        raise ValueError('Independent expected unit missing: '+name)
    return value


def expected_steps(group: str, period: str, gate: float):
    """Read only sealed outputs. Never invoke a research calculator here."""
    import gzip
    metadata = expected_unit(f'{group}_{period}_{gate}')
    path = EXPECTATIONS/metadata['file']
    if path.stat().st_size > 20*1024**2 or hashlib.sha256(path.read_bytes()).hexdigest() != metadata['sha256']:
        raise ValueError('Independent expected rows changed')
    count = size = 0
    digest = hashlib.sha256()
    with gzip.open(path, 'rb') as stream:
        for line in stream:
            size += len(line)
            if size > 128*1024**2:
                raise ValueError('Independent expected rows exceed budget')
            digest.update(line);count += 1
            yield json.loads(line)['expected']
    if count != metadata['rows'] or size != metadata['rawBytes'] or digest.hexdigest() != metadata['contentSha256']:
        raise ValueError('Independent expected row count/content changed')


def assert_expected_recognition(bars, group, period, gate, *, cuts=()):
    from collections import Counter
    from dataclasses import asdict
    from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
    from src.biz.services.wealth.market.index_detail_xxm.spec import XxmSpec
    metadata = expected_unit(f'{group}_{period}_{gate}')
    source_digest = hashlib.sha256(json.dumps([asdict(b) for b in bars],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    assert source_digest == metadata['inputSha256']
    calc = XxmCalculator(period=period,source_identity=metadata['sourceIdentity'],spec=XxmSpec(dif_turn_pct=gate))
    assert calc.spec.spec_hash == metadata['expectedSpecHash']
    events=[];snapshots={0:calc.snapshot()} if 0 in cuts else {};confirmations={0:None} if 0 in cuts else {};last=None
    for n,(bar,expected) in enumerate(zip(bars,expected_steps(group,period,gate),strict=True),1):
        step=calc.step(bar)
        assert json.loads(json.dumps(asdict(step))) == expected,(group,period,gate,bar.time)
        events.extend(step.events)
        last=next((e for e in step.events if e['type']=='STRUCTURE'),last)
        if n in cuts:snapshots[n]=calc.snapshot();confirmations[n]=last
    assert dict(Counter(e['direction']+':'+e['type'] for e in events)) == metadata['eventCounts']
    assert json.loads(json.dumps(calc.snapshot())) == metadata['finalSnapshot']
    return calc,events,snapshots,confirmations


def forecast_inventory():
    """Apply only the approved, source-backed classification correction."""
    from .cross_index_daily import read_unit
    root = EXPECTATIONS.parent/'xxm_top_activation_r2_implementation_20261019'
    path = root/'forecast_classification_correction.json'
    if hashlib.sha256(path.read_bytes()).hexdigest() != '4ef877e6bcdc0ddb54606b08c59af3a03f02ee5365db7f3b6dde96f45da1668f':
        raise ValueError('Approved forecast classification correction changed')
    correction=read_unit(root,'forecast_classification_correction')
    if correction['status']!='APPROVED' or hashlib.sha256((EXPECTATIONS/'forecast_inventory.json').read_bytes()).hexdigest()!=correction['originalInventorySha256']:
        raise ValueError('Correction does not match the sealed inventory')
    values=expected_unit('forecast_inventory')
    by_key={(v['period'],v['gate'],v['rows']):v for v in values}
    assert len(correction['items'])==18
    for item in correction['items']:
        value=by_key[item['period'],item['gate'],item['rows']]
        original=Path(__file__).resolve().parents[4]/item['originalFile']
        if hashlib.sha256(original.read_bytes()).hexdigest()!=item['originalFileSha256']:
            raise ValueError('Original confirmed response changed')
        assert value['oldStatus']=='CONFIRMED' and value['oldContext']==value['candidateContext']
        event=value['candidateContext']['confirmedNow']
        assert event==item['originalConfirmationEvent'] and event['direction']=='BOTTOM' and event['time']==item['through']
        value['category']='RETAIN_OLD_EXPECTATION'
    return values
