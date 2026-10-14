"""Retrospective candidate replay, not a production signal implementation.

Reads only the bundled CSV extracts. Outputs only beside this script.
No DB/Lake access, no trading, no dependency installation.
Labels were used during hypothesis formation; scores are calibration checks.
"""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read_rows(name):
    with (ROOT / "inputs" / name).open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    key = "trade_time" if "trade_time" in rows[0] else "trade_date"
    times = [row[key] for row in rows]
    assert times == sorted(set(times)), (name, "duplicate or unsorted timestamps")
    return [dict(time=r[key], **{k: float(r[k]) for k in ("close", "dif", "hist")}) for r in rows]


def replay(rows, threshold_pct, *, max_refs=2, min_bars=2, recheck_price=False,
           turn_measure="single_bar"):
    """Test one explicit hypothesis: sign waves, nearest qualifying of two refs.

    Price/DIF extrema are independent and causal; one opposite bar splits a wave.
    Activation uses current-wave extrema and >=2 bars. Both directions of DIF
    state transitions use the same relative threshold. Cancellation uses a raw
    strict DIF-extreme break. Zero DIF has no relative-turn event; zero histogram
    ends a wave. Equality and color-flip confirmation are intentionally untested.
    """
    history = {1: [], -1: []}
    wave = None
    state, ref, previous, turn_anchor = "NONE", None, None, None
    result = []
    for row in rows:
        sign = 1 if row["hist"] > 0 else -1 if row["hist"] < 0 else 0
        if wave is None or sign != wave["sign"]:
            if wave and wave["sign"]:
                history[wave["sign"]].append(wave)
            wave = dict(sign=sign, count=0, price=row["close"], dif=row["dif"], start=row["time"])
            state, ref, turn_anchor = "NONE", None, None
        wave["count"] += 1
        extreme = max if sign > 0 else min
        wave["price"] = extreme(wave["price"], row["close"])
        wave["dif"] = extreme(wave["dif"], row["dif"])
        event = "NONE"
        chosen_start = ref["start"] if ref else ""
        if sign and ref and sign * (wave["dif"] - ref["dif"]) > 0:
            event, state, ref, turn_anchor = "CANCEL", "NONE", None, None
        elif sign and ref and previous is not None:
            basis = previous["dif"]
            if turn_measure == "state_extreme":
                if (state == "DULL" and sign * (row["dif"] - turn_anchor) > 0
                        or state == "STRUCTURE" and sign * (row["dif"] - turn_anchor) < 0):
                    turn_anchor = row["dif"]
                basis = turn_anchor
            delta = sign * (row["dif"] - basis)
            if turn_measure == "integer_direction":
                delta = sign * (int(row["dif"]) - int(basis))
            gate = abs(basis) * threshold_pct / 100
            price_valid = not recheck_price or sign * (row["close"] - ref["price"]) > 0
            if previous["dif"] != 0 and state == "DULL" and delta < 0 and -delta >= gate and price_valid:
                event, state = "STRUCTURE", "STRUCTURE"
                turn_anchor = row["dif"]
            elif previous["dif"] != 0 and state == "STRUCTURE" and delta > 0 and delta >= gate:
                event, state = "DULL", "DULL"
                turn_anchor = row["dif"]
        elif sign and wave["count"] >= min_bars:
            for candidate in reversed(history[sign][-max_refs:]):
                if sign * (wave["price"] - candidate["price"]) > 0 and sign * (wave["dif"] - candidate["dif"]) < 0:
                    ref = candidate
                    chosen_start = candidate["start"]
                    event, state = "DULL", "DULL"
                    turn_anchor = row["dif"]
                    break
        result.append(dict(time=row["time"], event=event, state=state,
                           wave_count=wave["count"], ref_start=chosen_start,
                           close=row["close"], dif=row["dif"], hist=row["hist"]))
        previous = row
    return result


def main():
    cases = {
        "jul_120": "120_20250401_20250711.csv",
        "aug_120": "120_20250401_20251111.csv",
        "daily_2025": "daily_2025.csv",
        "may_120": "120_20260101_20260507.csv",
        "bottom_daily": "daily_20260801_20261009.csv",
    }
    data = {key: read_rows(name) for key, name in cases.items()}
    # Explicitly reviewed points, not labels for every unobserved historical bar.
    labels = [
        ("jul_120", "2025-06-27 15:00:00", "STRUCTURE", "mapped", "IMG_0309.PNG"),
        ("jul_120", "2025-06-30 15:00:00", "DULL", "mapped", "IMG_0309.PNG"),
        ("jul_120", "2025-07-02 15:00:00", "NONE", "mapped", "IMG_0309.PNG"),
        ("jul_120", "2025-07-03 15:00:00", "NONE", "mapped", "IMG_0309.PNG"),
        ("jul_120", "2025-07-07 11:30:00", "STRUCTURE", "mapped", "IMG_0309.PNG"),
        ("jul_120", "2025-07-08 11:30:00", "DULL", "mapped", "IMG_0309.PNG"),
        ("jul_120", "2025-07-09 15:00:00", "STRUCTURE", "mapped", "IMG_0309.PNG"),
        ("jul_120", "2025-07-10 11:30:00", "DULL", "mapped", "IMG_0309.PNG"),
        ("jul_120", "2025-07-11 11:30:00", "CANCEL", "mapped", "IMG_0309.PNG"),
        ("jul_120", "2025-07-11 15:00:00", "NONE", "direct", "IMG_0309.PNG"),
        ("aug_120", "2025-08-07 11:30:00", "DULL", "mapped", "IMG_0318.PNG"),
        ("aug_120", "2025-08-08 15:00:00", "NONE", "direct", "IMG_0318.PNG"),
        ("daily_2025", "2025-08-07", "NONE", "mapped", "IMG_0317.PNG"),
        ("daily_2025", "2025-08-08", "DULL", "direct", "IMG_0317.PNG"),
        ("daily_2025", "2025-08-14", "NONE", "direct", "IMG_0316.PNG"),
        ("daily_2025", "2025-11-06", "NONE", "mapped", "IMG_0311.PNG"),
        ("daily_2025", "2025-11-07", "NONE", "mapped", "IMG_0311.PNG"),
        ("daily_2025", "2025-11-10", "DULL", "mapped", "IMG_0311.PNG"),
        ("daily_2025", "2025-11-11", "STRUCTURE", "direct", "IMG_0311.PNG"),
        ("may_120", "2026-05-06 11:30:00", "NONE", "mapped", "IMG_0310.PNG"),
        ("may_120", "2026-05-06 15:00:00", "DULL", "mapped", "IMG_0310.PNG"),
        ("may_120", "2026-05-07 15:00:00", "CANCEL", "direct", "IMG_0310.PNG"),
        ("bottom_daily", "2026-09-24", "NONE", "direct", "IMG_0307.PNG"),
        ("bottom_daily", "2026-09-28", "DULL", "direct", "IMG_0308.PNG"),
        ("bottom_daily", "2026-09-29", "CANCEL", "direct", "IMG_0304.PNG"),
    ]
    thresholds = [0, 0.5, 0.7, 0.75, 0.8, 0.9, 1, 1.1, 1.2, 1.25]
    predictions, comparisons, summaries = {}, [], []
    for threshold in thresholds:
        predictions[threshold] = {key: {r["time"]: r for r in replay(rows, threshold)} for key, rows in data.items()}
        mismatches = []
        for key, time, expected, confidence, image in labels:
            actual = predictions[threshold][key][time]
            comparisons.append(dict(threshold_pct=threshold, case=key, time=time,
                                    expected=expected, predicted=actual["event"],
                                    label_confidence=confidence, screenshot=image,
                                    matched=expected == actual["event"],
                                    dif=actual["dif"], ref_start=actual["ref_start"]))
            if expected != actual["event"]:
                mismatches.append(f'{key} {time}: {expected} -> {actual["event"]}')
        summaries.append(dict(threshold_pct=threshold, checked_points=len(labels),
                              mismatches=len(mismatches), details=mismatches))
    for name, rows in [("label_comparison.csv", comparisons), ("events_r1.csv", [dict(case=k, **r) for k, v in predictions[1].items() for r in v.values() if r["event"] != "NONE"])]:
        with (ROOT / name).open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    constraints = []
    for key, time in [("aug_120", "2025-08-08 15:00:00"), ("daily_2025", "2025-08-14"), ("jul_120", "2025-07-09 15:00:00")]:
        rows = data[key]
        i = next(i for i, r in enumerate(rows) if r["time"] == time)
        before, after = rows[i-1]["dif"], rows[i]["dif"]
        constraints.append(dict(case=key, time=time, before=before, after=after,
                                delta=after-before, decline_pct=100*(before-after)/abs(before)))
    inputs = []
    for path in sorted((ROOT / "inputs").glob("*.csv")):
        inputs.append(dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                           rows=len(list(csv.DictReader(path.open())))))
    alternatives = []
    for name, threshold, options in [("nearest_only", 1, dict(max_refs=1)),
                          ("one_bar_activation", 1, dict(min_bars=1)),
                          ("recheck_close_on_structure", 1, dict(recheck_price=True)),
                          ("state_extreme_r1", 1, dict(turn_measure="state_extreme")),
                          ("integer_direction", 0, dict(turn_measure="integer_direction"))]:
        alternative = {key: {r["time"]: r for r in replay(rows, threshold, **options)} for key, rows in data.items()}
        failures = []
        for key, time, expected, confidence, image in labels:
            actual = alternative[key][time]["event"]
            if expected != actual:
                failures.append(f'{key} {time}: {expected} -> {actual}')
        alternatives.append(dict(variant=name, threshold_pct=threshold,
                                 mismatches=len(failures), details=failures))
    # Every labelled timestamp is replayed again on its historical prefix.
    # This checks causality of this scratch algorithm, not correctness of Xu's.
    for key, time, *_ in labels:
        prefix = [r for r in data[key] if r["time"] <= time]
        assert replay(prefix, 1)[-1] == predictions[1][key][time], (key, time)
    queue, search_summary = [], []
    for freq, name in [(30, "30_20250603_20261009.csv"),
                       (60, "60_20250603_20261009.csv")]:
        rows = read_rows(name)
        low, middle, high = [replay(rows, r) for r in (0.75, 1, 1.2)]
        cumulative = replay(rows, 1, turn_measure="state_extreme")
        cumulative_diffs = sum(a["event"] != b["event"] for a, b in zip(middle, cumulative))
        gate_diffs = 0
        for i, row in enumerate(rows):
            if low[i]["event"] != high[i]["event"]:
                gate_diffs += 1
                before = rows[i-1]["dif"] if i else None
                queue.append(dict(freq=freq, time=row["time"], previous_dif=before,
                                  dif=row["dif"], signed_change_pct=100*(row["dif"]-before)/abs(before) if before else None,
                                  event_r075=low[i]["event"], event_r1=middle[i]["event"],
                                  event_r12=high[i]["event"], ref_r1=middle[i]["ref_start"],
                                  software_label="NOT_CONFIRMED"))
        search_summary.append(dict(freq=freq, bars=len(rows),
                                   gate_event_differences=gate_diffs,
                                   single_vs_state_extreme_r1_differences=cumulative_diffs))
    with (ROOT / "candidate_queue.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(queue[0]))
        writer.writeheader()
        writer.writerows(queue)
    report = dict(scope="Retrospective calibration only; no out-of-sample accuracy estimate",
                  summaries=summaries, alternative_rules=alternatives,
                  candidate_search=search_summary,
                  causal_prefix_checks=len(labels), threshold_constraints=constraints, inputs=inputs)
    (ROOT / "replay_summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(dict(summaries=summaries, alternative_rules=alternatives,
                          causal_prefix_checks=len(labels), threshold_constraints=constraints), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
