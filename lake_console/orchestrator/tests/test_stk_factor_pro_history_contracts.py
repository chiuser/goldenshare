"""Literal wire fixtures follow LLD 5.4/16; no database, network or lake I/O."""

from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone

import pytest

from orchestrator.defs.run_contracts import stk_factor_pro as models
from orchestrator.tushare_download.contract_registry import content_digest

T, P, START = date(2026, 10, 16), date(2026, 10, 15), date(2026, 10, 14)
NOW = datetime(2026, 10, 16, 19, 0, tzinfo=timezone(timedelta(hours=8)))
SHA = "a" * 64


def identity(run="run-a"):
    return models.RunIdentity(run, None, T, T, P, "today", 0, None, None)


def contract():
    return models.ContractIdentity("stk_factor_pro", "1", SHA, "1")


def history_range():
    return models.HistoryRange(
        "000001.SZ", True, True, 2.0, 1.0, START, T, (1,), (T,), (), 1, START
    )


def unit():
    return models.UnitProjection(5, "000001.SZ", None, START, T)


def scope():
    # Exact literal projection specified by LLD 5.4.2, independent of helpers.
    return content_digest(
        {
            "record_kind": "stk_factor_pro.scope",
            "record_version": 1,
            "value": {
                "phase": "history",
                "T": "2026-10-16",
                "units": [
                    {
                        "mode": 5,
                        "object_code": "000001.SZ",
                        "point": None,
                        "start_date": "2026-10-14",
                        "end_date": "2026-10-16",
                    }
                ],
            },
        }
    )


def source_file():
    key = models.stk_factor_pro_unit_key(unit())
    return models.SourceFileRecord(
        "history",
        key,
        "native-unit-id",
        0,
        5,
        "000001.SZ",
        None,
        START,
        T,
        3,
        3,
        f"source/history/units/{key}.parquet",
        SHA,
        3,
        models.stk_factor_pro_schema_digest("raw"),
        SHA,
        NOW,
    )


def source_complete():
    return models.SourceCompleteRecord(
        1,
        identity(),
        "history",
        contract(),
        models.RecordRef("run-a", "history-plan.json", SHA),
        SHA,
        1,
        None,
        None,
        SHA,
        scope(),
        (unit(),),
        models.RecordRef("run-a", "source/history/source-files.parquet", SHA),
        SHA,
        1,
        NOW,
    )


def plan():
    return models.HistoryPlanRecord(
        1,
        identity(),
        contract(),
        1,
        NOW,
        SHA,
        SHA,
        models.RecordRef("run-a", "history-ranges.parquet", SHA),
        1,
        models.FactorFileRef(T, "raw_tushare_adj_factor", SHA, 1),
        models.FactorFileRef(P, "raw_tushare_adj_factor", SHA, 1),
        None,
        None,
        None,
        None,
    )


def publication(phase="history"):
    day = P if phase == "history" else T
    return models.StkFactorProPublicationRecord(
        1,
        identity(),
        phase,
        day,
        "raw",
        contract(),
        SHA,
        SHA if phase == "history" else None,
        SHA if phase == "day" else None,
        SHA if phase == "history" else None,
        f"/private/tmp/lake/raw/tushare/stk_factor_pro/trade_date={day}/data.parquet",
        f"candidates/history/{day}/raw/data.parquet"
        if phase == "history"
        else "candidates/day/raw/data.parquet",
        None,
        SHA,
        3,
        SHA,
        "replace",
        "intent",
        models.RecordRef(
            "run-a", f"publication/history/{day}/raw/unrefreshed-keys.parquet", SHA
        )
        if phase == "history"
        else None,
        0 if phase == "history" else None,
        None,
        None,
        None,
    )


def test_unit_key_and_scope_use_literal_projection():
    expected = content_digest(
        {
            "record_kind": "stk_factor_pro.unit",
            "record_version": 1,
            "value": {
                "mode": 5,
                "object_code": "000001.SZ",
                "point": None,
                "start_date": "2026-10-14",
                "end_date": "2026-10-16",
            },
        }
    )
    assert models.stk_factor_pro_unit_key(unit()) == expected
    assert models.stk_factor_pro_scope_digest("history", T, (unit(),)) == scope()
    assert (
        models.stk_factor_pro_unit_key(replace(unit(), object_code="600000.SH"))
        != expected
    )


def test_range_digest_keeps_unknown_null_and_rejects_duplicate():
    unknown = replace(
        history_range(),
        start_date=None,
        end_date=None,
        earliest_basis_kind=None,
        earliest_basis_date=None,
    )
    expected = content_digest(
        {
            "record_kind": "stk_factor_pro.history_ranges",
            "record_version": 1,
            "value": [{"ts_code": "000001.SZ", "start_date": None, "end_date": None}],
        }
    )
    assert models.stk_factor_pro_history_ranges_digest((unknown,)) == expected
    with pytest.raises(ValueError):
        models.stk_factor_pro_history_ranges_digest((unknown, unknown))


def test_plan_and_input_identity_ignore_run_but_track_business_values():
    rows = (history_range(),)
    original = models.stk_factor_pro_history_plan_digest(identity(), contract(), rows)
    assert (
        models.stk_factor_pro_history_plan_digest(identity("run-b"), contract(), rows)
        == original
    )
    changed = (replace(rows[0], t_value=3.0),)
    assert (
        models.stk_factor_pro_history_plan_digest(identity(), contract(), changed)
        != original
    )
    value = models.stk_factor_pro_history_input_digest(
        identity(), contract(), (unit(),), rows
    )
    assert (
        models.stk_factor_pro_history_input_digest(
            identity("run-b"), contract(), (unit(),), rows
        )
        == value
    )
    assert (
        models.stk_factor_pro_history_input_digest(
            identity(), contract(), (unit(),), changed
        )
        != value
    )
    with pytest.raises(ValueError):
        models.stk_factor_pro_history_input_digest(
            identity(),
            contract(),
            (unit(),),
            (replace(rows[0], p_present=False, p_value=None),),
        )


def test_manifest_digest_excludes_path_ordinal_and_observation_time():
    original = source_file()
    first = models.stk_factor_pro_files_manifest_digest(scope(), (original,))
    changed = replace(
        original,
        ordinal=18,
        component_unit_id="another-session-id",
        verified_at=NOW + timedelta(seconds=1),
    )
    assert models.stk_factor_pro_files_manifest_digest(scope(), (changed,)) == first


@pytest.mark.parametrize(
    "factory", [history_range, unit, source_file, source_complete, plan, publication]
)
def test_closed_codec_roundtrip_and_frozen_models(factory):
    record = factory()
    wire = models.stk_factor_pro_record_to_dict(record)
    assert models.parse_stk_factor_pro_record(type(record), wire) == record
    # Mutate an actual declared field; unknown slotted attributes differ across
    # Python releases and do not test the record's frozen field guarantee.
    field_name = next(iter(wire))
    with pytest.raises(FrozenInstanceError):
        setattr(record, field_name, getattr(record, field_name))
    bad = dict(wire, unexpected=True)
    with pytest.raises(ValueError):
        models.parse_stk_factor_pro_record(type(record), bad)
    bad = dict(wire)
    bad.pop(next(iter(bad)))
    with pytest.raises(ValueError):
        models.parse_stk_factor_pro_record(type(record), bad)


@pytest.mark.parametrize(
    "changes",
    [
        {"t_present": False},
        {"t_value": True},
        {"p_value": float("nan")},
        {"plan_reasons": (True,)},
        {"plan_reasons": (7,)},
        {"plan_reasons": (2, 1)},
        {"end_date": START - timedelta(days=1)},
    ],
)
def test_invalid_range_contract_rejected(changes):
    with pytest.raises((ValueError, TypeError)):
        replace(history_range(), **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"record_version": True},
        {"phase": "day"},
        {"completed_unit_count": True},
        {"completed_unit_count": 2},
        {"expected_units": ()},
        {"expected_units": (replace(unit(), end_date=P),)},
        {
            "files_manifest_ref": models.RecordRef(
                "old-run", "source/history/source-files.parquet", SHA
            )
        },
        {"verified_at": NOW.replace(tzinfo=None)},
    ],
)
def test_invalid_source_complete_rejected(changes):
    with pytest.raises((ValueError, TypeError)):
        replace(source_complete(), **changes)


def test_same_unit_key_cannot_authorize_old_run_source():
    with pytest.raises(ValueError):
        models.VerifiedSource(
            identity("new-run"),
            contract(),
            source_complete(),
            models.RecordRef("run-a", "source/history/source-complete.json", SHA),
        )


def test_publication_preserves_day_and_history_exclusion():
    assert publication("day").phase == "day"
    with pytest.raises(ValueError):
        replace(publication("day"), history_input_digest=SHA)
    with pytest.raises(ValueError):
        replace(publication(), day_source_digest=SHA)
    with pytest.raises(ValueError):
        replace(publication(), trade_date=T)
    with pytest.raises(ValueError):
        replace(publication(), unrefreshed_keys_ref=None)


def test_codec_exact_boolean_count_and_canonical_time():
    wire = models.stk_factor_pro_record_to_dict(source_complete())
    assert wire["verified_at"] == "2026-10-16T19:00:00.000000+08:00"
    for bad in (
        dict(wire, completed_unit_count=True),
        dict(wire, verified_at="2026-10-16T19:00:00+08:00"),
    ):
        with pytest.raises(ValueError):
            models.parse_stk_factor_pro_record(models.SourceCompleteRecord, bad)
