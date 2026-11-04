"""LLD 17.8.2 integration: real operation guard, bounded temporary files.

Prod transport is the existing DATE/float FakeProd. Capacity alone is injected;
source conversion, 261-column Parquet, publication and record reads remain real.
Byte expectations are literal arithmetic from the approved LLD, never generated
by estimate_bootstrap_space or by the operation guard being tested.
"""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_publication as P
from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_records as R
from orchestrator.defs.bootstrap import stk_factor_pro_history as B
from orchestrator.defs.io.stk_factor_pro_candidates import BOOTSTRAP_DAY_SOURCE
from orchestrator.defs.run_contracts import stk_factor_pro as C
from tests.stk_factor_pro_bootstrap_test_support import (
    approval_fixture,
    bootstrap_date_results,
    check_test_space,
    native_row,
    source_fixture,
)
from tests.stk_factor_pro_test_support import connection
from tests.test_stk_factor_pro_bootstrap import Instance, NoProd
from tests.test_stk_factor_pro_bootstrap_coverage import supplement_audits
from tests.test_stk_factor_pro_bootstrap_publication import (
    release_date_work,
    restore_source_context,
)
from tests.test_stk_factor_pro_bootstrap_source import FakeProd

DAY = date(2019, 10, 16)


def _setup(conn, tmp_path, counts, *, known_records):
    lake, staging, approval, identity = approval_fixture(
        conn, tmp_path, counts=counts, known_records=known_records
    )
    return (
        {
            "lake_root": lake,
            "staging_root": staging,
            "operation_id": approval.operation_id,
            "instance": Instance(),
        },
        approval,
        identity,
    )


def _root(args, approval):
    return R.operation_root(args["staging_root"], approval)


def _formal(args, day, layer):
    relative = (
        ("raw", "tushare", "stk_factor_pro")
        if layer == "raw"
        else ("silver", "stock_factor_pro")
    )
    return args["lake_root"].joinpath(*relative, f"trade_date={day}", "data.parquet")


def _guard(conn, args, approval, counts, *, trusted=None, known_records):
    classified = {
        day: B._classify_date(
            conn,
            lake_root=args["lake_root"],
            staging_root=args["staging_root"],
            approval=approval,
            day=day,
            trusted={} if trusted is None else trusted,
            known_records=known_records,
        )
        for day, _ in counts
    }
    return B._bootstrap_space_check(
        conn,
        lake_root=args["lake_root"],
        staging_root=args["staging_root"],
        approval=approval,
        counts=dict(counts),
        classified=classified,
        known_records=known_records,
    )


def _source(conn, args, approval, rows, *, day=DAY, attempt="a" * 32, known_records):
    return source_fixture(
        conn,
        staging_root=args["staging_root"],
        approval=approval,
        rows=rows,
        day=day,
        attempt=attempt,
        known_records=known_records,
    )


def _publish(
    conn, args, approval, source, *, guard=check_test_space, known_records, date_results
):
    with R.resource_cleanup(lambda: release_date_work(conn)):
        return P.publish_bootstrap_date(
            conn,
            lake_root=args["lake_root"],
            staging_root=args["staging_root"],
            approval=approval,
            source_complete=source,
            source_record_sha256=known_records[
                R.operation_path(
                    args["staging_root"],
                    approval,
                    f"source/dates/{source.trade_date}/source-complete.json",
                )
            ][1],
            source_relation=BOOTSTRAP_DAY_SOURCE,
            before_publish=lambda: None,
            check_space=guard,
            known_records=known_records,
            date_results=bootstrap_date_results(date_results, source),
        )


def test_zero_free_space_blocks_before_any_prod_detail_read(tmp_path, monkeypatch):
    known_records = {}
    with connection(tmp_path) as conn:
        args, approval, identity = _setup(
            conn, tmp_path, ((DAY, 1),), known_records=known_records
        )
        remote = FakeProd(approval, identity, ((DAY, 1),), [native_row()])
        monkeypatch.setattr(R.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
        with pytest.raises(ValueError, match="空间不足.*阶段=读取前核磁盘空间"):
            B._run_stk_factor_pro_bootstrap(conn, prod_postgres=remote, **args)
        assert remote.connections == 0 and remote.queries == []
        assert remote.fetch_sizes == []
        assert not list(_root(args, approval).rglob("fragment-*.parquet"))
        assert not _formal(args, DAY, "raw").exists()
        assert not _formal(args, DAY, "silver").exists()


def test_space_drop_after_first_date_keeps_it_and_stops_next_date(
    tmp_path, monkeypatch
):
    known_records = {}
    following = DAY + timedelta(days=1)
    counts = ((DAY, 1), (following, 1))
    with connection(tmp_path) as conn:
        args, approval, identity = _setup(
            conn, tmp_path, counts, known_records=known_records
        )
        remote = FakeProd(
            approval, identity, counts, [native_row(), native_row(day=following)]
        )
        first_result = _root(args, approval) / f"coverage/{DAY}/result.json"
        monkeypatch.setattr(
            R.shutil,
            "disk_usage",
            lambda _: SimpleNamespace(free=0 if first_result.exists() else 10**12),
        )
        with pytest.raises(ValueError, match="空间不足"):
            B._run_stk_factor_pro_bootstrap(conn, prod_postgres=remote, **args)
        assert first_result.is_file()
        for layer in ("raw", "silver"):
            assert conn.execute(
                "SELECT close FROM read_parquet(?,hive_partitioning=false)",
                [str(_formal(args, DAY, layer))],
            ).fetchone() == (10.0,)
            assert not _formal(args, following, layer).exists()
        assert remote.fetch_sizes == [3]
        assert remote.closes == ["named", "control", "rollback", "connection"]
        assert (
            R.read_stk_factor_pro_bootstrap_source_complete(
                conn,
                staging_root=args["staging_root"],
                approval=approval,
                trade_date=DAY,
                known_records=known_records,
            )
            is not None
        )
        assert (
            R.read_stk_factor_pro_bootstrap_source_complete(
                conn,
                staging_root=args["staging_root"],
                approval=approval,
                trade_date=following,
                known_records=known_records,
            )
            is None
        )


def test_half_day_left_on_disk_is_not_reused_by_new_attempt(tmp_path, monkeypatch):
    known_records = {}
    counts = ((DAY, 3),)
    rows = [native_row(f"{number:06d}.SZ") for number in (1, 2, 3)]
    monkeypatch.setattr(C, "STK_FACTOR_PRO_BOOTSTRAP_FETCH_ROWS", 1)
    with connection(tmp_path) as conn:
        args, approval, identity = _setup(
            conn, tmp_path, counts, known_records=known_records
        )
        root = _root(args, approval)
        first = FakeProd(approval, identity, counts, rows, sample_rows=[rows[0]])
        monkeypatch.setattr(
            R.shutil,
            "disk_usage",
            lambda _: SimpleNamespace(
                free=0 if list(root.rglob("fragment-*.parquet")) else 10**12
            ),
        )
        with pytest.raises(ValueError, match="空间不足"):
            B._run_stk_factor_pro_bootstrap(conn, prod_postgres=first, **args)
        fragments = list(root.rglob("fragment-*.parquet"))
        assert len(fragments) == 1 and first.fetch_sizes == [1]
        (old_fragment,) = fragments
        old_bytes = old_fragment.read_bytes()
        assert (
            R.read_stk_factor_pro_bootstrap_source_complete(
                conn,
                staging_root=args["staging_root"],
                approval=approval,
                trade_date=DAY,
                known_records=known_records,
            )
            is None
        )
        monkeypatch.setattr(
            R.shutil, "disk_usage", lambda _: SimpleNamespace(free=10**12)
        )
        second = FakeProd(approval, identity, counts, rows, sample_rows=[rows[0]])
        summary = B._run_stk_factor_pro_bootstrap(conn, prod_postgres=second, **args)
        assert summary.verified_source_rows == summary.current_raw_rows == 3
        assert old_fragment.read_bytes() == old_bytes
        saved = R.read_stk_factor_pro_bootstrap_source_complete(
            conn,
            staging_root=args["staging_root"],
            approval=approval,
            trade_date=DAY,
            known_records={},
        )
        assert saved.actual_rows == 3 and len(saved.fragments) == 3
        assert all(
            reference.fragment.relative_path
            != old_fragment.relative_to(root).as_posix()
            for reference in saved.fragments
        )
        assert second.fetch_sizes == [1, 1, 1, 1]
        assert len([query for query in second.queries if query[0]]) == 1
        assert conn.execute(
            "SELECT ts_code FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
            [str(_formal(args, DAY, "raw"))],
        ).fetchall() == [("000001.SZ",), ("000002.SZ",), ("000003.SZ",)]


def test_guard_reserves_all_ten_dates_of_formal_files(tmp_path, monkeypatch):
    known_records = {}
    counts = tuple((DAY + timedelta(days=i), 1) for i in range(10))
    monkeypatch.setattr(R.shutil, "disk_usage", lambda _: SimpleNamespace(free=10**12))
    with connection(tmp_path) as conn:
        args, approval, _ = _setup(conn, tmp_path, counts, known_records=known_records)
        guard = _guard(conn, args, approval, counts, known_records=known_records)
        actual = guard("读取前", path=_root(args, approval))
        assert actual == R.BootstrapSpaceEstimate(
            source_bytes=4_236_084,
            candidate_bytes=83_969_640,
            temp_bytes=50_532_192,
            record_bytes=11_534_336,
        )


def test_completed_date_source_rows_are_excluded_only_once(tmp_path, monkeypatch):
    date_results = {}
    known_records = {}
    following = DAY + timedelta(days=1)
    counts = ((DAY, 1), (following, 1))
    monkeypatch.setattr(R.shutil, "disk_usage", lambda _: SimpleNamespace(free=10**12))
    with connection(tmp_path) as conn:
        args, approval, _ = _setup(conn, tmp_path, counts, known_records=known_records)
        complete = _source(
            conn, args, approval, (native_row(),), known_records=known_records
        )
        _publish(
            conn,
            args,
            approval,
            complete,
            known_records=known_records,
            date_results=date_results,
        )
        guard = _guard(conn, args, approval, counts, known_records=known_records)
        initial = guard("剩余B日读取前", path=_root(args, approval))
        assert initial.source_bytes == 4_198_482
        remaining = _source(
            conn,
            args,
            approval,
            (native_row(day=following),),
            day=following,
            attempt="b" * 32,
            known_records=known_records,
        )
        path = R.operation_path(
            args["staging_root"],
            approval,
            remaining.fragments[0].fragment.relative_path,
        )
        after = guard(
            "B源已保存",
            path=path,
            rows=1,
            month_start=approval.month_limits[0].month_start,
            event="source_saved",
        )
        assert after.source_bytes == 0
        with pytest.raises(ValueError, match="重复扣减"):
            guard(
                "不能重复减B",
                path=path,
                rows=1,
                month_start=approval.month_limits[0].month_start,
                event="source_saved",
            )


def test_verified_candidates_do_not_end_two_layer_work_before_publication(
    tmp_path, monkeypatch
):
    date_results = {}
    known_records = {}
    counts = ((DAY, 3),)
    monkeypatch.setattr(R.shutil, "disk_usage", lambda _: SimpleNamespace(free=10**12))
    with connection(tmp_path) as conn:
        args, approval, _ = _setup(conn, tmp_path, counts, known_records=known_records)
        source = _source(
            conn,
            args,
            approval,
            tuple(native_row(f"{n:06d}.SZ") for n in (1, 2, 3)),
            known_records=known_records,
        )
        guard = _guard(conn, args, approval, counts, known_records=known_records)
        first = guard("完整源复用", path=_root(args, approval), trade_date=DAY)
        assert first.source_bytes == 0 and first.temp_bytes == 33_654_704
        checked = []
        original = R.require_bootstrap_space

        def record(**keywords):
            checked.append((keywords["stage"], keywords["estimate"]))
            return original(**keywords)

        monkeypatch.setattr(R, "require_bootstrap_space", record)
        _publish(
            conn,
            args,
            approval,
            source,
            guard=guard,
            known_records=known_records,
            date_results=date_results,
        )
        candidates = [
            estimate for stage, estimate in checked if stage == "候选完整检查通过"
        ]
        assert len(candidates) == 2
        assert [value.candidate_bytes for value in candidates] == [4_206_838, 0]
        assert [value.temp_bytes for value in candidates] == [33_654_704, 33_654_704]


def test_original_empty_source_current_five_rows_have_real_statistics_budget(
    tmp_path, monkeypatch
):
    # Real source approval has nonempty first/last dates. Its middle zero day
    # may later acquire five rows through an independently checked supplement.
    date_results = {}
    known_records = {}
    counts = ((DAY - timedelta(days=1), 1), (DAY, 0), (DAY + timedelta(days=1), 1))
    monkeypatch.setattr(R.shutil, "disk_usage", lambda _: SimpleNamespace(free=10**12))
    with connection(tmp_path) as conn:
        args, approval, _ = _setup(conn, tmp_path, counts, known_records=known_records)
        _source(conn, args, approval, (), known_records=known_records)
        for neighbor in (counts[0][0], counts[2][0]):
            saved = _source(
                conn,
                args,
                approval,
                (native_row(day=neighbor),),
                day=neighbor,
                attempt=neighbor.strftime("%Y%m%d") + "b" * 24,
                known_records=known_records,
            )
            _publish(
                conn,
                args,
                approval,
                saved,
                known_records=known_records,
                date_results=date_results,
            )
        raw, silver = supplement_audits(
            conn,
            {"trade_date": DAY, "lake_root": args["lake_root"]},
            tuple(f"{number:06d}.SZ" for number in (1, 2, 3, 4, 5)),
            known_records=known_records,
        )
        publication = C.StkFactorProBootstrapCurrentPublication(
            "supplement-run",
            DAY,
            11,
            12,
            13,
            14,
            raw.file_sha256,
            silver.file_sha256,
            raw.file_sha256,
            approval.contract_content_digest,
            "1",
        )
        guard = _guard(
            conn,
            args,
            approval,
            counts,
            trusted={DAY: (publication, raw, silver)},
            known_records=known_records,
        )
        root = _root(args, approval)
        expected = R.BootstrapSpaceEstimate(0, 0, 16_860_776, 4_194_304)
        assert guard("本地统计", path=root, trade_date=DAY) == expected
        assert guard("空缺失明细", path=root, trade_date=DAY, rows=0) == expected
        assert guard("一条差集", path=root, trade_date=DAY, rows=1) == expected
        summary = B._run_stk_factor_pro_bootstrap(
            conn,
            prod_postgres=NoProd(),
            current_publications=((publication, raw, silver),),
            **args,
        )
        assert summary.verified_source_rows == 2
        assert summary.current_raw_rows == summary.current_silver_rows == 7
        middle = R.read_json(
            root / f"coverage/{DAY}/result.json",
            C.StkFactorProBootstrapDateCoverage,
            known_records={},
        )
        assert middle.source_rows == 0 and middle.raw_rows == middle.silver_rows == 5


def test_record_growth_is_observed_and_present_bytes_not_reserved_twice(
    tmp_path, monkeypatch
):
    # This file exercises only the capacity ledger, not record/schema validation.
    known_records = {}
    counts = ((DAY, 1), (DAY + timedelta(days=1), 1))
    monkeypatch.setattr(R.shutil, "disk_usage", lambda _: SimpleNamespace(free=10**12))
    with connection(tmp_path) as conn:
        args, approval, _ = _setup(conn, tmp_path, counts, known_records=known_records)
        guard = _guard(conn, args, approval, counts, known_records=known_records)
        root = _root(args, approval)
        assert guard("初始记录估算", path=root).record_bytes == 3_145_728
        path = root / "coverage" / str(DAY) / "large.json"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"x" * 2_097_152)
        observed = guard("已保存记录", path=path, trade_date=DAY, event="record_saved")
        # Three remaining groups * 2MiB, less the 2MiB already present.
        assert observed.record_bytes == 4_194_304
        assert (
            guard("未变记录再次核验", path=path, trade_date=DAY).record_bytes
            == 4_194_304
        )


def test_final_summary_reserves_one_record_without_business_work(tmp_path, monkeypatch):
    known_records = {}
    seen = []
    original = R.require_bootstrap_space

    def record(**kwargs):
        seen.append((kwargs["stage"], kwargs["estimate"]))
        return original(**kwargs)

    monkeypatch.setattr(R, "require_bootstrap_space", record)
    with connection(tmp_path) as conn:
        args, approval, identity = _setup(
            conn, tmp_path, ((DAY, 1),), known_records=known_records
        )
        B._run_stk_factor_pro_bootstrap(
            conn,
            prod_postgres=FakeProd(approval, identity, ((DAY, 1),), [native_row()]),
            **args,
        )
        final = [value for stage, value in seen if stage == "最终统计准备前"]
        assert len(final) == 1
        assert final[0].source_bytes == final[0].candidate_bytes == 0
        # LLD 17.8.2: summary consumes held totals, without data or temp work.
        assert final[0].temp_bytes == 0
        assert final[0].record_bytes == 1_048_576


def test_expected_target_after_replace_without_complete_is_not_reserved_twice(
    tmp_path, monkeypatch
):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args, approval, _ = _setup(
            conn, tmp_path, ((DAY, 1),), known_records=known_records
        )
        source = _source(
            conn, args, approval, (native_row(),), known_records=known_records
        )
        original = P.write_stk_factor_pro_bootstrap_publication_complete

        def fail_raw(**kwargs):
            if kwargs["record"].layer == "raw":
                raise OSError("complete not saved")
            return original(**kwargs)

        monkeypatch.setattr(
            P, "write_stk_factor_pro_bootstrap_publication_complete", fail_raw
        )
        with pytest.raises(OSError, match="complete not saved"):
            _publish(
                conn,
                args,
                approval,
                source,
                known_records=known_records,
                date_results=date_results,
            )
        monkeypatch.setattr(
            P, "write_stk_factor_pro_bootstrap_publication_complete", original
        )
        known_records, date_results, restored = restore_source_context(
            conn, {**args, "approval": approval, "source_complete": source}
        )
        source = restored["source_complete"]
        guard = _guard(conn, args, approval, ((DAY, 1),), known_records=known_records)
        budget = guard(
            "原目标已提升但完成记录未写", path=_root(args, approval), trade_date=DAY
        )
        assert budget.source_bytes == 0
        assert budget.candidate_bytes == 4_198_482  # Only Silver still needs a file.
        assert (
            budget.temp_bytes == 33_587_856
        )  # Both layers still require recovery work.
        raw, silver = _publish(
            conn,
            args,
            approval,
            source,
            guard=guard,
            known_records=known_records,
            date_results=date_results,
        )
        assert raw.passed and silver.passed


def test_final_summary_keeps_only_record_budget_without_reading_5000_rows(
    tmp_path, monkeypatch
):
    # Arithmetic-only accepted facts deliberately stand in for completed files.
    # This does not claim those files have been imported or verified.
    known_records = {}
    earlier, later = date(2019, 1, 31), date(2019, 2, 1)
    counts = ((earlier, 5000), (later, 1))
    monkeypatch.setattr(R.shutil, "disk_usage", lambda _: SimpleNamespace(free=10**12))
    with connection(tmp_path) as conn:
        args, approval, _ = _setup(conn, tmp_path, counts, known_records=known_records)
        guard = B._bootstrap_space_check(
            conn,
            lake_root=args["lake_root"],
            staging_root=args["staging_root"],
            approval=approval,
            counts=dict(counts),
            classified={
                d: {
                    "source_complete": SimpleNamespace(actual_rows=n),
                    "current_files_verified": True,
                    "current_publication": None,
                }
                for d, n in counts
            },
            known_records=known_records,
        )
        root = _root(args, approval)
        assert guard("最后月份", path=root, month_start=later).temp_bytes == 16_793_928
        final = guard("最终汇总", path=root, event="final_statistics")
        assert (
            final.source_bytes,
            final.candidate_bytes,
            final.temp_bytes,
            final.record_bytes,
        ) == (
            0,
            0,
            0,
            1_048_576,
        )


def test_record_observation_does_not_reject_persisted_fact_and_next_write_checks(
    tmp_path, monkeypatch
):
    known_records = {}
    with connection(tmp_path) as conn:
        args, approval, _ = _setup(
            conn, tmp_path, ((DAY, 1),), known_records=known_records
        )
        guard = _guard(conn, args, approval, ((DAY, 1),), known_records=known_records)
        path = _root(args, approval) / "coverage" / str(DAY) / "size-observation.json"
        path.parent.mkdir(parents=True)
        path.write_text("{}")
        monkeypatch.setattr(R.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
        # The just-written file is a fact, never another pending write.
        observed = guard(
            "只观察已保存记录", path=path, trade_date=DAY, event="record_saved"
        )
        assert observed.record_bytes == 2_097_150
        with pytest.raises(ValueError, match="空间不足"):
            guard("下一写入前", path=path, trade_date=DAY)
