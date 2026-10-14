"""Bounded retrospective correction diagnostics; no candidate or label changes.

Keep each confirmed reference fixed until a strict raw DIF crossing. This is
an explicit diagnostic hypothesis, not recovered software structure validity.
Author October text has already been read; results are not blind scoring.
"""
import hashlib
import json
from pathlib import Path

from active_reference_candidate import replay
from replay import read_rows

ROOT = Path(__file__).resolve().parent
START, END = "2025-09-01", "2025-10-27"
KEYS = ("event", "state", "event_direction", "event_route", "event_ref_start")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def monitor(rows, gate):
    output = replay(rows, gate)
    records = []
    for index, event in enumerate(output):
        if event["event"] != "STRUCTURE" or event["time"][:10] < START:
            continue
        direction, ref = event["event_direction"], event["event_ref_dif"]
        tail = output[index + 1:]
        crossing = next((r for r in tail if direction * (r["dif"] - ref) > 0), None)
        # A flip is relative to the confirmed structure direction, including
        # color-flip confirmation on the confirming bar itself.
        flipped = next((r for r in output[index:] if r["wave_sign"] != direction), None)
        records.append(dict(confirmed_at=event["time"], direction=direction,
                            reference_start=event["event_ref_start"], reference_dif=ref,
                            first_different_wave_sign=flipped["time"] if flipped else None,
                            first_strict_cross=crossing["time"] if crossing else None,
                            status="NO_CROSS_BY_WINDOW_END" if crossing is None else "CROSSED",
                            software_reference="NOT_OBSERVED"))
    return output, records


def main():
    definitions = ROOT / "correction_definitions_20261012.json"
    sources = {90: "90_20250603_20260113.csv", 120: "120_20250401_20251111.csv"}
    result = dict(scope=dict(start=START, end=END),
                  method="RETROSPECTIVE_FIXED_CONFIRMED_REFERENCE_DIAGNOSTIC",
                  definitions_sha256=sha(definitions),
                  candidate_sha256=sha(ROOT / "active_reference_candidate.py"),
                  periods={}, prefix_checks=0, new_software_labels=0)
    for period, name in sources.items():
        rows = [r for r in read_rows(name) if r["time"][:10] <= END]
        variants = []
        for gate in (.75, 1., 1.2):
            output, records = monitor(rows, gate)
            daily = [r for r in output if r["time"][:10] in {"2025-10-24", END}]
            targets = {r["confirmed_at"] for r in records}
            targets.update(r["first_strict_cross"] for r in records if r["first_strict_cross"])
            targets.update(r["time"] for r in daily)
            for target in sorted(targets):
                prefix = [r for r in rows if r["time"] <= target]
                check, partial = monitor(prefix, gate)
                full = next(r for r in output if r["time"] == target)
                assert all(check[-1][k] == full[k] for k in KEYS)
                for item in partial:
                    original = next(r for r in records if r["confirmed_at"] == item["confirmed_at"])
                    expected = original["first_strict_cross"]
                    assert item["first_strict_cross"] == (expected if expected and expected <= target else None)
                result["prefix_checks"] += 1
            variants.append(dict(gate_pct=gate, confirmed_reference_records=records,
                                 final_days=daily))
        assert all(v["confirmed_reference_records"] == variants[0]["confirmed_reference_records"]
                   for v in variants)
        result["periods"][str(period)] = dict(input=name,
            input_sha256=sha(ROOT / "inputs" / name), variants=variants)
    result["limits"] = [
        "90-minute numerical source differences unresolved",
        "Original software confirmed-reference values are not observed",
        "Current eligible reference cancellation and prior decision correction are different objects",
        "No formal trade engine, universal expiry or reassignment policy inferred",
    ]
    (ROOT / "correction_lifecycle_20261012.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(dict(prefix_checks=result["prefix_checks"],
        records={k:v["variants"][1]["confirmed_reference_records"] for k,v in result["periods"].items()}),
        ensure_ascii=False))


if __name__ == "__main__":
    main()
