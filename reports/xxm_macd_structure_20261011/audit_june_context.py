"""Retrospective lecture-context comparison using unchanged research candidates.

Reads saved DG / derived series only. Text already read before this comparison;
this is not a blind test, software alignment, or trading implementation.
"""
import csv
import hashlib
import json
from pathlib import Path

from active_reference_candidate import replay
from replay import read_rows

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "june_context_20261012.json"
START, END = "2026-06-05", "2026-06-09"
KEYS = ("event", "state", "event_direction", "event_route", "event_ref_start")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    paths = {
        60: ROOT / "inputs/60_20250603_20261009.csv",
        90: ROOT / "discrimination_screen_20261012/derived_90.csv",
        120: ROOT / "discrimination_screen_20261012/derived_120.csv",
    }
    evidence = {
        "reviewed_on": "2026-10-12",
        "method": "RETROSPECTIVE_UNCHANGED_CANDIDATE_CONTEXT_COMPARISON",
        "software_labels_added": 0,
        "candidate_sha256": sha(ROOT / "active_reference_candidate.py"),
        "source_hashes": {str(k): sha(p) for k, p in paths.items()},
        "transcript_hashes": {
            d: sha(ROOT / f"sources/{d}_user_transcript.txt")
            for d in ("20260608", "20260609")
        },
        "series": {},
        "limitations": [
            "60-minute input is saved DG; 90/120 are prior research derivations",
            "60/90 software input and calculation differences remain unresolved",
            "No supplied software numeric values or exact software event timestamps",
            "Textual agreement cannot validate unique gate or reference policy",
            "Red/green wave terminology in the transcript requires image verification",
        ],
    }
    prefix_checks = 0
    for freq, path in paths.items():
        if freq == 60:
            rows = read_rows(path.name)
        else:
            with path.open(newline="") as handle:
                rows = [
                    dict(time=r["time"], **{k: float(r[k]) for k in ("close", "dif", "hist")})
                    for r in csv.DictReader(handle)
                ]
        indexes = [i for i, r in enumerate(rows) if START <= r["time"][:10] <= END]
        baseline = replay(rows, 1.0, diagnostics=True)
        baseline_signature = [tuple(baseline[i][k] for k in KEYS) for i in indexes]
        variants = []
        for gate in (.75, 1., 1.2):
            for policy in ("locked", "both_before", "dull_before", "both_after"):
                variant = replay(rows, gate, active_policy=policy)
                signature = [tuple(variant[i][k] for k in KEYS) for i in indexes]
                # Check only nontrivial events and the two lecture close endpoints.
                probes = [i for i in indexes if variant[i]["event"] != "NONE"
                          or rows[i]["time"] in ("2026-06-08 15:00:00", "2026-06-09 15:00:00")]
                for i in probes:
                    prefix = replay(rows[:i+1], gate, active_policy=policy)[-1]
                    assert all(prefix[k] == variant[i][k] for k in KEYS)
                    prefix_checks += 1
                variants.append(dict(gate_pct=gate, active_policy=policy,
                                     same_window_signature=signature == baseline_signature))
        evidence["series"][str(freq)] = {
            "origin": "SAVED_DG" if freq == 60 else "DERIVED_NOT_SOFTWARE_HISTORY",
            "variants": variants,
            "baseline_gate_pct": 1.0,
            "window": [
                {k: baseline[i][k] for k in (
                    "time", "close", "dif", "hist", "event", "state", "wave_count",
                    "event_direction", "event_route", "event_ref_dif", "event_ref_start")}
                for i in indexes
            ],
        }
    assert all(sha(paths[int(k)]) == h for k, h in evidence["source_hashes"].items())
    evidence["prefix_checks"] = prefix_checks
    evidence["all_36_sampled_variants_agree"] = all(
        v["same_window_signature"] for s in evidence["series"].values() for v in s["variants"]
    )
    OUT.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"prefix_checks": prefix_checks,
                      "all_36_sampled_variants_agree": evidence["all_36_sampled_variants_agree"],
                      "software_labels_added": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
