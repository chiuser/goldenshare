from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import duckdb

from orchestrator.defs.bootstrap.stk_mins_bse_history_recovery import (
    BseMinuteRecoveryError,
    BseMinuteRecoveryScope,
    _active_identity_rows,
    _allowed_raw_source_times,
    _assert_coarse_fallback_scopes_absent,
    _expected_session_times,
    _scope_manifest_relation,
    _select_aliases,
    audit_bse_one_minute_fallback_eligibility,
    audit_bse_raw_recovery_candidates,
    audit_bse_silver_recovery_candidates,
    build_bse_raw_recovery_candidates,
    build_bse_silver_recovery_candidates,
    load_bse_stk_mins_source_bundle,
    plan_bse_stk_mins_history_recovery,
    promote_bse_raw_recovery_candidates,
    promote_bse_silver_recovery_candidates,
    stage_bse_stk_mins_source_pages,
)
from orchestrator.defs.bootstrap.stk_mins_bse_history_recovery_cli import main
from orchestrator.defs.checks.stk_mins_checks import (
    SilverStkMinsPartitionDiagnostics,
    SilverStkMinsRuleDiagnostic,
)
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import (
    raw_stk_mins_path,
    silver_stk_mins_path,
    silver_stock_daily_path,
    silver_stock_identity_map_path,
    silver_stock_lifecycle_path,
    silver_stock_suspend_daily_path,
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

SILVER_SCHEMA = (
    ("ts_code", "VARCHAR"),
    ("freq", "INTEGER"),
    ("trade_date", "DATE"),
    ("trade_time", "TIMESTAMP"),
    ("open", "DOUBLE"),
    ("high", "DOUBLE"),
    ("low", "DOUBLE"),
    ("close", "DOUBLE"),
    ("vol", "DOUBLE"),
    ("amount", "DOUBLE"),
    ("exchange", "VARCHAR"),
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
                "INSERT INTO rows VALUES (" + ", ".join("?" for _ in schema) + ")",
                rows,
            )
        connection.execute(f"COPY rows TO {duckdb_string(path)} (FORMAT PARQUET)")


def _minute_rows(
    ts_code: str,
    trade_date: str,
    freq: int,
    *,
    source_faithful: bool = False,
) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    clocks = (
        _allowed_raw_source_times(freq)
        if source_faithful
        else _expected_session_times(freq)
    )
    for index, clock in enumerate(clocks, start=1):
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
                (
                    "920305.BJ",
                    "920305.BJ",
                    "2020-01-01",
                    None,
                    "2020-01-01",
                    None,
                    "current_code",
                    "high",
                    "self",
                    "2026-01-01 00:00:00+08",
                ),
            ],
        )
        _write_rows(
            silver_stock_suspend_daily_path(self.lake_root, self.trade_date),
            (
                ("ts_code", "VARCHAR"),
                ("trade_date", "DATE"),
                ("suspend_timing", "VARCHAR"),
                ("suspend_type", "VARCHAR"),
            ),
            [],
        )
        _write_rows(
            self.raw_path,
            RAW_SCHEMA,
            _minute_rows("920001.BJ", self.trade_date, 1, source_faithful=True)
            + _minute_rows("000001.SZ", self.trade_date, 1, source_faithful=True),
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
            for row in _minute_rows(
                "872392.BJ",
                self.trade_date,
                1,
                source_faithful=True,
            )
        ]

    def _complete_r1(self) -> tuple[Path, Path, Path]:
        plan, plan_path = self._plan()
        bundle_path = self.root / "r2-bundle.json"
        stage_bse_stk_mins_source_pages(
            plan_path=plan_path,
            tushare=_FakeTushare(self._source_rows()),
            duckdb_resource=self.resource,
            output_path=bundle_path,
            request_policy=TushareRequestPolicy(
                minimum_interval_seconds=0.0,
                max_retries=0,
                max_requests=10,
                max_elapsed_seconds=30.0,
            ),
        )
        candidate_path = self.root / "r2-raw-candidates.json"
        build_bse_raw_recovery_candidates(
            plan_path=plan_path,
            bundle_path=bundle_path,
            duckdb_resource=self.resource,
            output_path=candidate_path,
        )
        audit_path = self.root / "r2-raw-audit.json"
        audit_bse_raw_recovery_candidates(
            plan_path=plan_path,
            bundle_path=bundle_path,
            candidate_report_path=candidate_path,
            duckdb_resource=self.resource,
            output_path=audit_path,
        )
        promote_path = self.root / "r2-raw-promote.json"
        promote_bse_raw_recovery_candidates(
            plan_path=plan_path,
            bundle_path=bundle_path,
            audit_report_path=audit_path,
            confirm=True,
            checkpoint_path=(
                Path(str(plan["scope_manifest_path"])).parent
                / "r2-raw-promote-checkpoint.json"
            ),
            output_path=promote_path,
        )
        return plan_path, bundle_path, promote_path

    def _prepare_r2_inputs(self) -> None:
        for freq in (5, 15, 30, 60):
            _write_rows(
                raw_stk_mins_path(self.lake_root, freq, self.trade_date),
                RAW_SCHEMA,
                _minute_rows("000001.SZ", self.trade_date, freq),
            )
        _write_rows(
            silver_stock_suspend_daily_path(self.lake_root, self.trade_date),
            (
                ("ts_code", "VARCHAR"),
                ("trade_date", "DATE"),
                ("suspend_timing", "VARCHAR"),
                ("suspend_type", "VARCHAR"),
            ),
            [("000001.SZ", self.trade_date, None, "S")],
        )
        _write_rows(
            silver_stock_lifecycle_path(self.lake_root),
            (("ts_code", "VARCHAR"),),
            [("920001.BJ",)],
        )
        for freq in (1, 5, 15, 30, 60):
            _write_rows(
                silver_stk_mins_path(self.lake_root, freq, self.trade_date),
                SILVER_SCHEMA,
                [
                    (
                        "920001.BJ",
                        freq,
                        self.trade_date,
                        f"{self.trade_date} 15:00:00",
                        10.0,
                        10.2,
                        9.8,
                        10.1,
                        1000.0,
                        10000.0,
                        "BSE",
                    )
                ],
            )

    def _fake_silver_writer(self, **kwargs):
        freq = int(kwargs["freq"])
        output_path = Path(kwargs["output_path_override"])
        rows = [
            (
                "920001.BJ",
                freq,
                self.trade_date,
                f"{self.trade_date} 15:00:00",
                10.0,
                10.2,
                9.8,
                10.1,
                1000.0,
                10000.0,
                "BSE",
            )
        ]
        if freq == 1:
            rows.append(
                (
                    "920392.BJ",
                    freq,
                    self.trade_date,
                    f"{self.trade_date} 15:00:00",
                    20.0,
                    20.2,
                    19.8,
                    20.1,
                    2000.0,
                    40000.0,
                    "BSE",
                )
            )
        if freq in (1, 5):
            rows.append(
                (
                    "000156.SZ",
                    freq,
                    self.trade_date,
                    f"{self.trade_date} 15:00:00",
                    30.0,
                    30.2,
                    29.8,
                    30.1,
                    3000.0,
                    90000.0,
                    "SZSE",
                )
            )
        _write_rows(output_path, SILVER_SCHEMA, rows)
        return SimpleNamespace(
            source_row_count=len(rows),
            mapped_row_count=len(rows),
            duplicate_removed_count=0,
            full_day_suspend_deleted_row_count=0,
            price_correction_row_count=0,
            recomputed_row_count=0,
            missing_source_fallback_row_count=0,
            vol_amount_normalized_row_count=0,
            row_count=len(rows),
        )

    def _fake_silver_diagnostics(self, **kwargs):
        return SilverStkMinsPartitionDiagnostics(
            freq=int(kwargs["freq"]),
            partition_key=str(kwargs["partition_key"]),
            silver_path=Path(kwargs["silver_path"]),
            rules=(SilverStkMinsRuleDiagnostic("fixture_rule", True),),
        )

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

    def test_identity_alias_prefers_namechange_before_self(self) -> None:
        aliases, failures = _select_aliases(
            expected_latest_codes=("920021.BJ",),
            identity_rows=(
                ("920021.BJ", "920021.BJ", "stock_lifecycle"),
                ("920021.BJ", "834021.BJ", "namechange"),
            ),
        )
        bse_aliases, bse_failures = _select_aliases(
            expected_latest_codes=("920021.BJ",),
            identity_rows=(
                ("920021.BJ", "920021.BJ", "stock_lifecycle"),
                ("920021.BJ", "834021.BJ", "namechange"),
                ("920021.BJ", "830021.BJ", "bse_mapping"),
            ),
        )
        _ambiguous, ambiguous_failures = _select_aliases(
            expected_latest_codes=("920021.BJ",),
            identity_rows=(
                ("920021.BJ", "920021.BJ", "stock_lifecycle"),
                ("920021.BJ", "834021.BJ", "namechange"),
                ("920021.BJ", "830021.BJ", "namechange"),
            ),
        )

        self.assertEqual(failures, {})
        self.assertEqual(aliases["920021.BJ"], ("834021.BJ", "namechange"))
        self.assertEqual(bse_failures, {})
        self.assertEqual(bse_aliases["920021.BJ"], ("830021.BJ", "bse_mapping"))
        self.assertEqual(
            ambiguous_failures,
            {"920021.BJ": "multiple_active_namechange_aliases"},
        )

    def test_plan_canonicalizes_existing_raw_and_requests_only_missing_alias(
        self,
    ) -> None:
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

    def test_source_faithful_extra_times_are_preserved_and_not_partial(self) -> None:
        plan, _plan_path = self._plan()

        self.assertFalse(plan["should_stop"])
        summary = plan["frozen_payload"]["scope_summaries"][0]
        self.assertEqual(summary["canonical_existing_latest_code_count"], 1)
        with self.resource.connect() as connection:
            source_fact = connection.execute(
                f"SELECT count(*), min(trade_time), max(trade_time) "
                f"FROM read_parquet({duckdb_string(self.raw_path)}) "
                "WHERE ts_code = '920001.BJ'"
            ).fetchone()
        self.assertEqual(source_fact[0], 271)
        self.assertEqual(source_fact[1].strftime("%H:%M:%S"), "09:30:00")
        self.assertEqual(source_fact[2].strftime("%H:%M:%S"), "15:30:00")

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
            recovered_time_fact = connection.execute(
                f"SELECT count(*), max(trade_time) "
                f"FROM read_parquet({duckdb_string(candidate_path)}) "
                "WHERE ts_code = '872392.BJ'"
            ).fetchone()
        self.assertEqual(bse_codes, [("872392.BJ",), ("920001.BJ",)])
        self.assertEqual(recovered_time_fact[0], 271)
        self.assertEqual(
            recovered_time_fact[1].strftime("%H:%M:%S"),
            "15:30:00",
        )

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
            Path(str(plan["scope_manifest_path"])).parent / "promote-checkpoint.json"
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

    def test_r1_preserves_existing_bse_code_outside_daily_expected_set(self) -> None:
        _write_rows(
            self.raw_path,
            RAW_SCHEMA,
            _minute_rows("920001.BJ", self.trade_date, 1)
            + _minute_rows("920305.BJ", self.trade_date, 1)
            + _minute_rows("000001.SZ", self.trade_date, 1),
        )
        _plan, plan_path = self._plan()
        bundle_path = self.root / "extra-bse-bundle.json"
        stage_bse_stk_mins_source_pages(
            plan_path=plan_path,
            tushare=_FakeTushare(self._source_rows()),
            duckdb_resource=self.resource,
            output_path=bundle_path,
            request_policy=TushareRequestPolicy(
                minimum_interval_seconds=0.0,
                max_retries=0,
                max_requests=10,
                max_elapsed_seconds=30.0,
            ),
        )
        candidate_path = self.root / "extra-bse-candidate.json"
        candidate = build_bse_raw_recovery_candidates(
            plan_path=plan_path,
            bundle_path=bundle_path,
            duckdb_resource=self.resource,
            output_path=candidate_path,
        )

        self.assertFalse(candidate["should_stop"])
        with self.resource.connect() as connection:
            codes = connection.execute(
                "SELECT DISTINCT ts_code "
                f"FROM read_parquet({duckdb_string(Path(candidate['candidates'][0]['path']))}) "
                "WHERE ts_code LIKE '%.BJ' ORDER BY ts_code"
            ).fetchall()
        self.assertEqual(
            codes,
            [("872392.BJ",), ("920001.BJ",), ("920305.BJ",)],
        )

        audit = audit_bse_raw_recovery_candidates(
            plan_path=plan_path,
            bundle_path=bundle_path,
            candidate_report_path=candidate_path,
            duckdb_resource=self.resource,
        )
        self.assertFalse(audit["should_stop"])

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

    def test_r0b_reuses_identical_windows_from_complete_blocked_bundle(self) -> None:
        old_plan, old_plan_path = self._plan()
        old_bundle_output = self.root / "old-bundle.json"
        old_fake = _FakeTushare(self._source_rows())
        old_bundle = stage_bse_stk_mins_source_pages(
            plan_path=old_plan_path,
            tushare=old_fake,
            duckdb_resource=self.resource,
            output_path=old_bundle_output,
            request_policy=TushareRequestPolicy(
                minimum_interval_seconds=0.0,
                max_retries=0,
                max_requests=10,
                max_elapsed_seconds=30.0,
            ),
        )
        blocked_payload = json.loads(old_bundle_output.read_text(encoding="utf-8"))
        blocked_payload["should_stop"] = True
        blocked_payload["blocked_mode_count"] = 1
        old_bundle_output.write_text(
            json.dumps(blocked_payload),
            encoding="utf-8",
        )

        _write_rows(
            silver_stock_daily_path(self.lake_root, self.trade_date),
            (("ts_code", "VARCHAR"),),
            [("920001.BJ",), ("920392.BJ",)],
        )
        new_plan, new_plan_path = self._plan()
        self.assertNotEqual(old_plan["plan_hash"], new_plan["plan_hash"])

        new_fake = _FakeTushare([])
        new_bundle = stage_bse_stk_mins_source_pages(
            plan_path=new_plan_path,
            tushare=new_fake,
            duckdb_resource=self.resource,
            reuse_plan_path=old_plan_path,
            reuse_source_bundle_path=old_bundle_output,
            request_policy=TushareRequestPolicy(
                minimum_interval_seconds=0.0,
                max_retries=0,
                max_requests=10,
                max_elapsed_seconds=30.0,
            ),
        )

        self.assertFalse(new_bundle["should_stop"])
        self.assertEqual(new_bundle["reused_window_count"], 1)
        self.assertEqual(new_bundle["requested_window_count"], 0)
        self.assertEqual(new_bundle["request_count"], 0)
        self.assertEqual(new_fake.calls, [])
        old_page = Path(
            old_bundle["frozen_bundle"]["source_windows"][0]["pages"][0]["path"]
        )
        new_page = Path(
            new_bundle["frozen_bundle"]["source_windows"][0]["pages"][0]["path"]
        )
        self.assertNotEqual(old_page, new_page)
        self.assertEqual(old_page.read_bytes(), new_page.read_bytes())
        self.assertTrue(
            new_page.resolve().is_relative_to(
                Path(str(new_plan["scope_manifest_path"])).parent.resolve()
            )
        )

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

    def test_source_extras_do_not_hide_a_missing_required_time(self) -> None:
        _plan, plan_path = self._plan()
        rows = self._source_rows()
        rows = [row for row in rows if not str(row["trade_time"]).endswith("10:00:00")]

        bundle = stage_bse_stk_mins_source_pages(
            plan_path=plan_path,
            tushare=_FakeTushare(rows),
            duckdb_resource=self.resource,
            request_policy=TushareRequestPolicy(
                minimum_interval_seconds=0.0,
                max_retries=0,
                max_requests=10,
                max_elapsed_seconds=30.0,
            ),
        )

        self.assertTrue(bundle["should_stop"])
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

    def test_one_minute_source_with_invalid_optional_tail_is_preserved(self) -> None:
        _plan, plan_path = self._plan()
        raw_before = self.raw_path.read_bytes()
        rows = self._source_rows()
        tail = next(row for row in rows if str(row["trade_time"]).endswith("15:30:00"))
        tail["vol"] = -1
        tail["amount"] = -1.0

        bundle = stage_bse_stk_mins_source_pages(
            plan_path=plan_path,
            tushare=_FakeTushare(rows),
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
        self.assertEqual(mode["mode"], "source_unusable_skip")
        self.assertEqual(mode["reason_code"], "source_optional_tail_invalid")
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

    def test_partial_coarse_source_uses_complete_one_minute_fallback(self) -> None:
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
        rows = self._source_rows()
        for row in rows:
            row["freq"] = "5min"

        bundle = stage_bse_stk_mins_source_pages(
            plan_path=plan_path,
            tushare=_FakeTushare(rows),
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
        self.assertEqual(
            mode["reason_code"],
            "source_partial_complete_1m_fallback",
        )

    def test_coarse_fallback_absence_checks_only_frozen_missing_codes(self) -> None:
        _write_rows(
            raw_stk_mins_path(self.lake_root, 5, self.trade_date),
            RAW_SCHEMA,
            _minute_rows("920001.BJ", self.trade_date, 5),
        )
        plan, _plan_path = self._plan(5)
        bundle = {
            "frozen_bundle": {
                "mode_rows": [
                    {
                        "trade_date": self.trade_date,
                        "freq": 5,
                        "mode": "silver_fallback_recoverable",
                    }
                ]
            }
        }
        with self.resource.connect() as connection:
            _assert_coarse_fallback_scopes_absent(
                connection=connection,
                lake_root=self.lake_root,
                identity_path=silver_stock_identity_map_path(self.lake_root),
                scope_relation=_scope_manifest_relation(plan),
                bundle=bundle,
                trade_date=self.trade_date,
            )

        _write_rows(
            raw_stk_mins_path(self.lake_root, 5, self.trade_date),
            RAW_SCHEMA,
            _minute_rows("920001.BJ", self.trade_date, 5)
            + _minute_rows("872392.BJ", self.trade_date, 5)[:1],
        )
        with (
            self.resource.connect() as connection,
            self.assertRaisesRegex(
                BseMinuteRecoveryError,
                "coarse fallback target contains existing BSE code-days",
            ),
        ):
            _assert_coarse_fallback_scopes_absent(
                connection=connection,
                lake_root=self.lake_root,
                identity_path=silver_stock_identity_map_path(self.lake_root),
                scope_relation=_scope_manifest_relation(plan),
                bundle=bundle,
                trade_date=self.trade_date,
            )

    def test_r2_one_minute_eligibility_accepts_source_faithful_tail(self) -> None:
        _write_rows(
            self.raw_path,
            RAW_SCHEMA,
            _minute_rows("920001.BJ", self.trade_date, 1, source_faithful=True)
            + _minute_rows("872392.BJ", self.trade_date, 1, source_faithful=True),
        )

        eligibility = audit_bse_one_minute_fallback_eligibility(
            lake_root=self.lake_root,
            trade_date=self.trade_date,
            expected_latest_codes=("920001.BJ", "920392.BJ"),
            duckdb_resource=self.resource,
        )

        self.assertTrue(eligibility.passed)
        self.assertEqual(eligibility.expected_latest_code_count, 2)
        self.assertEqual(eligibility.raw_1m_returned_latest_code_count, 2)
        self.assertEqual(eligibility.raw_1m_required_241_point_code_count, 2)
        self.assertEqual(eligibility.raw_1m_allowed_source_time_code_count, 2)
        self.assertEqual(eligibility.invalid_code_count, 0)

    def test_r2_one_minute_eligibility_blocks_missing_required_point(self) -> None:
        rows = _minute_rows("920001.BJ", self.trade_date, 1)
        rows += [
            row
            for row in _minute_rows("872392.BJ", self.trade_date, 1)
            if not str(row[2]).endswith("10:00:00")
        ]
        _write_rows(self.raw_path, RAW_SCHEMA, rows)

        eligibility = audit_bse_one_minute_fallback_eligibility(
            lake_root=self.lake_root,
            trade_date=self.trade_date,
            expected_latest_codes=("920001.BJ", "920392.BJ"),
            duckdb_resource=self.resource,
        )

        self.assertFalse(eligibility.passed)
        self.assertEqual(eligibility.raw_1m_required_241_point_code_count, 1)
        self.assertEqual(eligibility.invalid_code_samples, ("920392.BJ",))

    def test_r2_one_minute_eligibility_ignores_full_day_suspended_raw_code(
        self,
    ) -> None:
        _write_rows(
            self.raw_path,
            RAW_SCHEMA,
            _minute_rows("920001.BJ", self.trade_date, 1, source_faithful=True)
            + _minute_rows("872392.BJ", self.trade_date, 1, source_faithful=True)
            + _minute_rows("920305.BJ", self.trade_date, 1, source_faithful=True),
        )
        _write_rows(
            silver_stock_suspend_daily_path(self.lake_root, self.trade_date),
            (
                ("ts_code", "VARCHAR"),
                ("trade_date", "DATE"),
                ("suspend_timing", "VARCHAR"),
                ("suspend_type", "VARCHAR"),
            ),
            [("920305.BJ", self.trade_date, None, "S")],
        )

        eligibility = audit_bse_one_minute_fallback_eligibility(
            lake_root=self.lake_root,
            trade_date=self.trade_date,
            expected_latest_codes=("920001.BJ", "920392.BJ"),
            duckdb_resource=self.resource,
        )

        self.assertTrue(eligibility.passed)
        self.assertEqual(eligibility.invalid_code_count, 0)
        self.assertEqual(eligibility.raw_1m_returned_latest_code_count, 2)

    def test_r2_promotes_only_canonical_silver_changes(self) -> None:
        plan_path, bundle_path, raw_promote_path = self._complete_r1()
        self._prepare_r2_inputs()
        formal_before = {
            freq: silver_stk_mins_path(
                self.lake_root, freq, self.trade_date
            ).read_bytes()
            for freq in (1, 5, 15, 30, 60)
        }
        candidate_report_path = self.root / "r2-silver-candidates.json"
        with (
            patch(
                "orchestrator.defs.bootstrap.stk_mins_bse_history_recovery."
                "stk_mins_assets.write_silver_stk_mins_partition",
                side_effect=self._fake_silver_writer,
            ),
            patch(
                "orchestrator.defs.bootstrap.stk_mins_bse_history_recovery."
                "evaluate_silver_stk_mins_partition_diagnostics",
                side_effect=self._fake_silver_diagnostics,
            ),
        ):
            candidates = build_bse_silver_recovery_candidates(
                plan_path=plan_path,
                bundle_path=bundle_path,
                raw_promote_report_path=raw_promote_path,
                duckdb_resource=self.resource,
                output_path=candidate_report_path,
            )

        self.assertTrue(candidates["complete"])
        self.assertFalse(candidates["should_stop"])
        self.assertEqual(candidates["candidate_count"], 1)
        self.assertEqual(candidates["changed_candidate_count"], 1)
        freq1_candidate = next(
            row for row in candidates["candidates"] if int(row["freq"]) == 1
        )
        with self.resource.connect() as connection:
            non_bse_count = connection.execute(
                f"""
                SELECT count(*)
                FROM read_parquet('{freq1_candidate["path"]}')
                WHERE ts_code = '000156.SZ'
                """
            ).fetchone()[0]
        self.assertEqual(non_bse_count, 0)
        for freq in (1, 5, 15, 30, 60):
            self.assertEqual(
                silver_stk_mins_path(
                    self.lake_root, freq, self.trade_date
                ).read_bytes(),
                formal_before[freq],
            )

        audit_report_path = self.root / "r2-silver-audit.json"
        with patch(
            "orchestrator.defs.bootstrap.stk_mins_bse_history_recovery."
            "evaluate_silver_stk_mins_partition_diagnostics",
            side_effect=self._fake_silver_diagnostics,
        ):
            audit = audit_bse_silver_recovery_candidates(
                plan_path=plan_path,
                bundle_path=bundle_path,
                raw_promote_report_path=raw_promote_path,
                candidate_report_path=candidate_report_path,
                duckdb_resource=self.resource,
                output_path=audit_report_path,
            )
        self.assertTrue(audit["complete"])
        self.assertEqual(audit["changed_silver_count"], 1)
        changed = audit["changed_silver_rows"][0]
        self.assertEqual((changed["trade_date"], changed["freq"]), (self.trade_date, 1))

        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan_root = Path(str(plan["scope_manifest_path"])).parent
        manifest_path = plan_root / "actual-changed-silver-manifest.json"
        promoted = promote_bse_silver_recovery_candidates(
            plan_path=plan_path,
            bundle_path=bundle_path,
            raw_promote_report_path=raw_promote_path,
            audit_report_path=audit_report_path,
            confirm=True,
            checkpoint_path=plan_root / "silver-promote-checkpoint.json",
            changed_manifest_path=manifest_path,
            duckdb_resource=self.resource,
        )
        self.assertEqual(promoted["promoted_count"], 1)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["changed_silver_count"], 1)
        self.assertNotEqual(
            silver_stk_mins_path(self.lake_root, 1, self.trade_date).read_bytes(),
            formal_before[1],
        )
        for freq in (5, 15, 30, 60):
            self.assertEqual(
                silver_stk_mins_path(
                    self.lake_root, freq, self.trade_date
                ).read_bytes(),
                formal_before[freq],
            )

    def test_r2_promote_requires_confirmation(self) -> None:
        with self.assertRaisesRegex(BseMinuteRecoveryError, "explicit confirmation"):
            promote_bse_silver_recovery_candidates(
                plan_path=self.root / "missing-plan.json",
                bundle_path=self.root / "missing-bundle.json",
                raw_promote_report_path=self.root / "missing-raw-promote.json",
                audit_report_path=self.root / "missing-audit.json",
                confirm=False,
                checkpoint_path=self.root / "checkpoint.json",
                changed_manifest_path=self.root / "manifest.json",
            )

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
                    "build-silver-candidates",
                    "--plan",
                    str(self.root / "missing-plan.json"),
                    "--bundle",
                    str(self.root / "missing-bundle.json"),
                    "--raw-promote-report",
                    str(self.root / "missing-raw-promote.json"),
                    "--output",
                    str(self.root / "silver-candidates.json"),
                ]
            ),
            2,
        )
        self.assertEqual(
            main(
                [
                    "promote-silver",
                    "--plan",
                    str(self.root / "missing-plan.json"),
                    "--bundle",
                    str(self.root / "missing-bundle.json"),
                    "--raw-promote-report",
                    str(self.root / "missing-raw-promote.json"),
                    "--audit-report",
                    str(self.root / "missing-audit.json"),
                    "--checkpoint",
                    str(self.root / "checkpoint.json"),
                    "--changed-manifest",
                    str(self.root / "changed-manifest.json"),
                    "--output",
                    str(self.root / "silver-promote.json"),
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
        self.assertNotIn('stk_mins"', source)

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
