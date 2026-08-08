from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.assets.index_daily import (
    write_silver_index_daily_partition_from_raw_file,
)
from orchestrator.defs.bootstrap import (
    index_daily_000680_history_supplement_apply as apply,
)
from orchestrator.defs.bootstrap.index_daily_000680_history_supplement_plan import (
    SupplementSourceAudit,
)
from orchestrator.defs.duckdb_sql import INDEX_DAILY_RAW_COLUMNS
from tests._index_daily_000680_history_supplement_helpers import (
    frozen_plan_payload,
    write_plan,
)


def _raw_row(ts_code: str, trade_date: str = "20200102") -> tuple[object, ...]:
    values = {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "pre_close": 10.0,
        "change": 0.5,
        "pct_chg": 5.0,
        "vol": 100.0,
        "amount": 1_000.0,
    }
    return tuple(values[column] for column in INDEX_DAILY_RAW_COLUMNS)


def _write_raw(path: Path, rows: tuple[tuple[object, ...], ...]) -> None:
    with duckdb.connect(":memory:") as connection:
        apply._write_source_staging(
            connection=connection,
            rows=rows,
            target_path=path,
        )


def test_apply_requires_explicit_confirmation() -> None:
    with pytest.raises(apply.IndexDaily000680HistorySupplementApplyError):
        apply.require_explicit_apply(False)


def test_frozen_plan_rejects_content_tampering(tmp_path: Path) -> None:
    payload = frozen_plan_payload()
    plan_path = tmp_path / "plan.json"
    write_plan(plan_path, payload)

    loaded = apply.load_frozen_plan(
        plan_path,
        expected_plan_hash=str(payload["plan_hash"]),
    )
    assert loaded["run_id"] == "test-run"

    payload["run_id"] = "tampered-run"
    write_plan(plan_path, payload)
    with pytest.raises(
        apply.IndexDaily000680HistorySupplementApplyError,
        match="content does not match",
    ):
        apply.load_frozen_plan(
            plan_path,
            expected_plan_hash=str(payload["plan_hash"]),
        )


def test_batch_selection_rejects_more_than_100_dates() -> None:
    start_date = date(2020, 1, 1)
    payload = frozen_plan_payload(
        dates=tuple(
            (start_date + timedelta(days=offset)).isoformat()
            for offset in range(101)
        )
    )

    with pytest.raises(
        apply.IndexDaily000680HistorySupplementApplyError,
        match="at most 100 dates",
    ):
        apply.select_batch_dates(
            payload,
            layer="raw",
            start_date=None,
            end_date=None,
        )


def test_source_staging_accepts_json_loaded_audit_samples(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = (_raw_row(apply.TARGET_CODE),)
    audit = SupplementSourceAudit(
        row_count=1223,
        distinct_date_count=1223,
        min_trade_date="2020-01-02",
        max_trade_date="2025-01-16",
        duplicate_key_count=0,
        null_critical_row_count=0,
        invalid_ohlc_row_count=0,
        unexpected_code_count=0,
        unexpected_date_count=0,
        expected_date_missing_count=0,
        unexpected_date_samples=(),
        missing_date_samples=(),
        date_fingerprint="date-fingerprint",
        boundary_close=10.5,
        following_pre_close=10.5,
        boundary_matches=True,
    )
    payload = frozen_plan_payload()
    payload["source_audit"] = audit.to_dict()
    payload["plan_hash"] = apply.compute_frozen_plan_hash(payload)
    plan_path = tmp_path / "plan.json"
    write_plan(plan_path, payload)
    loaded = apply.load_frozen_plan(
        plan_path,
        expected_plan_hash=str(payload["plan_hash"]),
    )
    source_path = tmp_path / "staging" / "source.parquet"
    monkeypatch.setattr(
        apply,
        "read_prod_source_rows",
        lambda _resource: (rows, 10.5, 10.5),
    )
    monkeypatch.setattr(apply, "build_source_audit", lambda **_kwargs: audit)
    monkeypatch.setattr(apply, "source_staging_path", lambda _plan: source_path)

    report = apply.run_source_staging(
        plan=loaded,
        expected_plan_hash=str(payload["plan_hash"]),
        duckdb_resource=apply.DuckDBResource(),
        prod_postgres=apply.ProdPostgresResource(),
        apply=True,
    )

    assert report["source_audit"] == loaded["source_audit"]
    assert source_path.is_file()


def test_raw_candidate_preserves_non_target_rows_and_is_idempotent(
    tmp_path: Path,
) -> None:
    formal_path = tmp_path / "formal" / "trade_date=2020-01-02" / "part.parquet"
    source_path = tmp_path / "source.parquet"
    candidate = tmp_path / "candidate.parquet"
    _write_raw(formal_path, (_raw_row("000001.SH"),))
    _write_raw(source_path, (_raw_row(apply.TARGET_CODE),))

    with duckdb.connect(":memory:") as connection:
        first = apply._build_raw_candidate(
            connection,
            formal_path=formal_path,
            source_path=source_path,
            candidate=candidate,
            partition_key="2020-01-02",
        )
    assert first.passed is True
    assert first.before_row_count == 1
    assert first.after_row_count == 2
    assert first.before_non_target_fingerprint == first.after_non_target_fingerprint
    apply.promote_candidate(
        candidate=candidate,
        formal_path=formal_path,
        expected_sha256=first.candidate_sha256,
    )

    with duckdb.connect(":memory:") as connection:
        second = apply._build_raw_candidate(
            connection,
            formal_path=formal_path,
            source_path=source_path,
            candidate=candidate,
            partition_key="2020-01-02",
        )
    assert second.passed is True
    assert second.before_row_count == second.after_row_count == 2


def test_atomic_replace_failure_keeps_formal_file_unchanged(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.bin"
    formal_path = tmp_path / "formal.bin"
    candidate.write_bytes(b"candidate")
    formal_path.write_bytes(b"formal-before")

    def _fail_replace(_source: str | Path, _target: str | Path) -> None:
        raise OSError("replace failed")

    with pytest.raises(OSError, match="replace failed"):
        apply.promote_candidate(
            candidate=candidate,
            formal_path=formal_path,
            expected_sha256=apply.file_sha256(candidate),
            replace_fn=_fail_replace,
        )

    assert formal_path.read_bytes() == b"formal-before"
    assert not formal_path.with_name(f".{formal_path.name}.incoming").exists()


def test_explicit_silver_writer_uses_formal_normalization(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.parquet"
    silver_path = tmp_path / "silver.parquet"
    _write_raw(raw_path, (_raw_row("000001.SH"), _raw_row(apply.TARGET_CODE)))

    with duckdb.connect(":memory:") as connection:
        result = write_silver_index_daily_partition_from_raw_file(
            connection,
            raw_path=raw_path,
            target_path=silver_path,
            partition_key="2020-01-02",
        )
        rows = connection.execute(
            "SELECT ts_code, trade_date FROM read_parquet(?) ORDER BY ts_code",
            [str(silver_path)],
        ).fetchall()

    assert result.output_row_count == 2
    assert [row[0] for row in rows] == ["000001.SH", apply.TARGET_CODE]
    assert all(str(row[1]) == "2020-01-02" for row in rows)
