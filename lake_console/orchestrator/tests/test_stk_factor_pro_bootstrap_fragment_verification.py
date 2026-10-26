"""LLD 17.8.3: real saved fragments, scoped reuse, and independent day checks.

The input producer is the existing 261-column native DATE/float fixture. Literal
row/date/value assertions below do not derive expected business values from the
verification implementation. Deliberate corruptions are rejection fixtures.
"""

import os
from dataclasses import replace
from datetime import date
from shutil import copy2

import duckdb
import pytest

from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_records as R
from orchestrator.defs.bootstrap import stk_factor_pro_history as B
from orchestrator.defs.io import stk_factor_pro_candidates as I
from orchestrator.defs.paths import (
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
)
from orchestrator.defs.run_contracts import stk_factor_pro as C
from tests.stk_factor_pro_bootstrap_test_support import (
    approval_fixture,
    native_row,
    source_fixture,
)
from tests.stk_factor_pro_test_support import connection
from tests.test_stk_factor_pro_bootstrap import Instance
from tests.test_stk_factor_pro_bootstrap_source import FakeProd


def source_path(staging, approval, record):
    return R.operation_path(
        staging, approval, record.fragments[0].fragment.relative_path
    )


def context(conn, staging, approval, record):
    month = next(
        m for m in approval.month_limits if m.month_start == record.month_start
    )
    return R.BootstrapFragmentVerification(
        conn, staging_root=staging, approval=approval, month=month
    )


def load(conn, staging, approval, record, verification):
    R.load_complete_source(
        conn,
        staging_root=staging,
        approval=approval,
        record=record,
        verification=verification,
    )


def change_record(record, **changes):
    changed = replace(record, **changes)
    return replace(
        changed,
        source_complete_digest=C.stk_factor_pro_bootstrap_source_complete_digest(
            changed
        ),
    )


def count_full_checks(monkeypatch):
    seen = []
    original = R.fragment_from_relation

    def counted(conn, **kwargs):
        seen.append(kwargs["path"])
        return original(conn, **kwargs)

    monkeypatch.setattr(R, "fragment_from_relation", counted)
    return seen


def test_one_saved_fragment_three_dates_checks_full_once_and_each_day_twice(
    tmp_path, monkeypatch
):
    dates = (date(2019, 10, 16), date(2019, 10, 17), date(2019, 10, 18))
    full, daily, contexts = [], [], []
    original_describe = I.describe_stk_factor_pro_fragment
    original_day = R.require_factor_relation
    original_init = R.BootstrapFragmentVerification.__init__

    def describe(conn, **kwargs):
        if "source" in kwargs["path"].parts:
            full.append(kwargs["path"])
        return original_describe(conn, **kwargs)

    def day(conn, relation, **kwargs):
        daily.append(kwargs["target_trade_date"])
        return original_day(conn, relation, **kwargs)

    def initialized(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        contexts.append(self)

    monkeypatch.setattr(I, "describe_stk_factor_pro_fragment", describe)
    monkeypatch.setattr(R, "require_factor_relation", day)
    monkeypatch.setattr(R.BootstrapFragmentVerification, "__init__", initialized)
    with connection(tmp_path) as conn:
        lake, staging, approval, identity = approval_fixture(
            conn, tmp_path, counts=tuple((d, 1) for d in dates)
        )
        remote = FakeProd(
            approval,
            identity,
            tuple((d, 1) for d in dates),
            [native_row(day=d) for d in dates],
        )
        summary = B._run_stk_factor_pro_bootstrap(
            conn,
            lake_root=lake,
            staging_root=staging,
            operation_id=approval.operation_id,
            instance=Instance(),
            prod_postgres=remote,
        )
        assert summary.verified_source_rows == summary.current_raw_rows == 3
        assert len(full) == 1
        assert daily == [dates[0], dates[0], dates[1], dates[1], dates[2], dates[2]]
        assert len(contexts) == 1 and contexts[0]._closed and not contexts[0]._entries
        for d in dates:
            raw = raw_stk_factor_pro_path(lake, d.isoformat())
            silver = silver_stock_factor_pro_path(lake, d.isoformat())
            assert conn.execute(
                "SELECT ts_code,trade_date,close FROM read_parquet(?,hive_partitioning=false)",
                [str(raw)],
            ).fetchall() == [("000001.SZ", d.strftime("%Y%m%d"), 10.0)]
            assert conn.execute(
                "SELECT ts_code,trade_date,close,typeof(trade_date) FROM read_parquet(?,hive_partitioning=false)",
                [str(silver)],
            ).fetchall() == [("000001.SZ", d, 10.0, "DATE")]


@pytest.mark.parametrize("change", ["mtime", "inode"])
def test_file_identity_change_rechecks_even_when_bytes_stay_equal(
    tmp_path, monkeypatch, change
):
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(conn, tmp_path)
        record = source_fixture(
            conn, staging_root=staging, approval=approval, rows=(native_row(),)
        )
        verification = context(conn, staging, approval, record)
        full = count_full_checks(monkeypatch)
        load(conn, staging, approval, record, verification)
        path = source_path(staging, approval, record)
        if change == "mtime":
            before = path.stat()
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
        else:
            replacement = path.with_suffix(".replacement")
            copy2(path, replacement)
            os.replace(replacement, path)
        load(conn, staging, approval, record, verification)
        load(conn, staging, approval, record, verification)
        assert full == [path, path]
        verification.close()


def test_same_size_corruption_with_restored_mtime_never_hits_old_success(
    tmp_path, monkeypatch
):
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(conn, tmp_path)
        record = source_fixture(
            conn, staging_root=staging, approval=approval, rows=(native_row(),)
        )
        verification = context(conn, staging, approval, record)
        load(conn, staging, approval, record, verification)
        path = source_path(staging, approval, record)
        before = path.stat()
        payload = bytearray(path.read_bytes())
        payload[-1] ^= 1  # Intentionally corrupt the Parquet footer, preserving size.
        path.write_bytes(payload)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        with pytest.raises((ValueError, duckdb.Error)):
            load(conn, staging, approval, record, verification)
        assert not verification._entries
        verification.close()


def test_changed_fragment_description_is_not_hidden_by_cached_bytes(
    tmp_path, monkeypatch
):
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(conn, tmp_path)
        record = source_fixture(
            conn, staging_root=staging, approval=approval, rows=(native_row(),)
        )
        verification = context(conn, staging, approval, record)
        load(conn, staging, approval, record, verification)
        fragment = replace(record.fragments[0].fragment, content_sha256="b" * 64)
        refs = (replace(record.fragments[0], fragment=fragment),)
        changed = change_record(
            record,
            fragments=refs,
            fragments_manifest_digest=C.fragments_manifest_digest(refs),
        )
        full = count_full_checks(monkeypatch)
        with pytest.raises(ValueError, match="片段完整内容"):
            load(conn, staging, approval, changed, verification)
        assert len(full) == 1 and not verification._entries
        verification.close()


def test_bad_source_record_still_rejected_before_cached_fragment(tmp_path, monkeypatch):
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(conn, tmp_path)
        record = source_fixture(
            conn, staging_root=staging, approval=approval, rows=(native_row(),)
        )
        verification = context(conn, staging, approval, record)
        load(conn, staging, approval, record, verification)
        full = count_full_checks(monkeypatch)
        with pytest.raises(ValueError, match="完整日源摘要"):
            load(
                conn,
                staging,
                approval,
                replace(record, source_complete_digest="b" * 64),
                verification,
            )
        assert full == []
        verification.close()


@pytest.mark.parametrize("change", ["rows", "content"])
def test_cached_fragment_does_not_skip_day_count_or_content(
    tmp_path, monkeypatch, change
):
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(
            conn, tmp_path, counts=((date(2019, 10, 16), 3),)
        )
        record = source_fixture(
            conn,
            staging_root=staging,
            approval=approval,
            rows=tuple(native_row(f"{n:06}.SZ") for n in range(3)),
        )
        verification = context(conn, staging, approval, record)
        load(conn, staging, approval, record, verification)
        changed = change_record(
            record,
            **(
                {"approved_rows": 2, "actual_rows": 2}
                if change == "rows"
                else {"date_content_sha256": "b" * 64}
            ),
        )
        full = count_full_checks(monkeypatch)
        with pytest.raises(ValueError, match="完整日源行数/业务内容"):
            load(conn, staging, approval, changed, verification)
        assert full == []
        verification.close()


def test_failed_full_check_is_not_cached(tmp_path, monkeypatch):
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(conn, tmp_path)
        record = source_fixture(
            conn, staging_root=staging, approval=approval, rows=(native_row(),)
        )
        verification = context(conn, staging, approval, record)
        original = R.fragment_from_relation
        calls = []

        def fail_once(conn, **kwargs):
            calls.append(kwargs["path"])
            if len(calls) == 1:
                raise RuntimeError("injected full-check error")
            return original(conn, **kwargs)

        monkeypatch.setattr(R, "fragment_from_relation", fail_once)
        with pytest.raises(RuntimeError, match="full-check"):
            load(conn, staging, approval, record, verification)
        assert not verification._entries
        load(conn, staging, approval, record, verification)
        assert len(calls) == 2
        verification.close()


def test_file_change_during_full_check_cannot_register_success(tmp_path, monkeypatch):
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(conn, tmp_path)
        record = source_fixture(
            conn, staging_root=staging, approval=approval, rows=(native_row(),)
        )
        verification = context(conn, staging, approval, record)
        original = R.fragment_from_relation

        def changed(conn, **kwargs):
            result = original(conn, **kwargs)
            path = kwargs["path"]
            before = path.stat()
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
            return result

        monkeypatch.setattr(R, "fragment_from_relation", changed)
        with pytest.raises(ValueError, match="完整核验期间改变"):
            load(conn, staging, approval, record, verification)
        assert not verification._entries
        monkeypatch.setattr(R, "fragment_from_relation", original)
        load(conn, staging, approval, record, verification)
        verification.close()


def test_file_change_during_cached_day_materialization_is_rejected(tmp_path):
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(conn, tmp_path)
        record = source_fixture(
            conn, staging_root=staging, approval=approval, rows=(native_row(),)
        )
        path = source_path(staging, approval, record)

        class Connection:
            change = False

            def execute(self, sql, *args, **kwargs):
                value = conn.execute(sql, *args, **kwargs)
                if self.change and sql.startswith(
                    f"CREATE TEMP TABLE {I.BOOTSTRAP_DAY_SOURCE} AS"
                ):
                    self.change = False
                    before = path.stat()
                    os.utime(
                        path,
                        ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000),
                    )
                return value

        wrapped = Connection()
        verification = context(wrapped, staging, approval, record)
        load(wrapped, staging, approval, record, verification)
        wrapped.change = True
        with pytest.raises(ValueError, match="本日物化期间改变"):
            load(wrapped, staging, approval, record, verification)
        verification.close()


def test_cached_path_cannot_be_replaced_by_symlink(tmp_path):
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(conn, tmp_path)
        record = source_fixture(
            conn, staging_root=staging, approval=approval, rows=(native_row(),)
        )
        verification = context(conn, staging, approval, record)
        load(conn, staging, approval, record, verification)
        path = source_path(staging, approval, record)
        outside = tmp_path / "outside.parquet"
        copy2(path, outside)
        path.unlink()
        path.symlink_to(outside)
        with pytest.raises(ValueError, match="符号链接"):
            load(conn, staging, approval, record, verification)
        verification.close()


def test_context_cannot_cross_connection_and_new_connection_rechecks(
    tmp_path, monkeypatch
):
    with connection(tmp_path) as conn, connection(tmp_path) as other:
        _, staging, approval, _ = approval_fixture(conn, tmp_path)
        record = source_fixture(
            conn, staging_root=staging, approval=approval, rows=(native_row(),)
        )
        verification = context(conn, staging, approval, record)
        load(conn, staging, approval, record, verification)
        full = count_full_checks(monkeypatch)
        with pytest.raises(ValueError, match="连接/operation/批准"):
            load(other, staging, approval, record, verification)
        fresh = context(other, staging, approval, record)
        load(other, staging, approval, record, fresh)
        assert len(full) == 1
        fresh.close()
        verification.close()


def test_context_cannot_cross_operation(tmp_path):
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(conn, tmp_path)
        record = source_fixture(
            conn, staging_root=staging, approval=approval, rows=(native_row(),)
        )
        verification = context(conn, staging, approval, record)
        load(conn, staging, approval, record, verification)
        _, _, other, _ = approval_fixture(conn, tmp_path, operation="other")
        other_record = source_fixture(
            conn, staging_root=staging, approval=other, rows=(native_row(),)
        )
        with pytest.raises(ValueError, match="连接/operation/批准"):
            load(conn, staging, other, other_record, verification)
        fresh = context(conn, staging, other, other_record)
        load(conn, staging, other, other_record, fresh)
        fresh.close()
        verification.close()


def test_context_cannot_cross_month_and_closed_context_cannot_be_reused(
    tmp_path, monkeypatch
):
    with connection(tmp_path) as conn:
        first, second = date(2019, 1, 31), date(2019, 2, 1)
        _, staging, approval, _ = approval_fixture(
            conn, tmp_path, counts=((first, 1), (second, 1))
        )
        records = tuple(
            source_fixture(
                conn,
                staging_root=staging,
                approval=approval,
                rows=(native_row(day=d),),
                day=d,
            )
            for d in (first, second)
        )
        verification = context(conn, staging, approval, records[0])
        load(conn, staging, approval, records[0], verification)
        with pytest.raises(ValueError, match="月份不符"):
            load(conn, staging, approval, records[1], verification)
        verification.close()
        assert not verification._entries
        with pytest.raises(ValueError, match="已关闭"):
            load(conn, staging, approval, records[0], verification)
        full = count_full_checks(monkeypatch)
        fresh = context(conn, staging, approval, records[1])
        load(conn, staging, approval, records[1], fresh)
        assert len(full) == 1
        fresh.close()


def test_writer_changed_during_real_readback_never_registers_success(
    tmp_path, monkeypatch
):
    with connection(tmp_path) as conn:
        _, staging, approval, _ = approval_fixture(conn, tmp_path)
        path = R.operation_path(
            staging,
            approval,
            "source/month=2019-10/attempt_id=" + "a" * 32 + "/fragment-000001.parquet",
        )
        frame = I.build_stk_factor_pro_raw_batch(
            rows=(native_row(),),
            source_fields=C.STK_FACTOR_PRO_SOURCE_COLUMNS,
            source="prod_postgres",
            expected_dates=(date(2019, 10, 16),),
        )
        original = I.describe_stk_factor_pro_fragment
        remembered = []

        def changed(conn, **kwargs):
            result = original(conn, **kwargs)
            before = kwargs["path"].stat()
            os.utime(
                kwargs["path"],
                ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000),
            )
            return result

        monkeypatch.setattr(I, "describe_stk_factor_pro_fragment", changed)
        with pytest.raises(ValueError, match="完整读回期间文件改变"):
            I.write_stk_factor_pro_raw_fragment(
                connection=conn,
                frame=frame,
                candidate_path=path,
                expected_row_count=1,
                on_verified_fragment=lambda **kwargs: remembered.append(kwargs),
            )
        assert not path.exists() and remembered == []
