import hashlib
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

import duckdb

from orchestrator.defs.bootstrap.wealth_market_turnover_history import (
    WEALTH_MARKET_TURNOVER_HISTORY_AUDIT_SECONDS_LIMIT,
    WealthMarketTurnoverFrequencyAction,
    audit_wealth_market_turnover_history,
    audit_wealth_market_turnover_history_candidates,
    build_wealth_market_turnover_history_candidates,
    plan_wealth_market_turnover_history,
    promote_wealth_market_turnover_history_candidates,
    publish_wealth_market_turnover_history_to_prod,
    wealth_market_turnover_history_plan_from_dict,
)
from orchestrator.defs.paths import (
    gold_wealth_market_turnover_path,
    silver_stk_mins_path,
    silver_stock_daily_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_FREQS
from orchestrator.defs.wealth_market_turnover_contract import (
    wealth_market_turnover_canonical_rows,
    wealth_market_turnover_source_paths,
    write_gold_wealth_market_turnover_partition,
)

DATE_1 = "2026-06-22"
DATE_2 = "2026-06-23"


class WealthMarketTurnoverHistoryBootstrapTests(unittest.TestCase):
    def test_history_helpers_are_staged_and_do_not_write_dagster_events(self) -> None:
        helper_paths = (
            Path("src/orchestrator/defs/bootstrap/wealth_market_turnover_history.py"),
            Path(
                "src/orchestrator/defs/bootstrap/"
                "wealth_market_turnover_history_cli.py"
            ),
        )
        forbidden_tokens = (
            "@dg.asset",
            "@dg.asset_check",
            "@dg.sensor",
            "define_asset_job",
            "report_runless_asset_event",
            "wealth_market_turnover_runless_events",
        )
        combined_source = "\n".join(path.read_text() for path in helper_paths)
        for token in forbidden_tokens:
            self.assertNotIn(token, combined_source)
        for required_stage in (
            "build-candidates",
            "audit-candidates",
            "promote",
            "formal-audit",
            "prod-publish",
        ):
            self.assertIn(required_stage, combined_source)

    def test_plan_requires_five_minute_sources_daily_source_and_bse_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            staging_root = root / "staging"
            _write_all_sources(root, DATE_1)
            _write_all_sources(root, DATE_2, include_daily=False)

            plan = _plan(root, staging_root=staging_root)

        self.assertEqual(plan.selected_partition_keys, (DATE_1,))
        self.assertEqual(plan.eligible_source_partition_count, 1)
        self.assertEqual(plan.planned_write_count, 1)
        self.assertEqual(plan.planned_event_count, 0)
        self.assertEqual(len(plan.partition_plans[0].source_files), 6)

    def test_requested_incomplete_partition_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _write_all_sources(root, DATE_1)
            _write_all_sources(root, DATE_2, include_daily=False)

            with self.assertRaisesRegex(
                ValueError,
                "missing complete minute and stock daily inputs",
            ):
                plan_wealth_market_turnover_history(
                    duckdb_resource=DuckDBResource(),
                    recovery_source_bundle_path=_recovery_paths(root)[0],
                    changed_silver_manifest_path=_recovery_paths(root)[1],
                    lake_root=root,
                    staging_root=root / "staging",
                    partition_keys=(DATE_1, DATE_2),
                )

    def test_plan_caps_batches_at_twenty_and_rejects_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _write_all_sources(root, DATE_1)
            with self.assertRaisesRegex(ValueError, "batch_size must be 1..20"):
                _plan(root, batch_size=21)
            plan = _plan(root)
            payload = asdict(plan)
            payload["correction_method"] = "changed"

            with self.assertRaisesRegex(RuntimeError, "plan hash mismatch"):
                wealth_market_turnover_history_plan_from_dict(payload)

    def test_candidate_audit_promote_and_formal_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _write_all_sources(root, DATE_1)
            target_path = gold_wealth_market_turnover_path(root, DATE_1)
            plan = _plan(root, partition_keys=(DATE_1,))

            write_report = build_wealth_market_turnover_history_candidates(
                plan=plan,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                partition_keys=(DATE_1,),
            )
            self.assertFalse(target_path.exists())
            candidate_audit = audit_wealth_market_turnover_history_candidates(
                plan=plan,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                partition_keys=(DATE_1,),
                expected_candidate_hashes=write_report.candidate_hashes,
            )
            self.assertTrue(candidate_audit.passed)
            self.assertLess(
                candidate_audit.elapsed_ms,
                WEALTH_MARKET_TURNOVER_HISTORY_AUDIT_SECONDS_LIMIT * 1000,
            )
            promote_report = promote_wealth_market_turnover_history_candidates(
                plan=plan,
                lake_root=root,
                partition_keys=(DATE_1,),
                candidate_hashes=write_report.candidate_hashes,
                candidate_audits=_partition_audits(candidate_audit),
                checkpoint_path=_checkpoint_path(plan),
                changed_manifest_path=_changed_wmt_manifest_path(plan),
            )
            formal_audit = audit_wealth_market_turnover_history(
                plan=plan,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                partition_keys=(DATE_1,),
                expected_hashes=write_report.candidate_hashes,
            )

        self.assertEqual(write_report.written_partition_keys, (DATE_1,))
        self.assertEqual(promote_report.promoted_partition_keys, (DATE_1,))
        self.assertTrue(formal_audit.passed)
        self.assertEqual(formal_audit.target_file_count, 1)
        self.assertEqual(formal_audit.target_row_count, 5)

    def test_promote_rejects_concurrent_target_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _write_all_sources(root, DATE_1)
            plan = _plan(root, partition_keys=(DATE_1,))
            write_report = build_wealth_market_turnover_history_candidates(
                plan=plan,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                partition_keys=(DATE_1,),
            )
            target_path = gold_wealth_market_turnover_path(root, DATE_1)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(b"concurrent change")
            candidate_audit = audit_wealth_market_turnover_history_candidates(
                plan=plan,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                partition_keys=(DATE_1,),
                expected_candidate_hashes=write_report.candidate_hashes,
            )

            with self.assertRaisesRegex(RuntimeError, "appeared after plan"):
                promote_wealth_market_turnover_history_candidates(
                    plan=plan,
                    lake_root=root,
                    partition_keys=(DATE_1,),
                    candidate_hashes=write_report.candidate_hashes,
                    candidate_audits=_partition_audits(candidate_audit),
                    checkpoint_path=_checkpoint_path(plan),
                    changed_manifest_path=_changed_wmt_manifest_path(plan),
                )

    def test_build_rejects_source_fingerprint_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _write_all_sources(root, DATE_1)
            plan = _plan(root, partition_keys=(DATE_1,))
            _write_minute_file(root, DATE_1, 1, extra_sh_row=True)

            with self.assertRaisesRegex(RuntimeError, "Source fingerprint changed"):
                build_wealth_market_turnover_history_candidates(
                    plan=plan,
                    lake_root=root,
                    duckdb_resource=DuckDBResource(),
                    partition_keys=(DATE_1,),
                )

    def test_mixed_candidate_preserves_source_empty_frequency_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _write_all_sources(root, DATE_1)
            _write_existing_target(root, DATE_1, legacy_freqs=(1,))
            original_file_hash = _sha256_file(
                gold_wealth_market_turnover_path(root, DATE_1)
            )
            source_bundle, changed_silver = _write_recovery_contracts(
                root,
                mode_rows=(
                    _mode_row(DATE_1, 1, "source_empty_skip", "source_empty"),
                    _mode_row(DATE_1, 5, "source_recoverable", "source_recovered"),
                ),
                changed_rows=({"trade_date": DATE_1, "freq": 5},),
            )
            plan = plan_wealth_market_turnover_history(
                duckdb_resource=DuckDBResource(),
                recovery_source_bundle_path=source_bundle,
                changed_silver_manifest_path=changed_silver,
                lake_root=root,
                staging_root=root / "staging",
                partition_keys=(DATE_1,),
            )
            with DuckDBResource().connect() as connection:
                original_rows = wealth_market_turnover_canonical_rows(
                    connection=connection,
                    path=gold_wealth_market_turnover_path(root, DATE_1),
                )
            write_report = build_wealth_market_turnover_history_candidates(
                plan=plan,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                partition_keys=(DATE_1,),
            )
            candidate_audit = audit_wealth_market_turnover_history_candidates(
                plan=plan,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                partition_keys=(DATE_1,),
                expected_candidate_hashes=write_report.candidate_hashes,
            )
            candidate_path = Path(candidate_audit.partition_audits[0].target_path)
            with DuckDBResource().connect() as connection:
                candidate_rows = wealth_market_turnover_canonical_rows(
                    connection=connection,
                    path=candidate_path,
                )
            promote_report = promote_wealth_market_turnover_history_candidates(
                plan=plan,
                lake_root=root,
                partition_keys=(DATE_1,),
                candidate_hashes=write_report.candidate_hashes,
                candidate_audits=_partition_audits(candidate_audit),
                checkpoint_path=_checkpoint_path(plan),
                changed_manifest_path=_changed_wmt_manifest_path(plan),
            )
            final_file_hash = _sha256_file(
                gold_wealth_market_turnover_path(root, DATE_1)
            )
            changed_manifest = json.loads(
                _changed_wmt_manifest_path(plan).read_text(encoding="utf-8")
            )
            with self.assertRaisesRegex(
                ValueError,
                "only consume actual changed WMT partitions",
            ):
                publish_wealth_market_turnover_history_to_prod(
                    plan=plan,
                    lake_root=root,
                    duckdb_resource=DuckDBResource(),
                    prod_postgres_write=object(),
                    partition_keys=(DATE_1,),
                    formal_audit_hashes={},
                    changed_manifest=changed_manifest,
                )

        self.assertTrue(candidate_audit.passed)
        self.assertEqual(candidate_rows[1], original_rows[1])
        self.assertEqual(
            plan.partition_plans[0].frequency_plans[0].action,
            WealthMarketTurnoverFrequencyAction.PRESERVE_EXISTING.value,
        )
        self.assertEqual(promote_report.no_op_partition_keys, (DATE_1,))
        self.assertEqual(final_file_hash, original_file_hash)

    def test_partial_scope_blocks_plan_before_candidate_build(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _write_all_sources(root, DATE_1)
            source_bundle, changed_silver = _write_recovery_contracts(
                root,
                mode_rows=(
                    _mode_row(DATE_1, 1, "partial_blocked", "partial_source_scope"),
                ),
            )
            plan = plan_wealth_market_turnover_history(
                duckdb_resource=DuckDBResource(),
                recovery_source_bundle_path=source_bundle,
                changed_silver_manifest_path=changed_silver,
                lake_root=root,
                staging_root=root / "staging",
                partition_keys=(DATE_1,),
            )

        self.assertTrue(plan.should_stop)
        self.assertEqual(plan.blocked_partition_count, 1)
        self.assertEqual(plan.selected_partition_keys, ())

    def test_unfrozen_partial_bse_code_set_blocks_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _write_all_sources(root, DATE_1, extra_daily_bse_code=True)

            plan = _plan(root, partition_keys=(DATE_1,))

        self.assertTrue(plan.should_stop)
        self.assertEqual(plan.blocked_partition_count, 1)
        self.assertEqual(plan.stop_reason_codes, ("bse_code_set_mismatch",))
        self.assertEqual(plan.selected_partition_keys, ())

    def test_unfrozen_missing_bse_close_point_blocks_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _write_all_sources(root, DATE_1, missing_close_freq=1)

            plan = _plan(root, partition_keys=(DATE_1,))

        self.assertTrue(plan.should_stop)
        self.assertEqual(plan.blocked_partition_count, 1)
        self.assertEqual(plan.stop_reason_codes, ("bse_close_point_missing",))
        self.assertEqual(plan.selected_partition_keys, ())

    def test_all_source_empty_frequencies_leave_partition_out_of_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _write_all_sources(root, DATE_1)
            _write_existing_target(root, DATE_1, legacy_freqs=STK_MINS_FREQS)
            source_bundle, changed_silver = _write_recovery_contracts(
                root,
                mode_rows=tuple(
                    _mode_row(DATE_1, freq, "source_empty_skip", "source_empty")
                    for freq in STK_MINS_FREQS
                ),
            )
            plan = plan_wealth_market_turnover_history(
                duckdb_resource=DuckDBResource(),
                recovery_source_bundle_path=source_bundle,
                changed_silver_manifest_path=changed_silver,
                lake_root=root,
                staging_root=root / "staging",
                partition_keys=(DATE_1,),
            )

        self.assertFalse(plan.should_stop)
        self.assertEqual(plan.all_preserve_partition_count, 1)
        self.assertEqual(plan.selected_partition_keys, ())


def _write_all_sources(
    root: Path,
    partition_key: str,
    *,
    include_daily: bool = True,
    extra_daily_bse_code: bool = False,
    missing_close_freq: int | None = None,
) -> None:
    for freq in STK_MINS_FREQS:
        _write_minute_file(
            root,
            partition_key,
            freq,
            include_bse_close=freq != missing_close_freq,
        )
    if include_daily:
        _write_daily_file(
            root,
            partition_key,
            extra_bse_code=extra_daily_bse_code,
        )


def _plan(root: Path, **kwargs):
    source_bundle, changed_silver = _recovery_paths(root)
    return plan_wealth_market_turnover_history(
        duckdb_resource=DuckDBResource(),
        recovery_source_bundle_path=source_bundle,
        changed_silver_manifest_path=changed_silver,
        lake_root=root,
        staging_root=kwargs.pop("staging_root", root / "staging"),
        **kwargs,
    )


def _recovery_paths(root: Path) -> tuple[Path, Path]:
    source_bundle = root / "recovery" / "source-bundle.json"
    changed_silver = root / "recovery" / "actual-changed-silver-manifest.json"
    if not source_bundle.exists() or not changed_silver.exists():
        return _write_recovery_contracts(root)
    return source_bundle, changed_silver


def _write_recovery_contracts(
    root: Path,
    *,
    mode_rows: tuple[dict[str, object], ...] = (),
    changed_rows: tuple[dict[str, object], ...] = (),
) -> tuple[Path, Path]:
    recovery_root = root / "recovery"
    recovery_root.mkdir(parents=True, exist_ok=True)
    source_bundle_path = recovery_root / "source-bundle.json"
    changed_silver_path = recovery_root / "actual-changed-silver-manifest.json"
    frozen_bundle = {
        "schema_version": 1,
        "recovery_kind": "stk_mins_bse_history_recovery",
        "plan_hash": "test-plan",
        "scope_manifest_sha256": "test-scope",
        "source_windows": [],
        "mode_rows": list(mode_rows),
    }
    bundle_hash = _hash_payload(frozen_bundle)
    source_bundle_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "recovery_kind": "stk_mins_bse_history_recovery",
                "stage": "r0b_source_bundle",
                "plan_hash": "test-plan",
                "should_stop": False,
                "frozen_bundle": frozen_bundle,
                "bundle_hash": bundle_hash,
            }
        ),
        encoding="utf-8",
    )
    frozen_changed = {
        "schema_version": 1,
        "recovery_kind": "stk_mins_bse_history_recovery",
        "stage": "r2_actual_changed_silver_manifest",
        "plan_hash": "test-plan",
        "bundle_hash": bundle_hash,
        "raw_promote_hash": "test-raw",
        "audit_hash": "test-audit",
        "changed_silver_count": len(changed_rows),
        "changed_silver_rows": list(changed_rows),
    }
    changed_silver_path.write_text(
        json.dumps(
            {
                **frozen_changed,
                "should_stop": False,
                "manifest_hash": _hash_payload(frozen_changed),
            }
        ),
        encoding="utf-8",
    )
    return source_bundle_path, changed_silver_path


def _mode_row(
    trade_date: str,
    freq: int,
    mode: str,
    reason_code: str,
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "freq": freq,
        "mode": mode,
        "reason_code": reason_code,
    }


def _partition_audits(report) -> dict[str, dict[str, object]]:
    return {
        audit.partition_key: audit.to_dict()
        for audit in report.partition_audits
    }


def _checkpoint_path(plan) -> Path:
    return Path(plan.staging_root) / "r5" / "promote-checkpoint.json"


def _changed_wmt_manifest_path(plan) -> Path:
    return Path(plan.staging_root) / "r5" / "actual-changed-wmt-manifest.json"


def _write_existing_target(
    root: Path,
    partition_key: str,
    *,
    legacy_freqs: tuple[int, ...],
) -> None:
    target_path = gold_wealth_market_turnover_path(root, partition_key)
    write_gold_wealth_market_turnover_partition(
        duckdb_resource=DuckDBResource(),
        source_paths=wealth_market_turnover_source_paths(root, partition_key),
        partition_key=partition_key,
        staging_path=root / "target-staging" / f"{partition_key}.parquet",
        target_path=target_path,
        built_at_sql="TIMESTAMPTZ '2026-06-22 16:00:00+08:00'",
    )
    values = ", ".join(str(freq) for freq in legacy_freqs)
    rewritten = target_path.with_name("part-000.rewritten.parquet")
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT * REPLACE (
                CASE WHEN freq IN ({values}) THEN 'v1' ELSE build_version END
                  AS build_version,
                CASE WHEN freq IN ({values}) THEN 'legacy' ELSE build_note END
                  AS build_note
              )
              FROM read_parquet('{target_path.as_posix()}', hive_partitioning=false)
              ORDER BY freq
            ) TO '{rewritten.as_posix()}' (FORMAT PARQUET)
            """
        )
    rewritten.replace(target_path)


def _hash_payload(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_minute_file(
    root: Path,
    partition_key: str,
    freq: int,
    *,
    extra_sh_row: bool = False,
    include_bse_close: bool = True,
) -> None:
    path = silver_stk_mins_path(root, freq, partition_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        ("000001.SZ", freq, partition_key, f"{partition_key} 09:30:00", 100, 1000.0),
        ("920001.BJ", freq, partition_key, f"{partition_key} 09:30:00", 100 + freq, 1000.0 + freq * 10),
        ("000001.SZ", freq, partition_key, f"{partition_key} 15:00:00", 200, 2000.0),
    ]
    if include_bse_close:
        rows.append(
            ("920001.BJ", freq, partition_key, f"{partition_key} 15:00:00", 0, 0.0)
        )
    if extra_sh_row:
        rows.append(
            ("600000.SH", freq, partition_key, f"{partition_key} 14:59:00", 1, 10.0)
        )
    values_sql = ", ".join(
        "(" + ", ".join(_sql_literal(value) for value in row) + ")"
        for row in rows
    )
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT
                CAST(ts_code AS VARCHAR) AS ts_code,
                CAST(freq AS INTEGER) AS freq,
                CAST(trade_date AS DATE) AS trade_date,
                CAST(trade_time AS TIMESTAMP) AS trade_time,
                CAST(vol AS DOUBLE) AS vol,
                CAST(amount AS DOUBLE) AS amount
              FROM (VALUES {values_sql})
                rows(ts_code, freq, trade_date, trade_time, vol, amount)
            ) TO '{path.as_posix()}' (FORMAT PARQUET)
            """
        )


def _write_daily_file(
    root: Path,
    partition_key: str,
    *,
    extra_bse_code: bool = False,
) -> None:
    path = silver_stock_daily_path(root, partition_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    extra_row = (
        f", ('920002.BJ', DATE '{partition_key}', 1.0, 1.0)"
        if extra_bse_code
        else ""
    )
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT *
              FROM (
                VALUES
                  ('000001.SZ', DATE '{partition_key}', 3.0, 3.0),
                  ('920001.BJ', DATE '{partition_key}', 10.0, 10.0)
                  {extra_row}
              ) rows(ts_code, trade_date, vol, amount)
            ) TO '{path.as_posix()}' (FORMAT PARQUET)
            """
        )


def _sql_literal(value: object) -> str:
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return str(value)


if __name__ == "__main__":
    unittest.main()
