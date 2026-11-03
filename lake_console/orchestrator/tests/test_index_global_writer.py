"""Filesystem protocol tests; byte fixtures do not claim Parquet validation.

The independent literal bytes below exercise publication/checkpoint boundaries.
The Raw/Silver integration tests own real schema, SQL and candidate validation.
"""

import json
import os
from pathlib import Path

import pytest

from orchestrator.defs.io.index_global_writer import IndexGlobalPublication
from orchestrator.defs.paths import (
    raw_index_global_path,
    raw_index_global_staging_path,
    silver_index_global_path,
    silver_index_global_staging_path,
)

DAY = "2026-10-04"
EMPTY_RESULT = {"output_row_count": 0, "source_row_count": 0, "promoted": False}
WRITTEN_RESULT = {"output_row_count": 1, "source_row_count": 1, "promoted": True}


@pytest.fixture
def lake(tmp_path: Path) -> Path:
    root = tmp_path / "lake"
    root.mkdir()
    return root


def _publication(
    root: Path,
    operation: str = "run-1",
    *,
    phase: str = "late_empty",
    day: str = DAY,
    silver: bool = False,
) -> IndexGlobalPublication:
    if silver:
        target = silver_index_global_path(root, day)
        directory = silver_index_global_staging_path(root, operation, day).parent
        asset, phase = "silver_index_global", "silver"
        sources = (raw_index_global_path(root, day),)
    else:
        target = raw_index_global_path(root, day)
        directory = raw_index_global_staging_path(root, operation, day, phase).parent
        asset, sources = "raw_index_global", ()
    return IndexGlobalPublication(
        lake_root_path=root,
        target_path=target,
        operation_directory=directory,
        asset_key=asset,
        day=day,
        phase=phase,
        operation_id=operation,
        source_paths=sources,
    )


def _write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def _byte_fixture_validator(path: Path) -> None:
    """No business validation: these protocol tests intentionally use byte files."""


def _freeze(publication: IndexGlobalPublication) -> None:
    publication.freeze_input({"rows": [], "fetch": {"request_count": 1}})


def _fail_after_validation(monkeypatch):
    original = IndexGlobalPublication._save

    def save(self):
        original(self)
        if self.state["status"] == "validated":
            raise OSError("after validated")

    monkeypatch.setattr(IndexGlobalPublication, "_save", save)
    return original


def test_publish_retains_frozen_input_and_reexecution_does_not_replace(lake, monkeypatch):
    data = {"rows": [{"amount": None}], "fetch": {"request_count": 1}}
    with _publication(lake) as publication:
        assert publication.completed() is None
        publication.freeze_input(data)
        assert json.loads(publication.input_path.read_text()) == data
        candidate = publication.new_candidate()
        candidate.write_bytes(b"independent validated output")
        assert publication.publish(candidate, result=WRITTEN_RESULT, validator=_byte_fixture_validator) == WRITTEN_RESULT
        target = publication.target
    assert target.read_bytes() == b"independent validated output"

    def no_replace(*args):
        pytest.fail("a completed operation must not replace anything again")

    monkeypatch.setattr(os, "replace", no_replace)
    with _publication(lake) as publication:
        assert publication.completed() == WRITTEN_RESULT
        assert publication.read_input() == data


def test_empty_source_reuses_existing_zero_row_file_without_changing_identity(lake):
    target = raw_index_global_path(lake, DAY)
    _write(target, b"zero-row parquet supplied by caller")
    before = target.stat()
    with _publication(lake) as publication:
        _freeze(publication)
        assert publication.reuse(result=EMPTY_RESULT) == EMPTY_RESULT
    assert target.stat().st_ino == before.st_ino
    assert target.stat().st_mtime_ns == before.st_mtime_ns
    with _publication(lake) as publication:
        assert publication.completed() == EMPTY_RESULT


def test_new_empty_partition_can_be_published(lake):
    with _publication(lake) as publication:
        _freeze(publication)
        candidate = publication.new_candidate()
        candidate.write_bytes(b"validated zero-row parquet")
        result = {**EMPTY_RESULT, "promoted": True}
        assert publication.publish(candidate, result=result, validator=_byte_fixture_validator) == result
    assert publication.target.read_bytes() == b"validated zero-row parquet"


def test_interrupted_build_keeps_attempt_and_uses_new_candidate(lake):
    target = raw_index_global_path(lake, DAY)
    _write(target, b"previous formal data")
    with pytest.raises(OSError, match="COPY interrupted"), _publication(lake) as publication:
        _freeze(publication)
        partial = publication.new_candidate()
        partial.write_bytes(b"unfinished copy")
        raise OSError("COPY interrupted")
    assert target.read_bytes() == b"previous formal data"
    assert partial.read_bytes() == b"unfinished copy"
    with _publication(lake) as publication:
        assert publication.read_input() == {"rows": [], "fetch": {"request_count": 1}}
        candidate = publication.new_candidate()
        assert candidate != partial
        candidate.write_bytes(b"complete copy")
        publication.publish(candidate, result=WRITTEN_RESULT, validator=_byte_fixture_validator)
    assert partial.exists()
    assert target.read_bytes() == b"complete copy"


def test_validated_candidate_resumes_without_rebuilding(lake, monkeypatch):
    original = _fail_after_validation(monkeypatch)
    with pytest.raises(OSError, match="after validated"), _publication(lake) as publication:
        _freeze(publication)
        candidate = publication.new_candidate()
        candidate.write_bytes(b"fully validated before interruption")
        publication.publish(candidate, result=WRITTEN_RESULT, validator=_byte_fixture_validator)
    assert candidate.exists()
    assert not publication.target.exists()
    monkeypatch.setattr(IndexGlobalPublication, "_save", original)
    with _publication(lake) as publication:
        assert publication.completed() == WRITTEN_RESULT
    assert publication.target.read_bytes() == b"fully validated before interruption"


def test_replace_before_checkpoint_resumes_without_replacing_again(lake, monkeypatch):
    original_save = IndexGlobalPublication._save

    def save(self):
        if self.state["status"] == "promoted":
            raise OSError("after rename before checkpoint")
        original_save(self)

    monkeypatch.setattr(IndexGlobalPublication, "_save", save)
    with pytest.raises(OSError, match="after rename"), _publication(lake) as publication:
        _freeze(publication)
        candidate = publication.new_candidate()
        candidate.write_bytes(b"already renamed")
        publication.publish(candidate, result=WRITTEN_RESULT, validator=_byte_fixture_validator)
    assert not candidate.exists()
    target_identity = publication.target.stat()
    monkeypatch.setattr(IndexGlobalPublication, "_save", original_save)
    original_replace = os.replace
    replacements = []

    def replace(source, target):
        replacements.append((Path(source), Path(target)))
        return original_replace(source, target)

    monkeypatch.setattr(os, "replace", replace)
    with _publication(lake) as publication:
        assert publication.completed() == WRITTEN_RESULT
    assert publication.target.stat().st_ino == target_identity.st_ino
    assert all(source.name != "part-000.parquet" for source, _ in replacements)


def test_candidate_changed_after_validation_stops_and_preserves_files(lake, monkeypatch):
    original = _fail_after_validation(monkeypatch)
    with pytest.raises(OSError), _publication(lake) as publication:
        _freeze(publication)
        candidate = publication.new_candidate()
        candidate.write_bytes(b"validated")
        publication.publish(candidate, result=WRITTEN_RESULT, validator=_byte_fixture_validator)
    candidate.write_bytes(b"changed after validation")
    monkeypatch.setattr(IndexGlobalPublication, "_save", original)
    with _publication(lake) as publication, pytest.raises(ValueError, match="candidate changed"):
        publication.completed()
    assert candidate.read_bytes() == b"changed after validation"
    assert not publication.target.exists()


def test_target_changed_during_build_stops_before_promotion(lake):
    target = raw_index_global_path(lake, DAY)
    _write(target, b"previous formal data")
    with _publication(lake) as publication:
        _freeze(publication)
        candidate = publication.new_candidate()
        candidate.write_bytes(b"candidate")
        target.write_bytes(b"another writer's result")
        with pytest.raises(ValueError, match="target changed"):
            publication.publish(candidate, result=WRITTEN_RESULT, validator=_byte_fixture_validator)
    assert target.read_bytes() == b"another writer's result"
    assert candidate.exists()


def test_validator_returning_with_changed_candidate_cannot_publish(lake):
    target = raw_index_global_path(lake, DAY)
    _write(target, b"previous valid formal data")
    calls = []

    def validator(path):
        calls.append(path)
        assert path.read_bytes() == b"the content that passed validation"
        path.write_bytes(b"different content after successful validation")

    with _publication(lake) as publication:
        _freeze(publication)
        candidate = publication.new_candidate()
        candidate.write_bytes(b"the content that passed validation")
        with pytest.raises(ValueError, match="changed during validation"):
            publication.publish(candidate, result=WRITTEN_RESULT, validator=validator)
    assert calls == [candidate]
    assert target.read_bytes() == b"previous valid formal data"
    assert candidate.read_bytes() == b"different content after successful validation"
    assert json.loads(publication.control.read_text())["status"] == "building"


def test_candidate_changed_while_saving_promoting_is_rejected_before_replace(lake, monkeypatch):
    target = raw_index_global_path(lake, DAY)
    _write(target, b"previous valid formal data")
    original_save = IndexGlobalPublication._save

    def save(self):
        original_save(self)
        if self.state["status"] == "promoting":
            self._candidate().write_bytes(b"changed while the promoting checkpoint was saved")

    monkeypatch.setattr(IndexGlobalPublication, "_save", save)
    with _publication(lake) as publication:
        _freeze(publication)
        candidate = publication.new_candidate()
        candidate.write_bytes(b"validated candidate")
        with pytest.raises(ValueError, match="changed before replacement"):
            publication.publish(
                candidate, result=WRITTEN_RESULT, validator=_byte_fixture_validator
            )
    assert target.read_bytes() == b"previous valid formal data"
    assert candidate.read_bytes() == b"changed while the promoting checkpoint was saved"
    assert json.loads(publication.control.read_text())["status"] == "promoting"


def test_published_target_changed_stops_reexecution(lake):
    with _publication(lake) as publication:
        _freeze(publication)
        candidate = publication.new_candidate()
        candidate.write_bytes(b"validated")
        publication.publish(candidate, result=WRITTEN_RESULT, validator=_byte_fixture_validator)
    publication.target.write_bytes(b"changed later")
    with _publication(lake) as publication, pytest.raises(ValueError, match="target changed"):
        publication.completed()


def test_silver_source_changed_during_build_is_not_published(lake):
    raw = raw_index_global_path(lake, DAY)
    _write(raw, b"original raw source")
    with _publication(lake, silver=True) as publication:
        candidate = publication.new_candidate()
        candidate.write_bytes(b"silver from original raw")
        raw.write_bytes(b"new raw source")
        with pytest.raises(ValueError, match="source changed"):
            publication.publish(candidate, result=WRITTEN_RESULT, validator=_byte_fixture_validator)
    assert candidate.exists()
    assert not publication.target.exists()


def test_silver_source_changed_between_attempts_is_rejected(lake, monkeypatch):
    raw = raw_index_global_path(lake, DAY)
    _write(raw, b"source before validation")
    original = _fail_after_validation(monkeypatch)
    with pytest.raises(OSError), _publication(lake, silver=True) as publication:
        candidate = publication.new_candidate()
        candidate.write_bytes(b"silver candidate")
        publication.publish(candidate, result=WRITTEN_RESULT, validator=_byte_fixture_validator)
    raw.write_bytes(b"different source")
    monkeypatch.setattr(IndexGlobalPublication, "_save", original)
    with pytest.raises(ValueError, match="source changed"), _publication(lake, silver=True):
        pytest.fail("must fail while opening the changed-source operation")
    assert candidate.exists()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonstandard_json_input_is_rejected_before_frozen_file_creation(lake, value):
    with _publication(lake) as publication:
        with pytest.raises(ValueError, match="JSON compliant"):
            publication.freeze_input({"rows": [{"amount": value}]})
        assert not publication.input_path.exists()
        assert publication.read_input() is None


def test_frozen_input_changed_after_commit_is_rejected(lake):
    with _publication(lake) as publication:
        _freeze(publication)
    publication.input_path.write_text('{"rows": [{"amount": 9}]}')
    with pytest.raises(ValueError, match="frozen input changed"), _publication(lake):
        pytest.fail("must not consume a changed frozen input")


def test_full_input_without_operation_confirmation_stops(lake, monkeypatch):
    original_save = IndexGlobalPublication._save

    def save(self):
        if self.state["status"] == "input_ready":
            raise OSError("input renamed before operation checkpoint")
        original_save(self)

    monkeypatch.setattr(IndexGlobalPublication, "_save", save)
    with pytest.raises(OSError), _publication(lake) as publication:
        _freeze(publication)
    assert publication.input_path.exists()
    monkeypatch.setattr(IndexGlobalPublication, "_save", original_save)
    with pytest.raises(ValueError, match="incomplete or unconfirmed"), _publication(lake):
        pytest.fail("unconfirmed complete input must not be guessed safe")


@pytest.mark.parametrize("name", ["phase_rows.json", ".phase_rows.json.partial.tmp"])
def test_orphan_or_partial_frozen_input_stops_without_deletion(lake, name):
    with _publication(lake) as publication:
        pass
    partial = publication.directory / name
    partial.write_text('{"unfinished":')
    with pytest.raises(ValueError, match="incomplete or unconfirmed"), _publication(lake):
        pytest.fail("partial frozen input must never be consumed")
    assert partial.read_text() == '{"unfinished":'


def test_frozen_input_cannot_be_rebound_to_different_data(lake):
    with _publication(lake) as publication:
        _freeze(publication)
        with pytest.raises(ValueError, match="differs from this attempt"):
            publication.freeze_input({"rows": [{"close": 2}]})
        assert publication.read_input() == {"rows": [], "fetch": {"request_count": 1}}


def test_raw_candidate_requires_frozen_input(lake):
    with _publication(lake) as publication, pytest.raises(ValueError, match="frozen input"):
        publication.new_candidate()


def test_target_lock_covers_other_operations_and_phases(lake):
    with (
        _publication(lake),
        pytest.raises(BlockingIOError),
        _publication(lake, "other-operation", phase="asia_1"),
    ):
        pytest.fail("same target across phases must be locked")


def test_distinct_date_does_not_share_target_lock(lake):
    with _publication(lake), _publication(lake, "other-day", day="2026-10-05"):
        pass


def test_new_phase_operation_can_legitimately_replace_previous_result(lake):
    with _publication(lake, "phase-1", phase="asia_1") as publication:
        publication.freeze_input({"rows": [{"close": 1}]})
        candidate = publication.new_candidate()
        candidate.write_bytes(b"first phase")
        publication.publish(candidate, result=WRITTEN_RESULT, validator=_byte_fixture_validator)
    with _publication(lake, "phase-2", phase="americas") as publication:
        publication.freeze_input({"rows": [{"close": 2}]})
        candidate = publication.new_candidate()
        candidate.write_bytes(b"later legitimate market update")
        publication.publish(candidate, result=WRITTEN_RESULT, validator=_byte_fixture_validator)
    assert publication.target.read_bytes() == b"later legitimate market update"


def test_checkpoint_cannot_point_candidate_outside_operation(lake, monkeypatch):
    original = _fail_after_validation(monkeypatch)
    with pytest.raises(OSError), _publication(lake) as publication:
        _freeze(publication)
        candidate = publication.new_candidate()
        candidate.write_bytes(b"validated")
        publication.publish(candidate, result=WRITTEN_RESULT, validator=_byte_fixture_validator)
    state = json.loads(publication.control.read_text())
    state["candidate"] = "../../outside.parquet"
    publication.control.write_text(json.dumps(state))
    monkeypatch.setattr(IndexGlobalPublication, "_save", original)
    with _publication(lake) as publication, pytest.raises(ValueError, match="escaped"):
        publication.completed()
    assert candidate.exists()


def test_checkpoint_scope_change_is_rejected(lake):
    with _publication(lake) as publication:
        _freeze(publication)
    state = json.loads(publication.control.read_text())
    state["scope"]["day"] = "2026-10-05"
    publication.control.write_text(json.dumps(state))
    with pytest.raises(ValueError, match="scope changed"), _publication(lake):
        pytest.fail("must not accept a checkpoint from another date")


def test_methods_require_context_lock(lake):
    publication = _publication(lake)
    with pytest.raises(RuntimeError, match="writer context"):
        publication.completed()


def test_candidate_path_must_be_the_current_attempt(lake):
    with _publication(lake) as publication:
        _freeze(publication)
        publication.new_candidate()
        other = publication.directory / "outside.parquet"
        other.write_bytes(b"not the current attempt")
        with pytest.raises(ValueError, match="current building attempt"):
            publication.publish(other, result=WRITTEN_RESULT, validator=_byte_fixture_validator)
        assert other.exists()
