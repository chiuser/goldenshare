from datetime import datetime
from argparse import Namespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb

from orchestrator.defs.asset_guards.dc_daily_technical_quality import (
    GoldDcDailyTechnicalAudit,
)
from orchestrator.defs.bootstrap.dc_daily_technical_clickhouse_bootstrap import (
    DC_DAILY_TECHNICAL_SERVING_TABLE,
    DC_DAILY_TECHNICAL_SERVING_COLUMNS,
    DcDailyTechnicalClickHouseBootstrapError,
    audit_sample_staging,
    build_gold_dc_daily_technical_bootstrap_plan,
    insert_sample_rows,
    iter_gold_clickhouse_rows,
)
from orchestrator.defs.bootstrap.dc_daily_technical_clickhouse_bootstrap_cli import (
    _parser,
    _run_sample,
    _target_env_prefixes,
)
from orchestrator.defs.bootstrap.dc_daily_technical_clickhouse_bootstrap_apply import (
    prepare_apply_target,
    validate_apply_request,
)
from orchestrator.defs.paths import gold_dc_daily_technical_path


DATE_1 = "2026-07-14"
DATE_2 = "2026-07-15"


class _FakeClickHouseClient:
    def __init__(self, reported_count: int | None = None):
        self.calls: list[tuple[str, list[tuple]]] = []
        self.inserted_rows = 0
        self.reported_count = reported_count

    def execute(self, query, data=None, params=None):
        self.calls.append((query, list(data or params or [])))
        if query.startswith("DESCRIBE TABLE"):
            return [
                (column,)
                for column in (*DC_DAILY_TECHNICAL_SERVING_COLUMNS, "updated_at")
            ]
        if query.startswith("INSERT INTO"):
            self.inserted_rows += len(data or params or [])
        if query.startswith("SELECT count()"):
            return [(
                self.reported_count
                if self.reported_count is not None
                else self.inserted_rows,
            )]
        return []


class DcDailyTechnicalClickHouseBootstrapTests(unittest.TestCase):
    def test_plan_fingerprint_is_stable_and_counts_source_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lake_root = Path(directory)
            for trade_date in (DATE_1, DATE_2):
                path = gold_dc_daily_technical_path(lake_root, trade_date)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            audits = {
                DATE_1: GoldDcDailyTechnicalAudit(
                    trade_date=DATE_1,
                    passed=True,
                    materialized=True,
                    checked_row_count=2,
                    failed_row_count=0,
                ),
                DATE_2: GoldDcDailyTechnicalAudit(
                    trade_date=DATE_2,
                    passed=True,
                    materialized=True,
                    checked_row_count=1,
                    failed_row_count=0,
                ),
            }
            with patch(
                "orchestrator.defs.bootstrap.dc_daily_technical_clickhouse_bootstrap._expected_dates_from_calendar",
                return_value=(DATE_1, DATE_2, "2026-12-31"),
            ), patch(
                "orchestrator.defs.bootstrap.dc_daily_technical_clickhouse_bootstrap.batch_gold_dc_daily_technical_audit",
                return_value=audits,
            ):
                first = build_gold_dc_daily_technical_bootstrap_plan(
                    connection=object(),
                    lake_root=lake_root,
                    batch_size=2,
                )
                second = build_gold_dc_daily_technical_bootstrap_plan(
                    connection=object(),
                    lake_root=lake_root,
                    batch_size=2,
                )
            self.assertFalse(first.should_stop)
            self.assertEqual(first.source_file_count, 2)
            self.assertEqual(first.source_row_count, 3)
            self.assertEqual(first.estimated_batch_count, 2)
            self.assertEqual(first.plan_fingerprint, second.plan_fingerprint)

    def test_iterator_uses_fetchmany_batches_and_explicit_updated_at(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lake_root = Path(directory)
            connection = duckdb.connect()
            try:
                path = gold_dc_daily_technical_path(lake_root, DATE_1)
                path.parent.mkdir(parents=True, exist_ok=True)
                connection.execute(
                    """
                    CREATE TABLE source AS
                    SELECT
                      *
                    FROM (VALUES
                      ('BK0001.DC', DATE '2026-07-14', '行业', 1.0,
                       NULL::DOUBLE, NULL::DOUBLE, NULL::DOUBLE, NULL::DOUBLE,
                       NULL::DOUBLE, NULL::DOUBLE, NULL::DOUBLE, NULL::DOUBLE,
                       1.0, 1.0, 1.0, 1.0, 1.0, 1.0,
                       NULL::DOUBLE, NULL::DOUBLE, NULL::DOUBLE, 1,
                       'params', 'v1'),
                      ('BK0002.DC', DATE '2026-07-14', '概念', 2.0,
                       NULL::DOUBLE, NULL::DOUBLE, NULL::DOUBLE, NULL::DOUBLE,
                       NULL::DOUBLE, NULL::DOUBLE, NULL::DOUBLE, NULL::DOUBLE,
                       1.0, 1.0, 1.0, 1.0, 1.0, 1.0,
                       NULL::DOUBLE, NULL::DOUBLE, NULL::DOUBLE, 2,
                       'params', 'v1')
                    ) AS values_table(
                      ts_code, trade_date, category, close,
                      ma_5, ma_10, ma_15, ma_20, ma_30, ma_60, ma_120, ma_250,
                      kdj_k, kdj_d, kdj_j, macd_dif, macd_dea, macd,
                      boll_mid, boll_upper, boll_lower, observation_count,
                      params_key, indicator_version
                    )
                    """
                )
                connection.execute(f"COPY source TO '{path}' (FORMAT PARQUET)")
                batches = list(
                    iter_gold_clickhouse_rows(
                        connection=connection,
                        lake_root=lake_root,
                        trade_dates=(DATE_1,),
                        batch_size=1,
                        updated_at=datetime(2026, 7, 16, 10, 0),
                    )
                )
            finally:
                connection.close()
            self.assertEqual([len(batch) for batch in batches], [1, 1])
            self.assertEqual(len(batches[0][0]), 25)
            self.assertEqual(batches[0][0][-1], datetime(2026, 7, 16, 10, 0))

    def test_sample_insert_requires_isolated_staging_name(self) -> None:
        client = _FakeClickHouseClient()
        with self.assertRaisesRegex(ValueError, "formal serving table"):
            insert_sample_rows(
                client=client,
                staging_table=DC_DAILY_TECHNICAL_SERVING_TABLE,
                row_batches=iter([[(1,)] ]),
            )
        self.assertEqual(client.calls, [])

    def test_sample_insert_is_batched(self) -> None:
        client = _FakeClickHouseClient()
        result = insert_sample_rows(
            client=client,
            staging_table="staging_dc_daily_technical_sample",
            row_batches=iter([[(1,), (2,)], [(3,)], []]),
        )
        self.assertEqual(result["inserted_row_count"], 3)
        self.assertEqual(result["staging_row_count"], 3)
        self.assertEqual(result["batch_count"], 2)
        self.assertEqual(len(client.calls), 4)

    def test_sample_insert_fails_closed_on_staging_count_mismatch(self) -> None:
        client = _FakeClickHouseClient(reported_count=2)
        with self.assertRaises(DcDailyTechnicalClickHouseBootstrapError):
            insert_sample_rows(
                client=client,
                staging_table="staging_dc_daily_technical_sample",
                row_batches=iter([[(1,), (2,), (3,)]]),
            )

    def test_sample_staging_audit_checks_daily_counts_and_keys(self) -> None:
        class AuditClient(_FakeClickHouseClient):
            def execute(self, query, data=None, params=None):
                if query.lstrip().startswith("SELECT trade_date, count()"):
                    return [(DATE_1, 2, 2), (DATE_2, 1, 1)]
                return super().execute(query, data=data, params=params)

        result = audit_sample_staging(
            client=AuditClient(),
            staging_table="staging_dc_daily_technical_sample",
            expected_rows_by_date={DATE_1: 2, DATE_2: 1},
        )
        self.assertEqual(result["row_count"], 3)
        self.assertEqual(result["unique_key_count"], 3)

    def test_apply_requires_all_explicit_safety_confirmations(self) -> None:
        with self.assertRaises(PermissionError):
            validate_apply_request(
                target="local",
                expected_plan_fingerprint="abc",
                actual_plan_fingerprint="abc",
                confirm_clickhouse_write=False,
                confirm_target_empty=True,
                run_id="run_1",
            )

    def test_apply_rejects_fingerprint_drift(self) -> None:
        with self.assertRaisesRegex(
            DcDailyTechnicalClickHouseBootstrapError,
            "fingerprint mismatch",
        ):
            validate_apply_request(
                target="local",
                expected_plan_fingerprint="old",
                actual_plan_fingerprint="new",
                confirm_clickhouse_write=True,
                confirm_target_empty=True,
                run_id="run_1",
            )

    def test_apply_cli_requires_explicit_writer_and_admin_prefixes(self) -> None:
        with self.assertRaises(SystemExit):
            _parser().parse_args(["apply", "--target", "local"])

    def test_apply_cli_accepts_prod_with_primary_prefixes(self) -> None:
        args = _parser().parse_args(
            [
                "apply",
                "--target",
                "prod",
                "--lake-root",
                "/private/tmp/lake",
                "--plan-fingerprint",
                "fingerprint",
                "--staging-table",
                "staging_dc_daily_technical_sample",
                "--run-id",
                "run_1",
                "--writer-env-prefix",
                "PROD_CLICKHOUSE",
                "--admin-env-prefix",
                "PROD_CLICKHOUSE_ADMIN",
                "--confirm-clickhouse-write",
                "--confirm-target-empty",
            ]
        )
        self.assertEqual(args.target, "prod")
        self.assertEqual(args.writer_env_prefix, "PROD_CLICKHOUSE")
        self.assertIsNone(args.prod_writer_env_prefix)
        self.assertEqual(
            _target_env_prefixes(args, "prod"),
            ("PROD_CLICKHOUSE", "PROD_CLICKHOUSE_ADMIN"),
        )

    def test_admin_preflight_prepares_empty_staging_before_writer_phase(self) -> None:
        client = _FakeClickHouseClient()
        prepared = prepare_apply_target(
            client,
            "staging_dc_daily_technical_bootstrap",
        )
        self.assertEqual(
            prepared,
            "goldenshare_serving.staging_dc_daily_technical_bootstrap",
        )
        query_text = "\n".join(query for query, _ in client.calls)
        self.assertIn("DESCRIBE TABLE goldenshare_serving.board_fact_technical_daily", query_text)
        self.assertIn(
            "CREATE TABLE goldenshare_serving.staging_dc_daily_technical_bootstrap AS",
            query_text,
        )

    def test_sample_requires_explicit_date_range_before_connecting(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires --start-date"):
            _run_sample(
                Namespace(
                    start_date=None,
                    end_date=DATE_1,
                    lake_root=Path("/private/tmp/unused"),
                    batch_size=1,
                    staging_table="staging_sample",
                    clickhouse_env_prefix="CLICKHOUSE",
                )
            )
