"""Publication byte/identity boundaries, with all files under pytest's tmp_path.

Literal byte files exercise publication, not QFQ/MACD Parquet business validation.
The existing staging-publication suite exercises the real business writers.
The frozen input is produced by real in-memory DuckDB; no configured connection,
formal Lake, instance, database service or network is used here.
"""

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.io import stk_mins_qfq_publication as module

DAY = "2026-10-22"
PAYLOADS = (b"literal annual replacement one", b"literal annual replacement two")


def _publication(root, *, family="qfq"):
    return module.StkMinsQfqPublication(
        lake_root=root, family=family, freq=5,
        trade_dates=(DAY,), publication_id="same-operation",
    )


def _targets(root):
    return tuple(root / "gold" / f"file-{index}.parquet" for index in range(2))


def _seed_formal(targets):
    for index, target in enumerate(targets):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f"old annual content {index}".encode())


def _bind(publication, connection, targets, *, value=1):
    publication.bind(
        connection, inputs={"rows": f"SELECT {value} AS id"}, targets=targets,
    )


def _build(publication, targets):
    candidates = []
    for target, payload in zip(targets, PAYLOADS, strict=True):
        candidate, reused = publication.candidate(target)
        assert reused is None
        candidate.write_bytes(payload)
        publication.validated(target, candidate, 1)
        candidates.append(candidate)
    return tuple(candidates)


def _receipt(publication, target):
    return json.loads(publication._receipt_path(target).read_text())


def _set_receipt(publication, target, receipt):
    publication._receipt_path(target).write_text(json.dumps(receipt))


@pytest.fixture
def digest_reads(monkeypatch):
    """Count bytes actually returned by Python's SHA input streams, plus paths."""
    calls = []
    byte_counts = Counter()
    original_digest = module._digest
    original_open = Path.open

    class TrackedReader:
        def __init__(self, path, stream):
            self.path = path
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def read(self, size=-1):
            result = self.stream.read(size)
            byte_counts[self.path] += len(result)
            return result

        def __getattr__(self, name):
            return getattr(self.stream, name)

    def open_file(path, mode="r", *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        return TrackedReader(path, stream) if mode == "rb" else stream

    def digest(path, **kwargs):
        calls.append(path)
        return original_digest(path, **kwargs)

    monkeypatch.setattr(Path, "open", open_file)
    monkeypatch.setattr(module, "_digest", digest)
    return calls, byte_counts


@pytest.mark.parametrize("family", ["qfq", "macd_kdj"])
def test_normal_hashes_each_candidate_once_and_never_reads_formal_bytes(
    tmp_path, digest_reads, family,
):
    root = tmp_path / "lake"
    targets = _targets(root)
    _seed_formal(targets)
    with _publication(root, family=family) as publication, duckdb.connect() as connection:
        _bind(publication, connection, targets)
        candidates = _build(publication, targets)
        publication.promote()
        # Rechecking in the same lock lifetime reuses the bound byte evidence.
        publication.promote()
    calls, byte_counts = digest_reads
    assert [path for path in calls if "candidates" in path.parts] == list(candidates)
    assert not any(path in targets for path in calls)
    assert [byte_counts[path] for path in candidates] == list(map(len, PAYLOADS))
    assert not any(byte_counts[path] for path in targets)
    frozen = [path for path in calls if "attempts" in path.parts]
    assert len(frozen) == 1 and byte_counts[frozen[0]] > 0
    assert set(_receipt(publication, targets[0])) == {
        "status", "target", "candidate", "before", "sha256", "row_count",
        "candidate_identity",
    }


def test_digest_optional_callback_counts_actual_chunks_and_default_still_works(tmp_path):
    path = tmp_path / "digest-input.bin"
    path.write_bytes(b"abc")
    expected = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert module._digest(path) == expected
    reads = []
    assert module._digest(path, on_read=reads.append) == expected
    assert reads == [3]


@pytest.mark.parametrize("resume", [False, True])
def test_progress_separates_stat_budgets_from_actual_digest_bytes(
    tmp_path, monkeypatch, digest_reads, resume,
):
    root = tmp_path / "lake"
    targets = _targets(root)
    _seed_formal(targets)
    if resume:
        with _publication(root) as publication, duckdb.connect() as connection:
            _bind(publication, connection, targets)
            _build(publication, targets)
            publication.promote()
    events = []
    monkeypatch.setattr(module.LOGGER, "stdout", lambda event, **fields: events.append(fields))
    with _publication(root) as publication, duckdb.connect() as connection:
        _bind(publication, connection, targets)
        frozen = next((publication.directory / "attempts").glob("*/*.parquet"))
        input_size = frozen.stat().st_size
        if resume:
            for target in targets:
                publication.candidate(target)
        else:
            _build(publication, targets)
        publication._progress("before_promotion", force=True)
        before = events[-1]
        publication.promote()
    total = len(PAYLOADS[0]) + len(PAYLOADS[1])
    assert before["existing_build_target_stat_bytes"] == (
        0 if resume else len(b"old annual content 0") + len(b"old annual content 1")
    )
    assert before["frozen_input_stat_bytes"] == input_size
    assert before["verified_candidate_stat_bytes"] == (0 if resume else total)
    assert before["verified_formal_stat_bytes"] == (total if resume else 0)
    assert before["input_sha256_read_bytes"] == input_size
    assert before["candidate_sha256_read_bytes"] == (0 if resume else total)
    assert before["formal_sha256_read_bytes"] == (total if resume else 0)
    completed = events[-1]
    assert completed["stage"] == "completed"
    assert completed["verified_candidate_stat_bytes"] == 0
    assert completed["verified_formal_stat_bytes"] == total
    for name in ("input_sha256_read_bytes", "candidate_sha256_read_bytes", "formal_sha256_read_bytes"):
        assert completed[name] == before[name]


@pytest.mark.parametrize("phase", ["validated", "promoting_before", "promoting_after", "promoted"])
@pytest.mark.parametrize("family", ["qfq", "macd_kdj"])
def test_resume_hashes_only_each_selected_file_once(
    tmp_path, digest_reads, phase, family,
):
    root = tmp_path / "lake"
    targets = _targets(root)
    _seed_formal(targets)
    with _publication(root, family=family) as publication, duckdb.connect() as connection:
        _bind(publication, connection, targets)
        candidates = _build(publication, targets)
        if phase.startswith("promoting"):
            for target, candidate in zip(targets, candidates, strict=True):
                receipt = _receipt(publication, target)
                receipt["status"] = "promoting"
                _set_receipt(publication, target, receipt)
                if phase == "promoting_after":
                    os.replace(candidate, target)
        elif phase == "promoted":
            publication.promote()
    calls, byte_counts = digest_reads
    calls.clear()
    byte_counts.clear()
    with _publication(root, family=family) as publication, duckdb.connect() as connection:
        _bind(publication, connection, targets)
        for target in targets:
            assert publication.candidate(target) == (None, 1)
            assert publication.candidate(target) == (None, 1)
        publication.promote()
        publication.promote()
    selected = targets if phase in {"promoted", "promoting_after"} else candidates
    assert [path for path in calls if "attempts" not in path.parts] == list(selected)
    assert [byte_counts[path] for path in selected] == list(map(len, PAYLOADS))


def test_digest_rejects_change_during_hash_even_if_payload_is_restored(tmp_path, monkeypatch):
    root = tmp_path / "lake"
    target = _targets(root)[0]
    original = module._digest
    with _publication(root) as publication, duckdb.connect() as connection:
        _bind(publication, connection, (target,))
        candidate, _ = publication.candidate(target)
        candidate.write_bytes(PAYLOADS[0])

        def changed(path, **kwargs):
            value = original(path, **kwargs)
            before = path.stat()
            path.write_bytes(PAYLOADS[0])
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000))
            return value

        monkeypatch.setattr(module, "_digest", changed)
        with pytest.raises(ValueError, match="identity changed during digest"):
            publication.validated(target, candidate, 1)
        assert not target.exists()
        assert _receipt(publication, target)["status"] == "building"


def test_last_candidate_conflict_is_found_before_first_promotion(tmp_path):
    root = tmp_path / "lake"
    targets = _targets(root)
    with _publication(root) as publication, duckdb.connect() as connection:
        _bind(publication, connection, targets)
        candidates = _build(publication, targets)
        candidates[-1].write_bytes(b"damaged final candidate")
        with pytest.raises(ValueError, match="candidate changed"):
            publication.promote()
        assert not any(path.exists() for path in targets)


def test_same_bytes_replacement_before_resume_digest_cannot_pass_batch_preflight(
    tmp_path, monkeypatch,
):
    root = tmp_path / "lake"
    targets = _targets(root)
    with _publication(root) as publication, duckdb.connect() as connection:
        _bind(publication, connection, targets)
        candidates = _build(publication, targets)
    with _publication(root) as publication, duckdb.connect() as connection:
        _bind(publication, connection, targets)
        original = publication._stable_digest

        def replaced(path):
            if path == candidates[-1]:
                replacement = path.with_name("same-bytes.parquet")
                replacement.write_bytes(PAYLOADS[-1])
                os.replace(replacement, path)
            return original(path)

        monkeypatch.setattr(publication, "_stable_digest", replaced)
        with pytest.raises(ValueError, match="candidate identity changed"):
            publication.promote()
        assert not any(path.exists() for path in targets)


def test_build_receipt_cannot_change_before_validation(tmp_path, digest_reads):
    root = tmp_path / "lake"
    target = _targets(root)[0]
    with _publication(root) as publication, duckdb.connect() as connection:
        _bind(publication, connection, (target,))
        candidate, _ = publication.candidate(target)
        candidate.write_bytes(PAYLOADS[0])
        receipt = _receipt(publication, target)
        receipt["before"] = [1, 2, 3, 4, 5]
        _set_receipt(publication, target, receipt)
        before = list(digest_reads[0])
        with pytest.raises(ValueError, match="receipt changed"):
            publication.validated(target, candidate, 1)
        assert digest_reads[0] == before


def test_receipt_change_during_resume_digest_stops_batch_preflight(tmp_path, monkeypatch):
    root = tmp_path / "lake"
    targets = _targets(root)
    with _publication(root) as publication, duckdb.connect() as connection:
        _bind(publication, connection, targets)
        candidates = _build(publication, targets)
    original = module._digest
    with _publication(root) as publication, duckdb.connect() as connection:
        _bind(publication, connection, targets)

        def changed(path, **kwargs):
            result = original(path, **kwargs)
            if path == candidates[-1]:
                receipt = _receipt(publication, targets[-1])
                receipt["row_count"] = 99
                _set_receipt(publication, targets[-1], receipt)
            return result

        monkeypatch.setattr(module, "_digest", changed)
        with pytest.raises(ValueError, match="receipt changed during digest"):
            publication.promote()
        assert not any(path.exists() for path in targets)


@pytest.mark.parametrize("field", ["sha256", "row_count", "candidate_identity", "before", "status"])
def test_verified_receipt_changes_cannot_borrow_prior_digest(
    tmp_path, digest_reads, field,
):
    root = tmp_path / "lake"
    targets = _targets(root)
    with _publication(root) as publication, duckdb.connect() as connection:
        _bind(publication, connection, targets)
        _build(publication, targets)
        receipt = _receipt(publication, targets[-1])
        receipt[field] = {
            "sha256": "0" * 64, "row_count": 99,
            "candidate_identity": [1, 2, 3, 4, 5],
            "before": [1, 2, 3, 4, 5], "status": "promoted",
        }[field]
        _set_receipt(publication, targets[-1], receipt)
        before = list(digest_reads[0])
        with pytest.raises(ValueError):
            publication.promote()
        assert digest_reads[0] == before
        assert not any(path.exists() for path in targets)


@pytest.mark.parametrize("phase", ["validated", "promoted"])
@pytest.mark.parametrize("entry", ["candidate", "promote"])
@pytest.mark.parametrize("field", ["row_count", "status", "before", "sha256", "candidate_identity"])
def test_bind_receipt_changes_cannot_become_first_verification_baseline(
    tmp_path, digest_reads, phase, entry, field,
):
    root = tmp_path / "lake"
    targets = _targets(root)
    _seed_formal(targets)
    with _publication(root) as publication, duckdb.connect() as connection:
        _bind(publication, connection, targets)
        _build(publication, targets)
        if phase == "promoted":
            publication.promote()
    first_before = targets[0].read_bytes()
    with _publication(root) as publication, duckdb.connect() as connection:
        _bind(publication, connection, targets)
        calls, byte_counts = digest_reads
        calls.clear()
        byte_counts.clear()
        receipt = _receipt(publication, targets[-1])
        receipt[field] = {
            "row_count": 99,
            "status": "promoted" if phase == "validated" else "validated",
            "before": None,
            "sha256": "0" * 64,
            "candidate_identity": [1, 2, 3, 4, 5],
        }[field]
        _set_receipt(publication, targets[-1], receipt)
        with pytest.raises(ValueError, match="receipt changed after operation binding"):
            if entry == "candidate":
                publication.candidate(targets[-1])
            else:
                publication.promote()
        assert calls == [] and not any(byte_counts.values())
        assert targets[0].read_bytes() == first_before


@pytest.mark.parametrize("damage", ["json", "sha256", "row_count", "before", "candidate_identity", "candidate", "status"])
def test_malformed_receipt_stops_before_any_promotion(tmp_path, damage):
    root = tmp_path / "lake"
    targets = _targets(root)
    with _publication(root) as publication, duckdb.connect() as connection:
        _bind(publication, connection, targets)
        _build(publication, targets)
        receipt = _receipt(publication, targets[-1])
        if damage == "json":
            publication._receipt_path(targets[-1]).write_text("{")
        else:
            receipt[damage] = {
                "sha256": "bad", "row_count": True, "before": [],
                "candidate_identity": None,
                "candidate": str(tmp_path / "outside.parquet"), "status": [],
            }[damage]
            _set_receipt(publication, targets[-1], receipt)
        with pytest.raises(ValueError):
            publication.promote()
        assert not any(path.exists() for path in targets)


@pytest.mark.parametrize("component", range(4))
def test_post_replace_stable_identity_changes_are_rejected(tmp_path, monkeypatch, component):
    root = tmp_path / "lake"
    target = _targets(root)[0]
    original = module._identity
    with _publication(root) as publication, duckdb.connect() as connection:
        _bind(publication, connection, (target,))
        candidate, _ = publication.candidate(target)
        candidate.write_bytes(PAYLOADS[0])
        publication.validated(target, candidate, 1)

        def identity(path):
            result = original(path)
            if path == target and result is not None:
                result[component] += 1
            return result

        monkeypatch.setattr(module, "_identity", identity)
        with pytest.raises(ValueError, match="published file identity mismatch"):
            publication.promote()
        assert _receipt(publication, target)["status"] == "promoting"


def test_post_replace_ctime_change_is_allowed_and_remembered(tmp_path, monkeypatch, digest_reads):
    root = tmp_path / "lake"
    target = _targets(root)[0]
    original = module._identity
    with _publication(root) as publication, duckdb.connect() as connection:
        _bind(publication, connection, (target,))
        candidate, _ = publication.candidate(target)
        candidate.write_bytes(PAYLOADS[0])
        publication.validated(target, candidate, 1)

        def identity(path):
            result = original(path)
            if path == target and result is not None:
                result[4] += 1_000_000
            return result

        monkeypatch.setattr(module, "_identity", identity)
        publication.promote()
        publication.promote()
        assert publication.verified_files[target]["identity"] == identity(target)
        assert target not in digest_reads[0]


@pytest.mark.parametrize("conflict", ["both_changed", "both_missing", "different_inode"])
def test_promoting_ambiguous_paths_stop_without_trying_hashes(tmp_path, monkeypatch, conflict):
    root = tmp_path / "lake"
    target = _targets(root)[0]
    with _publication(root) as publication, duckdb.connect() as connection:
        _bind(publication, connection, (target,))
        candidate, _ = publication.candidate(target)
        candidate.write_bytes(PAYLOADS[0])
        publication.validated(target, candidate, 1)
        receipt = _receipt(publication, target)
        receipt["status"] = "promoting"
        _set_receipt(publication, target, receipt)
        if conflict == "both_changed":
            target.write_bytes(b"unrelated target")
        else:
            candidate.unlink()
            if conflict == "different_inode":
                target.write_bytes(PAYLOADS[0])
    original = module._digest
    annual_hashes = []

    def digest(path, **kwargs):
        if "attempts" not in path.parts:
            annual_hashes.append(path)
        return original(path, **kwargs)

    monkeypatch.setattr(module, "_digest", digest)
    with _publication(root) as publication, duckdb.connect() as connection:
        _bind(publication, connection, (target,))
        with pytest.raises(ValueError, match="promoting paths conflict"):
            publication.candidate(target)
    assert annual_hashes == []


def test_resume_inputs_changed_stops_before_annual_hash(tmp_path, monkeypatch):
    root = tmp_path / "lake"
    targets = _targets(root)
    with _publication(root) as publication, duckdb.connect() as connection:
        _bind(publication, connection, targets)
        _build(publication, targets)
    original = module._digest
    calls = []

    def digest(path, **kwargs):
        calls.append(path)
        return original(path, **kwargs)

    monkeypatch.setattr(module, "_digest", digest)
    with (
        _publication(root) as publication,
        duckdb.connect() as connection,
        pytest.raises(ValueError, match="inputs or targets changed"),
    ):
        _bind(publication, connection, targets, value=2)
    assert all("attempts" in path.parts for path in calls)
    assert not any(target.exists() for target in targets)


@pytest.mark.parametrize("all_receipts", [False, True])
def test_missing_completed_receipts_block_resume(tmp_path, all_receipts):
    root = tmp_path / "lake"
    targets = _targets(root)
    with _publication(root) as publication, duckdb.connect() as connection:
        _bind(publication, connection, targets)
        _build(publication, targets)
        publication.promote()
        removed = targets if all_receipts else targets[:1]
        for target in removed:
            publication._receipt_path(target).unlink()
    with (
        _publication(root) as publication,
        duckdb.connect() as connection,
        pytest.raises(ValueError, match="receipt missing"),
    ):
        _bind(publication, connection, targets)


def test_build_interruption_can_continue_unstarted_suffix(tmp_path):
    root = tmp_path / "lake"
    targets = _targets(root)
    with _publication(root) as publication, duckdb.connect() as connection:
        _bind(publication, connection, targets)
        candidate, _ = publication.candidate(targets[0])
        candidate.write_bytes(PAYLOADS[0])
        publication.validated(targets[0], candidate, 1)
    with _publication(root) as publication, duckdb.connect() as connection:
        _bind(publication, connection, targets)
        assert publication.candidate(targets[0]) == (None, 1)
        candidate, _ = publication.candidate(targets[1])
        candidate.write_bytes(PAYLOADS[1])
        publication.validated(targets[1], candidate, 1)
        publication.promote()
    assert [target.read_bytes() for target in targets] == list(PAYLOADS)


def test_building_candidate_is_preserved_and_rebuild_hashes_only_new_files(
    tmp_path, digest_reads,
):
    root = tmp_path / "lake"
    targets = _targets(root)
    _seed_formal(targets)
    with _publication(root) as publication, duckdb.connect() as connection:
        _bind(publication, connection, targets)
        failed, _ = publication.candidate(targets[0])
        failed.write_bytes(b"unfinished candidate")
    calls, byte_counts = digest_reads
    calls.clear()
    byte_counts.clear()
    with _publication(root) as publication, duckdb.connect() as connection:
        _bind(publication, connection, targets)
        candidates = _build(publication, targets)
        publication.promote()
    assert [path for path in calls if "attempts" not in path.parts] == list(candidates)
    assert [byte_counts[path] for path in candidates] == list(map(len, PAYLOADS))
    assert failed.is_file() and byte_counts[failed] == 0
    assert not any(byte_counts[path] for path in targets)


def test_missing_verified_receipt_blocks_current_process(tmp_path):
    root = tmp_path / "lake"
    targets = _targets(root)
    with _publication(root) as publication, duckdb.connect() as connection:
        _bind(publication, connection, targets)
        _build(publication, targets)
        publication._receipt_path(targets[0]).unlink()
        with pytest.raises(ValueError, match="receipt missing"):
            publication.candidate(targets[0])
        assert not any(target.exists() for target in targets)


def test_real_exit_after_replace_reuses_formal_once(tmp_path, monkeypatch):
    root = tmp_path / "lake"
    source = """
import os, sys
from pathlib import Path
import duckdb
from orchestrator.defs.io import stk_mins_qfq_publication as module
root = Path(sys.argv[1])
target = root / 'gold' / 'file-0.parquet'
original = os.replace
def replace(source, destination):
    original(source, destination)
    if Path(destination) == target:
        os._exit(17)
module.os.replace = replace
with module.StkMinsQfqPublication(lake_root=root, family='qfq', freq=5,
        trade_dates=('2026-10-22',), publication_id='same-operation') as publication, duckdb.connect() as connection:
    publication.bind(connection, inputs={'rows': 'SELECT 1 AS id'}, targets=(target,))
    candidate, _ = publication.candidate(target)
    candidate.write_bytes(b'literal annual replacement one')
    publication.validated(target, candidate, 1)
    publication.promote()
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", source, str(root)], timeout=15, check=False,
    )
    assert result.returncode == 17
    original = module._digest
    selected = []

    def digest(path, **kwargs):
        if "attempts" not in path.parts:
            selected.append(path)
        return original(path, **kwargs)

    monkeypatch.setattr(module, "_digest", digest)
    target = _targets(root)[0]
    before = target.stat()
    with _publication(root) as publication, duckdb.connect() as connection:
        _bind(publication, connection, (target,))
        assert publication.candidate(target) == (None, 1)
        publication.promote()
    assert selected == [target]
    assert target.stat().st_ino == before.st_ino
