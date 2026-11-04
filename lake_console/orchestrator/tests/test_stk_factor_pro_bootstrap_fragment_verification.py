"""LLD 18: one real fragment audit, retained SQL rows and explicit ownership.

The three-day source uses Prod DATE/float rows and the existing 261-field
contract. Recovery starts a fresh execution from the persisted producer output.
"""

import os
from datetime import date
from pathlib import Path
from shutil import copy2

import duckdb
import pytest

from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_records as R
from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_source as S
from orchestrator.defs.bootstrap import stk_factor_pro_history as B
from orchestrator.defs.checks import stk_factor_pro as checks
from orchestrator.defs.io import stk_factor_pro_candidates as I
from orchestrator.defs.run_contracts import stk_factor_pro as C
from tests.stk_factor_pro_bootstrap_test_support import (
    approval_fixture,
    native_row,
    source_fixture,
)
from tests.stk_factor_pro_test_support import connection
from tests.test_stk_factor_pro_bootstrap import Instance
from tests.test_stk_factor_pro_bootstrap_source import (
    FakeProd,
    accept_source_only,
    execute,
)

DATES = (date(2019, 10, 16), date(2019, 10, 17), date(2019, 10, 18))


class Queries:
    def __init__(self, conn):
        self.conn, self.statements = conn, []

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def execute(self, statement, *args, **kwargs):
        self.statements.append(str(statement))
        return self.conn.execute(statement, *args, **kwargs)


def context(conn, staging, approval, record, *, known_records):
    return R.BootstrapFragmentVerification(
        conn,
        staging_root=staging,
        approval=approval,
        month=next(
            m for m in approval.month_limits if m.month_start == record.month_start
        ),
        known_records=known_records,
    )


def source_path(staging, approval, record):
    return R.operation_path(
        staging, approval, record.fragments[0].fragment.relative_path
    )


def first_source(conn, tmp_path, *, known_records):
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
    conn.execute(f"DROP TABLE {I.BOOTSTRAP_DAY_SOURCE}")
    return staging, approval, record


def verify(conn, verification, staging, approval, record):
    return verification.verify(
        conn,
        staging_root=staging,
        approval=approval,
        record=record,
        reference=record.fragments[0],
    )


def test_normal_three_day_task_reads_source_once_and_hands_same_facts(
    tmp_path, monkeypatch
):
    known_records = {}
    full, hashes, daily = [], [], []
    original_describe = I.describe_stk_factor_pro_fragment
    original_sha = checks.factor_file_sha
    original_day = S.factor_content_sha

    def describe(conn, **kwargs):
        if "source" in kwargs["path"].parts:
            full.append(kwargs["path"])
        return original_describe(conn, **kwargs)

    def file_sha(path):
        if "source" in Path(path).parts:
            hashes.append(path)
        return original_sha(path)

    def day_sha(conn, relation):
        if relation == I.BOOTSTRAP_DAY_SOURCE:
            daily.append(relation)
        return original_day(conn, relation)

    monkeypatch.setattr(I, "describe_stk_factor_pro_fragment", describe)
    monkeypatch.setattr(checks, "factor_file_sha", file_sha)
    monkeypatch.setattr(S, "factor_content_sha", day_sha)
    monkeypatch.setattr(
        R,
        "load_complete_source",
        lambda *_a, **_k: pytest.fail("正常导入不得重新加载源"),
    )
    with connection(tmp_path) as conn:
        wrapped = Queries(conn)
        lake, staging, approval, identity = approval_fixture(
            conn,
            tmp_path,
            counts=tuple((d, 1) for d in DATES),
            known_records=known_records,
        )
        remote = FakeProd(
            approval,
            identity,
            tuple((d, 1) for d in DATES),
            [native_row(day=d) for d in DATES],
        )
        summary = B._run_stk_factor_pro_bootstrap(
            wrapped,
            lake_root=lake,
            staging_root=staging,
            operation_id=approval.operation_id,
            instance=Instance(),
            prod_postgres=remote,
        )
        assert summary.verified_source_rows == summary.current_raw_rows == 3
        assert len(full) == len(hashes) == 1
        assert len(daily) == 3
        reads = [
            q
            for q in wrapped.statements
            if "read_parquet(" in q.lower()
            and "/source/month=" in q
            and "/fragment-" in q
        ]
        assert len(reads) == 1 and reads[0].startswith("CREATE TEMP TABLE")
        assert not conn.execute(
            "SELECT table_name FROM duckdb_tables() WHERE temporary AND "
            "(table_name LIKE 'stk_factor_bootstrap_fragment%' OR "
            "table_name LIKE 'stk_factor_bootstrap_verify_fragment%' OR table_name=?)",
            [I.BOOTSTRAP_DAY_SOURCE],
        ).fetchall()


def test_recovery_adjacent_dates_reuses_one_actual_fragment_table(
    tmp_path, monkeypatch
):
    original_known, seen = {}, []
    with connection(tmp_path) as conn:
        _, staging, approval, identity = approval_fixture(
            conn,
            tmp_path,
            counts=tuple((d, 1) for d in DATES),
            known_records=original_known,
        )
        remote = FakeProd(
            approval,
            identity,
            tuple((d, 1) for d in DATES),
            [native_row(day=d) for d in DATES],
        )
        execute(
            conn,
            staging,
            approval,
            remote,
            callback=accept_source_only(monkeypatch, seen),
            known_records=original_known,
        )
        known_records = {}
        records = tuple(
            R.read_stk_factor_pro_bootstrap_source_complete(
                conn,
                staging_root=staging,
                approval=approval,
                trade_date=d,
                known_records=known_records,
            )
            for d in DATES
        )
        wrapped = Queries(conn)
        verification = context(
            wrapped, staging, approval, records[0], known_records=known_records
        )
        checks_done = []
        original = R.fragment_from_relation

        def checked(conn, **kwargs):
            checks_done.append(kwargs["path"])
            return original(conn, **kwargs)

        monkeypatch.setattr(R, "fragment_from_relation", checked)
        with R.resource_cleanup(verification.close):
            for record in records:
                relation = R.load_complete_source(
                    wrapped,
                    staging_root=staging,
                    approval=approval,
                    record=record,
                    verification=verification,
                    known_records=known_records,
                )
                with R.resource_cleanup(
                    lambda relation=relation: conn.execute(f"DROP TABLE {relation}")
                ):
                    assert conn.execute(
                        f"SELECT ts_code,trade_date,open,close FROM {relation}"
                    ).fetchall() == [
                        ("000001.SZ", record.trade_date.strftime("%Y%m%d"), 1.25, 10.0)
                    ]
            assert len(checks_done) == 1
            assert not verification._relations
        reads = [q for q in wrapped.statements if "read_parquet(" in q.lower()]
        assert len(reads) == 1 and reads[0].startswith("CREATE TEMP TABLE")
        assert not verification._entries and verification._closed


@pytest.mark.parametrize("change", ["mtime", "inode"])
def test_changed_first_file_identity_stops_without_reaudit(
    tmp_path, monkeypatch, change
):
    known_records = {}
    with connection(tmp_path) as conn:
        staging, approval, record = first_source(
            conn, tmp_path, known_records=known_records
        )
        verification = context(
            conn, staging, approval, record, known_records=known_records
        )
        with R.resource_cleanup(verification.close):
            path, _, relation = verify(conn, verification, staging, approval, record)
            assert conn.execute(f"SELECT close FROM {relation}").fetchall() == [(10.0,)]
            if change == "mtime":
                before = path.stat()
                os.utime(
                    path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000)
                )
            else:
                replacement = path.with_suffix(".replacement")
                copy2(path, replacement)
                os.replace(replacement, path)
            monkeypatch.setattr(
                R,
                "fragment_from_relation",
                lambda *_a, **_k: pytest.fail("变化后不得重审继续"),
            )
            with pytest.raises(ValueError, match="身份或描述已改变"):
                verify(conn, verification, staging, approval, record)


def test_bad_existing_source_record_is_rejected_on_first_read(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        staging, approval, record = first_source(
            conn, tmp_path, known_records=known_records
        )
        path = R.operation_path(
            staging, approval, f"source/dates/{record.trade_date}/source-complete.json"
        )
        payload = path.read_text()
        path.write_text(payload.replace(record.source_complete_digest, "b" * 64))
        with pytest.raises(ValueError, match="完整日源摘要"):
            R.read_stk_factor_pro_bootstrap_source_complete(
                conn,
                staging_root=staging,
                approval=approval,
                trade_date=record.trade_date,
                known_records={},
            )


def test_context_cannot_cross_month(tmp_path):
    known_records = {}
    first, second = date(2019, 1, 31), date(2019, 2, 1)
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(
            conn,
            tmp_path,
            counts=((first, 1), (second, 1)),
            known_records=known_records,
        )
        records = tuple(
            source_fixture(
                conn,
                staging_root=staging,
                approval=approval,
                rows=(native_row(day=day),),
                day=day,
                known_records=known_records,
            )
            for day in (first, second)
        )
        conn.execute(f"DROP TABLE {I.BOOTSTRAP_DAY_SOURCE}")
        verification = context(
            conn, staging, approval, records[0], known_records=known_records
        )
        with (
            R.resource_cleanup(verification.close),
            pytest.raises(ValueError, match="月份不符"),
        ):
            verify(conn, verification, staging, approval, records[1])


def test_bad_first_fragment_is_not_registered_and_partial_table_is_cleaned(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        staging, approval, record = first_source(
            conn, tmp_path, known_records=known_records
        )
        path = source_path(staging, approval, record)
        path.write_bytes(b"broken parquet")
        verification = context(
            conn, staging, approval, record, known_records=known_records
        )
        with R.resource_cleanup(verification.close):
            with pytest.raises(duckdb.Error):
                verify(conn, verification, staging, approval, record)
            assert not verification._entries and not verification._relations
        assert not conn.execute(
            "SELECT table_name FROM duckdb_tables() WHERE temporary AND table_name LIKE 'stk_factor_bootstrap_verify_fragment%'"
        ).fetchall()


def test_context_does_not_cross_connection_operation_month_or_close(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn, connection(tmp_path) as other:
        staging, approval, record = first_source(
            conn, tmp_path, known_records=known_records
        )
        verification = context(
            conn, staging, approval, record, known_records=known_records
        )
        with pytest.raises(ValueError, match="连接/operation/批准"):
            verify(other, verification, staging, approval, record)
        _, _, other_approval, _ = approval_fixture(
            conn, tmp_path, operation="other", known_records=known_records
        )
        with pytest.raises(ValueError, match="连接/operation/批准"):
            verification._require_scope(
                conn, staging_root=staging, approval=other_approval
            )
        verification.close()
        with pytest.raises(ValueError, match="已关闭"):
            verify(conn, verification, staging, approval, record)
        assert not verification._entries and not verification._relations


def test_writer_transfers_real_table_and_callback_failure_cleans_it(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(
            conn, tmp_path, known_records=known_records
        )
        path = R.operation_path(
            staging,
            approval,
            "source/month=2019-10/attempt_id=" + "a" * 32 + "/fragment-000001.parquet",
        )
        frame = I.build_stk_factor_pro_raw_batch(
            rows=(native_row(),),
            source_fields=C.STK_FACTOR_PRO_SOURCE_COLUMNS,
            source="prod_postgres",
            expected_dates=(DATES[0],),
        )
        delivered = []

        def reject(*, path, fragment, source_relation):
            assert (
                conn.execute(
                    "SELECT count(*) FROM duckdb_tables() WHERE temporary AND table_name=?",
                    [source_relation],
                ).fetchone()[0]
                == 1
            )
            assert conn.execute(
                f"SELECT ts_code,trade_date,close FROM {source_relation}"
            ).fetchall() == [("000001.SZ", "20191016", 10.0)]
            delivered.append((path, fragment, source_relation))
            raise LookupError("business callback failed")

        with pytest.raises(LookupError, match="business callback failed"):
            I.write_stk_factor_pro_raw_fragment(
                connection=conn,
                frame=frame,
                candidate_path=path,
                expected_row_count=1,
                on_verified_fragment=reject,
            )
        assert path.is_file() and len(delivered) == 1
        assert not conn.execute(
            "SELECT table_name FROM duckdb_tables() WHERE temporary AND table_name LIKE 'stk_factor_bootstrap_fragment%'"
        ).fetchall()
