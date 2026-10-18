"""Retrospective qualification timing for the 16 frozen restart episodes."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path

from .acceptance import load_source, sha
from .cancellation_restart_audit import ROOT, SOURCE, BASELINE, PERIODS
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC

PREVIOUS = ROOT / "reports/xxm_cancellation_restart_20261016_01/run_03"


def qualifies(wave, pool, reference, *, current_close=None):
    """Literal eligibility arithmetic; no events/state/alternative engine."""
    price = wave.price if current_close is None else current_close
    return bool(wave.sign == -1 and wave.count >= MAIN_SPEC.min_bars and pool
        and reference in [r.reference() for r in pool]
        and price < min(pool[-1].price, reference["price"])
        and wave.dif > reference["dif"])


def timing(first_time, cancel_time):
    return "BEFORE" if first_time < cancel_time else "SAME" if first_time == cancel_time else "AFTER"


def detail(period, bars, episodes):
    cases = [e for e in episodes if e["status"] == "RESTART_BEFORE_RED"]
    result = [dict(cancelAt=e["cancel"]["bar"]["time"], restartAt=e["nextDull"]["bar"]["time"],
        segmentStart=e["cancel"]["context"]["wave"]["start"],
        oldReference=e["cancel"]["event"]["eventReference"],
        nextReference=e["nextDull"]["event"]["eventReference"],
        firstQualified=None, trace=[]) for e in cases]
    calc = XxmCalculator(period=period, source_identity="restart-detail:" + period)
    events = []
    for bar in bars:
        step = calc.step(bar)
        events.extend(step.events)
        for case in result:
            if not case["segmentStart"] <= bar.time <= case["restartAt"]:
                continue
            if calc.wave.start != case["segmentStart"]:
                raise ValueError("Frozen case segment changed")
            hit = qualifies(calc.wave, calc.history[-1], case["nextReference"])
            node = dict(time=bar.time, close=bar.close, dif=bar.dif, hist=bar.hist,
                segmentLowClose=calc.wave.price, segmentLowDif=calc.wave.dif,
                ordinaryState=calc.state, activeReference=step.point["activeReference"],
                otherReferenceEligible=hit,
                currentCloseEligible=qualifies(calc.wave, calc.history[-1], case["nextReference"], current_close=bar.close),
                events=list(step.events))
            case["trace"].append(node)
            if hit and case["firstQualified"] is None:
                case["firstQualified"] = node
    for case in result:
        if case["firstQualified"] is None:
            raise ValueError("Frozen restart reference never qualified")
        case["qualificationTiming"] = timing(case["firstQualified"]["time"], case["cancelAt"])
        case["currentCloseEligibleAtRestart"] = case["trace"][-1]["currentCloseEligible"]
        if case["trace"][-1]["time"] != case["restartAt"]:
            raise ValueError("Frozen restart endpoint absent")
    return result, events


def run(output):
    output = Path(output).resolve()
    if not output.is_relative_to((ROOT / "reports").resolve()) or not output.name.startswith("run_"):
        raise ValueError("Output must be a new reports/.../run_* directory")
    output.mkdir(exist_ok=False)
    previous = json.loads((PREVIOUS / "summary.json").read_text())
    protected = dict(previous["protectedSha256"])
    for path in [Path(__file__), PREVIOUS / "summary.json", *(PREVIOUS / f"episodes_{p}.json" for p in PERIODS)]:
        protected[str(path.relative_to(ROOT))] = sha(path)
    for path, expected in protected.items():
        if sha(ROOT / path) != expected:
            raise ValueError("Protected research input changed: " + path)
    totals = Counter()
    summary = dict(specHash=MAIN_SPEC.spec_hash, retrospective=True, periods={},
        softwareFormulaProven=False, productModified=False, formalBudgetTested=False)
    for period in PERIODS:
        bars = load_source(SOURCE, period)
        episodes = json.loads((PREVIOUS / f"episodes_{period}.json").read_text())["episodes"]
        rows, events = detail(period, bars, episodes)
        if events != json.loads((BASELINE / f"events_{period}.json").read_text())["events"]:
            raise ValueError("Product replay changed: " + period)
        counts = Counter(r["qualificationTiming"] for r in rows)
        totals.update(counts)
        summary["periods"][period] = dict(rows=len(bars), cases=len(rows), timing=dict(counts),
            currentCloseInsufficient=sum(not r["currentCloseEligibleAtRestart"] for r in rows),
            baselineEventsEqual=True)
        (output / f"details_{period}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    summary["qualificationTiming"] = dict(totals)
    summary["protectedSha256"] = protected
    for path, expected in protected.items():
        if sha(ROOT / path) != expected:
            raise ValueError("Protected evidence changed during audit: " + path)
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    result = run(parser.parse_args().output)
    print(json.dumps(result["periods"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
