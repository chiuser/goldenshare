"""Compare a supplied lecture with saved, previously frozen daily predictions.

This is a historical diagnostic. It does not recalculate or change production
indicators, score original software labels, or simulate filled trades.
"""
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "sources/20260626_user_transcript.txt"
PREDICTIONS = ROOT / "post_june9_predictions_20261012.json"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    raw = SOURCE.read_text()
    lines = raw.splitlines()
    assert lines[0] == "大家好今天是2026年的6月26号"
    assert lines[-1] == "咱们下周再见"
    prediction = json.loads(PREDICTIONS.read_text())
    assert sha(PREDICTIONS) == "24023ccc46498d43f8ac7a0b63c24b8f77f1a677f6f2f48ecd1ea154bbe8fac9"
    assert sha(ROOT / "active_reference_candidate.py") == prediction["candidate_sha256"]
    correction = json.loads((ROOT / "correction_definitions_20261012.json").read_text())
    assert correction["source_sha256"] == sha(PREDICTIONS)
    rows = [r for r in prediction["trend"]["rows"] if "2026-06-15" <= r["date"] <= "2026-06-26"]
    assert len(rows) == 9
    june26 = next(r for r in rows if r["date"] == "2026-06-26")
    assert june26 == correction["trend_correction_alternatives"]["first_below_lower"]["row"]
    june18 = next(r for r in rows if r["date"] == "2026-06-18")
    assert june18 == correction["trend_correction_alternatives"]["return_under_upper_not_down"]["row"]

    specs = [
        ("short_preclose", 5, 9, "已经确定跌穿短期趋势", "14:50 已确定短期，长期未确定；应减四成。", "EXPLICIT_EPISODE_PLAN_NOT_FILL"),
        ("long_close", 10, 18, "这个通道的下轨", "收盘长期也破下轨，下一周一早盘再减两成。", "EXPLICIT_EDGE_CONTEXT_NOT_EXACT_SOFTWARE_VALUE"),
        ("core_position", 63, 64, "4成仓底仓嘛", "明确四成底仓；上一行转写混乱，不据此新增其他数量。", "EXPLICIT_EPISODE_HOLDING_FLOOR_NOT_UNIVERSAL"),
        ("other_object_top", 67, 76, "如果要是创业板的话", "创业板上一日钝化加9是另一信号对象的条件性减仓说明。", "OBJECT_SPECIFIC_NOT_SSE_LABEL"),
        ("ambiguous_bottom_object", 84, 99, "中微指数今天跌幅也很大", "出现90/120底钝化的指数名称转写不清；3959为作者观察价位。", "UNRESOLVED_OBJECT_NO_NEW_LABEL_OR_NUMERIC_ANCHOR"),
        ("chart_identity", 154, 162, "一个是都是上证指数啊", "作者称展示两张均为上证日线，近期与远期。", "CHART_DESCRIPTION_NOT_SCREENSHOT_OBSERVATION"),
        ("forecast_override", 212, 224, "昨天我认为今天大概率不会破趋势", "前一日预测不破，实际双破仍按事实处理。", "REALIZED_TRIGGER_OVERRIDES_QUALITATIVE_FORECAST_IN_EPISODE"),
        ("independent_exit", 225, 240, "上证指数破趋势也是要减仓", "日线结构按收盘；上证破趋势本身提供减仓依据，钝化加9非上证。", "PARALLEL_RATIONALES_NOT_ADDITIVE_TRADE_AMOUNTS"),
        ("context_not_fill", 330, 336, "如果后面有上升突破趋势", "防守针对未来风险；以后重新突破再恢复，未给期限。", "CONDITIONAL_FUTURE_PATH_NOT_CURRENT_EVENT"),
    ]
    claims = []
    for ident, start, end, marker, finding, status in specs:
        excerpt = "\n".join(lines[start-1:end])
        assert marker in excerpt, (ident, start, end)
        claims.append(dict(id=ident, lines=[start, end], locator=marker,
                           finding=finding, status=status))

    comparisons = []
    position_checks = 0
    for name in ("short_channel", "long_channel"):
        events = {"return_below_upper": [], "cross_below_lower": []}
        for prev, row in zip(rows, rows[1:]):
            channel = row[name]
            expected_position = "ABOVE" if row["close"] > channel["upper"] else "BELOW" if row["close"] < channel["lower"] else "INSIDE"
            assert expected_position == channel["position"]
            position_checks += 1
            if prev[name]["position"] == "ABOVE" and channel["position"] != "ABOVE":
                events["return_below_upper"].append(row["date"])
            if prev[name]["position"] != "BELOW" and channel["position"] == "BELOW":
                events["cross_below_lower"].append(row["date"])
        comparisons.append(dict(channel=name, **events))
    assert comparisons[0]["return_below_upper"] == ["2026-06-18", "2026-06-26"]
    assert comparisons[0]["cross_below_lower"] == ["2026-06-26"]
    assert comparisons[1]["return_below_upper"] == ["2026-06-26"]
    assert comparisons[1]["cross_below_lower"] == ["2026-06-26"]

    margins = {name: dict(**june26[name], lower_minus_close=june26[name]["lower"]-june26["close"])
               for name in ("short_channel", "long_channel")}
    source_manifest = dict(received_on="2026-10-12", date="2026-06-26", provider="user inline pasted transcript",
        original_path=None, original_locator="Current conversation user message beginning 文字稿如下; no attached text file",
        capture_method="Manually saved supplied text with line breaks; no independent original-file byte comparison possible",
        saved_path=str(SOURCE), sha256=sha(SOURCE), characters=len(raw), lines=len(lines),
        video_identity="Date confirmed by user and text; no video URL or audio independently verified",
        limitations=["Raw wording retained including transcription errors", "Line numbers locate supplied text, not video timestamps",
                     "Lecture instructions are evidence, not authorization to trade", "No software terminal value or bar label added"])
    save(ROOT / "sources/20260626_user_transcript_manifest.json", source_manifest)
    monday = date(2026, 6, 26) + timedelta(days=3)
    assert monday.weekday() == 0
    out = dict(research_date="2026-10-12", source=str(SOURCE), source_sha256=sha(SOURCE),
        prediction_file=str(PREDICTIONS), prediction_sha256=sha(PREDICTIONS),
        correction_definition_sha256=sha(ROOT / "correction_definitions_20261012.json"),
        method="Previously frozen numerical paths compared with now-known user lecture; June28 blog context already known; not blind market prediction or original software scoring",
        claims=claims, trend_rows=rows, june26_close=june26["close"], june26_bands=margins,
        execution_plan=[dict(signal_date="2026-06-26", knowledge_time="14:50 as stated by author", signal="short trend breach determined", stated_reduction_percentage_points=40, execution="June26 late session", filled_trade=False),
                        dict(signal_date="2026-06-26", knowledge_time="after final close", signal="long trend breach also confirmed", stated_reduction_percentage_points=20, execution=f"{monday.isoformat()} early session per lecture", filled_trade=False)],
        size_comparison=dict(june15=dict(long_add_points=20, short_add_points=40), june26=dict(short_reduce_points=40, long_reduce_points=20),
            support="Repeated channel-specific 20/40 stated plans are symmetric in this episode", not_proven="Universal allocation, full holdings path, actual fills, repeated-signal deduplication or overlap priority"),
        candidate_policy_transitions=comparisons,
        discrimination=dict(june26="Both upper-return and lower-breach alternatives trigger here; lecture supports lower-edge explanation but does not falsify a separate earlier upper-return rule",
                            june18="Only short upper-return alternative triggers; short remains INSIDE/UP. If June18 reduced and June22 restored, June26 could still start fully allocated; do not infer no earlier action from current size alone",
                            next_source="2026-06-18 closing lecture; specifically whether short INSIDE causes reduction, otherwise waiting for lower breach"),
        resolved_questions=["Long-trend downside explanation explicitly points at channel lower edge", "Separate channel amounts and closing/next-morning scheduling repeated in actual breach episode", "Trend exit does not require additional other-index top structure in this episode"],
        unresolved_questions=["June18 actual handling while short INSIDE/UP", "Exact original software daily boundaries and intraday determination", "All positions, actual fills and expiry of following-morning pending actions", "Universal trend/structure overlap priority, cap and deduplication", "Ambiguous name of index with minute bottom dulling; no same-object opposing-signal test", "Original structure post-confirmation reference retirement rules"],
        validations=dict(source_locator_checks=len(claims), saved_daily_position_checks=position_checks, software_labels_added=0),
        evidence_counts=dict(mcp_transcripts=13, user_transcripts=6, unique_transcript_dates=18, screenshots=37, software_terminal_values=21, conditional_software_labels=52, new_software_labels=0))
    save(ROOT / "june26_lecture_comparison_20261012.json", out)
    print(json.dumps(dict(source_lines=len(lines), source_sha256=sha(SOURCE), validations=out["validations"],
                          lower_margins={k:v["lower_minus_close"] for k,v in margins.items()}), ensure_ascii=False))


if __name__ == "__main__":
    main()
