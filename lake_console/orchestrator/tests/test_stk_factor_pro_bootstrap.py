"""Single bootstrap orchestration on temporary files and isolated dependencies."""

from datetime import date
from types import SimpleNamespace

import dagster as dg
import pytest

from orchestrator.defs.asset_guards.stk_factor_pro_readiness import (
    read_stk_factor_pro_other_active_runs,
    require_stk_factor_pro_no_other_active_runs,
)
from orchestrator.defs.bootstrap import stk_factor_pro_history as B
from orchestrator.defs.bootstrap.stk_factor_pro_bootstrap_records import (
    operation_path,
    read_json,
)
from orchestrator.defs.run_contracts import stk_factor_pro as C
from tests.stk_factor_pro_bootstrap_test_support import approval_fixture, native_row
from tests.stk_factor_pro_test_support import connection
from tests.test_stk_factor_pro_bootstrap_source import FakeProd


class Instance:
    def __init__(self):
        self.reads = []
        self.partitions = {"old-existing-key"}

    def get_run_records(self, *, filters, limit):
        self.reads.append((filters, limit))
        return []

    def add_dynamic_partitions(self, name, keys):
        assert name == C.STK_FACTOR_PRO_PARTITIONS
        self.partitions.update(keys)


class NoProd:
    def __getattr__(self, name):
        pytest.fail(f"local statistics attempted Prod {name}")


def test_full_named_source_to_raw_silver_summary_and_local_replay(tmp_path):
    # Missing all local market basis intentionally leaves coverage unknown;
    # it must never prevent faithful source import or invent open partitions.
    with connection(tmp_path) as conn:
        lake, staging, approval, identity = approval_fixture(conn, tmp_path)
        counts = ((date(2019, 10, 16), 1),)
        remote = FakeProd(approval, identity, counts, [native_row()])
        instance = Instance()
        args = {
            "lake_root": lake,
            "staging_root": staging,
            "operation_id": approval.operation_id,
            "instance": instance,
        }
        summary = B._run_stk_factor_pro_bootstrap(conn, prod_postgres=remote, **args)
        assert (
            summary.verified_source_rows
            == summary.verified_raw_rows
            == summary.verified_silver_rows
            == 1
        )
        assert summary.current_raw_rows == summary.current_silver_rows == 1
        assert (
            summary.total_missing_count is None and not summary.all_coverage_determined
        )
        assert (
            remote.connections == 1
            and sum(named for named, _, _ in remote.queries) == 1
        )
        assert len(instance.reads) == 4 and all(
            limit == 2 for _, limit in instance.reads
        )
        assert instance.partitions == {"old-existing-key"}
        result = read_json(
            operation_path(staging, approval, "coverage/2019-10-16/result.json"),
            C.StkFactorProBootstrapDateCoverage,
        )
        assert result.source_rows == result.raw_rows == result.silver_rows == 1
        assert result.coverage_complete is None
        old_reads = len(instance.reads)
        again = B._run_stk_factor_pro_bootstrap(conn, prod_postgres=NoProd(), **args)
        assert again.verified_source_rows == again.current_raw_rows == 1
        assert len(instance.reads) - old_reads == 2


@pytest.mark.parametrize("status", list(C.STK_FACTOR_PRO_ACTIVE_RUN_STATUSES))
def test_other_active_run_blocks_including_queue_and_cancel(status):
    class Busy(Instance):
        def get_run_records(self, *, filters, limit):
            assert (
                limit == 2 and filters.statuses == C.STK_FACTOR_PRO_ACTIVE_RUN_STATUSES
            )
            return [
                SimpleNamespace(
                    dagster_run=SimpleNamespace(
                        run_id="other", job_name=filters.job_name, status=status
                    )
                )
            ]

    with pytest.raises(dg.Failure, match="存在其他"):
        require_stk_factor_pro_no_other_active_runs(Busy())


def test_own_run_only_is_excluded_not_entire_job():
    class Busy(Instance):
        def get_run_records(self, *, filters, limit):
            return [
                SimpleNamespace(
                    dagster_run=SimpleNamespace(
                        run_id=run,
                        job_name=filters.job_name,
                        status=dg.DagsterRunStatus.STARTED,
                    )
                )
                for run in ("self", "other")
            ]

    active = read_stk_factor_pro_other_active_runs(Busy(), own_run_id="self")
    assert tuple(run.run_id for run in active) == ("other", "other")


def test_run_read_error_blocks_without_source(tmp_path):
    class Broken(Instance):
        def get_run_records(self, **kwargs):
            raise OSError("state unavailable")

    with connection(tmp_path) as conn:
        lake, staging, approval, _ = approval_fixture(conn, tmp_path)
        with pytest.raises(dg.Failure, match="无法确认"):
            B._run_stk_factor_pro_bootstrap(
                conn,
                lake_root=lake,
                staging_root=staging,
                operation_id=approval.operation_id,
                instance=Broken(),
                prod_postgres=NoProd(),
            )


def test_real_temporary_instance_partition_registration_is_idempotent(tmp_path):
    from datetime import timedelta

    from tests.test_stk_factor_pro_bootstrap_coverage import upstream

    first = date(2019, 10, 15)
    days = tuple(first + timedelta(days=i) for i in range(3))
    counts = ((days[0], 1), (days[1], 0), (days[2], 1))
    with connection(tmp_path) as conn, dg.DagsterInstance.ephemeral() as instance:
        lake, staging, approval, identity = approval_fixture(
            conn, tmp_path, counts=counts
        )
        upstream(
            conn,
            lake,
            days=days,
            codes=("000001.SZ",),
            calendar=[("SSE", d, True, None) for d in days[:2]],
        )
        instance.add_dynamic_partitions(C.STK_FACTOR_PRO_PARTITIONS, ["2010-01-01"])
        remote = FakeProd(
            approval,
            identity,
            counts,
            [native_row(day=days[0]), native_row(day=days[2])],
            sample_rows=[native_row(day=days[0])],
        )
        args = {
            "lake_root": lake,
            "staging_root": staging,
            "operation_id": approval.operation_id,
            "instance": instance,
        }
        result = B._run_stk_factor_pro_bootstrap(conn, prod_postgres=remote, **args)
        expected = {"2010-01-01", days[0].isoformat(), days[1].isoformat()}
        assert (
            set(instance.get_dynamic_partitions(C.STK_FACTOR_PRO_PARTITIONS))
            == expected
        )
        assert (
            days[1] in result.source_empty_dates
            and days[2] in result.calendar_unknown_dates
        )
        B._run_stk_factor_pro_bootstrap(conn, prod_postgres=NoProd(), **args)
        assert (
            set(instance.get_dynamic_partitions(C.STK_FACTOR_PRO_PARTITIONS))
            == expected
        )
