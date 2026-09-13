"""Direct DG Gold 90-minute opportunity experiment; no Lake writes."""

import argparse
from dataclasses import dataclass, asdict, replace
from datetime import datetime
from enum import Enum
import json
import math
from pathlib import Path
import time

from scripts.research.index_market.chan import stock_opportunity as base
from scripts.research.index_market.chan import stock_opportunity_filters as filters
from scripts.research.index_market.chan.minute_replay import MinuteLedger
from scripts.research.index_market.chan.minute_variant_a import VARIANT_A
from scripts.research.index_market.chan.stock_chan_replay_data import LAKE, Reader, SPEC as READ_SPEC
from scripts.research.index_market.chan.stock_qfq_run import source_gate
from scripts.research.index_market.chan.stock_timeframe_opportunity import project
from scripts.research.index_market.chan.run_m0 import save


@dataclass(frozen=True)
class Spec:
    code: str = "002245.SZ"
    frequency: int = 90
    years: tuple = tuple(range(2021, 2027))
    slots: tuple = ("11:00:00", "14:00:00", "15:00:00")
    start: str = "2021-09-09"
    end: str = "2026-09-08"
    tolerance: float = 1e-7
    max_bars: int = 4000
    seconds: int = 180
    replay_seconds: int = 30
    output_bytes: int = 32 * 1024**2
    control: str = "reports/stock_opportunity_002245_60m_20260912_audited"


SPEC = Spec()


class ResearchLevel(Enum):
    K_90M = "DG_90M"


def validate(rows, original):
    days = sorted({r["date"] for r in original})
    if not rows or len(rows) > SPEC.max_bars or [r["time"] for r in rows] != [
        f"{d} {s}" for d in days for s in SPEC.slots
    ]:
        raise ValueError("90-minute grid mismatch")
    lookup = {r["time"]: i for i, r in enumerate(original)}
    for r in rows:
        if (r["code"], r["frequency"], r["exchange"], r["price_basis"]) != (
            SPEC.code, 90, "SZSE", "qfq"
        ) or r["date"] != r["time"][:10]:
            raise ValueError("identity/basis mismatch")
        if any(not math.isfinite(r[k]) or r[k] <= 0 for k in ("open", "high", "low", "close")) or any(
            not math.isfinite(r[k]) or r[k] < 0 for k in ("vol", "amount")
        ) or not r["low"] <= min(r["open"], r["close"]) <= max(r["open"], r["close"]) <= r["high"]:
            raise ValueError("invalid OHLC/volume")
        i = lookup[r["time"]]
        if abs(r["close"] / original[i]["close"] - 1) > SPEC.tolerance:
            raise ValueError("different QFQ scale")
        r["source_end"] = i


def replay(rows, frequency):
    from ChanConfig import CChanConfig
    from Common.CEnum import KL_TYPE
    from Common.CTime import CTime
    from KLine.KLine_List import CKLine_List
    from KLine.KLine_Unit import CKLine_Unit

    kind = {60: KL_TYPE.K_60M, 90: ResearchLevel.K_90M}[frequency]
    spec = replace(VARIANT_A, codes=(SPEC.code,), frequencies=(frequency,))
    kl = CKLine_List(kind, CChanConfig(spec.chan_config()))
    ledger = MinuteLedger(SPEC.code, frequency, spec)
    previous, events, started = None, [], time.monotonic()
    for i, row in enumerate(rows):
        if time.monotonic() - started > SPEC.replay_seconds:
            raise TimeoutError("replay budget")
        if row["code"] != SPEC.code or row["frequency"] != frequency:
            raise ValueError("replay identity")
        dt = datetime.fromisoformat(row["time"])
        unit = CKLine_Unit(dict(time_key=CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute, auto=False),
                               **{k: row[k] for k in ("open", "high", "low", "close")}))
        unit.set_idx(i)
        unit.kl_type = kind
        if previous is not None:
            unit.set_pre_klu(previous)
        kl.add_single_klu(unit)
        previous = unit
        points = []
        for bsp in kl.bs_point_lst.bsp_store_flat_dict.values():
            begin, end, anchor = bsp.bi.get_begin_klu().idx, bsp.bi.get_end_klu().idx, bsp.klu.idx
            points.append(dict(buy=bool(bsp.is_buy), sure=bool(bsp.bi.is_sure),
                types=sorted({t.value for t in bsp.type}), bi_index=bsp.bi.idx,
                start_index=begin, end_index=end, anchor_index=anchor,
                start_time=rows[begin]["time"], end_time=rows[end]["time"], anchor_time=rows[anchor]["time"]))
        new, _ = ledger.step(row["time"], i, points)
        events.extend(new)
    return events


def execute(output):
    started = time.monotonic()
    output = base.safe_output(output)
    control = base.REPO / SPEC.control
    source = base.REPO / base.SPEC.source
    for folder in (source, control):
        manifest = filters.checked_report(folder)
        for name, expected in manifest["code_sha256"].items():
            path = Path(name) if Path(name).is_absolute() else Path(__file__).with_name(name)
            if base.sha(path) != expected:
                raise ValueError(f"changed dependency {path}")
    info = source_gate()
    original = json.loads((source / "input.json").read_text())
    reader = Reader(replace(READ_SPEC, max_files=6, max_bytes=1024**2, max_bars=4000, query_seconds=30))
    paths = [LAKE / f"gold/quote/stk_mins_qfq/freq=90/ts_code={SPEC.code}/year={y}/part-000.parquet" for y in SPEC.years]
    rows = reader.read(paths, """SELECT ts_code AS code, freq AS frequency, exchange,
        'qfq' AS price_basis, CAST(trade_date AS VARCHAR) AS date,
        CAST(trade_time AS VARCHAR) AS time, open, high, low, close, vol, amount
        FROM read_parquet(?, hive_partitioning=false)
        WHERE trade_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE) ORDER BY trade_time""",
        [[str(p) for p in paths], SPEC.start, SPEC.end], SPEC.max_bars)
    validate(rows, original)
    output.mkdir()
    receipt = dict(status="running", spec=asdict(SPEC), source=info,
        filter_spec=asdict(filters.SPEC), observation_spec=asdict(base.SPEC),
        plan_sha256_at_start=base.sha(base.REPO / filters.SPEC.plan),
        source_manifests={str(f): base.sha(f / "manifest.json") for f in (source, control)},
        code_sha256={str(p): base.sha(p) for p in (Path(__file__), Path(base.__file__), Path(filters.__file__), Path(__file__).with_name("minute_replay.py"), Path(__file__).with_name("stock_timeframe_opportunity.py"), Path(__file__).with_name("stock_chan_replay_data.py"))})
    try:
        save(output / "input_90.json", rows)
        def one(name, data, frequency=90):
            if time.monotonic() - started > SPEC.seconds:
                raise TimeoutError("experiment budget")
            print(f"{name}: {len(data)} bars", flush=True)
            result = replay(data, frequency)
            save(output / f"{name}_events.json", result)
            return result
        checks = {}
        checks["native_60_control"] = one("control60", json.loads((control / "input_60.json").read_text()), 60) == json.loads((control / "full_events.json").read_text())
        if not checks["native_60_control"]:
            raise ValueError("60 adapter control differs")
        events = one("full", rows)
        for year in range(2022, 2026):
            cutoff = f"{year}-12-31 23:59:59"
            checks[f"prefix_{year}"] = one(f"prefix_{year}", [r for r in rows if r["time"] <= cutoff]) == [e for e in events if e["signal_time"] <= cutoff]
        cutoff = "2024-12-31 23:59:59"
        future = [dict(r, **{k: r[k] * (1.37 if r["time"] > cutoff else 1) for k in ("open", "high", "low", "close")}) for r in rows]
        checks["future_isolation"] = [e for e in one("future", future) if e["signal_time"] <= cutoff] == [e for e in events if e["signal_time"] <= cutoff]
        checks["scaled"] = one("scaled", [dict(r, **{k: r[k]*2 for k in ("open", "high", "low", "close")}) for r in rows]) == events
        days = sorted({r["date"] for r in rows})
        short = one("shorter", [r for r in rows if r["date"] >= days[250]])
        omit = {"signal_index", "start_index", "end_index", "anchor_index", "bi_index"}
        def semantic(es):
            return [{k: v for k, v in e.items() if k not in omit} for e in es if e["signal_time"][:10] >= days[500]]
        left, right = semantic(events), semantic(short)
        checks["shorter_initialization"] = left == right
        save(output / "signal_checks.json", dict(checks=checks, all_passed=all(checks.values()), shorter_only_full=[e for e in left if e not in right], shorter_only_short=[e for e in right if e not in left]))
        buys = [e for e in events if e["group"] in ("B1", "B2", "B3")]
        fs = [filters.features(rows, e) for e in buys]
        if any(filters.features(rows[:e["signal_index"]+1], e) != f for e, f in zip(buys, fs, strict=True)):
            raise ValueError("filter prefix mismatch")
        save(output / "features.json", fs)
        results = {}
        for variant in filters.SPEC.variants:
            r = base.evaluate(original, [project(e, rows) for e, f in zip(buys, fs, strict=True) if filters.passes(f, variant)])
            mapping = {r["source_end"]: i for i, r in enumerate(rows)}
            for event in r["events"]:
                event.update(detection_signal_index=mapping[event["index"]], detection_frequency=90, observation_frequency=30)
            filters.enrich(original, r)
            expected = json.loads((control / "original.json").read_text())["recall"]["rallies"]
            if r["recall"]["rallies"] != expected:
                # Recall signals differ, but the opportunity labels must not.
                if [(x["entry_index"], x["exit_index"]) for x in r["recall"]["rallies"]] != [(x["entry_index"], x["exit_index"]) for x in expected]:
                    raise ValueError("rally labels changed")
            results[variant] = r
            save(output / f"{variant}.json", r)
        receipt.update(status="complete" if all(checks.values()) else "complete_with_signal_stability_differences", bars=len(rows), all_signal_checks_passed=all(checks.values()), filter_prefix=True, read_audit=reader.verify_unchanged(), source_hashes=reader.hashes, queries=reader.queries, seconds=time.monotonic()-started)
        if receipt["seconds"] > SPEC.seconds or sum(p.stat().st_size for p in output.iterdir()) > SPEC.output_bytes:
            raise ValueError("time/output budget")
    except BaseException as exc:
        receipt.update(status="failed", error=str(exc))
        raise
    finally:
        receipt["artifacts_sha256"] = {p.name: base.sha(p) for p in output.iterdir()}
        save(output / "manifest.json", receipt)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    execute(parser.parse_args().output)
