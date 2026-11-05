"""Coverage/readiness through real temporary files and native bound events.

Inputs use the existing lifecycle/identity/suspend producer-schema fixture and
actual day publication. Literal expected sets are independent of that writer.
"""

from datetime import timedelta
from unittest.mock import patch

import dagster as dg
import pytest
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.asset_guards import stk_factor_pro_readiness as R
from orchestrator.defs.io.stk_factor_pro_history import (
    write_stk_factor_pro_missing_codes,
)
from orchestrator.defs.run_contracts import stk_factor_pro as C
from tests.stk_factor_pro_test_support import DAY, connection, row
from tests.test_stk_factor_pro_bootstrap_coverage import upstream
from tests.test_stk_factor_pro_dagster_events import _isolated_instance
from tests.test_stk_factor_pro_publication import roots, run_day

A, B, D = "000001.SZ", "600000.SH", "000002.SZ"


def events(instance, audits, raw_sha):
    @dg.op(out={})
    def operation(context):
        for target, audit in audits:
            asset = (
                C.STK_FACTOR_PRO_RAW_ASSET_KEY
                if audit.layer == "raw"
                else C.STK_FACTOR_PRO_SILVER_ASSET_KEY
            )
            check_name = (
                C.STK_FACTOR_PRO_RAW_CHECK_NAME
                if audit.layer == "raw"
                else C.STK_FACTOR_PRO_SILVER_CHECK_NAME
            )
            metadata = {
                "goldenshare/file_path": str(audit.path),
                "goldenshare/file_sha256": audit.file_sha256,
                "goldenshare/contract_content_digest": C.STK_FACTOR_PRO_CONTRACT_CONTENT_DIGEST,
                "goldenshare/processing_version": "1",
            }
            if audit.layer == "silver":
                metadata["goldenshare/raw_sha256"] = raw_sha
            yield dg.AssetMaterialization(
                asset_key=asset, partition=str(DAY), metadata=metadata
            )
            record = context.instance.get_records_for_run(
                context.run_id,
                of_type=dg.DagsterEventType.ASSET_MATERIALIZATION,
                limit=1,
                ascending=False,
            ).records[0]
            yield AssetCheckEvaluation(
                asset_key=dg.AssetKey(asset),
                check_name=check_name,
                passed=audit.passed,
                blocking=True,
                partition=str(DAY),
                metadata=metadata,
                severity=dg.AssetCheckSeverity.ERROR,
                target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                    storage_id=record.storage_id,
                    run_id=context.run_id,
                    timestamp=record.timestamp,
                ),
            )

    @dg.job
    def job():
        operation()

    assert job.execute_in_process(instance=instance).success


def test_single_day_preparation_and_missing_codes_are_reused(tmp_path):
    lake, staging = roots(tmp_path)
    known, facts = {}, {}
    with connection(tmp_path) as conn:
        upstream(
            conn,
            lake,
            days=(DAY,),
            codes=(A, B, D),
            suspensions={DAY: [(D, DAY, None, "S")]},
        )
        with patch.object(R, "factor_file_sha", wraps=R.factor_file_sha) as hashes:
            prepared = R.prepare_stk_factor_pro_coverage_inputs(
                conn,
                lake_root=lake,
                trade_date=DAY,
                inherited_facts=facts,
                known_records=known,
            )
            assert prepared["unknown_input_kinds"] == ()
            assert prepared["is_open"] is True
            assert hashes.call_count == 4
            assert (
                R.prepare_stk_factor_pro_coverage_inputs(
                    conn,
                    lake_root=lake,
                    trade_date=DAY,
                    inherited_facts=facts,
                    known_records=known,
                )
                is prepared
            )
            assert hashes.call_count == 4
        conn.execute("CREATE TEMP TABLE sample(trade_date VARCHAR,ts_code VARCHAR)")
        conn.execute("INSERT INTO sample VALUES (?,?)", [DAY.strftime("%Y%m%d"), A])
        calculated = R.calculate_stk_factor_pro_coverage(
            conn, coverage_inputs=prepared, raw_relation="sample"
        )
        counts = calculated["coverage_counts"]
        assert (
            counts.expected_count,
            counts.actual_count,
            counts.missing_count,
            counts.extra_count,
        ) == (2, 1, 1, 0)
        coverage = C.StkFactorProRawCoverage(
            DAY,
            False,
            False,
            None,
            None,
            None,
            None,
            2,
            1,
            1,
            (),
            "缺一股",
            None,
            None,
            None,
        )
        identity = C.RunIdentity(
            "diagnostic-run",
            None,
            DAY,
            DAY,
            DAY - timedelta(days=1),
            "today",
            0,
            None,
            None,
        )
        saved = write_stk_factor_pro_missing_codes(
            conn,
            staging_root=staging,
            identity=identity,
            coverage=coverage,
            calculated=calculated,
            known_records=known,
        )
        assert saved.missing_sample_codes == (B,)
        assert calculated["missing_sample_codes"] == (B,)
        with patch(
            "orchestrator.defs.io.stk_factor_pro_history.factor_file_sha",
            side_effect=AssertionError("repeat SHA"),
        ):
            assert (
                write_stk_factor_pro_missing_codes(
                    conn,
                    staging_root=staging,
                    identity=identity,
                    coverage=saved,
                    calculated=calculated,
                    known_records=known,
                )
                is saved
            )
        R.release_stk_factor_pro_coverage_inputs(conn, inherited_facts=facts)
        assert all(not f["owned"] for f in facts.values())


def test_real_bound_checks_are_reused_and_silver_matches_current_raw(tmp_path):
    lake, staging = roots(tmp_path)
    known, facts = {}, {}
    with connection(tmp_path) as conn, _isolated_instance(tmp_path) as instance:
        upstream(conn, lake, days=(DAY,), codes=(A,))
        audits, _ = run_day(conn, lake, staging, (row(),), known_records=known)
        raw, silver = audits[0][1], audits[1][1]
        events(instance, audits, raw.file_sha256)
        inputs = R.prepare_stk_factor_pro_coverage_inputs(
            conn,
            lake_root=lake,
            trade_date=DAY,
            inherited_facts=facts,
            known_records=known,
        )
        conn.execute(
            "CREATE TEMP TABLE current_raw(trade_date VARCHAR,ts_code VARCHAR)"
        )
        conn.execute(
            "INSERT INTO current_raw VALUES (?,?)", [DAY.strftime("%Y%m%d"), A]
        )
        calc = R.calculate_stk_factor_pro_coverage(
            conn, coverage_inputs=inputs, raw_relation="current_raw"
        )
        pg = {}
        coverage = R.evaluate_stk_factor_pro_raw_coverage(
            instance,
            conn,
            lake_root=lake,
            target_trade_date=DAY,
            known_pg=pg,
            known_records=known,
            calculated=calc,
            verified_raw_audit=raw,
        )
        assert coverage.complete is True and coverage.raw_check_passed is True
        assert coverage.missing_count == 0
        assert (
            coverage.raw_check_storage_id
            == pg[
                (
                    "check_execution",
                    C.STK_FACTOR_PRO_RAW_ASSET_KEY,
                    C.STK_FACTOR_PRO_RAW_CHECK_NAME,
                    DAY,
                )
            ].id
        )
        result = R.evaluate_stk_factor_pro_target_silver(
            instance,
            lake_root=lake,
            raw_coverage=coverage,
            known_pg=pg,
            known_records=known,
            verified_silver_audit=silver,
        )
        assert result.ready is True
        assert (
            result.current_raw_file_sha256
            == result.source_raw_file_sha256
            == raw.file_sha256
        )
        with (
            patch.object(
                instance,
                "fetch_materializations",
                side_effect=AssertionError("repeat PG"),
            ),
            patch.object(
                R, "factor_file_sha", side_effect=AssertionError("repeat SHA")
            ),
        ):
            assert R.evaluate_stk_factor_pro_target_silver(
                instance,
                lake_root=lake,
                raw_coverage=coverage,
                known_pg=pg,
                known_records=known,
                verified_silver_audit=silver,
            ).ready
        R.release_stk_factor_pro_coverage_inputs(conn, inherited_facts=facts)


def test_missing_upstream_is_unknown_and_zero_diagnostic_does_not_write(tmp_path):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        facts, known = {}, {}
        inputs = R.prepare_stk_factor_pro_coverage_inputs(
            conn,
            lake_root=lake,
            trade_date=DAY,
            inherited_facts=facts,
            known_records=known,
        )
        calculated = R.calculate_stk_factor_pro_coverage(
            conn, coverage_inputs=inputs, raw_relation=None
        )
        assert calculated["coverage_counts"] is None
        assert set(calculated["unknown_input_kinds"]) == {
            "calendar",
            "lifecycle",
            "identity",
            "suspend",
        }
        coverage = C.StkFactorProRawCoverage(
            DAY,
            None,
            False,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            (),
            "未知",
            None,
            None,
            None,
        )
        identity = C.RunIdentity(
            "run-a", None, DAY, DAY, DAY - timedelta(days=1), "today", 0, None, None
        )
        assert (
            write_stk_factor_pro_missing_codes(
                conn,
                staging_root=staging,
                identity=identity,
                coverage=coverage,
                calculated=None,
                known_records=known,
            )
            is coverage
        )
        assert list(staging.rglob("*.parquet")) == []
        with pytest.raises(dg.Failure, match="原日期数据缺失"):
            R.require_stk_factor_pro_history_raw(coverage)


def test_raw_only_publication_leaves_old_silver_ineligible(tmp_path):
    # Real interrupted publication: the new Raw is committed and its check is
    # persisted, while Silver remains the previous day's version for the same T.
    from orchestrator.defs.io.stk_factor_pro_candidates import (
        release_stk_factor_pro_day_source,
    )
    from orchestrator.defs.io.stk_factor_pro_download import download_stk_factor_pro_day
    from orchestrator.defs.io.stk_factor_pro_publication import (
        publish_stk_factor_pro_day,
    )
    from tests.stk_factor_pro_test_support import Downloader, contract, identity, result

    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn, _isolated_instance(tmp_path) as instance:
        old_known = {}
        old, _ = run_day(conn, lake, staging, (row(),), known_records=old_known)
        events(instance, old, old[0][1].file_sha256)
        known = {}
        source = download_stk_factor_pro_day(
            conn,
            identity=identity("raw-only"),
            contract=contract(),
            downloader=Downloader(result((row(close=12),))),
            check_cancel=lambda: None,
        )
        publisher = publish_stk_factor_pro_day(
            conn,
            source=source,
            lake_root=lake,
            staging_root=staging,
            check_cancel=lambda: None,
            known_records=known,
        )
        try:
            raw_target, raw_audit = next(publisher)
        finally:
            publisher.close()
            release_stk_factor_pro_day_source(conn)
        assert raw_audit.file_sha256 != old[0][1].file_sha256
        events(instance, [(raw_target, raw_audit)], raw_audit.file_sha256)
        raw_coverage = C.StkFactorProRawCoverage(
            DAY,
            True,
            True,
            raw_audit.file_sha256,
            "a" * 64,
            "b" * 64,
            "c" * 64,
            1,
            1,
            0,
            (),
            "已齐",
            1,
            2,
            None,
        )
        silver = R.evaluate_stk_factor_pro_target_silver(
            instance,
            lake_root=lake,
            raw_coverage=raw_coverage,
            known_pg={},
            known_records=known,
        )
        assert not silver.ready
        assert "Raw已过期" in silver.reason
        with pytest.raises(dg.Failure, match="原日期Silver不可用"):
            R.require_stk_factor_pro_history_silver(silver)


def test_same_files_new_native_checks_do_not_recalculate_coverage(tmp_path):
    from dataclasses import replace

    lake, staging = roots(tmp_path)
    known, facts = {}, {}
    with connection(tmp_path) as conn, _isolated_instance(tmp_path) as instance:
        upstream(conn, lake, days=(DAY,), codes=(A,))
        audits, _ = run_day(conn, lake, staging, (row(),), known_records=known)
        events(instance, audits, audits[0][1].file_sha256)
        inputs = R.prepare_stk_factor_pro_coverage_inputs(
            conn,
            lake_root=lake,
            trade_date=DAY,
            inherited_facts=facts,
            known_records=known,
        )
        conn.execute(
            "CREATE TEMP TABLE single_raw AS SELECT ?::VARCHAR trade_date,?::VARCHAR ts_code",
            [DAY.strftime("%Y%m%d"), A],
        )
        calc = R.calculate_stk_factor_pro_coverage(
            conn, coverage_inputs=inputs, raw_relation="single_raw"
        )
        coverage = R.evaluate_stk_factor_pro_raw_coverage(
            instance,
            conn,
            lake_root=lake,
            target_trade_date=DAY,
            known_pg={},
            known_records=known,
            calculated=calc,
            verified_raw_audit=audits[0][1],
        )
        events(instance, audits, audits[0][1].file_sha256)
        previous = replace(
            C.empty_stk_factor_pro_recorded_results(DAY), raw_coverage=coverage
        )
        pg = {("recorded_results", DAY): previous}
        with patch.object(
            R,
            "_build_stk_factor_pro_coverage_keys",
            side_effect=AssertionError("repeat coverage"),
        ):
            reused = R.evaluate_stk_factor_pro_raw_coverage(
                instance,
                conn,
                lake_root=lake,
                target_trade_date=DAY,
                known_pg=pg,
                known_records=known,
                calculated=None,
                verified_raw_audit=audits[0][1],
            )
        assert reused.complete is True
        assert (
            reused.raw_materialization_storage_id
            != coverage.raw_materialization_storage_id
        )
        assert reused.raw_check_storage_id != coverage.raw_check_storage_id
        assert reused.expected_count == reused.actual_count == 1
        R.release_stk_factor_pro_coverage_inputs(conn, inherited_facts=facts)
