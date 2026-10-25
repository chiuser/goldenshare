"""Conditional DIF-reference diagnosis, next plan v0.6 section 8 / LLD 10.

This is not a lifecycle calculator. No old state, EMA restart, active rescue,
software event timestamp inference, or production import is permitted here.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, asdict
import hashlib
import json
from pathlib import Path
import resource
import time

from src.biz.services.wealth.market.index_detail_daily_wave.local_extrema import LocalExtremaScanner, number
from .near_first_review import quantize_dif


@dataclass(frozen=True)
class ReviewSpec:
    source_sha: str = "9b1690492e3e8d470addba8bc6a0bed3ccdcb4d76f26fbdc1da668606c955e04"
    start: str = "2025-10-20 11:00:00"
    end: str = "2025-12-16 15:00:00"
    inspect_start: str = "2025-12-10 11:00:00"
    conditional_bind_at: str = "2025-12-15 15:00:00"
    max_rows: int = 150
    max_bytes: int = 65536


SPEC = ReviewSpec()
LIMITATION = ("Conditional initial selection only; lifecycle permission to start "
              "a new round is not evaluated. Window history is not full history.")


def sign(value) -> int:
    x = number(value)
    return 1 if x > 0 else -1 if x < 0 else 0


def build_references(rows: list[dict]) -> dict:
    """Use only supplied prefix. Freeze each price window at its first opposite."""
    if not rows:
        raise ValueError("Empty prefix")
    phases, assignments, turns = [], [], []
    scanner = LocalExtremaScanner()
    for index, row in enumerate(rows):
        if number(row["close"]) <= 0:
            raise ValueError("Nonpositive close")
        colour = sign(row["macd"])
        if colour and (not phases or phases[-1]["sign"] != colour):
            if phases:
                phases[-1]["end_exclusive"] = index
            phases.append(dict(id=len(phases), sign=colour, start=index,
                               end_exclusive=None, actual_bars=0,
                               left_censored=not phases))
        if colour:
            phases[-1]["actual_bars"] += 1
        assignments.append(phases[-1]["id"] if phases else None)
        point = scanner.step(row["trade_time"], row["macd_dif"])
        if point:
            turns.append(point.record())

    references, censored = [], []
    for point in turns:
        first, last = point["first_index"], point["last_index"]
        phase_id = assignments[first]
        if phase_id is None:
            continue
        phase = phases[phase_id]
        expected = "MAX" if phase["sign"] > 0 else "MIN"
        if point["kind"] != expected:
            continue
        if phase["left_censored"]:
            censored.append(dict(point=point, reason="left_censored_phase"))
            continue
        end = phase["end_exclusive"]
        if end is None:
            continue  # Current phase cannot be its own historical reference.
        if last >= end:
            censored.append(dict(point=point, reason="plateau_crosses_colour_boundary"))
            continue
        direction = "TOP" if phase["sign"] > 0 else "BOTTOM"
        price_index = (max if direction == "TOP" else min)(
            range(first, end), key=lambda i: number(rows[i]["close"]))
        references.append(dict(
            id=f"{direction}:{point['first_at']}", direction=direction,
            phase_id=phase_id, dif=point["value"], qdif=str(quantize_dif(point["value"])),
            peak_first=point["first_at"], peak_last=point["last_at"],
            confirmed_at=point["confirmed_at"], first_index=first,
            window_start=rows[first]["trade_time"],
            window_last=rows[end - 1]["trade_time"],
            first_opposite=rows[end]["trade_time"],
            price=rows[price_index]["close"], price_at=rows[price_index]["trade_time"],
        ))
    return dict(phases=phases, assignments=assignments, references=references,
                censored=censored, raw_turns=turns)


def inspect_prefix(rows: list[dict], direction: str) -> dict:
    if direction not in ("TOP", "BOTTOM"):
        raise ValueError("Unknown direction")
    shape = build_references(rows)
    current = rows[-1]
    expected_sign = 1 if direction == "TOP" else -1
    phase = shape["phases"][-1] if shape["phases"] else None
    stage_ok = bool(phase and not phase["left_censored"]
                    and phase["sign"] == expected_sign
                    and sign(current["macd"]) == expected_sign
                    and phase["actual_bars"] >= 2)
    phase_dif = None
    if phase:
        phase_dif = (max if direction == "TOP" else min)(
            number(row["macd_dif"]) for row in rows[phase["start"]:])
    qdif = quantize_dif(phase_dif) if phase_dif is not None else None
    refs = sorted((r for r in shape["references"] if r["direction"] == direction),
                  key=lambda r: r["first_index"], reverse=True)
    old_phases = [p["id"] for p in reversed(shape["phases"])
                  if p["sign"] == expected_sign and p["end_exclusive"] is not None
                  and not p["left_censored"]]
    results = {}
    for name, allowed in (("recent_two_phases", set(old_phases[:2])),
                          ("all_complete_phases_in_window", set(old_phases))):
        checked, selected = [], None
        for ref in refs:
            if ref["phase_id"] not in allowed:
                continue
            price_ok = (number(current["close"]) > number(ref["price"]) if direction == "TOP"
                        else number(current["close"]) < number(ref["price"]))
            dif_ok = qdif is not None and (qdif < number(ref["qdif"]) if direction == "TOP"
                                          else qdif > number(ref["qdif"]))
            eligible = bool(stage_ok and price_ok and dif_ok)
            checked.append(dict(reference=ref, price_passed=price_ok,
                                dif_passed=bool(dif_ok), phase_passed=stage_ok,
                                eligible=eligible,
                                considered_before_selection=selected is None))
            if selected is None and eligible:
                selected = ref
        results[name] = dict(selected=selected, checked=checked)
    return dict(time=current["trade_time"], direction=direction,
                latest_close=current["close"], latest_dif=current["macd_dif"],
                latest_qdif=str(quantize_dif(current["macd_dif"])),
                current_phase=phase,
                phase_extreme=str(phase_dif) if phase_dif is not None else None,
                phase_qdif=str(qdif) if qdif is not None else None,
                phase_passed=stage_ok, ranges=results, limitation=LIMITATION)


def review_locked_reference(reference: dict, rows: list[dict]) -> list[dict]:
    """Independent numerical checks; no claim that a lifecycle actually binds it."""
    direction, threshold = reference["direction"], number(reference["qdif"])
    if direction not in ("TOP", "BOTTOM"):
        raise ValueError("Unknown direction")
    output, previous = [], None
    for row in rows:
        value = quantize_dif(row["macd_dif"])
        broken = value > threshold if direction == "TOP" else value < threshold
        turned = None if previous is None else (value < previous if direction == "TOP" else value > previous)
        output.append(dict(time=row["trade_time"], dif=row["macd_dif"], qdif=str(value),
                           reference_id=reference["id"], reference_qdif=str(threshold),
                           strictly_broken=broken, previous_available=previous is not None,
                           reversal_toward_structure=turned))
        previous = value
    return output


def run(source: Path, output: Path) -> dict:
    from .saved_minute_window import read_window

    started = time.perf_counter()
    if output.parent.resolve().name != "reports" or output.exists():
        raise ValueError("Use a new, direct reports child")
    output.mkdir()
    (output / "started.json").write_text(json.dumps(asdict(SPEC), indent=2) + "\n")
    saved = read_window(source, start=SPEC.start, end=SPEC.end,
                        expected_sha=SPEC.source_sha,
                        max_rows=SPEC.max_rows, max_bytes=SPEC.max_bytes)
    rows = saved["rows"]
    (output / "source_window.json").write_text(json.dumps(saved, indent=2) + "\n")
    probes = [inspect_prefix(rows[:i + 1], "BOTTOM") for i, row in enumerate(rows)
              if row["trade_time"] >= SPEC.inspect_start]
    binding = next(p for p in probes if p["time"] == SPEC.conditional_bind_at)
    traces = {}
    tail = [r for r in rows if r["trade_time"] >= SPEC.conditional_bind_at]
    for name, result in binding["ranges"].items():
        traces[name] = (review_locked_reference(result["selected"], tail)
                        if result["selected"] else None)
    code_paths = [Path(__file__), Path(__file__).with_name("saved_minute_window.py"),
                  (Path(__file__).resolve().parents[4] /
                   "src/biz/services/wealth/market/index_detail_daily_wave/local_extrema.py"),
                  Path(__file__).with_name("near_first_review.py")]
    report = dict(spec=asdict(SPEC), limitation=LIMITATION, probes=probes,
                  final_prefix_shape=build_references(rows),
                  conditional_binding_time=SPEC.conditional_bind_at,
                  conditional_fixed_checks=traces,
                  code_sha={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in code_paths},
                  seconds=time.perf_counter() - started,
                  peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  full_lifecycle_executed=False, production_changed=False)
    if report["seconds"] > 60 or report["peak_rss_bytes"] > 256 * 1024 * 1024:
        raise ValueError("Budget exceeded")
    data = json.dumps(report, indent=2) + "\n"
    if len(data.encode()) + (output / "source_window.json").stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Output budget exceeded")
    (output / "reference_review.json").write_text(data)
    (output / "diagnostic_complete.json").write_text(json.dumps(dict(
        full_lifecycle_executed=False,
        result_sha=hashlib.sha256(data.encode()).hexdigest()), indent=2) + "\n")
    return dict(rows=len(rows), probes=len(probes), seconds=report["seconds"],
                full_lifecycle_executed=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.output)))


if __name__ == "__main__":
    main()
