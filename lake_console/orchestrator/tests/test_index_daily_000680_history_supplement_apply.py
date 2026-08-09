from __future__ import annotations

import csv
import json
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
    compute_frozen_plan_hash,
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


def _write_major_indices_seed(path: Path, *, row_count: int) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=apply.major_indices_seed.MAJOR_INDICES_SEED_COLUMNS,
        )
        writer.writeheader()
        for rank in range(1, row_count + 1):
            writer.writerow(
                {
                    "rank": rank,
                    "ts_code": f"{rank:06d}.SH",
                    "display_name": "",
                    "effective_start_date": "2020-01-02",
                    "effective_end_date": "",
                }
            )


def _frozen_plan_with_seed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    row_count: int = 11,
) -> dict[str, object]:
    seed_path = tmp_path / "major_indices.cn_a.csv"
    _write_major_indices_seed(seed_path, row_count=row_count)
    monkeypatch.setattr(
        apply.major_indices_seed,
        "MAJOR_INDICES_SEED_PATH",
        seed_path,
    )
    monkeypatch.setattr(
        apply.major_indices_seed,
        "EXPECTED_MAJOR_INDICES_COUNT",
        11,
    )
    apply.major_indices_seed.load_major_indices_seed.cache_clear()
    payload = frozen_plan_payload()
    seed = payload["seed"]
    assert isinstance(seed, dict)
    seed.update(
        {
            "file_path": str(seed_path),
            "file_hash": apply.file_sha256(seed_path),
            "current_count": 11,
            "target_count": 11,
        }
    )
    payload["plan_hash"] = compute_frozen_plan_hash(payload)
    return payload


def test_apply_requires_explicit_confirmation() -> None:
    with pytest.raises(apply.IndexDaily000680HistorySupplementApplyError):
        apply.require_explicit_apply(False)


def test_frozen_seed_contract_accepts_exact_path_hash_and_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _frozen_plan_with_seed(tmp_path, monkeypatch)

    apply.require_frozen_seed_contract(payload)


def test_frozen_seed_contract_rejects_path_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _frozen_plan_with_seed(tmp_path, monkeypatch)
    seed = payload["seed"]
    assert isinstance(seed, dict)
    seed["file_path"] = str(tmp_path / "other-seed.csv")
    payload["plan_hash"] = compute_frozen_plan_hash(payload)

    with pytest.raises(
        apply.IndexDaily000680HistorySupplementApplyError,
        match="seed path differs",
    ):
        apply.require_frozen_seed_contract(payload)


def test_frozen_seed_contract_rejects_hash_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _frozen_plan_with_seed(tmp_path, monkeypatch)
    apply.major_indices_seed.MAJOR_INDICES_SEED_PATH.write_text(
        "drifted seed\n",
        encoding="utf-8",
    )

    with pytest.raises(
        apply.IndexDaily000680HistorySupplementApplyError,
        match="seed hash differs",
    ):
        apply.require_frozen_seed_contract(payload)


def test_frozen_seed_contract_rejects_row_count_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _frozen_plan_with_seed(tmp_path, monkeypatch, row_count=10)

    with pytest.raises(
        apply.IndexDaily000680HistorySupplementApplyError,
        match="cannot satisfy its formal contract",
    ):
        apply.require_frozen_seed_contract(payload)


def test_gold_batch_checks_seed_before_calling_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = frozen_plan_payload()
    plan_hash = str(payload["plan_hash"])

    def _blocked_seed(_plan: object) -> None:
        raise apply.IndexDaily000680HistorySupplementApplyError("seed blocked")

    monkeypatch.setattr(apply, "require_frozen_seed_contract", _blocked_seed)
    monkeypatch.setattr(
        apply,
        "write_gold_market_major_indices_daily_partition",
        lambda *_args, **_kwargs: pytest.fail("Gold writer must not run"),
    )

    with pytest.raises(
        apply.IndexDaily000680HistorySupplementApplyError,
        match="seed blocked",
    ):
        apply.run_gold_batch(
            plan=payload,
            expected_plan_hash=plan_hash,
            duckdb_resource=apply.DuckDBResource(),
            start_date="2020-01-02",
            end_date="2020-01-02",
            apply=True,
        )


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


def test_checkpoint_replace_failure_keeps_previous_checkpoint(tmp_path: Path) -> None:
    checkpoint = tmp_path / "manifest" / "raw-checkpoints.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text("previous-checkpoint\n", encoding="utf-8")
    report = apply.LayerBatchReport(
        layer="raw",
        plan_hash="plan-hash",
        selected_dates=(),
        audits=(),
        promoted_count=0,
        checkpoint_path=str(checkpoint),
    )

    def _fail_replace(_source: str | Path, _target: str | Path) -> None:
        raise OSError("checkpoint replace failed")

    with pytest.raises(OSError, match="checkpoint replace failed"):
        apply._checkpoint(report, replace_fn=_fail_replace)

    assert checkpoint.read_text(encoding="utf-8") == "previous-checkpoint\n"
    assert not checkpoint.with_name(f".{checkpoint.name}.incoming").exists()


def test_raw_checkpoint_accumulates_and_skips_verified_dates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = ("2020-01-02", "2020-01-03")
    payload = frozen_plan_payload(dates=dates)
    plan_hash = str(payload["plan_hash"])
    source_path = tmp_path / "source.parquet"
    checkpoint = tmp_path / "manifest" / "raw-checkpoints.json"
    formal_root = tmp_path / "formal" / "raw"
    candidate_root = tmp_path / "candidate"
    _write_raw(
        source_path,
        tuple(
            _raw_row(apply.TARGET_CODE, trade_date.replace("-", ""))
            for trade_date in dates
        ),
    )
    for trade_date in dates:
        _write_raw(
            formal_root / trade_date / "part.parquet",
            (_raw_row("000001.SH", trade_date.replace("-", "")),),
        )
    monkeypatch.setattr(apply, "source_staging_path", lambda _plan: source_path)
    monkeypatch.setattr(
        apply,
        "raw_index_daily_path",
        lambda _root, partition_key: formal_root / partition_key / "part.parquet",
    )
    monkeypatch.setattr(
        apply,
        "candidate_path",
        lambda _plan, layer, partition_key: (
            candidate_root / layer / partition_key / "part.parquet"
        ),
    )
    monkeypatch.setattr(apply, "checkpoint_path", lambda _plan, _layer: checkpoint)

    first = apply.run_raw_batch(
        plan=payload,
        expected_plan_hash=plan_hash,
        duckdb_resource=apply.DuckDBResource(),
        start_date=dates[0],
        end_date=dates[0],
        apply=True,
    )
    second = apply.run_raw_batch(
        plan=payload,
        expected_plan_hash=plan_hash,
        duckdb_resource=apply.DuckDBResource(),
        start_date=dates[1],
        end_date=dates[1],
        apply=True,
    )
    resumed = apply.run_raw_batch(
        plan=payload,
        expected_plan_hash=plan_hash,
        duckdb_resource=apply.DuckDBResource(),
        start_date=dates[0],
        end_date=dates[1],
        apply=True,
    )

    checkpoint_payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert first.promoted_count == second.promoted_count == 1
    assert resumed.promoted_count == 0
    assert resumed.passed is True
    assert checkpoint_payload["selected_dates"] == list(dates)
    assert checkpoint_payload["promoted_count"] == 2
    assert [value["partition_key"] for value in checkpoint_payload["audits"]] == list(
        dates
    )


def test_silver_checkpoint_accumulates_across_batches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = ("2020-01-02", "2020-01-03")
    payload = frozen_plan_payload(dates=dates)
    plan_hash = str(payload["plan_hash"])
    raw_root = tmp_path / "formal" / "raw"
    silver_root = tmp_path / "formal" / "silver"
    candidate_root = tmp_path / "candidate"
    checkpoint = tmp_path / "manifest" / "silver-checkpoints.json"
    with duckdb.connect(":memory:") as connection:
        for trade_date in dates:
            compact_date = trade_date.replace("-", "")
            raw_path = raw_root / trade_date / "part.parquet"
            prior_raw_path = tmp_path / "prior-raw" / trade_date / "part.parquet"
            _write_raw(
                raw_path,
                (
                    _raw_row("000001.SH", compact_date),
                    _raw_row(apply.TARGET_CODE, compact_date),
                ),
            )
            _write_raw(
                prior_raw_path,
                (_raw_row("000001.SH", compact_date),),
            )
            write_silver_index_daily_partition_from_raw_file(
                connection,
                raw_path=prior_raw_path,
                target_path=silver_root / trade_date / "part.parquet",
                partition_key=trade_date,
            )
    monkeypatch.setattr(
        apply,
        "raw_index_daily_path",
        lambda _root, partition_key: raw_root / partition_key / "part.parquet",
    )
    monkeypatch.setattr(
        apply,
        "silver_index_daily_path",
        lambda _root, partition_key: silver_root / partition_key / "part.parquet",
    )
    monkeypatch.setattr(
        apply,
        "candidate_path",
        lambda _plan, layer, partition_key: (
            candidate_root / layer / partition_key / "part.parquet"
        ),
    )
    monkeypatch.setattr(apply, "checkpoint_path", lambda _plan, _layer: checkpoint)

    for trade_date in dates:
        report = apply.run_silver_batch(
            plan=payload,
            expected_plan_hash=plan_hash,
            duckdb_resource=apply.DuckDBResource(),
            start_date=trade_date,
            end_date=trade_date,
            apply=True,
        )
        assert report.promoted_count == 1

    resumed = apply.run_silver_batch(
        plan=payload,
        expected_plan_hash=plan_hash,
        duckdb_resource=apply.DuckDBResource(),
        start_date=dates[0],
        end_date=dates[1],
        apply=True,
    )
    checkpoint_payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert resumed.promoted_count == 0
    assert resumed.passed is True
    assert checkpoint_payload["selected_dates"] == list(dates)


def test_checkpoint_hash_drift_stops_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = frozen_plan_payload()
    plan_hash = str(payload["plan_hash"])
    source_path = tmp_path / "source.parquet"
    formal_path = tmp_path / "formal.parquet"
    candidate = tmp_path / "candidate.parquet"
    checkpoint = tmp_path / "raw-checkpoints.json"
    _write_raw(source_path, (_raw_row(apply.TARGET_CODE),))
    _write_raw(formal_path, (_raw_row("000001.SH"),))
    monkeypatch.setattr(apply, "source_staging_path", lambda _plan: source_path)
    monkeypatch.setattr(
        apply, "raw_index_daily_path", lambda _root, _partition_key: formal_path
    )
    monkeypatch.setattr(
        apply,
        "candidate_path",
        lambda _plan, _layer, _partition_key: candidate,
    )
    monkeypatch.setattr(apply, "checkpoint_path", lambda _plan, _layer: checkpoint)
    apply.run_raw_batch(
        plan=payload,
        expected_plan_hash=plan_hash,
        duckdb_resource=apply.DuckDBResource(),
        start_date="2020-01-02",
        end_date="2020-01-02",
        apply=True,
    )
    candidate.write_bytes(b"drifted candidate")

    with pytest.raises(
        apply.IndexDaily000680HistorySupplementApplyError,
        match="checkpoint hash drifted",
    ):
        apply.run_raw_batch(
            plan=payload,
            expected_plan_hash=plan_hash,
            duckdb_resource=apply.DuckDBResource(),
            start_date="2020-01-02",
            end_date="2020-01-02",
            apply=True,
        )


def test_checkpoint_only_hashes_completed_dates_selected_for_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = ("2020-01-02", "2020-01-03")
    payload = frozen_plan_payload(dates=dates)
    plan_hash = str(payload["plan_hash"])
    source_path = tmp_path / "source.parquet"
    checkpoint = tmp_path / "raw-checkpoints.json"
    formal_root = tmp_path / "formal"
    candidate_root = tmp_path / "candidate"
    _write_raw(
        source_path,
        tuple(
            _raw_row(apply.TARGET_CODE, trade_date.replace("-", ""))
            for trade_date in dates
        ),
    )
    for trade_date in dates:
        _write_raw(
            formal_root / trade_date / "part.parquet",
            (_raw_row("000001.SH", trade_date.replace("-", "")),),
        )
    monkeypatch.setattr(apply, "source_staging_path", lambda _plan: source_path)
    monkeypatch.setattr(
        apply,
        "raw_index_daily_path",
        lambda _root, partition_key: formal_root / partition_key / "part.parquet",
    )
    monkeypatch.setattr(
        apply,
        "candidate_path",
        lambda _plan, layer, partition_key: (
            candidate_root / layer / partition_key / "part.parquet"
        ),
    )
    monkeypatch.setattr(apply, "checkpoint_path", lambda _plan, _layer: checkpoint)

    for trade_date in dates:
        apply.run_raw_batch(
            plan=payload,
            expected_plan_hash=plan_hash,
            duckdb_resource=apply.DuckDBResource(),
            start_date=trade_date,
            end_date=trade_date,
            apply=True,
        )

    first_candidate = candidate_root / "raw" / dates[0] / "part.parquet"
    first_candidate.write_bytes(b"drifted outside selected batch")
    selected_report = apply.run_raw_batch(
        plan=payload,
        expected_plan_hash=plan_hash,
        duckdb_resource=apply.DuckDBResource(),
        start_date=dates[1],
        end_date=dates[1],
        apply=True,
    )
    assert selected_report.promoted_count == 0

    with pytest.raises(
        apply.IndexDaily000680HistorySupplementApplyError,
        match="checkpoint hash drifted",
    ):
        apply.load_checkpoint_audits(
            payload,
            layer="raw",
            expected_plan_hash=plan_hash,
        )


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
