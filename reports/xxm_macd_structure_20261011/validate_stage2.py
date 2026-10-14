"""Bounded replay of existing evidence plus falsifiable research comparisons.

Only reads saved CSV/JSON evidence; writes new stage-2 reports beside this file.
Existing labels are calibration/retrospective evidence, not a blind test.
"""
import csv
import hashlib
import json
from pathlib import Path

from replay import replay as old_replay
from replay_color_flip import read_rows, replay

ROOT = Path(__file__).resolve().parent
POLICIES = ("nearest_qualifying", "strongest_eligible", "strongest_separate")
CASES = {
    "jul_120": "120_20250401_20250711.csv",
    "aug_120": "120_20250401_20251111.csv",
    "daily_2025": "daily_2025.csv",
    "may_120": "120_20260101_20260507.csv",
    "bottom_daily": "daily_20260801_20261009.csv",
    "mins60": "60_20250603_20261009.csv",
    "mins90": "90_20250603_20260113.csv",
}


def evidence_labels():
    labels = []
    with (ROOT / "label_comparison.csv").open(newline="") as handle:
        for r in csv.DictReader(handle):
            if float(r["threshold_pct"]) == 1:
                labels.append(dict(case=r["case"], time=r["time"],
                                   expected=r["expected"], confidence=r["label_confidence"],
                                   source="original_25"))
    labels.append(dict(case="mins60", time="2026-04-07 15:00:00",
                       expected="NONE", confidence="direct", source="IMG_0366"))
    for case in ("mins60", "mins90"):
        labels.append(dict(case=case, time="2026-01-13 15:00:00",
                           expected="NONE", confidence="direct", source="IMG_0369_0370"))
    for r in json.loads((ROOT / "holdout_0374.json").read_text())["observed"]["labels"]:
        labels.append(dict(case="mins90", time=r["time"], expected=r["event"],
                           confidence=r["confidence"], source="IMG_0374"))
    for r in json.loads((ROOT / "holdout_20251016.json").read_text())["checks"]:
        if r["reference_mode"] == "frozen_reference" and r["threshold_pct"] == 1:
            labels.append(dict(case="daily_2025" if r["case"] == "daily" else "aug_120",
                               time=r["time"], expected=r["expected"],
                               confidence=r["label_confidence"], source="20251016"))
    assert len(labels) == 39
    assert len({(r["case"], r["time"]) for r in labels}) == len(labels)
    return labels


def scenario_checks():
    def rows(values):
        return [dict(time=f"t{i:02d}", close=c, dif=d, hist=h)
                for i, (c, d, h) in enumerate(values)]
    base = [(100, 10, 1), (101, 12, 1), (95, 9, -1),
            (102, 9, 1), (103, 9.5, 1)]
    cases = []
    def check(name, data, expected, expected_direction=0):
        r = replay(rows(data), 1)[-1]
        assert r["event"] == expected, (name, r)
        if expected_direction:
            assert r["event_direction"] == expected_direction, (name, r)
        cases.append(dict(name=name, expected=expected, actual=r["event"], passed=True))
    check("top_color_flip_despite_tiny_dif_turn", base + [(102, 9.49, -0.1)], "STRUCTURE", 1)
    mirrored = [(200-c, -d, -h) for c, d, h in base + [(102, 9.49, -0.1)]]
    check("bottom_color_flip_despite_tiny_dif_turn", mirrored, "STRUCTURE", -1)
    check("no_prior_dull_no_color_structure", base[:3] + [(99, 9, 1), (100, 9.5, 1), (99, 9.49, -0.1)], "NONE")
    canceled = base[:4] + [(103, 13, 1)]
    check("top_canceled_before_flip", canceled + [(102, 12.9, -0.1)], "NONE")
    check("bottom_canceled_before_flip", [(200-c, -d, -h) for c,d,h in canceled + [(102, 12.9, -0.1)]], "NONE")
    check("already_confirmed_no_duplicate_at_flip", base + [(102, 9, 1), (101, 8.9, -0.1)], "NONE")
    check("zero_histogram_not_assumed_color_confirmation", base + [(102, 9.49, 0)], "NONE")
    check("tiny_same_color_turn_stays_filtered", base + [(102, 9.49, 0.1)], "NONE")
    # Contrived input collision tests ordering, not a claimed realizable EMA path.
    check("reference_break_priority_on_flip_synthetic", base + [(104, 12.1, -0.1)], "CANCEL", 1)
    filtered = replay(rows(base + [(102, 9.49, -0.1)]), 1, flip_requires_turn=True)[-1]
    assert filtered["event"] == "NONE"
    cases.append(dict(name="filtered_flip_distinguishes_tiny_synthetic_turn", expected="NONE", actual=filtered["event"], passed=True))
    # Shared causality/negatives are checked on market evidence below as well.
    return cases


def main():
    frozen = json.loads((ROOT / "validation_stage2_frozen.json").read_text())
    for entry in frozen["files"]:
        assert hashlib.sha256((ROOT / entry["file"]).read_bytes()).hexdigest() == entry["sha256"], entry["file"]
    labels = evidence_labels()
    data = {k: read_rows(f) for k, f in CASES.items()}
    checks, summaries = [], []
    for policy in POLICIES:
        for pct in (.75, 1, 1.2):
            predictions = {k: {r["time"]: r for r in replay(rr, pct, reference_policy=policy)}
                           for k, rr in data.items()}
            current = []
            for label in labels:
                actual = predictions[label["case"]][label["time"]]
                prefix = [r for r in data[label["case"]] if r["time"] <= label["time"]]
                assert replay(prefix, pct, reference_policy=policy)[-1] == actual
                current.append(dict(**label, policy=policy, threshold_pct=pct,
                                    predicted=actual["event"], matched=label["expected"] == actual["event"],
                                    event_route=actual["event_route"], event_ref_start=actual["event_ref_start"],
                                    event_ref_dif=actual["event_ref_dif"], causal_prefix_matched=True))
            checks.extend(current)
            summaries.append(dict(policy=policy, threshold_pct=pct, points=len(current),
                                  direct_mismatches=sum(not r["matched"] for r in current if r["confidence"] == "direct"),
                                  mapped_mismatches=sum(not r["matched"] for r in current if r["confidence"] == "mapped"),
                                  failures=[r for r in current if not r["matched"]]))
    filtered_label_checks = []
    for pct in (.75, 1, 1.2):
        for label in labels:
            rows = data[label["case"]]
            prefix = [r for r in rows if r["time"] <= label["time"]]
            actual = replay(prefix, pct, flip_requires_turn=True)[-1]
            complete = {r["time"]: r for r in replay(rows, pct, flip_requires_turn=True)}
            assert actual == complete[label["time"]]
            filtered_label_checks.append(dict(**label, threshold_pct=pct,
                                              predicted=actual["event"], matched=actual["event"] == label["expected"],
                                              causal_prefix_matched=True))
    scope_checks, added, disagreements, ref_differences, filtered_diffs = [], [], [], [], []
    labelled = {(CASES[r["case"]], r["time"]): r["expected"] for r in labels}
    for filename in sorted(p.name for p in (ROOT / "inputs").glob("*.csv")):
        rows = read_rows(filename)
        old = old_replay(rows, 1, require_nearest_price_break=True)
        disabled = replay(rows, 1, color_flip=False)
        # With flip path off, the new nearest candidate exactly reproduces v1.
        assert all(all(b[k] == a[k] for k in a) for a,b in zip(old, disabled))
        variants = {p: replay(rows, 1, reference_policy=p) for p in POLICIES}
        for pct in (.75, 1, 1.2):
            unfiltered = replay(rows, pct)
            filtered = replay(rows, pct, flip_requires_turn=True)
            filtered_diffs.append(dict(input=filename, threshold_pct=pct,
                                       event_differences=sum(a["event"] != b["event"] for a,b in zip(unfiltered,filtered))))
        causal = 0
        for policy, outputs in variants.items():
            for i, out in enumerate(outputs):
                assert replay(rows[:i+1], 1, reference_policy=policy)[-1] == out
                causal += 1
        a = variants["nearest_qualifying"]
        for i, row in enumerate(rows):
            if old[i]["event"] != a[i]["event"]:
                added.append(dict(input=filename, time=row["time"], old_event=old[i]["event"],
                                  new_event=a[i]["event"], route=a[i]["event_route"],
                                  direction=a[i]["event_direction"],
                                  software_label=labelled.get((filename,row["time"]),"NOT_CONFIRMED")))
            for policy in POLICIES[1:]:
                b = variants[policy][i]
                if b["event"] != a[i]["event"]:
                    disagreements.append(dict(input=filename, time=row["time"], alternative=policy,
                                              nearest_event=a[i]["event"], alternative_event=b["event"],
                                              nearest_ref=a[i]["event_ref_start"], alternative_ref=b["event_ref_start"],
                                              software_label=labelled.get((filename,row["time"]),"NOT_CONFIRMED")))
                elif b["event_ref_start"] != a[i]["event_ref_start"]:
                    ref_differences.append(dict(input=filename, time=row["time"], alternative=policy,
                                               event=a[i]["event"], nearest_ref=a[i]["event_ref_start"],
                                               alternative_ref=b["event_ref_start"],
                                               nearest_dif=a[i]["event_ref_dif"], alternative_dif=b["event_ref_dif"],
                                               software_label=labelled.get((filename,row["time"]),"NOT_CONFIRMED")))
        scope_checks.append(dict(input=filename, rows=len(rows), v1_disabled_exact_match=True,
                                 causal_checks=causal))
    for name, records in [("stage2_label_comparison.csv",checks),
                          ("stage2_new_events.csv",added),
                          ("stage2_reference_disagreements.csv",disagreements),
                          ("stage2_reference_choices.csv",ref_differences)]:
        with (ROOT / name).open("w",newline="") as handle:
            if records:
                writer=csv.DictWriter(handle,fieldnames=list(records[0]))
                writer.writeheader(); writer.writerows(records)
    output=dict(scope="Existing-evidence replay; not out-of-sample accuracy or original formula",
                candidate_sha256=hashlib.sha256((ROOT / "replay_color_flip.py").read_bytes()).hexdigest(),
                labels=len(labels),model_point_checks=len(checks),summaries=summaries,
                filtered_flip_label_checks=filtered_label_checks,
                filtered_flip_market_differences=filtered_diffs,
                synthetic_checks=scenario_checks(),scope_checks=scope_checks,
                added_events=added,reference_event_disagreements=disagreements,
                reference_choice_differences=ref_differences,
                limitations=["Mapped labels may shift by one bar; no new screenshot was received.",
                             "Event state after color flip belongs to old wave; current-wave state resets.",
                             "Cross-wave validity/cancellation of old confirmed references remains unimplemented.",
                             "Strongest of two and sign-wave peak definitions are hypotheses, not software facts.",
                             "Color flip bypassing the DIF-turn threshold is not identified by the existing market evidence.",
                             "Bottom turn thresholds and zero-bar splitting remain unconfirmed."])
    (ROOT / "validation_stage2.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(dict(labels=len(labels),model_point_checks=len(checks),summaries=summaries,
                          synthetic_checks=len(output["synthetic_checks"]),
                          all_input_causal_checks=sum(r["causal_checks"] for r in scope_checks),
                          added_event_rows=len(added),reference_disagreement_rows=len(disagreements),
                          reference_choice_rows=len(ref_differences)),ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
