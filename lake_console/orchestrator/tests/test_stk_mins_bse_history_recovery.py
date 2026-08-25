from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from pathlib import Path

import duckdb

from orchestrator.defs.bootstrap.stk_mins_bse_history_recovery import (
    BseMinuteRecoveryError,
    BseMinuteRecoveryScope,
    _active_identity_rows,
    _expected_session_times,
    _select_aliases,
    audit_bse_raw_recovery_candidates,
    build_bse_raw_recovery_candidates,
    load_bse_stk_mins_source_bundle,
    plan_bse_stk_mins_history_recovery,
    promote_bse_raw_recovery_candidates,
    stage_bse_stk_mins_source_pages,
)
from orchestrator.defs.bootstrap.stk_mins_bse_history_recovery_cli import main
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import (
    raw_stk_mins_path,
    silver_stock_daily_path,
    silver_stock_identity_map_path,
)
from orchestrator.defs.resources import DuckDBResource, TushareResult
from orchestrator.defs.tushare_request_policy import TushareRequestPolicy

RAW_SCHEMA = (
    ("ts_code", "VARCHAR"),
    ("freq", "INTEGER"),
    ("trade_time", "TIMESTAMP"),
    ("open", "DOUBLE"),
    ("close", "DOUBLE"),
    ("high", "DOUBLE"),
    ("low", "DOUBLE"),
    ("vol", "BIGINT"),
    ("amount", "DOUBLE"),
    ("exchange", "VARCHAR"),
    ("vwap", "DOUBLE"),
)


def _write_rows(
    path: Path,
    schema: tuple[tuple[str, str], ...],
    rows: list[tuple[object, ...]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            "CREATE TABLE rows ("
            + ", ".join(f'"{name}" {type_name}' for name, type_name in schema)
            + ")"
        )
        if rows:
            connection.executemany(
                "INSERT INTO rows VALUES ("
                + ", ".join("?" for _ in schema)
                + ")",
                rows,
            )
        connection.execute(
            f"COPY rows TO {duckdb_string(path)} (FORMAT PARQUET)"
        )


def _minute_rows(ts_code: str, trade_date: str, freq: int) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    for index, clock in enumerate(_expected_session_times(freq), start=1):
        price = 10.0 + index / 1000
        rows.append(
            (
                ts_code,
                freq,
                f"{trade_date} {clock}",
                price,
                price + 0.01,
                price + 0.02,
                price - 0.02,
                index * 100,
                index * 1000.0,
                "BSE" if ts_code.endswith(".BJ") else "SSE",
                price + 0.005,
            )
        )
    return rows


class _FakeTushare:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, dict[str, object], tuple[str, ...]]] = []

    def call(self, api_name, params, fields):
        normalized_params = dict(params)
        normalized_fields = tuple(fields)
        self.calls.append((api_name, normalized_params, normalized_fields))
        offset = int(normalized_params["offset"])
        limit = int(normalized_params["limit"])
        page = self.rows[offset : offset + limit]
        return TushareResult(
            rows=page,
            columns=normalized_fields,
            metadata={},
        )


class BseMinuteHistoryRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.lake_root = self.root / "lake"
        self.staging_root = self.root / "staging" / "stk_mins_bse_recovery"
        self.trade_date = "2025-09-03"
        self.resource = DuckDBResource()
        self.raw_path = raw_stk_mins_path(self.lake_root, 1, self.trade_date)
        _write_rows(
            silver_stock_daily_path(self.lake_root, self.trade_date),
            (("ts_code", "VARCHAR"),),
            [("920001.BJ",), ("920392.BJ",)],
        )
        identity_schema = (
            ("latest_ts_code", "VARCHAR"),
            ("source_ts_code", "VARCHAR"),
            ("valid_from", "DATE"),
            ("valid_to", "DATE"),
            ("effective_list_date", "DATE"),
            ("effective_delist_date", "DATE"),
            ("identity_source", "VARCHAR"),
            ("confidence", "VARCHAR"),
            ("reason", "VARCHAR"),
            ("created_at", "TIMESTAMP WITH TIME ZONE"),
        )
        _write_rows(
            silver_stock_identity_map_path(self.lake_root),
            identity_schema,
            [
                (
                    "920001.BJ",
                    "920001.BJ",
                    "2020-01-01",
                    None,
                    "2020-01-01",
                    None,
                    "current_code",
                    "high",
                    "self",
                    "2026-01-01 00:00:00+08",
                ),
                (
                    "920392.BJ",
                    "920392.BJ",
                    "2025-09-03",
                    None,
                    "2025-09-03",
                    None,
                    "current_code",
                    "high",
                    "self",
                    "2026-01-01 00:00:00+08",
                ),
                (
                    "920392.BJ",
                    "872392.BJ",
                    "2022-01-01",
                    "2025-09-04",
                    "2022-01-01",
                    None,
                    "bse_mapping",
                    "high",
                    "historical alias",
                    "2026-01-01 00:00:00+08",
                ),
            ],
        )
        _write_rows(
            self.raw_path,
            RAW_SCHEMA,
            _minute_rows("920001.BJ", self.trade_date, 1)
            + _minute_rows("000001.SZ", self.trade_date, 1),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _plan(self, freq: int = 1) -> tuple[dict[str, object], Path]:
        output = self.root / f"plan-output-{freq}.json"
        plan = plan_bse_stk_mins_history_recovery(
            lake_root=self.lake_root,
            staging_root=self.staging_root,
            scopes=(BseMinuteRecoveryScope(self.trade_date, freq),),
            duckdb_resource=self.resource,
            output_path=output,
        )
        return plan, Path(str(plan["plan_path"]))

    def _source_rows(self) -> list[dict[str, object]]:
        names = tuple(name for name, _ in RAW_SCHEMA)
        return [
            dict(zip(names, row, strict=True))
            | {"freq": "1min", "trade_time": str(row[2])}
            for row in _minute_rows("872392.BJ", self.trade_date, 1)
        ]

    def test_identity_alias_prefers_bse_mapping_and_valid_to_is_exclusive(self) -> None:
        identity_path = silver_stock_identity_map_path(self.lake_root)
        with self.resource.connect() as connection:
            active = _active_identity_rows(connection, identity_path, self.trade_date)
            aliases, failures = _select_aliases(
                expected_latest_codes=("920392.BJ",),
                identity_rows=active,
            )
            expired = _active_identity_rows(connection, identity_path, "2025-09-04")
            expired_aliases, expired_failures = _select_aliases(
                expected_latest_codes=("920392.BJ",),
                identity_rows=expired,
            )

        self.assertEqual(failures, {})
        self.assertEqual(aliases["920392.BJ"], ("872392.BJ", "bse_mapping"))
        self.assertEqual(expired_failures, {})
        self.assertEqual(
            expired_aliases["920392.BJ"],
            ("920392.BJ", "self_mapping"),
        )

    def test_plan_canonicalizes_existing_raw_and_requests_only_missing_alias(self) -> None:
        plan, _plan_path = self._plan()

        self.assertFalse(plan["should_stop"])
        summary = plan["frozen_payload"]["scope_summaries"][0]
        self.assertEqual(summary["expected_latest_code_count"], 2)
        self.assertEqual(summary["canonical_existing_latest_code_count"], 1)
        self.assertEqual(summary["missing_latest_code_samples"], ["920392.BJ"])
        with self.resource.connect() as connection:
            rows = connection.execute(
                f"SELECT latest_ts_code, preferred_source_ts_code, coverage_status "
                f"FROM read_parquet({duckdb_string(Path(str(plan['scope_manifest_path'])))}) "
                "ORDER BY latest_ts_code"
            ).fetchall()
        self.assertEqual(
            rows,
            [
                ("920001.BJ", "920001.BJ", "covered"),
                ("920392.BJ", "872392.BJ", "missing"),
            ],
        )

    def test_existing_partial_code_day_blocks_source_recovery(self) -> None:
        _write_rows(
            self.raw_path,
            RAW_SCHEMA,
            _minute_rows("920001.BJ", self.trade_date, 1)
            + _minute_rows("920392.BJ", self.trade_date, 1)[:20],
        )

        plan, _plan_path = self._plan()

        self.assertTrue(plan["should_stop"])
        summary = plan["frozen_payload"]["scope_summaries"][0]
        self.assertEqual(summary["mode"], "partial_blocked")
        self.assertEqual(summary["partial_existing_code_samples"], ["920392.BJ"])

    def test_r0b_stages_only_missing_alias_and_r1_never_requests_source(self) -> None:
        plan, plan_path = self._plan()
        raw_before = self.raw_path.read_bytes()
        fake = _FakeTushare(self._source_rows())
        bundle_output = self.root / "bundle.json"
        bundle = stage_bse_stk_mins_source_pages(
            plan_path=plan_path,
            tushare=fake,
            duckdb_resource=self.resource,
            output_path=bundle_output,
            request_policy=TushareRequestPolicy(
                minimum_interval_seconds=0.0,
                max_retries=0,
                max_requests=10,
                max_elapsed_seconds=30.0,
            ),
        )

        self.assertFalse(bundle["should_stop"])
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0][1]["ts_code"], "872392.BJ")
        self.assertEqual(self.raw_path.read_bytes(), raw_before)
        source_page = Path(
            bundle["frozen_bundle"]["source_windows"][0]["pages"][0]["path"]
        )
        self.assertTrue(
            source_page.resolve().is_relative_to(self.staging_root.resolve())
        )

        candidate_output = self.root / "candidate.json"
        candidate = build_bse_raw_recovery_candidates(
            plan_path=plan_path,
            bundle_path=bundle_output,
            duckdb_resource=self.resource,
            output_path=candidate_output,
        )
        self.assertFalse(candidate["should_stop"])
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(self.raw_path.read_bytes(), raw_before)

        candidate_path = Path(candidate["candidates"][0]["path"])
        with self.resource.connect() as connection:
            bse_codes = connection.execute(
                f"SELECT DISTINCT ts_code FROM read_parquet({duckdb_string(candidate_path)}) "
                "WHERE ts_code LIKE '%.BJ' ORDER BY ts_code"
            ).fetchall()
        self.assertEqual(bse_codes, [("872392.BJ",), ("920001.BJ",)])

        audit_output = self.root / "candidate-audit.json"
        audit = audit_bse_raw_recovery_candidates(
            plan_path=plan_path,
            bundle_path=bundle_output,
            candidate_report_path=candidate_output,
            duckdb_resource=self.resource,
            output_path=audit_output,
        )
        self.assertFalse(audit["should_stop"])
        self.assertEqual(audit["audited_candidate_count"], 1)
        self.assertEqual(self.raw_path.read_bytes(), raw_before)

        checkpoint = (
            Path(str(plan["scope_manifest_path"])).parent
            / "promote-checkpoint.json"
        )
        checkpoint.write_text(
            json.dumps(
                {
                    "plan_hash": plan["plan_hash"],
                    "bundle_hash": bundle["bundle_hash"],
                    "promoted": [],
                    "in_progress": {
                        "trade_date": self.trade_date,
                        "freq": 1,
                        "sha256": candidate["candidates"][0]["sha256"],
                        "candidate_path": str(candidate_path),
                    },
                }
            ),
            encoding="utf-8",
        )
        promoted = promote_bse_raw_recovery_candidates(
            plan_path=plan_path,
            bundle_path=bundle_output,
            audit_report_path=audit_output,
            confirm=True,
            checkpoint_path=checkpoint,
        )
        self.assertEqual(promoted["promoted_count"], 1)
        self.assertFalse(candidate_path.exists())
        with self.resource.connect() as connection:
            bse_codes = connection.execute(
                f"SELECT DISTINCT ts_code FROM read_parquet({duckdb_string(self.raw_path)}) "
                "WHERE ts_code LIKE '%.BJ' ORDER BY ts_code"
            ).fetchall()
        self.assertEqual(bse_codes, [("872392.BJ",), ("920001.BJ",)])

        resumed = promote_bse_raw_recovery_candidates(
            plan_path=plan_path,
            bundle_path=bundle_output,
            audit_report_path=audit_output,
            confirm=True,
            checkpoint_path=checkpoint,
        )
        self.assertEqual(resumed["promoted_count"], 1)

    def test_source_bundle_detects_page_tampering(self) -> None:
        _plan, plan_path = self._plan()
        fake = _FakeTushare(self._source_rows())
        bundle_output = self.root / "bundle.json"
        bundle = stage_bse_stk_mins_source_pages(
            plan_path=plan_path,
            tushare=fake,
            duckdb_resource=self.resource,
            output_path=bundle_output,
            request_policy=TushareRequestPolicy(
                minimum_interval_seconds=0.0,
                max_retries=0,
                max_requests=10,
                max_elapsed_seconds=30.0,
            ),
        )
        page = Path(bundle["frozen_bundle"]["source_windows"][0]["pages"][0]["path"])
        page.write_bytes(page.read_bytes() + b"tampered")

        with self.assertRaisesRegex(BseMinuteRecoveryError, "page changed"):
            load_bse_stk_mins_source_bundle(bundle_output)

    def test_partial_source_scope_stops_the_bundle(self) -> None:
        _plan, plan_path = self._plan()
        fake = _FakeTushare(self._source_rows()[:20])
        bundle = stage_bse_stk_mins_source_pages(
            plan_path=plan_path,
            tushare=fake,
            duckdb_resource=self.resource,
            request_policy=TushareRequestPolicy(
                minimum_interval_seconds=0.0,
                max_retries=0,
                max_requests=10,
                max_elapsed_seconds=30.0,
            ),
        )

        self.assertTrue(bundle["should_stop"])
        self.assertEqual(bundle["blocked_mode_count"], 1)
        self.assertEqual(
            bundle["frozen_bundle"]["mode_rows"][0]["mode"],
            "partial_blocked",
        )

    def test_empty_source_scope_is_classified_without_fabricating_raw(self) -> None:
        _plan, plan_path = self._plan()
        raw_before = self.raw_path.read_bytes()
        bundle_output = self.root / "empty-bundle.json"
        bundle = stage_bse_stk_mins_source_pages(
            plan_path=plan_path,
            tushare=_FakeTushare([]),
            duckdb_resource=self.resource,
            output_path=bundle_output,
            request_policy=TushareRequestPolicy(
                minimum_interval_seconds=0.0,
                max_retries=0,
                max_requests=10,
                max_elapsed_seconds=30.0,
            ),
        )

        self.assertFalse(bundle["should_stop"])
        self.assertEqual(
            bundle["frozen_bundle"]["mode_rows"][0]["mode"],
            "source_empty_skip",
        )
        self.assertEqual(self.raw_path.read_bytes(), raw_before)

    def test_empty_coarse_source_uses_fallback_only_with_complete_1m(self) -> None:
        _write_rows(
            self.raw_path,
            RAW_SCHEMA,
            _minute_rows("920001.BJ", self.trade_date, 1)
            + _minute_rows("872392.BJ", self.trade_date, 1),
        )
        raw_5m_path = raw_stk_mins_path(self.lake_root, 5, self.trade_date)
        _write_rows(
            raw_5m_path,
            RAW_SCHEMA,
            _minute_rows("920001.BJ", self.trade_date, 5),
        )
        _plan, plan_path = self._plan(5)
        bundle = stage_bse_stk_mins_source_pages(
            plan_path=plan_path,
            tushare=_FakeTushare([]),
            duckdb_resource=self.resource,
            request_policy=TushareRequestPolicy(
                minimum_interval_seconds=0.0,
                max_retries=0,
                max_requests=10,
                max_elapsed_seconds=30.0,
            ),
        )

        self.assertFalse(bundle["should_stop"])
        mode = bundle["frozen_bundle"]["mode_rows"][0]
        self.assertEqual(mode["mode"], "silver_fallback_recoverable")
        self.assertEqual(mode["reason_code"], "source_empty_complete_1m_fallback")

    def test_promote_requires_confirmation(self) -> None:
        with self.assertRaisesRegex(BseMinuteRecoveryError, "explicit confirmation"):
            promote_bse_raw_recovery_candidates(
                plan_path=self.root / "missing-plan.json",
                bundle_path=self.root / "missing-bundle.json",
                audit_report_path=self.root / "missing-audit.json",
                confirm=False,
                checkpoint_path=self.root / "checkpoint.json",
            )

    def test_cli_write_stages_require_explicit_confirmation(self) -> None:
        self.assertEqual(
            main(
                [
                    "stage-source",
                    "--plan",
                    str(self.root / "missing-plan.json"),
                    "--output",
                    str(self.root / "bundle.json"),
                ]
            ),
            2,
        )
        self.assertEqual(
            main(
                [
                    "build-raw-candidates",
                    "--plan",
                    str(self.root / "missing-plan.json"),
                    "--bundle",
                    str(self.root / "missing-bundle.json"),
                    "--output",
                    str(self.root / "candidate.json"),
                ]
            ),
            2,
        )
        self.assertEqual(
            main(
                [
                    "promote-raw",
                    "--plan",
                    str(self.root / "missing-plan.json"),
                    "--bundle",
                    str(self.root / "missing-bundle.json"),
                    "--audit-report",
                    str(self.root / "missing-audit.json"),
                    "--checkpoint",
                    str(self.root / "checkpoint.json"),
                    "--output",
                    str(self.root / "promote.json"),
                ]
            ),
            2,
        )

    def test_r1_candidate_builder_has_no_source_request_dependency(self) -> None:
        source = inspect.getsource(build_bse_raw_recovery_candidates)
        self.assertNotIn("TushareResource", source)
        self.assertNotIn(".call(", source)
        self.assertNotIn("stk_mins\"", source)

    def test_recovery_module_does_not_define_dagster_runtime_objects(self) -> None:
        module_path = Path(inspect.getfile(build_bse_raw_recovery_candidates))
        source = module_path.read_text(encoding="utf-8")
        self.assertNotIn("@dg.asset", source)
        self.assertNotIn("@dg.sensor", source)
        self.assertNotIn("define_asset_job", source)
        self.assertNotIn("report_runless_asset_event", source)
        self.assertNotIn("get_event_records", source)

    def test_scope_file_contract_is_explicit(self) -> None:
        scope_file = self.root / "scope.json"
        scope_file.write_text(
            json.dumps({"scopes": [{"trade_date": self.trade_date, "freq": 1}]}),
            encoding="utf-8",
        )
        output = self.root / "plan.json"
        result = main(
            [
                "plan",
                "--scope-file",
                str(scope_file),
                "--lake-root",
                str(self.lake_root),
                "--staging-root",
                str(self.staging_root),
                "--output",
                str(output),
            ]
        )
        self.assertEqual(result, 0)
        self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
