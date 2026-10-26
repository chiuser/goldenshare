"""Operation ownership, full source readback and immutable bootstrap facts."""

from dataclasses import replace
from datetime import date

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
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(conn, tmp_path)
        record = source_fixture(
            conn, staging_root=staging, approval=approval, rows=(native_row(),)
        )
        assert (
            R.read_stk_factor_pro_bootstrap_source_complete(
                conn,
                staging_root=staging,
                approval=approval,
                trade_date=date(2019, 10, 16),
            )
            == record
        )
        R.load_complete_source(
            conn, staging_root=staging, approval=approval, record=record
        )
        assert conn.execute(
            f"SELECT ts_code,trade_date,open,close FROM {BOOTSTRAP_DAY_SOURCE}"
        ).fetchone() == ("000001.SZ", "20191016", 1.25, 10.0)
        assert (
            R.write_stk_factor_pro_bootstrap_source_complete(
                conn,
                staging_root=staging,
                approval=approval,
                record=record,
                check_space=check_test_space,
            )
            == record
        )
        wrong = replace(record, date_content_sha256="b" * 64)
        wrong = replace(
            wrong,
            source_complete_digest=C.stk_factor_pro_bootstrap_source_complete_digest(
                wrong
            ),
        )
        with pytest.raises(ValueError, match="业务内容"):
            R.write_stk_factor_pro_bootstrap_source_complete(
                conn,
                staging_root=staging,
                approval=approval,
                record=wrong,
                check_space=check_test_space,
            )


def test_json_corrupt_existing_not_absent_and_cannot_replace_immutable(tmp_path):
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(conn, tmp_path)
        path = R.operation_path(staging, approval, "approval.json")
        with pytest.raises(ValueError, match="冲突"):
            R.write_json(path, replace(approval, source_statement_timeout_ms=123))
        path.write_text('{"record_version":1,"record_version":1}')
        with pytest.raises(ValueError, match="重复"):
            R.read_json(path, C.StkFactorProBootstrapApproval)


def test_empty_complete_keeps_explicit_fact_no_source_files(tmp_path):
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(
            conn,
            tmp_path,
            counts=(
                (date(2019, 10, 15), 1),
                (date(2019, 10, 16), 0),
                (date(2019, 10, 17), 1),
            ),
        )
        record = source_fixture(
            conn,
            staging_root=staging,
            approval=approval,
            rows=(),
            day=date(2019, 10, 16),
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
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(conn, tmp_path)
        root = R.operation_root(staging, approval)
        (root / "linked").symlink_to(tmp_path, target_is_directory=True)
        with pytest.raises(ValueError, match="符号链接"):
            R.operation_path(staging, approval, "linked/source.json")
        record = source_fixture(
            conn, staging_root=staging, approval=approval, rows=(native_row(),)
        )
        with pytest.raises(ValueError, match="批准"):
            R.load_complete_source(
                conn,
                staging_root=staging,
                approval=approval,
                record=replace(record, operation_id="other"),
            )
