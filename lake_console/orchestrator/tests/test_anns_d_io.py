from pathlib import Path

import pytest

from orchestrator.defs.anns_d_contract import AnnouncementCancelled, AnnouncementError
from orchestrator.defs.anns_d_io import AnnouncementStore
from tests.anns_d_test_support import archive as _archive_fixture
from tests.anns_d_test_support import checkpoint, source_row

archive = _archive_fixture


def test_full_field_distinct_and_same_title_versions(archive):
    rows = [
        source_row(),
        source_row(),
        source_row(url="https://example/a.pdf"),
        source_row(url=""),
        source_row(url=" "),
    ]
    page = archive.write_page(rows, archive.directory / "page.parquet", archive.control)
    delivery = archive.build_day("2023-06-09", [page])
    assert (
        delivery["source_rows"] == 5
        and delivery["written_rows"] == 4
        and delivery["duplicate_rows"] == 1
    )
    archive.promote_day("2023-06-09", delivery, checkpoint(archive))
    assert (
        archive.audit_file(archive.target("2023-06-09"), "2023-06-09")["written_rows"]
        == 4
    )


def test_missing_code_and_title_preserved(archive):
    page = archive.write_page(
        [source_row(ts_code=None, title=None)],
        archive.directory / "nullable.parquet",
        archive.control,
    )
    assert archive.build_day("2023-06-09", [page])["written_rows"] == 1


def test_empty_file_six_varchars(archive):
    page = archive.write_page([], archive.directory / "empty.parquet", archive.control)
    delivery = archive.build_day("2023-06-09", [page])
    archive.promote_day("2023-06-09", delivery, checkpoint(archive))
    assert (
        archive.audit_file(archive.target("2023-06-09"), "2023-06-09")["written_rows"]
        == 0
    )


def test_old_rows_preserved_and_replay_idempotent(archive):
    old = archive.write_page(
        [source_row()], archive.directory / "old.parquet", archive.control
    )
    archive.promote_day(
        "2023-06-09", archive.build_day("2023-06-09", [old]), checkpoint(archive)
    )
    new = archive.write_page(
        [source_row(url="https://example/a.pdf")],
        archive.directory / "new.parquet",
        archive.control,
    )
    merged = archive.build_day("2023-06-09", [new])
    assert (
        merged["existing_rows"] == 1
        and merged["written_rows"] == 2
        and merged["new_unique_rows"] == 1
    )
    archive.promote_day("2023-06-09", merged, checkpoint(archive))
    replay = archive.build_day("2023-06-09", [new])
    assert replay["written_rows"] == 2 and replay["new_unique_rows"] == 0


def test_mutated_target_or_candidate_blocks(archive):
    page = archive.write_page(
        [source_row()], archive.directory / "page.parquet", archive.control
    )
    delivery = archive.build_day("2023-06-09", [page])
    Path(delivery["candidate"]).write_bytes(b"bad")
    with pytest.raises(AnnouncementError, match="candidate_changed"):
        archive.promote_day("2023-06-09", delivery, checkpoint(archive))
    delivery = archive.build_day("2023-06-09", [page])
    target = archive.target("2023-06-09")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"changed")
    with pytest.raises(AnnouncementError, match="target_changed"):
        archive.promote_day("2023-06-09", delivery, checkpoint(archive))


def test_rename_before_checkpoint_failure_recovers(archive, monkeypatch):
    page = archive.write_page(
        [source_row()], archive.directory / "page.parquet", archive.control
    )
    delivery = archive.build_day("2023-06-09", [page])
    cp = checkpoint(archive)
    save = cp.save

    def fail(**values):
        if values.get("phase") == "promoted":
            raise OSError("simulated disk failure")
        save(**values)

    monkeypatch.setattr(cp, "save", fail)
    with pytest.raises(OSError):
        archive.promote_day("2023-06-09", delivery, cp)
    assert archive.target("2023-06-09").exists()
    monkeypatch.setattr(cp, "save", save)
    assert archive.promote_day("2023-06-09", delivery, cp) == "recovered"


def test_cancel_before_promotion_retains_candidate(archive):
    page = archive.write_page(
        [source_row()], archive.directory / "page.parquet", archive.control
    )
    delivery = archive.build_day("2023-06-09", [page])
    archive.control.cancelled = lambda: True
    with pytest.raises(AnnouncementCancelled):
        archive.promote_day("2023-06-09", delivery, checkpoint(archive))
    assert (
        Path(delivery["candidate"]).exists()
        and not archive.target("2023-06-09").exists()
    )


def test_unsafe_paths_block(archive, tmp_path):
    bad = tmp_path / "link"
    bad.symlink_to(archive.root, target_is_directory=True)
    with pytest.raises(AnnouncementError):
        AnnouncementStore(bad, archive.staging, "x", archive.policy, archive.control)
    with pytest.raises(AnnouncementError):
        AnnouncementStore(
            archive.root, archive.root, "x", archive.policy, archive.control
        )
    with pytest.raises(AnnouncementError):
        archive.write_page([], tmp_path / "outside.parquet", archive.control)


def test_low_space_and_unmounted_roots_block(archive, monkeypatch):
    import shutil
    from collections import namedtuple

    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda _: usage(10, 9, 1))
    with pytest.raises(AnnouncementError, match="disk_space"):
        archive.gate()


def test_wrong_physical_schema_cannot_enter_merge(archive):
    path = archive.directory / "wrong.parquet"
    with archive.connection() as connection:
        connection.execute(
            "COPY (SELECT 1 AS ann_date) TO ? (FORMAT PARQUET)", [str(path)]
        )
    with pytest.raises(AnnouncementError, match="file_schema"):
        archive.build_day("2023-06-09", [path])


def test_writer_lock_conflict(archive):
    from orchestrator.defs.anns_d_checkpoint import announcement_file_lock

    lock = archive.staging / "anns_d" / "locks" / "day-2023-06-09.lock"
    with (
        announcement_file_lock(lock),
        pytest.raises(AnnouncementError, match="writer_busy"),
        announcement_file_lock(lock),
    ):
        pytest.fail("cannot acquire second lock")


def test_source_page_changed_after_build_blocks_promotion(archive):
    from orchestrator.defs.anns_d_checkpoint import announcement_file_fingerprint

    page = archive.write_page(
        [source_row()], archive.directory / "page.parquet", archive.control
    )
    delivery = archive.build_day("2023-06-09", [page])
    delivery["source_pages"] = [
        {"path": str(page), "fingerprint": announcement_file_fingerprint(page)}
    ]
    page.write_bytes(b"changed")
    with pytest.raises(AnnouncementError, match="delivery_source_changed"):
        archive.promote_day("2023-06-09", delivery, checkpoint(archive))
    assert not archive.target("2023-06-09").exists()


def test_canonical_path_uses_ann_date_and_no_system_layer(tmp_path):
    from orchestrator.defs.paths import raw_anns_d_path

    assert (
        raw_anns_d_path(tmp_path, "2023-06-09")
        == tmp_path / "raw/tushare/anns_d/ann_date=2023-06-09/part-000.parquet"
    )
    with pytest.raises(AnnouncementError):
        raw_anns_d_path(tmp_path, "20230609")
