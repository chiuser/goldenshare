"""Replay audited source snapshots with the product kernel; never write DB/Lake.

Software readouts remain literal observations from existing frozen reports.
They are not fitted inputs or an independent holdout validation.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar
from .frozen_inputs import load_frozen_inputs


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_source(root: Path, period: str) -> list[XxmBar]:
    path = root / ("daily_source.csv" if period == "day" else f"minute_{period[1:]}_source.csv")
    manifest = json.loads((root / "manifest.json").read_text())
    expected = next(item["sha256"] for item in manifest["files"] if item["name"] == path.name)
    if sha(path) != expected:
        raise ValueError(f"M0 source snapshot changed: {path.name}")
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if period == "day":
        return [XxmBar(r["trade_date"], *(float(r[k]) for k in ("close", "macd_dif_bfq", "macd_dea_bfq", "macd_bfq"))) for r in rows]
    return [XxmBar(r["trade_time"].replace(" ", "T") + "+08:00",
                   *(float(r[k]) for k in ("close", "macd_dif", "macd_dea", "macd"))) for r in rows]


def replay(period: str, bars: list[XxmBar]) -> tuple[list, XxmCalculator]:
    origin = f"{period}|{bars[0].time}|{'bfq' if period == 'day' else 1}"
    calc = XxmCalculator(period=period, source_identity=origin)
    return [calc.step(bar) for bar in bars], calc


def collect_readouts(root: Path) -> list[dict]:
    records = []
    observations = json.loads((root / "software_numeric_history_audit.json").read_text())["observations"]
    for item in observations:
        records.append(dict(period=f"m{item['freq']}", time=item["time"].replace(" ", "T") + "+08:00", image=item["image"],
                            expectedImageSha256=item["image_sha256"], sourceRecord="software_numeric_history_audit.json:observations",
                            software=item["software"]))
    pair = json.loads((root / "holdout_20260105_pair.json").read_text())
    for item, image in zip(pair["comparisons"], pair["sources"], strict=True):
        records.append(dict(period=f"m{item['freq']}", time="2026-01-05T15:00:00+08:00", image=image["saved_path"],
                            sourceRecord="holdout_20260105_pair.json:comparisons", software=item["software"]))
    november = json.loads((root / "nov13_17_charts_comparison_20261012.json").read_text())
    for item, image in zip(november["numerical_endpoint_comparisons"], november["sources"], strict=True):
        records.append(dict(period=f"m{item['period']}", time=item["time"].replace(" ", "T") + "+08:00",
                            image=image["saved_path"], sourceRecord="nov13_17_charts_comparison_20261012.json:numerical_endpoint_comparisons",
                            software=item["software"]))
    for name, key, period, image_key in (
        ("july3_chart_comparison_20261012.json", "numerical_endpoint", "m90", "source"),
        ("apr21_23_source_comparison_20261012.json", "software_numerical_endpoint", "m60", "image_source"),
    ):
        report = json.loads((root / name).read_text())
        item = report[key]
        records.append(dict(period=period, time=item["time"].replace(" ", "T") + "+08:00",
                            image=report[image_key]["saved_path"], sourceRecord=name + ":" + key, software=item["software"]))
    daily = json.loads((root / "nov14_daily_disappearance_20261012.json").read_text())
    records.append(dict(period="day", time=daily["image_date"], image=str(root / "sources/20251114_daily.png"),
                        sourceRecord="nov14_daily_disappearance_20261012.json:software_terminal_readout",
                        software={key: daily["software_terminal_readout"][key] for key in ("close", "dif", "dea", "hist")}))
    if len(records) != 27 or len({(r["period"], r["time"]) for r in records}) != 27:
        raise ValueError("Expected 26 unique minute readouts and one daily readout")
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--research", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.resolve() in (args.source.resolve(), args.research.resolve()):
        raise ValueError("Acceptance output must not be a source/evidence root")
    if (args.output / "algorithm_acceptance.json").exists() or any(args.output.glob("baseline_*.json")):
        raise ValueError("Refusing to overwrite an existing acceptance run")
    if not all((args.output / f"api_{period}_sample.json").is_file() for period in ("day", "m60", "m90", "m120")):
        raise ValueError("Capture the four new API samples in an unused output directory first")
    args.output.mkdir(parents=True, exist_ok=True)
    frozen, _ = load_frozen_inputs(args.research)
    sources = {period: load_source(args.source, period) for period in ("day", "m60", "m90", "m120")}
    summary = {"asOf": "2026-10-13 close", "algorithmVersion": MAIN_SPEC.algorithm_version,
               "specHash": MAIN_SPEC.spec_hash, "spec": asdict(MAIN_SPEC), "periods": {},
               "limitations": ["Full audited history baseline is a new source-origin baseline, not a software event oracle.",
                               "Daily has not passed an independent software event timeline validation.",
                               "Minute frozen CSVs missing DEA infer it only for old test inputs; formal baselines use explicit source DEA."]}
    for period, bars in sources.items():
        steps, calc = replay(period, bars)
        events = [event for step in steps for event in step.events]
        histories = {h["id"]: h for step in steps for h in step.histories}
        bottom_histories = {h["id"]: h for step in steps for h in step.bottom_histories}
        # Independently replay every ordinary/history event and lifecycle-change
        # prefix. Compare the complete prefix event ledger, not just its count.
        seen_histories, ended_histories = set(), set()
        event_cuts = []
        for i, step in enumerate(steps):
            lifecycle_change = any(h["id"] not in seen_histories or
                                   (h["status"] == "ENDED" and h["id"] not in ended_histories)
                                   for h in (*step.histories, *step.bottom_histories))
            if step.events or lifecycle_change:
                event_cuts.append(i + 1)
            seen_histories.update(h["id"] for h in (*step.histories, *step.bottom_histories))
            ended_histories.update(h["id"] for h in (*step.histories, *step.bottom_histories) if h["status"] == "ENDED")
        event_cuts = sorted(set(event_cuts + [len(bars)]))
        for cut in event_cuts:
            prefix_calc = XxmCalculator(period=period, source_identity=calc.source_identity)
            prefix_events = []
            for bar in bars[:cut]:
                last = prefix_calc.step(bar)
                prefix_events.extend(last.events)
            assert last == steps[cut - 1]
            assert prefix_events == [event for event in events if event["time"] <= bars[cut - 1].time]
        cuts = sorted({min(n, len(bars) - 1) for n in (25, 1000, len(bars) // 2, len(bars) - 1)})
        for cut in cuts:
            before, prefix = replay(period, bars[:cut])
            assert before == steps[:cut]
            restored = XxmCalculator(period=period, source_identity=prefix.source_identity)
            restored.restore(prefix.snapshot())
            assert [restored.step(bar) for bar in bars[cut:]] == steps[cut:]
            assert restored.snapshot() == calc.snapshot()
        state_bytes = len(json.dumps(calc.snapshot(), default=str).encode())
        assert state_bytes < 65536
        numeric_overlap = 0
        if period != "day":
            by_time = {bar.time: bar for bar in bars}
            for old in frozen[int(period[1:])]:
                current = by_time[old.time]
                assert current.close == old.close and abs(current.dif - old.dif) < 1e-8 and abs(current.hist - old.hist) < 1e-8
                numeric_overlap += 1
        point_hash = hashlib.sha256(json.dumps([s.point for s in steps], sort_keys=True).encode()).hexdigest()
        api = json.loads((args.output / f"api_{period}_sample.json").read_text())
        first, last_time = api["meta"]["responseStart"], api["meta"]["responseEnd"]
        expected_points = [s.point for s in steps if first <= s.point["time"] <= last_time]
        assert api["points"] == expected_points
        assert api["events"] == [e for e in events if first <= e["time"] <= last_time]
        for history in api["topHistories"]:
            assert all(histories[history["id"]][key] == value for key, value in history.items())
        for history in api["bottomHistories"]:
            assert all(bottom_histories[history["id"]][key] == value for key, value in history.items())
        result = dict(rows=len(bars), start=bars[0].time, end=bars[-1].time, eventCounts=dict(Counter(e["type"] for e in events)),
                      historyCounts=dict(Counter(h["status"] for h in histories.values())),
                      independentEventPrefixChecks=len(event_cuts), prefixAndRestoreCuts=cuts,
                      stateBytes=state_bytes, frozenNumericOverlap=numeric_overlap,
                      realApiWindowMatchedRows=len(expected_points),
                      pointSequenceSha256=point_hash, events=events, topHistories=list(histories.values()), bottomHistories=list(bottom_histories.values()),
                      bottomHistoryCounts=dict(Counter(h["status"] for h in bottom_histories.values())))
        (args.output / f"baseline_{period}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        summary["periods"][period] = {k: v for k, v in result.items() if k not in ("events", "topHistories", "bottomHistories")}
        print(f"{period}: {len(event_cuts)} independent event/lifecycle prefixes passed", flush=True)
    readouts = []
    lookup = {p: {b.time: b for b in bars} for p, bars in sources.items()}
    for record in collect_readouts(args.research):
        bar = lookup[record["period"]][record["time"]]
        actual = {key: getattr(bar, "hist" if key == "hist" else key) for key in ("close", "dif", "dea", "hist")}
        record.update(source=actual, imageSha256=sha(Path(record["image"])),
                      softwareMinusSource={k: None if v is None else v - actual[k] for k, v in record["software"].items()},
                      sameDisplayedValue={k: None if v is None else f"{v:.{2 if k == 'close' else 3}f}" == f"{actual[k]:.{2 if k == 'close' else 3}f}"
                                          for k, v in record["software"].items()})
        if record.get("expectedImageSha256") and record["imageSha256"] != record["expectedImageSha256"]:
            raise ValueError("Software source image changed")
        readouts.append(record)
    (args.output / "software_readouts.json").write_text(json.dumps(readouts, ensure_ascii=False, indent=2) + "\n")
    with (args.output / "software_readouts.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["period", "time", "imageSha256"] +
                                [f"{prefix}_{key}" for key in ("close", "dif", "dea", "hist") for prefix in ("software", "source", "delta", "display_match")])
        writer.writeheader()
        for r in readouts:
            row = {k: r[k] for k in ("period", "time", "imageSha256")}
            for k in ("close", "dif", "dea", "hist"):
                row.update({f"software_{k}": r["software"][k], f"source_{k}": r["source"][k],
                            f"delta_{k}": r["softwareMinusSource"][k], f"display_match_{k}": r["sameDisplayedValue"][k]})
            writer.writerow(row)
    summary["softwareReadouts"] = {p: dict(count=len(group),
        deltaDifRange=[min(r["softwareMinusSource"]["dif"] for r in group), max(r["softwareMinusSource"]["dif"] for r in group)],
        allIndicatorDisplaysMatch=sum(all(r["sameDisplayedValue"][k] is True for k in ("dif", "dea", "hist")) for r in group))
        for p in sources for group in [[r for r in readouts if r["period"] == p]]}
    summary["sourceManifestSha256"] = sha(args.source / "manifest.json")
    summary["kernelFiles"] = {str(p): sha(p) for p in Path("src/biz/services/wealth/market/index_detail_xxm").glob("*.py")}
    (args.output / "algorithm_acceptance.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary["periods"], ensure_ascii=False))
    print(json.dumps(summary["softwareReadouts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
