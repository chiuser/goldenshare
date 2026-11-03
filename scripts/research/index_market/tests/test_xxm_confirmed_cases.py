"""Three independently confirmed author dates, current r4 fields; no old oracle.

Authority: original screenshots, administrator time correction, LLD P5-17/18.
Only known local CSV prefixes are used, never DB/Lake or a dual-group replay.
"""
from datetime import date
import json
from pathlib import Path
import time

import pytest

from scripts.research.index_market.xxm.acceptance import sha, load_source
from scripts.research.index_market.xxm.daily_window_precheck import validate_window
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.response_projection import event_display_flags

ROOT = Path(__file__).resolve().parents[4]
DAILY = ROOT / "reports/xxm/sources/xxm_reference_rescue_r1_implementation_20261017/daily_2020_source_01"
MINUTES = ROOT / "reports/xxm/sources/xxm_source_audit_20261013_213852"
PINNED_FILES = (
    ('reports/xxm/sources/xxm_reference_rescue_r1_implementation_20261017/daily_2020_source_01/daily_source.csv', '8b0f62ff5a44a2935ce86cada196fd4c566b7c2493d60b9b28ed515d10da2f14'),
    ('reports/xxm/sources/xxm_source_audit_20261013_213852/minute_90_source.csv', '9b1690492e3e8d470addba8bc6a0bed3ccdcb4d76f26fbdc1da668606c955e04'),
    ('reports/xxm/sources/xxm_source_audit_20261013_213852/minute_120_source.csv', 'dcaf1206e6567ee69c4a131f8855bc8fa1e6f963fb0ccf155193d1daa55cdf4b'),
    ('reports/xxm/sources/xxm_software_case_20240311_m120_20261019/sources/20240311_m120.png', '56601dc09920ebc242203308c1a5e5d6f9d5953668727e01b41bfe949ace1d84'),
    ('reports/xxm/observations/xxm_history_replacement_screen_20261019_01/new_image_20230418/review_20261019_01/user_confirmation.json', '09caaa8b68f56ee8cabf2fd65244466dcd6333aba2b4043e7b7ee95df79b8369'),
    ('reports/xxm/sources/xxm_history_replacement_screen_20261019_01/new_image_20230418/review_20261019_01/supplement_20230414/sources/day_20230414.png', '85280879aa3ab33350c8eeee29d14ed805d229f5f3077946d848e2c965b16172'),
    ('reports/xxm/sources/xxm_history_replacement_screen_20261019_01/new_image_20230418/sources/day_20230418.png', 'c3a0103e4b8b8014d7316c304aa1ce86c38f1d76864c5e768874d117ba4ef502'),
    ('reports/xxm/conclusions/xxm_history_lifetime_review_20261020_01/jun12_time_correction_20261020.md', 'df215f61d84c8c97c321124bfbe47c4c12dc2f8e00853dda0fcb39ee52a11d43'),
    ('reports/xxm/sources/xxm_history_lifetime_review_20261020_01/jun12_followup_20261020/sources/20250612_m90.png', '13c438b697ff07849801843fbf05a251690d397aef96dad98880c9e43fd48f57'),
)
MARCH_FACTS = ROOT / "reports/xxm/observations/xxm_software_case_20240311_m120_20261019/transcript_update/evidence.json"


@pytest.mark.parametrize("relative,digest", PINNED_FILES)
def test_case_source_and_observation_bytes_are_unchanged(relative, digest):
    assert sha(ROOT / relative) == digest, relative


def test_march_author_confirmation_is_preserved_after_field_extraction():
    facts = json.loads(MARCH_FACTS.read_text())
    assert facts["userConfirmation"] == {
        "userAnswer": "对着倒数第二根，上午的小阳线",
        "questionContext": "绿色消失第一个字对应倒数第二根3/11上午小阳线，还是最后下午大阳线",
        "softwareGreenEndpoint": "2024-03-11T11:30:00+08:00",
        "timeEvidence": "USER_CONFIRMED_CANDLE_POSITION_ON_SUPPLIED_120_MIN_CHART",
        "authorTranscriptIndependentlyStatesIntradayTime": False,
    }
    assert facts["eventIdentity"] == "OLD_TOP_STRUCTURE_DISAPPEARANCE"
    assert facts["softwareMorningExactDifKnown"] is False
    assert facts["softwareActualReferenceKnown"] is False
    assert facts["uniqueSoftwareFormulaProven"] is False
    assert "workingRuleDecision" not in facts and "priorModelEventTime" not in facts


@pytest.fixture(scope="module")
def case_windows():
    """Single formal engine, original three endpoints, bounded retained windows."""
    started = time.monotonic()
    files = (DAILY/"daily_source.csv", DAILY/"manifest.json", DAILY/"calendar.json",
             MINUTES/"minute_90_source.csv", MINUTES/"minute_120_source.csv", MINUTES/"manifest.json")
    if sum(p.stat().st_size for p in files) > 8*1024*1024:
        raise ValueError("Confirmed-case saved inputs exceed 8MiB")
    windows = {}
    for period, start, end, expected_rows in (
        ("day", "2023-03-07", "2023-04-21", 1643),
        ("m120", "2024-03-06T15:00:00+08:00", "2024-03-11T15:00:00+08:00", 8630),
        ("m90", "2025-06-12T11:00:00+08:00", "2025-06-12T15:00:00+08:00", 12945),
    ):
        source = load_source(DAILY if period == "day" else MINUTES, period)
        assert len(source) == expected_rows
        for bar in source:
            bar.validate(period)
        times = [bar.time for bar in source]
        assert times == sorted(set(times))
        if period == "day":
            manifest = json.loads((DAILY/"manifest.json").read_text())
            calendar_sha = next(v["sha256"] for v in manifest["files"] if v["name"] == "calendar.json")
            assert sha(DAILY/"calendar.json") == calendar_sha
            calendar = json.loads((DAILY/"calendar.json").read_text())
            assert len(calendar) == manifest["calendarRows"] == 2571
            assert manifest["rows"] == expected_rows
            validate_window(source, calendar, date.fromisoformat(manifest["businessDate"]))
        calc = XxmCalculator(period=period, source_identity="confirmed-cases-20261020")
        steps, bars, processed = {}, {}, 0
        for bar in source:
            if bar.time > end:
                break
            if time.monotonic()-started >= 60:
                raise TimeoutError("Confirmed-case prefixes exceeded 60 seconds")
            step = calc.step(bar)
            processed += 1
            if bar.time >= start:
                steps[bar.time], bars[bar.time] = step, bar
        assert max(steps) == end, (period, "case endpoint missing")
        windows[period] = steps, bars
        print(f"\n{period}: source={len(source)}, replayed={processed}, kept={len(steps)}")
    if time.monotonic()-started >= 60:
        raise TimeoutError("Confirmed-case final checks exceeded 60 seconds")
    return windows


def test_march11_m120_green_is_at_1130_even_while_local_dif_falls(case_windows):
    steps, bars = case_windows["m120"]
    confirmed = steps["2024-03-06T15:00:00+08:00"]
    structure, = [e for e in confirmed.events if e["direction"] == "TOP" and e["type"] == "STRUCTURE"]
    structure_id = structure["relatedStructureId"]
    record, = [r for r in confirmed.structures if r["id"] == structure_id]
    assert record["priceExtreme"] == 3051.3457  # Saved local anchor, not a software readout.
    morning = "2024-03-11T11:30:00+08:00"
    assert bars[morning].close == 3052.2827 > record["priceExtreme"]
    assert bars[morning].dif < bars["2024-03-08T15:00:00+08:00"].dif
    green, = [e for e in steps[morning].events if e["type"] == "CANCEL"
              and e["route"] == "structure_price_break" and e["relatedStructureId"] == structure_id]
    assert (green["time"], green["direction"]) == (morning, "TOP")
    assert event_display_flags(steps[morning].events)[green["id"]] is True
    assert not any(e["type"] == "CANCEL" and e["relatedStructureId"] == structure_id
                   for e in steps["2024-03-11T15:00:00+08:00"].events)


def test_april_dull_and_no_visible_old_green_followed_by_a_new_structure(case_windows):
    steps, bars = case_windows["day"]
    structure, = [e for e in steps["2023-03-07"].events if e["direction"] == "TOP" and e["type"] == "STRUCTURE"]
    old_id = structure["relatedStructureId"]
    old, = [r for r in steps["2023-03-07"].structures if r["id"] == old_id]
    assert (old["priceExtreme"], old["originalReference"]["dif"]) == (3328.3927, 41.186)
    assert any(e["direction"] == "TOP" and e["type"] == "DULL" for e in steps["2023-04-14"].events)
    assert bars["2023-04-17"].close == 3385.6095 > old["priceExtreme"]
    assert bars["2023-04-17"].dif == 22.553 < old["originalReference"]["dif"]
    for day in ("2023-04-17", "2023-04-18"):
        flags = event_display_flags(steps[day].events)
        assert not any(e["type"] == "CANCEL" and e["relatedStructureId"] == old_id and flags[e["id"]]
                       for e in steps[day].events)
    new, = [e for e in steps["2023-04-21"].events if e["direction"] == "TOP" and e["type"] == "STRUCTURE"]
    assert new["relatedStructureId"] != old_id


def test_june12_m90_structure_is_at_final_confirmed_1400_not_1500(case_windows):
    steps, bars = case_windows["m90"]
    when = "2025-06-12T14:00:00+08:00"
    assert bars[when].close == 3401.2473
    structure, = [e for e in steps[when].events if e["direction"] == "TOP" and e["type"] == "STRUCTURE"]
    assert structure["time"] == when
    record, = [r for r in steps[when].structures if r["id"] == structure["relatedStructureId"]]
    assert record["formedAt"] == when
    assert not any(e["direction"] == "TOP" and e["type"] == "STRUCTURE"
                   for e in steps["2025-06-12T15:00:00+08:00"].events)
