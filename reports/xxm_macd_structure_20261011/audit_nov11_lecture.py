"""Compare a newly supplied lecture with the preserved November screen.

No parameter fitting, source fetching, software-label editing or trade logic.
Source line numbers and literal prefixes are retained independently of claims.
"""
import hashlib
import json
from pathlib import Path

from active_reference_candidate import replay
from replay import read_rows

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
SOURCE = ROOT / "sources/20251111_user_transcript.txt"
SCREEN = ROOT / "october_reference_membership_20261012.json"
KEYS = ("event", "state", "event_direction", "event_route", "event_ref_start")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    text = SOURCE.read_text()
    lines = text.splitlines()
    screen = json.loads(SCREEN.read_text())
    assert screen["candidate_sha256"] == sha(ROOT / "active_reference_candidate.py")
    specs = [
        ("novel_minute_structure", 3, 4, "90分钟形成了顶部结构", "Author states 90-minute top structure at 11:00; malformed first sentence resolved by following 11:00 sentence", "NEW_EPISODE_SOURCE_ASSERTION_NOT_EXACT_SOFTWARE_REFERENCE"),
        ("near_trend_period_context", 4, 11, "价格到趋势的距离比较近", "Near-trend context makes 60-and-above structures useful in this case; does not alter MACD formation formula", "CONTEXT_RULE_NO_DISTANCE_THRESHOLD"),
        ("reverse_cycle_count", 6, 8, "反向周期数 是24个周期", "24 periods, with author's 90-minute=8 days and 60-minute=6 days examples", "AUTHOR_HEURISTIC_NOT_FIXED_EXPIRY_OR_GUARANTEED_MOVE"),
        ("observed_vs_forecast_periods", 11, 14, "90分钟和日线昨天有钝化 今天形成结构", "Yesterday's four-period usefulness forecast differs from today's observed 90/daily structure and absent 60/120", "DO_NOT_LABEL_FOUR_ACTUAL_STRUCTURES"),
        ("price_pair_ambiguity", 13, 14, "一个是4,018.6 一个是4,018.8", "Two nearby quoted levels differ by 0.2, without sufficient assignment to period or exact historical bar", "NO_NEW_REFERENCE_VALUE_LABEL"),
        ("time_context", 31, 46, "同时出现高点或低点的确定性", "Sensitive time window plus structure narrows a point; large high-point degree remains conditional on trend breach", "EMPIRICAL_CONTEXT_NOT_AUTOMATIC_TIME_THRESHOLD"),
        ("asymmetric_adjustments", 48, 58, "它不是对称性的", "Do not infer correction duration equals preceding uptrend duration", "NO_FIXED_145_DAY_DECLINE"),
        ("separate_expectation_action", 87, 88, "短期我们该防守防守 长期坚决看多", "Long-term outlook does not cancel short-term defensive action", "FORECAST_AND_ACTION_SEPARATE"),
        ("reduction_amount", 89, 95, "今天我们觉得减4成是没问题的", "Four-tenths reduction stated; six-tenths would need stronger cross-period/index/sequence coordination in this context", "NO_UNIVERSAL_WEIGHTS_OR_COORDINATION_SCORE"),
        ("second_structure", 91, 99, "再减两成", "A later second structure could support an extra two-tenths; not every repeat is additive", "CONDITIONAL_NOT_OBSERVED_SECOND_ACTION"),
        ("correction_and_conflicting_position", 118, 121, "钝化消失我们就买回来", "New defensive context has a future buyback upon disappearance; final four-tenths-position wording conflicts with earlier reduction wording", "PERIOD_JOIN_AND_FINAL_HOLDING_UNRESOLVED"),
    ]
    claims = []
    for key, start, end, marker, meaning, status in specs:
        block = "\n".join(lines[start-1:end])
        assert marker in block, (key, start, end)
        claims.append(dict(key=key, lines=[start, end], literal_prefix=lines[start-1].split("秒钟", 1)[0],
                           marker=marker, interpretation=meaning, status=status))
    variants, prefix_checks = [], 0
    names = {"60": "60_20250603_20261009.csv", "90": "90_20250603_20260113.csv",
             "120": "120_20250401_20251111.csv", "daily": "daily_2025.csv"}
    input_hashes = {p: sha(ROOT / "inputs" / name) for p, name in names.items()}
    for gate in (.75, 1., 1.2):
        for policy in ("nearest_qualifying", "strongest_eligible"):
            results = {}
            for period, name in names.items():
                rows = [r for r in read_rows(name) if r["time"][:10] <= "2025-11-11"]
                output = replay(rows, gate, reference_policy=policy)
                selected = [i for i,r in enumerate(rows) if r["time"][:10] in {"2025-11-10", "2025-11-11"}]
                for i in selected:
                    partial = replay(rows[:i+1], gate, reference_policy=policy)[-1]
                    assert all(partial[k] == output[i][k] for k in KEYS)
                    prefix_checks += 1
                results[period] = [output[i] for i in selected]
            prior = next(p for p in screen["followup_screen"] if p["gate_pct"] == gate and p["policy"] == policy)
            assert [e for e in results["90"] if e["event"] != "NONE"] == [
                next(e for e in results["90"] if e["time"] == expected["time"])
                for expected in prior["top_events"]["90"]]
            for expected in prior["top_events"]["90"]:
                actual = next(e for e in results["90"] if e["time"] == expected["time"])
                assert all(actual[k] == v for k,v in expected.items())
            assert not any(e["event"] != "NONE" for e in results["120"])
            variants.append(dict(gate_pct=gate, policy=policy, results=results))
    assert all(v["results"] == variants[0]["results"] for v in variants)
    # Read the already saved historical trend fixture, not a live quote or
    # original-author software measurement; no calculator/config is modified.
    fixture = REPO / "tests/fixtures/quote_trend_channel/000001_sh_daily_input.json"
    expected_path = REPO / "tests/fixtures/quote_trend_channel/000001_sh_daily_expected_v1.json"
    payload, expected = json.loads(fixture.read_text()), json.loads(expected_path.read_text())
    assert sha(fixture) == expected["input_file_sha256"]
    input_row = next(r for r in payload["rows"] if r["trade_date"] == "2025-11-11")
    trend = next(r for r in expected["rows"] if r["trade_date"] == "2025-11-11")
    close = float(input_row["close"])
    margins = {key: dict(close_minus_upper=close-float(trend[key]["upper_raw"]),
                        close_minus_lower=close-float(trend[key]["lower_raw"]),
                        position=trend[key]["position"], state=trend[key]["state"])
               for key in ("short_channel", "long_channel")}
    assert all(v["position"] == "ABOVE" and v["state"] == "UP" for v in margins.values())
    save(ROOT / "sources/20251111_user_transcript_manifest.json", dict(
        received_on="2026-10-12", date="2025-11-11", provider="user async-question reply",
        original_path=None, saved_path=str(SOURCE), sha256=sha(SOURCE), characters=len(text), lines=len(lines),
        capture_method="Manually saved supplied transcript with original prefixes and wording; no independent original-file byte comparison",
        limitations=["Malformed duplicated seconds/minutes prefixes retained; literal locators are not independently verified video timestamps",
                     "No audio or video URL verification", "Historical trading statements are research evidence, not authorization or fills",
                     "Final position wording conflicts with earlier reduction wording; no inferred final holdings"]))
    out = dict(research_date="2026-10-12", status="NEW_LECTURE_COMPARISON_WITH_PRESERVED_NUMERIC_SCREEN_NOT_BLIND_SOFTWARE_VALIDATION",
        source_sha256=sha(SOURCE), prior_screen_sha256=sha(SCREEN), candidate_sha256=sha(ROOT/"active_reference_candidate.py"),
        input_sha256=input_hashes, claims=claims, variants=variants, prefix_checks=prefix_checks,
        software_labels_added=0, source_assertions=[
            dict(period="90", event="STRUCTURE", asserted_time="2025-11-11 11:00:00", candidate_agreement=True),
            dict(period="daily", event="STRUCTURE", asserted_date="2025-11-11", exact_intraday_time_unknown=True, candidate_agreement=True),
            dict(periods=["60","120"], meaning="No corresponding top structure stated today", candidate_has_no_event=True)],
        trend_fixture=dict(input_sha256=sha(fixture), expected_sha256=sha(expected_path), close=close, row=trend, margins=margins,
                           limitation="Saved fixture only; exact author bands and his intended trend unspecified; closeness is not identified by this number"),
        cycle_examples=dict(author_period_count=24, examples={"60":dict(bars_per_day=4, days=6), "90":dict(bars_per_day=3, days=8), "daily":dict(bars_per_day=1, days=24)},
            limitation="90-minute conversion follows the author's three-bars-per-day convention; not continuous 90-minute wall-clock intervals; 120-minute duration is not explicitly supplied; not a hard expiry or tested price forecast"),
        episode_interpretation="October correction cannot be a permanent global clearance suppressing later structure decisions. New 90/daily evidence supports a new defensive context, not reuse of October 90/120 join. New exact AND/OR is not stated.",
        amount_interpretation="Earlier explicit reduce four-tenths is a change, not final holding; final four-tenths-position statement conflicts. Do not assign final holding 40 or60 or fills. Six-tenths remains conditional.",
        pending=["What periods must disappear for this new context's buyback; AND/OR unspecified", "Precise author's reference values and 90-minute source alignment", "Interpretation of final holding statement", "Quantified trend-distance/coordination gates and measured 24-period outcome", "Whether future second structure actually led to another action"])
    save(ROOT / "nov11_lecture_comparison_20261012.json", out)
    print(json.dumps(dict(source_lines=len(lines), source_sha256=sha(SOURCE), located_claims=len(claims), prefix_checks=prefix_checks,
                         all_variants_equal=True, trend_margins=margins, labels_added=0), ensure_ascii=False))


if __name__ == "__main__":
    main()
