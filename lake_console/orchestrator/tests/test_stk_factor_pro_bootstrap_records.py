"""Operation ownership, full source readback and immutable bootstrap facts."""

from dataclasses import replace
from datetime import date
from hashlib import sha256
from pathlib import Path

import pytest

from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_records as R
from orchestrator.defs.io.stk_factor_pro_candidates import BOOTSTRAP_DAY_SOURCE
from orchestrator.defs.paths import stk_factor_pro_bootstrap_record_path
from orchestrator.defs.run_contracts import stk_factor_pro as C
from tests.stk_factor_pro_bootstrap_test_support import (
    approval_fixture,
    check_test_space,
    native_row,
    source_fixture,
)
from tests.stk_factor_pro_test_support import connection


@pytest.mark.parametrize(
    "relative", ["../escape", "/absolute", "source//x", "./x", "a/./x", "a\\b", ""]
)
def test_bootstrap_rejects_noncanonical_paths(tmp_path, relative):
    with pytest.raises(ValueError):
        stk_factor_pro_bootstrap_record_path(tmp_path, "op-a", relative)


def test_source_saved_read_back_immutable_and_content_verified(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(
            conn, tmp_path, known_records=known_records
        )
        record = source_fixture(
            conn,
            staging_root=staging,
            approval=approval,
            rows=(native_row(),),
            known_records=known_records,
        )
        assert (
            R.read_stk_factor_pro_bootstrap_source_complete(
                conn,
                staging_root=staging,
                approval=approval,
                trade_date=date(2019, 10, 16),
                known_records=known_records,
            )
            == record
        )
        # The source fixture hands its actual first readback relation straight
        # to the next consumer; normal writes must not reload that same source.
        assert conn.execute(
            f"SELECT ts_code,trade_date,open,close FROM {BOOTSTRAP_DAY_SOURCE}"
        ).fetchone() == ("000001.SZ", "20191016", 1.25, 10.0)
        assert (
            R.write_stk_factor_pro_bootstrap_source_complete(
                conn,
                staging_root=staging,
                approval=approval,
                record=record,
                approved_date_rows=1,
                source_relation=BOOTSTRAP_DAY_SOURCE,
                check_space=check_test_space,
                known_records=known_records,
            )[0]
            == record
        )
        wrong = replace(record, date_content_sha256="b" * 64)
        wrong = replace(
            wrong,
            source_complete_digest=C.stk_factor_pro_bootstrap_source_complete_digest(
                wrong
            ),
        )
        with pytest.raises(ValueError, match="冲突"):
            R.write_stk_factor_pro_bootstrap_source_complete(
                conn,
                staging_root=staging,
                approval=approval,
                record=wrong,
                approved_date_rows=1,
                source_relation=BOOTSTRAP_DAY_SOURCE,
                check_space=check_test_space,
                known_records=known_records,
            )


def test_json_corrupt_existing_not_absent_and_cannot_replace_immutable(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(
            conn, tmp_path, known_records=known_records
        )
        path = R.operation_path(staging, approval, "approval.json")
        with pytest.raises(ValueError, match="冲突"):
            R.write_json(
                path,
                replace(approval, source_statement_timeout_ms=123),
                known_records=known_records,
            )
        path.write_text('{"record_version":1,"record_version":1}')
        with pytest.raises(ValueError, match="重复"):
            R.read_json(path, C.StkFactorProBootstrapApproval, known_records={})


def test_empty_complete_keeps_explicit_fact_no_source_files(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(
            conn,
            tmp_path,
            counts=(
                (date(2019, 10, 15), 1),
                (date(2019, 10, 16), 0),
                (date(2019, 10, 17), 1),
            ),
            known_records=known_records,
        )
        record = source_fixture(
            conn,
            staging_root=staging,
            approval=approval,
            rows=(),
            day=date(2019, 10, 16),
            known_records=known_records,
        )
        assert (
            record.source_empty and record.actual_rows == 0 and record.fragments == ()
        )
        assert tuple(R.operation_root(staging, approval).glob("source/month=*")) == ()


def test_cleanup_attempts_all_and_preserves_original():
    done = []

    def fail():
        done.append("fail")
        raise OSError("close")

    original = ValueError("original")
    with (
        pytest.raises(ValueError) as result,
        R.resource_cleanup(fail, lambda: done.append("last")),
    ):
        raise original
    assert result.value is original and done == ["fail", "last"]
    assert "OSError" in original.__notes__[0]
    with pytest.raises(OSError), R.resource_cleanup(fail):
        pass


def test_symlink_and_other_operation_rejected(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(
            conn, tmp_path, known_records=known_records
        )
        root = R.operation_root(staging, approval)
        (root / "linked").symlink_to(tmp_path, target_is_directory=True)
        with pytest.raises(ValueError, match="符号链接"):
            R.operation_path(staging, approval, "linked/source.json")
        record = source_fixture(
            conn,
            staging_root=staging,
            approval=approval,
            rows=(native_row(),),
            known_records=known_records,
        )
        with pytest.raises(ValueError, match="批准"):
            R.write_stk_factor_pro_bootstrap_source_complete(
                conn,
                staging_root=staging,
                approval=approval,
                record=replace(record, operation_id="other"),
                approved_date_rows=1,
                source_relation=BOOTSTRAP_DAY_SOURCE,
                check_space=check_test_space,
                known_records=known_records,
            )


def test_json_first_bytes_and_approval_digest_are_shared(tmp_path, monkeypatch):
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(conn, tmp_path, known_records={})
    path = R.operation_path(staging, approval, "approval.json")
    expected_digest = sha256(path.read_bytes()).hexdigest()
    reads, parses = [], []
    read_bytes = Path.read_bytes
    parse_record = C.parse_stk_factor_pro_record

    def observed_read(value):
        reads.append(value)
        return read_bytes(value)

    def observed_parse(*args):
        parses.append(args[0])
        return parse_record(*args)

    def no_file_hash(*args):
        raise AssertionError("JSON摘要应来自首次读取的同一份字节")

    monkeypatch.setattr(Path, "read_bytes", observed_read)
    monkeypatch.setattr(C, "parse_stk_factor_pro_record", observed_parse)
    monkeypatch.setattr(R, "factor_file_sha", no_file_hash)
    known_records = {}
    assert (
        R.read_json(path, C.StkFactorProBootstrapApproval, known_records=known_records)
        == approval
    )
    assert (
        R.read_json(path, C.StkFactorProBootstrapApproval, known_records=known_records)
        == approval
    )
    assert (
        R.approval_sha(staging, approval, known_records=known_records)
        == expected_digest
    )
    assert reads == [path]
    assert parses == [
        C.StkFactorProBootstrapApproval,
        C.StkFactorProBootstrapMonthLimit,
    ]
    assert known_records[path][:2] == (approval, expected_digest)


def test_json_writer_returns_facts_without_parse_readback_or_same_version_write(
    tmp_path, monkeypatch
):
    known_records = {}
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(
            conn, tmp_path, known_records=known_records
        )
    path = R.operation_path(staging, approval, "approval.json")
    revised = replace(approval, source_statement_timeout_ms=123)

    def forbidden(*args, **kwargs):
        raise AssertionError("合法内存记录不应反解析或写后回读")

    monkeypatch.setattr(C, "parse_stk_factor_pro_record", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    saved, digest = R.write_json(
        path, revised, known_records=known_records, mutable=True
    )
    assert saved is revised
    assert known_records[path][:2] == (revised, digest)
    monkeypatch.setattr(C, "stk_factor_pro_record_to_dict", forbidden)
    monkeypatch.setattr(R, "atomic_promote", forbidden)
    assert R.write_json(path, revised, known_records=known_records, mutable=True) == (
        revised,
        digest,
    )


def test_saved_record_registered_before_post_save_space_failure(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(
            conn, tmp_path, known_records=known_records
        )
    path = R.operation_path(staging, approval, "approval.json")
    revised = replace(approval, source_statement_timeout_ms=123)

    def capacity(stage, **facts):
        if facts.get("event") == "record_saved":
            assert known_records[path][0] is revised
            raise OSError("post-save capacity")

    with pytest.raises(OSError, match="post-save capacity"):
        R.write_json(
            path,
            revised,
            known_records=known_records,
            mutable=True,
            check_space=capacity,
        )
    assert known_records[path][0] is revised
    assert sha256(path.read_bytes()).hexdigest() == known_records[path][1]


def test_replace_callback_precedes_directory_sync_and_failed_sync_is_not_registered(
    tmp_path, monkeypatch
):
    known_records = {}
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(
            conn, tmp_path, known_records=known_records
        )
    path = R.operation_path(staging, approval, "approval.json")
    revised = replace(approval, source_statement_timeout_ms=123)
    order = []

    def replaced():
        assert path not in known_records
        order.append("replaced")

    def sync_directory(parent):
        assert order == ["replaced"] and parent == path.parent
        order.append("sync")
        raise OSError("directory sync")

    monkeypatch.setattr(R, "fsync_directory", sync_directory)
    with pytest.raises(OSError, match="directory sync"):
        R.write_json(
            path,
            revised,
            known_records=known_records,
            mutable=True,
            on_replaced=replaced,
        )
    assert order == ["replaced", "sync"]
    assert path not in known_records


def test_approved_counts_reuse_first_rows_and_digest(tmp_path, monkeypatch):
    known_records = {}
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(
            conn, tmp_path, known_records=known_records
        )
        hashes, queries = [], []
        original_hash = R.factor_file_sha

        def observed_hash(path):
            hashes.append(path)
            return original_hash(path)

        class ObservedConnection:
            def execute(self, query, parameters=None):
                queries.append(query)
                return (
                    conn.execute(query)
                    if parameters is None
                    else conn.execute(query, parameters)
                )

        monkeypatch.setattr(R, "factor_file_sha", observed_hash)
        observed = ObservedConnection()
        expected = ((date(2019, 10, 16), 1),)
        assert (
            R.load_approved_counts(
                observed,
                staging_root=staging,
                approval=approval,
                known_records=known_records,
            )
            == expected
        )
        first_query_count = len(queries)
        assert (
            R.load_approved_counts(
                observed,
                staging_root=staging,
                approval=approval,
                known_records=known_records,
            )
            == expected
        )
        assert hashes == [R.operation_path(staging, approval, "daily-counts.parquet")]
        assert len(queries) == first_query_count
