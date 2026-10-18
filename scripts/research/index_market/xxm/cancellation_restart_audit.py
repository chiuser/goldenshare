"""Frozen-only audit of true bottom CANCEL -> next DULL; no alternate engine."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import time

from .acceptance import load_source, sha
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / "reports/xxm_source_audit_20261013_213852"
BASELINE = ROOT / "reports/xxm_same_segment_a1_implementation_20261016/frozen_final"
OBSERVATIONS = ROOT / "reports/xxm_software_indicator_crosscheck_20261015"
PERIODS = ("day", "m60", "m90", "m120")


class RestartAudit:
    """Classify literal event/column sequences independently of signal detection."""

    def __init__(self):
        self.episodes = []
        self.active = None
        self.last_dull = None
        self.previous_time = None
        self.negative_streak = 0
        self.excluded = Counter()
        self.checkpoints = {}

    def observe(self, bar: XxmBar, events, context=None):
        if self.previous_time is not None and bar.time <= self.previous_time:
            raise ValueError("Audit requires ordered, unique input")
        self.previous_time = bar.time
        self.negative_streak = self.negative_streak + 1 if bar.hist < 0 else 0
        bottom = [e for e in events if e["direction"] == "BOTTOM"]
        for event in bottom:
            if event["type"] == "CANCEL":
                if event["route"] not in ("dif_break", "dif_break_on_flip"):
                    raise ValueError("Unknown true CANCEL route")
                if self.active is not None:
                    raise ValueError("Second cancellation before any new DULL")
                self.active = dict(cancel=self._node(bar, event, context),
                    precedingDull=self.last_dull, nextDull=None, firstRedAt=None,
                    firstZeroAt=None, redBars=0, zeroBars=0, barsObserved=0,
                    status="RIGHT_CENSORED", observedThrough=bar.time)
                self.episodes.append(self.active)
            elif event["type"] not in ("DULL", "STRUCTURE"):
                self.excluded[event["type"]] += 1
        episode = self.active
        if episode is not None:
            episode["barsObserved"] += 1  # includes cancellation endpoint
            episode["observedThrough"] = bar.time
            if bar.hist > 0:
                episode["redBars"] += 1
                episode["firstRedAt"] = episode["firstRedAt"] or bar.time
            if bar.hist == 0:
                episode["zeroBars"] += 1
                episode["firstZeroAt"] = episode["firstZeroAt"] or bar.time
        for event in bottom:
            if event["type"] != "DULL":
                continue
            node = self._node(bar, event, context)
            if episode is not None:
                episode.update(nextDull=node,
                    status="RESTART_BEFORE_RED" if episode["firstRedAt"] is None else "RESTART_AFTER_RED",
                    negativeBarsAtRestart=self.negative_streak,
                    referenceChanged=episode["cancel"]["event"]["eventReference"] != event["eventReference"],
                    sameContinuousGreen=episode["redBars"] == episode["zeroBars"] == 0)
                self.active = None
            self.last_dull = node

    @staticmethod
    def _node(bar, event, context):
        return dict(bar=asdict(bar), event=event, context=context)


def replay(period, bars):
    calculator = XxmCalculator(period=period, source_identity="restart-audit:" + period)
    audit, events, trace = RestartAudit(), [], []
    for bar in bars:
        step = calculator.step(bar)
        bottom_event = any(e["direction"] == "BOTTOM" and e["type"] in ("CANCEL", "DULL") for e in step.events)
        context = None
        if bottom_event:
            context = dict(wave=asdict(calculator.wave),
                pool=[w.reference() for w in calculator.history[-1]],
                ordinaryState=calculator.state,
                pendingRearm=step.point["pendingRearmId"])
        audit.observe(bar, step.events, context)
        # Close-of-day contexts for the supplied statement and the daily example.
        if bar.time[:10] in ("2024-08-06", "2026-07-20"):
            audit.checkpoints[bar.time[:10]] = dict(time=bar.time, point=step.point,
                wave=asdict(calculator.wave), pool=[w.reference() for w in calculator.history[-1]])
        events.extend(step.events)
        trace.append(dict(bar=asdict(bar), events=list(step.events)))
    return audit, events, trace


def run(output: Path):
    # Do not allow arbitrary directories, existing results, DB/Lake or source writes.
    output = output.resolve()
    reports = (ROOT / "reports").resolve()
    if not output.is_relative_to(reports) or not output.name.startswith("run_"):
        raise ValueError("Output must be a new reports/.../run_* directory")
    output.mkdir(parents=False, exist_ok=False)
    product = ROOT / "src/biz/services/wealth/market/index_detail_xxm"
    protected = list(product.glob("*.py")) + [Path(__file__), SOURCE / "manifest.json"]
    protected += [SOURCE / ("daily_source.csv" if p == "day" else f"minute_{p[1:]}_source.csv") for p in PERIODS]
    protected += [BASELINE / f"events_{p}.json" for p in PERIODS]
    protected += [OBSERVATIONS / "sources/20260803_day.png",
        OBSERVATIONS / "sources/20240806_user_transcript.txt",
        OBSERVATIONS / "case_20260803_events_20261015.json"]
    before = {str(p.relative_to(ROOT)): sha(p) for p in protected}
    started = time.perf_counter()
    summary = dict(spec=asdict(MAIN_SPEC), specHash=MAIN_SPEC.spec_hash, periods={},
        softwareFormulaProven=False, formalBudgetTested=False, productModified=False)
    for period in PERIODS:
        bars = load_source(SOURCE, period)
        audit, events, trace = replay(period, bars)
        baseline = json.loads((BASELINE / f"events_{period}.json").read_text())["events"]
        if events != baseline:
            raise ValueError(f"Current product differs from frozen A1 ledger: {period}")
        cases = [e for e in audit.episodes if e["status"] == "RESTART_BEFORE_RED"]
        exhausted = [e for e in audit.episodes if e["cancel"]["bar"]["hist"] < 0
            and e["cancel"]["context"]["wave"]["dif"] <= min(r["dif"] for r in e["cancel"]["context"]["pool"])]
        for episode in cases:
            cancel, restart = episode["cancel"], episode["nextDull"]
            ref = restart["event"]["eventReference"]
            # Explanatory facts, not a second detector or new product constraint.
            checks = dict(referenceAlreadyInPool=ref in cancel["context"]["pool"],
                lowerDifReference=ref["dif"] < cancel["event"]["eventReference"]["dif"],
                sameSegment=cancel["context"]["wave"]["start"] == restart["context"]["wave"]["start"],
                divergenceRetained=restart["context"]["wave"]["dif"] > ref["dif"],
                priceQualified=restart["context"]["wave"]["price"] < ref["price"],
                activationRoute=restart["event"]["route"] == "activation")
            if not all(checks.values()):
                raise ValueError(f"Unexpected before-red case needs separate explanation: {period}, {cancel['bar']['time']}")
            episode["explanation"] = dict(checks=checks,
                priceQualifiedAtCancel=cancel["context"]["wave"]["price"] < ref["price"],
                reason="qualified_while_reference_locked" if cancel["context"]["wave"]["price"] < ref["price"] else "price_qualified_after_cancel")
        windows = []
        for episode in cases:
            start = episode["precedingDull"]["bar"]["time"] if episode["precedingDull"] else episode["cancel"]["bar"]["time"]
            end = episode["nextDull"]["bar"]["time"]
            windows.append(dict(cancelAt=episode["cancel"]["bar"]["time"],
                restartAt=end, rows=[r for r in trace if start <= r["bar"]["time"] <= end]))
        counts = dict(Counter(e["status"] for e in audit.episodes))
        summary["periods"][period] = dict(rows=len(bars), start=bars[0].time, through=bars[-1].time,
            trueCancels=len(audit.episodes), statuses=counts, baselineEventsEqual=True,
            sameGreenRestarts=sum(e["sameContinuousGreen"] for e in cases),
            changedReferenceRestarts=sum(e["referenceChanged"] for e in cases),
            beforeRedExplanations=dict(Counter(e["explanation"]["reason"] for e in cases)),
            allPoolDifExhaustedOnGreen=len(exhausted),
            beforeRedWithExhaustedPool=sum(e["status"] == "RESTART_BEFORE_RED" for e in exhausted),
            afterRedTooFewGreen=sum(e["status"] == "RESTART_AFTER_RED" and e["negativeBarsAtRestart"] < 2 for e in audit.episodes),
            excluded=dict(audit.excluded))
        payload = dict(episodes=audit.episodes, counterexampleWindows=windows,
            suppliedEvidenceContexts=audit.checkpoints)
        (output / f"episodes_{period}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    summary["elapsedMs"] = (time.perf_counter() - started) * 1000
    after = {str(p.relative_to(ROOT)): sha(p) for p in protected}
    if before != after:
        raise ValueError("Protected source/product/evidence changed during audit")
    summary["protectedSha256"] = before
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output)
    print(json.dumps({p: r for p, r in result["periods"].items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
