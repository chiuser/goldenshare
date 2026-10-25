"""Bounded reference-condition replay, plan 12.93 / LLD 71.

No full state machine, price-wave definition, amplitude gate or source fetch.
The broad merge comparison ignores the still undefined small-fluctuation test.
The saved June reference pool is an input assumption, not a recovered formula.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN
import hashlib
import json
from pathlib import Path
import resource
import time

from src.biz.services.wealth.market.index_detail_daily_wave.local_extrema import LocalExtremaScanner, number
from .local_extrema_study import CASES, ROOT, SavedCase, read_case, save_new, validate_rows


@dataclass(frozen=True)
class ReviewSpec:
    max_references: int = 2
    max_opposite_peaks: int = 1
    merge_more_than: int = 2
    merge_basis: str = "DIF"


SPEC = ReviewSpec()
JUNE_PATH = "reports/xxm_jun25_reference_evidence_20261021_01/saved_comparison.json"
JUNE_SHA = "4d0dcb434bb2976796c12e36f53b005a8afc34ce0c2e759c457d533c6a81ad88"
AUG_CASE = SavedCase(
    "m120_aug_old", "reports/xxm_aug07_price_reference_evidence_20261021_01/old_segment_source_projection.json",
    "c343d17da79542ea7ea0b45eac577ae448985be0bc05c4316088883f184fabfa", 14, "120",
)


def decimal_value(value) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("Boolean is not a financial value")
    return number(str(value))


def quantize_dif(value) -> Decimal:
    x = decimal_value(value)
    if not x:
        return x
    unit = Decimal(1).scaleb(abs(x).adjusted() - 1)
    return (x / unit).to_integral_value(rounding=ROUND_DOWN) * unit


@dataclass(frozen=True)
class Reference:
    label: str
    price: Decimal
    dif: Decimal


def choose_reference(direction: str, price, dif, references: list[Reference],
                     *, two_digits: bool = True) -> dict:
    """Independently recheck an already ordered pool; never retain a binding."""
    if direction not in ("TOP", "BOTTOM") or not isinstance(two_digits, bool):
        raise ValueError("Invalid comparison mode")
    current_price, raw_dif = decimal_value(price), decimal_value(dif)
    if current_price <= 0:
        raise ValueError("Positive prices required")
    current_dif = quantize_dif(raw_dif) if two_digits else raw_dif
    checked = []
    for reference in references[:SPEC.max_references]:
        reference_price, reference_raw = decimal_value(reference.price), decimal_value(reference.dif)
        if reference_price <= 0:
            raise ValueError("Positive reference prices required")
        reference_dif = quantize_dif(reference_raw) if two_digits else reference_raw
        price_ok = current_price > reference_price if direction == "TOP" else current_price < reference_price
        dif_ok = current_dif < reference_dif if direction == "TOP" else current_dif > reference_dif
        checked.append(dict(label=reference.label, pricePassed=price_ok, difPassed=dif_ok,
                            comparisonDif=str(reference_dif)))
        if price_ok and dif_ok:
            return dict(condition=True, selected=reference.label, checked=checked,
                        comparisonDif=str(current_dif))
    return dict(condition=False, selected=None, checked=checked, comparisonDif=str(current_dif))


def decision_signature(result: dict) -> tuple:
    """Compare decisions, excluding the deliberately different numeric display."""
    return (result["condition"], result["selected"],
            tuple((r["label"], r["pricePassed"], r["difPassed"]) for r in result["checked"]))


def inspect_histogram(rows: list[dict]) -> dict:
    scanner, turns = LocalExtremaScanner(), []
    for row in rows:
        point = scanner.step(row["trade_time"], row["macd"])
        if point is not None:
            turns.append(point.record())
    peaks = [p for p in turns if (p["kind"] == "MAX" and number(p["value"]) > 0)
             or (p["kind"] == "MIN" and number(p["value"]) < 0)]
    pairs = []
    for kind in ("MAX", "MIN"):
        same = [p for p in peaks if p["kind"] == kind]
        for left, right in zip(same, same[1:]):
            opposite = [p for p in peaks if p["kind"] != kind
                        and left["last_index"] < p["first_index"] < right["first_index"]]
            pairs.append(dict(direction="TOP" if kind == "MAX" else "BOTTOM",
                              left=left, right=right, oppositePeaks=len(opposite),
                              allowedByProposedCount=len(opposite) <= SPEC.max_opposite_peaks))

    groups = []
    for index, row in enumerate(rows):
        value = number(row["macd"])
        sign = 1 if value > 0 else -1 if value < 0 else 0
        if not sign:
            continue
        if groups and groups[-1]["endIndex"] == index - 1 and groups[-1]["sign"] == sign:
            groups[-1]["endIndex"] = index
        else:
            groups.append(dict(sign=sign, startIndex=index, endIndex=index))
    for group in groups:
        start, end, sign = group["startIndex"], group["endIndex"], group["sign"]
        members = [p for p in peaks if start <= p["first_index"] <= end]
        dif_index = max(range(start, end + 1), key=lambda i: sign * number(rows[i]["macd_dif"]))
        hist_index = max(range(start, end + 1), key=lambda i: sign * number(rows[i]["macd"]))
        group.update(confirmedHistogramPeaks=len(members), peaks=members,
                     moreThanTwo=len(members) > 2,
                     histogramExtreme=dict(time=rows[hist_index]["trade_time"], value=rows[hist_index]["macd"]),
                     difExtreme=dict(time=rows[dif_index]["trade_time"], value=rows[dif_index]["macd_dif"]),
                     extremesAtSameTime=hist_index == dif_index,
                     leftMayBeTruncated=start == 0, rightMayContinue=end == len(rows) - 1)
    return dict(rows=len(rows), confirmedPeaks=peaks, adjacentPairs=pairs, colourGroups=groups,
                mergingExecuted=False, numericDivergenceSignalsProduced=False)


def merge_for_review(rows: list[dict], shape: dict) -> dict:
    """Broad comparison only: merge all >2-peak colour groups, no size gate.

    Raw positions remain histogram positions; only merged representatives use
    the group's observed DIF extreme. This is not a complete DIF reference pool.
    """
    items, merged = [], []
    index_by_time = {row["trade_time"]: i for i, row in enumerate(rows)}
    for group in shape["colourGroups"]:
        if group["confirmedHistogramPeaks"] > SPEC.merge_more_than:
            extreme = group["difExtreme"]
            index = index_by_time[extreme["time"]]
            item = dict(kind="MAX" if group["sign"] == 1 else "MIN",
                        first_index=index, last_index=index,
                        first_at=extreme["time"], last_at=extreme["time"],
                        basis=SPEC.merge_basis, difValue=extreme["value"],
                        originalPeakCount=group["confirmedHistogramPeaks"],
                        originalPeaks=group["peaks"], knownAt=rows[-1]["trade_time"],
                        groupStillOpen=group["rightMayContinue"],
                        leftMayBeTruncated=group["leftMayBeTruncated"],
                        confirmedDifTurningPoint=False, priceAssigned=False)
            items.append(item)
            merged.append(item)
        else:
            items.extend(dict(p, basis="histogram_position", priceAssigned=False,
                              difReferenceAssigned=False) for p in group["peaks"])
    items.sort(key=lambda p: p["first_index"])
    pairs = []
    for kind in ("MAX", "MIN"):
        same = [p for p in items if p["kind"] == kind]
        for left, right in zip(same, same[1:]):
            count = sum(p["kind"] != kind and left["last_index"] < p["first_index"] < right["first_index"]
                        for p in items)
            pairs.append(dict(direction="TOP" if kind == "MAX" else "BOTTOM",
                              leftAt=left["first_at"], rightAt=right["first_at"],
                              oppositePeaks=count, allowedByProposedCount=count <= SPEC.max_opposite_peaks))
    return dict(items=items, mergedGroups=merged, adjacentPairs=pairs,
                allMoreThanTwoMerged=True, smallFluctuationConditionEvaluated=False,
                completeDifReferencePool=False, technicalSignalsProduced=False)


def read_frozen_json(path: str, expected: str):
    target = ROOT / path
    if target.stat().st_size > 100_000 or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
        raise ValueError("Changed or oversized frozen input")
    return json.loads(target.read_text())


def replay_june(source: dict) -> dict:
    if set(source) != {"m60", "m90", "m120"}:
        raise ValueError("Changed saved comparison periods")
    output = []
    for period, slots, expected_count in (("m60", {"10:30", "11:30", "14:00", "15:00"}, 5),
                                           ("m90", {"11:00", "14:00", "15:00"}, 4),
                                           ("m120", {"11:30", "15:00"}, 3)):
        saved = source[period]
        bars = [saved["activation"], *saved["sourceBars"]]
        if len(bars) != expected_count:
            raise ValueError("Changed bounded June sample count")
        previous = None
        refs = []
        end_times = []
        for label, key in (("near", "localNearest"), ("far", "localSelected")):
            item = saved[key]
            refs.append(Reference(label, decimal_value(item["price"]), decimal_value(item["dif"])))
            end_times.append(item["endTime"])
        if not end_times[1] < end_times[0] < bars[0]["time"]:
            raise ValueError("Reference ordering or chronology changed")
        for bar in bars:
            stamp = datetime.fromisoformat(bar["time"])
            if (bar["completed"] is not True or stamp.utcoffset() != timedelta(hours=8)
                    or stamp.strftime("%H:%M") not in slots or stamp.second != 0
                    or bar["time"][:10] not in {"2025-06-24", "2025-06-25"}
                    or previous is not None and bar["time"] <= previous):
                raise ValueError("Invalid saved completed sample")
            previous = bar["time"]
            values = {key: decimal_value(bar[key]) for key in ("close", "dif", "dea", "hist")}
            if abs(values["hist"] - 2 * (values["dif"] - values["dea"])) > Decimal("0.0000000001"):
                raise ValueError("Broken saved MACD identity")
            output.append(dict(period=period, time=bar["time"], bar=bar,
                               raw=choose_reference("TOP", values["close"], values["dif"], refs, two_digits=False),
                               twoDigits=choose_reference("TOP", values["close"], values["dif"], refs),
                               historicalReferencePoolAssumed=True, oppositePeakCountUnknown=True))
    return dict(rows=output, count=len(output), sparse=True, fullStructureBacktest=False,
                referencePoolReconstructed=False, signalsAreComparisonConditionsOnly=True)


def protected_evidence() -> dict:
    old = ROOT / "reports/xxm_local_extrema_trial_20261021_01"
    result = dict(json.loads((old / "run.json").read_text())["protected"])
    for path in old.iterdir():
        if path.is_file():
            result[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    for directory in ("xxm_near_first_review_20261021_01", "xxm_near_first_review_20261021_02",
                      "xxm_near_first_review_20261021_03",
                      "xxm_dif_peak_confirmation_20261021_01"):
        prior = ROOT / "reports" / directory
        if prior.is_dir():
            for path in prior.iterdir():
                if path.is_file():
                    result[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path in ("src/biz/services/wealth/market/index_detail_daily_wave/local_extrema.py",
                 "scripts/research/index_market/xxm/local_extrema_study.py",
                 "scripts/research/index_market/xxm/top_reference_priority.py",
                 "scripts/research/index_market/xxm/top_return_reference.py", JUNE_PATH, AUG_CASE.path):
        result[path] = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
    return result


def check_protected(expected: dict):
    for name, digest in expected.items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Protected evidence changed: " + name)


def run(output: Path) -> dict:
    out = output.resolve()
    if out.parent != ROOT / "reports" or not out.name.startswith("xxm_near_first_review_"):
        raise ValueError("Use a new reports/xxm_near_first_review_* directory")
    out.mkdir(exist_ok=False)
    started = time.perf_counter()
    protected = protected_evidence()
    code = [Path(__file__), ROOT / "scripts/research/index_market/tests/test_xxm_near_first_review.py"]
    save_new(out, "run.json", dict(status="RUNNING", spec=asdict(SPEC), protected=protected,
                                   codeSha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in code},
                                   limits=dict(seconds=60, memoryBytes=256 * 1024 * 1024, outputBytes=16_000_000)))
    try:
        june = replay_june(read_frozen_json(JUNE_PATH, JUNE_SHA))
        save_new(out, "june_conditions.json", june)
        windows, prefix_checks = [], 0
        for case in (*CASES, AUG_CASE):
            if case == AUG_CASE:
                wrapper = read_frozen_json(case.path, case.sha256)
                rows = wrapper["rows"]
                quality = validate_rows(rows, case)
            else:
                rows, quality = read_case(case)
            shape = inspect_histogram(rows)
            merged = merge_for_review(rows, shape)
            snapshots = []
            for length in range(1, len(rows) + 1):
                prefix_shape = inspect_histogram(rows[:length])
                actual = prefix_shape["confirmedPeaks"]
                expected = [p for p in shape["confirmedPeaks"] if p["confirmed_index"] < length]
                if actual != expected:
                    raise AssertionError("Confirmed peak depends on later rows")
                prefix_checks += 1
                prefix_merge = merge_for_review(rows[:length], prefix_shape)
                snapshots.append(dict(asOf=rows[length - 1]["trade_time"],
                                      merged=[dict(time=p["first_at"], dif=p["difValue"], open=p["groupStillOpen"])
                                              for p in prefix_merge["mergedGroups"]],
                                      pairCount=len(prefix_merge["adjacentPairs"])))
            save_new(out, case.name + ".json", dict(source=asdict(case), quality=quality, shape=shape,
                                                   broadMerge=merged, prefixMergeSnapshots=snapshots))
            windows.append(dict(name=case.name, rows=len(rows), pairs=shape["adjacentPairs"],
                                groups=shape["colourGroups"], merged=merged))
            if time.perf_counter() - started > 45:
                raise TimeoutError("Review budget exceeded before final validation")
        pairs = [p for w in windows for p in w["pairs"]]
        groups = [g for w in windows for g in w["groups"]]
        merged_pairs = [p for w in windows for p in w["merged"]["adjacentPairs"]]
        summary = dict(junePointCount=june["count"], rawRows=sum(w["rows"] for w in windows),
                       juneLast=[r for r in june["rows"] if r["time"][:10] == "2025-06-25" and "T15:00" in r["time"]],
                       rawVsTwoDigitDecisionDifferences=[r for r in june["rows"]
                                                        if decision_signature(r["raw"]) != decision_signature(r["twoDigits"])],
                       adjacentPairCount=len(pairs), oppositePeakCounts=dict(Counter(str(p["oppositePeaks"]) for p in pairs)),
                       rejectedByProposedCount=[dict(window=w["name"], **p) for w in windows for p in w["pairs"] if not p["allowedByProposedCount"]],
                       contiguousMoreThanTwo=[dict(window=w["name"], **g) for w in windows for g in w["groups"] if g["moreThanTwo"]],
                       colourGroups=len(groups), histogramAndDifExtremesAtDifferentTimes=sum(not g["extremesAtSameTime"] for g in groups),
                       prefixChecks=prefix_checks, peakMergingExecuted=True, highestDefinitionAwaitingUser=False,
                       highestDefinition="DIF; TOP maximum, BOTTOM minimum",
                       mergedGroupCount=sum(len(w["merged"]["mergedGroups"]) for w in windows),
                       broadMergeAdjacentPairs=len(merged_pairs),
                       broadMergeOppositePeakCounts=dict(Counter(str(p["oppositePeaks"]) for p in merged_pairs)),
                       broadMergeRejected=[dict(window=w["name"], **p) for w in windows
                                           for p in w["merged"]["adjacentPairs"] if not p["allowedByProposedCount"]],
                       smallFluctuationConditionEvaluated=False,
                       smallFluctuationThresholdDefined=False, fullStructureBacktest=False, methodConfirmed=False,
                       softwareLabelsAdded=0, previous52And13Changed=False,
                       knownLimits=["Saved June reference pool assumed; topology not reconstructable from sparse rows",
                                    "Column shapes not substituted for DIF comparisons or price-wave boundaries",
                                    "Counter statistics not author accuracy or independent software labels",
                                    "Broad merge ignores undefined small-fluctuation condition; not the full user rule",
                                    "Open-group DIF representatives update; not fixed confirmed DIF turning points",
                                    "Strict DIF equality remains a candidate convention, not confirmed author formula"])
        save_new(out, "summary.json", summary)
        check_protected(protected)
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if rss > 256 * 1024 * 1024 or time.perf_counter() - started > 60:
            raise RuntimeError("Review resource budget exceeded")
        completed = dict(status="COMPLETED_PARTIAL_METHOD_REVIEW", seconds=time.perf_counter() - started,
                         rssMaxBytes=rss, protectedFiles=len(protected), protectedUnchanged=True,
                         engineeringChecksPassed=True, fullStructureBacktest=False, mergingExecuted=True,
                         smallFluctuationConditionEvaluated=False)
        save_new(out, "completion.json", completed)
        return completed
    except BaseException as exc:
        save_new(out, "failure.json", dict(status="FAILED", errorType=type(exc).__name__, error=str(exc)))
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
