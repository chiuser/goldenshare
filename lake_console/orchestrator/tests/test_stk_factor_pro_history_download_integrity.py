"""Additional source-write faults: transfer values, cleanup and path ownership."""

import pytest
from duckdb import Error as DuckDBError

from orchestrator.defs.io import stk_factor_pro_download as downloads
from tests.stk_factor_pro_history_test_support import NAMES, connection
from tests.test_stk_factor_pro_history_download import (
    assert_no_complete,
    assert_no_relations,
    prepare,
    run_download,
    sample_downloader,
)


def test_valid_schema_and_row_count_do_not_hide_changed_source_value(
    tmp_path, monkeypatch
):
    known_records = {}
    with connection(tmp_path) as conn:
        root, args = prepare(conn, tmp_path, known_records=known_records)
        original = downloads.copy_query_to_parquet

        def alter(query, path):
            if "source/history/units" in str(path):
                columns = ",".join(
                    '123.0::DOUBLE AS "close"' if name == "close" else f'"{name}"'
                    for name in NAMES
                )
                query = f"SELECT {columns} FROM {downloads.HISTORY_CURRENT_UNIT}"
            return original(query, path)

        monkeypatch.setattr(downloads, "copy_query_to_parquet", alter)
        with pytest.raises(ValueError, match="全部业务字段或NULL对账"):
            run_download(conn, args, sample_downloader(), known_records=known_records)
        assert_no_complete(root)
        assert list((root / "source/history/units").glob("*.parquet")) == []
        assert_no_relations(conn)


class CleanupFaultConnection:
    def __init__(self, conn):
        self.conn, self.attempts = conn, []

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def execute(self, query, parameters=None):
        if query.startswith("DROP TABLE IF EXISTS stk_factor_pro_history_saved_unit"):
            self.attempts.append("saved_unit")
            raise DuckDBError("source table cleanup error")
        if query.startswith("DROP TABLE IF EXISTS stk_factor_pro_history_current_unit"):
            self.attempts.append("table")
        return (
            self.conn.execute(query, parameters)
            if parameters is not None
            else self.conn.execute(query)
        )

    def unregister(self, name):
        self.attempts.append("unregister")
        return self.conn.unregister(name)


def test_cleanup_attempts_remaining_resources_and_preserves_save_error(
    tmp_path, monkeypatch
):
    known_records = {}
    with connection(tmp_path) as conn:
        root, args = prepare(conn, tmp_path, known_records=known_records)
        proxy = CleanupFaultConnection(conn)

        def fail_copy(*args, **kwargs):
            raise OSError("synthetic source disk write failed")

        monkeypatch.setattr(downloads, "copy_query_to_parquet", fail_copy)
        downloader = sample_downloader()
        with pytest.raises(OSError, match="source disk write") as captured:
            run_download(proxy, args, downloader, known_records=known_records)
        assert any("清理" in note for note in captured.value.__notes__)
        assert "table" in proxy.attempts and "unregister" in proxy.attempts
        assert len(downloader.calls) == 1
        assert downloader.sessions[0].closed and downloader.sessions[0].delivered == 1
        assert_no_relations(conn)
        assert_no_complete(root)


def test_history_unit_parent_symlink_created_during_delivery_is_write_rejected(
    tmp_path,
):
    known_records = {}
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "marker"
    marker.write_bytes(b"unchanged")
    with connection(tmp_path) as conn:
        root, args = prepare(conn, tmp_path, known_records=known_records)

        def unsafe_parent(result):
            source = root / "source/history"
            source.mkdir(parents=True)
            (source / "units").symlink_to(outside, target_is_directory=True)
            return result

        loader = sample_downloader(result_transform=unsafe_parent)
        with pytest.raises(ValueError, match="路径"):
            run_download(conn, args, loader, known_records=known_records)
        assert_no_complete(root)
        assert sorted(path.name for path in outside.iterdir()) == ["marker"]
        assert marker.read_bytes() == b"unchanged"
        assert_no_relations(conn)
