"""Audit one newly supplied screenshot against the previously frozen candidate.

The two reference refinements are fitted after viewing IMG_0366, so they are
not independent holdout successes. Leaves the original 25-point outputs intact.
"""
import csv
import hashlib
import json
from pathlib import Path

from replay import read_rows, replay

ROOT = Path(__file__).resolve().parent


def main():
    files = dict(jul_120="120_20250401_20250711.csv",
                 aug_120="120_20250401_20251111.csv",
                 daily_2025="daily_2025.csv", may_120="120_20260101_20260507.csv",
                 bottom_daily="daily_20260801_20261009.csv")
    prior = [r for r in csv.DictReader((ROOT / "label_comparison.csv").open()) if r["threshold_pct"] == "1"]
    assert len(prior) == 25
    full_rows = read_rows("60_20250603_20261009.csv")
    rows = [r for r in full_rows if r["time"] <= "2026-04-07 15:00:00"]
    target = rows[-1]
    # One direct terminal label; a whole region lacks the predicted earlier DULL.
    expected = "NONE"
    checks = []
    options = [("frozen_reference_r075", .75, {}),
               ("frozen_reference_r1", 1, {}),
               ("frozen_reference_r12", 1.2, {}),
               ("require_nearest_price_break_r1", 1, dict(require_nearest_price_break=True)),
               ("reject_dominated_reference_r1", 1, dict(reject_dominated_reference=True))]
    for name, threshold, kwargs in options:
        result = replay(rows, threshold, **kwargs)
        old_results = {k: {r["time"]: r for r in replay(read_rows(f), threshold, **kwargs)} for k, f in files.items()}
        failures = [dict(case=r["case"], time=r["time"], expected=r["expected"],
                         predicted=old_results[r["case"]][r["time"]]["event"])
                    for r in prior if old_results[r["case"]][r["time"]]["event"] != r["expected"]]
        complete = {r["time"]: r for r in replay(full_rows, threshold, **kwargs)}
        assert complete[target["time"]] == result[-1]
        checks.append(dict(variant=name, prior_25_mismatches=len(failures),
                           prior_failures=failures, terminal_expected=expected,
                           terminal_predicted=result[-1]["event"],
                           terminal_matched=result[-1]["event"] == expected,
                           causal_prefix_matched=True,
                           current_wave_events=[r for r in result if r["time"] >= "2026-04-03 11:30:00" and r["event"] != "NONE"]))
    waves = []
    for r in rows:
        sign = 1 if r["hist"] > 0 else -1 if r["hist"] < 0 else 0
        if not waves or waves[-1]["sign"] != sign:
            waves.append(dict(sign=sign, rows=[]))
        waves[-1]["rows"].append(r)
    refs = []
    for wave in [w for w in waves if w["sign"] == -1][-3:]:
        rs = wave["rows"]
        low_c, low_d = min(rs, key=lambda r:r["close"]), min(rs, key=lambda r:r["dif"])
        refs.append(dict(start=rs[0]["time"], end=rs[-1]["time"], bars=len(rs),
                         min_close=low_c["close"], min_close_time=low_c["time"],
                         min_dif=low_d["dif"], min_dif_time=low_d["time"]))
    snapshot = ROOT / "replay_frozen_25_points.py"
    output = dict(screenshot="IMG_0366.PNG", screenshot_date="2026-04-07", freq=60,
                  frozen_script=snapshot.name, frozen_script_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                  observed=dict(terminal_event="NONE", terminal_confidence="direct",
                                current_wave_no_visible_dull_label=True,
                                earlier_dull_absence_confidence="regional_not_per_bar_capture",
                                software_dif=-10.804, software_dea=-8.638, software_hist=-4.331),
                  dg_terminal=dict(**target, dea=target["dif"]-target["hist"]/2),
                  reference_wave_stats=refs, candidate_checks=checks,
                  interpretation="No terminal structure is observed. Reference activation is challenged; do not infer a larger turn threshold from this alone.",
                  limitations=["software/DG numeric mismatch", "reference precision margin is only about 0.00317 in DIF", "refinements fitted after new screenshot"])
    (ROOT / "holdout_0366.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(dict(reference_wave_stats=refs, candidate_checks=checks),ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
