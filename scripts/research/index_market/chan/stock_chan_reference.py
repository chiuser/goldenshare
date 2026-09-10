"""Authenticated B0 index windows shared by the paused stock research."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from scripts.research.index_market.chan.m0_data import digest
from scripts.research.index_market.chan.minute_roundtrip import opening_time


@dataclass(frozen=True)
class IndexWindowSpec:
    report: str = 'reports/chan_minute_roundtrip_b0_20260910'
    manifest_sha256: str = '22ce1a36f285de394fdf422086dcc572efd27ecb3f6579f63e4b95936c94ce95'
    code: str = '000001.SH'
    frequency: int = 30
    asof: str = '2026-09-08'
    windows: int = 3


SPEC = IndexWindowSpec()


def authenticate(folder, expected, max_files=100, max_bytes=128*1024**2):
    raw = (folder/'manifest.json').read_bytes()
    if digest(raw) != expected:
        raise ValueError('reference manifest changed')
    manifest = json.loads(raw)
    if manifest['status'] != 'complete' or len(manifest['artifacts_sha256']) > max_files:
        raise ValueError('reference incomplete/file budget')
    paths = [(folder/n).resolve(strict=True) for n in manifest['artifacts_sha256']]
    if any(not p.is_relative_to(folder.resolve()) for p in paths) or sum(p.stat().st_size for p in paths) > max_bytes:
        raise ValueError('reference path/byte budget')
    for name, expected_hash in manifest['artifacts_sha256'].items():
        if digest((folder/name).read_bytes()) != expected_hash:
            raise ValueError(f'reference artifact changed: {name}')
    for name, expected_hash in manifest['code_sha256'].items():
        if digest((Path(__file__).parent/name).read_bytes()) != expected_hash:
            raise ValueError(f'reference code changed: {name}')
    return manifest


def select_windows(trades, rows, spec=SPEC):
    eligible = sorted((t for t in trades if t['status'] == 'natural_exit'
                       and t['exit_time'][:10] <= spec.asof),
                      key=lambda t: (t['buy_event']['signal_time'], t['buy_event']['event_id']))
    if len({t['buy_event']['event_id'] for t in eligible}) != len(eligible):
        raise ValueError('duplicate index event')
    if len(eligible) < spec.windows:
        raise ValueError('insufficient completed windows')
    result = []
    for t in eligible[-spec.windows:]:
        buy = t['buy_event']
        a, b = t['entry_index'], t['exit_index']
        if not 0 < a < b < len(rows) or a != buy['signal_index']+1:
            raise ValueError('invalid buy boundary')
        if not t['sell_events'] or any(e['signal_index']+1 != b for e in t['sell_events']):
            raise ValueError('invalid sell boundary')
        assert rows[a-1]['time'] == buy['signal_time']
        assert t['entry_time'] == opening_time(rows[a])
        assert t['exit_time'] == opening_time(rows[b])
        assert t['entry_price'] == rows[a]['open'] and t['exit_price'] == rows[b]['open']
        q = rows[b]['open']/rows[a]['open']-1
        assert abs(q-t['gross_change']) < 1e-12
        result.append(dict(window_id=buy['signal_time'][:10], buy_event_id=buy['event_id'],
                           signal_time=buy['signal_time'], start=t['entry_time'], end=t['exit_time'],
                           entry_bar_end=rows[a]['time'], exit_bar_end=rows[b]['time'],
                           sell_event_ids=[e['event_id'] for e in t['sell_events']],
                           sell_signal_time=t['sell_events'][0]['signal_time'],
                           index_gross_change=q, holding_bars=b-a))
    return result
