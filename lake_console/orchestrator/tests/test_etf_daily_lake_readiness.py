from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from orchestrator.defs.asset_guards.etf_daily_lake_readiness import (
    batch_etf_adj_factor_silver_lake_readiness,
    batch_etf_daily_silver_lake_readiness,
    batch_fund_adj_raw_lake_readiness,
    batch_fund_daily_raw_lake_readiness,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.etf_daily_raw_writer import (
    FUND_ADJ_RAW_SPEC,
    FUND_DAILY_RAW_SPEC,
    audit_etf_daily_raw_relation,
)
from orchestrator.defs.io.etf_daily_silver_writer import (
    write_etf_adj_factor_silver_partition,
    write_etf_daily_silver_partition,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.etf_daily import (
    RAW_TUSHARE_FUND_ADJ_ASSET_KEY,
    RAW_TUSHARE_FUND_DAILY_ASSET_KEY,
    SILVER_ETF_ADJ_FACTOR_ASSET_KEY,
    SILVER_ETF_DAILY_ASSET_KEY,
)
from orchestrator.defs.run_contracts.metadata import build_materialization_metadata
from tests.etf_daily_test_support import (
    basic_row,
    make_roots,
    write_basic_reference,
    write_raw_fixture,
)


@dataclass
class _FakeInstance:
    records_by_asset: dict[str, list[Any]]
    query_count: int = 0

    def fetch_materializations(self, records_filter, *, limit):  # type: ignore[no-untyped-def]
        self.query_count += 1
        asset_key = records_filter.asset_key.to_user_string()
        allowed = set(records_filter.asset_partitions or ())
        records = [
            record
            for record in self.records_by_asset.get(asset_key, ())
            if record.partition_key in allowed
        ]
        return SimpleNamespace(records=records[:limit])


def _record(
    *,
    storage_id: int,
    partition_key: str,
    metadata: dict[str, object],
) -> Any:
    return SimpleNamespace(
        storage_id=storage_id,
        partition_key=partition_key,
        asset_materialization=SimpleNamespace(
            partition=partition_key,
            metadata=metadata,
        ),
    )


def _daily_row(partition_key: str, ts_code: str = "510330.SH") -> dict[str, object]:
    source_date = partition_key.replace("-", "")
    return {
        "ts_code": ts_code,
        "trade_date": source_date,
        "pre_close": 4.0,
        "open": 4.0,
        "high": 4.02,
        "low": 3.99,
        "close": 4.01,
        "change": 0.01,
        "pct_chg": 0.25,
        "vol": 100.0,
        "amount": 400.0,
    }


def _adj_row(partition_key: str, ts_code: str = "510330.SH") -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "trade_date": partition_key.replace("-", ""),
        "adj_factor": 1.0,
        "discount_rate": None,
    }


def _raw_metadata(
    *,
    path: Path,
    partition_key: str,
    spec,
) -> dict[str, object]:  # type: ignore[no-untyped-def]
    with DuckDBResource().connect() as connection:
        audit = audit_etf_daily_raw_relation(
            connection,
            relation_sql=read_parquet(path, hive_partitioning=False),
            spec=spec,
            partition_key=partition_key,
        )
    assert not audit.error_codes
    assert audit.content_hash is not None
    return build_materialization_metadata(
        uri=path,
        row_count=audit.row_count,
        observed_columns=spec.source_columns,
        extra_metadata={
            "asset_key": spec.asset_key,
            "partition_key": partition_key,
            "source_row_count": audit.row_count,
            "normalized_row_count": audit.row_count,
            "written_row_count": audit.row_count,
            "content_hash": audit.content_hash,
        },
    )


def _silver_metadata(result) -> dict[str, object]:  # type: ignore[no-untyped-def]
    return build_materialization_metadata(
        uri=result.target_path,
        row_count=result.written_row_count,
        extra_metadata=result.to_details(),
    )


def _ten_weekdays() -> tuple[str, ...]:
    cursor = date(2026, 8, 19)
    values: list[str] = []
    while len(values) < 10:
        if cursor.weekday() < 5:
            values.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return tuple(values)


def test_ten_day_batch_readiness_uses_one_query_per_asset_and_one_connection(
    tmp_path: Path,
) -> None:
    lake_root, staging_root = make_roots(tmp_path)
    trade_dates = _ten_weekdays()
    basic_reference = write_basic_reference(
        lake_root=lake_root,
        staging_root=staging_root,
        rows=(basic_row("510330.SH"), basic_row("159919.SZ")),
        eligibility_as_of=date(2026, 9, 2),
    )
    raw_records: list[Any] = []
    silver_records: list[Any] = []
    for storage_id, trade_date in enumerate(trade_dates, start=1):
        raw_path = write_raw_fixture(
            lake_root=lake_root,
            spec=FUND_DAILY_RAW_SPEC,
            partition_key=trade_date,
            rows=(_daily_row(trade_date),),
        )
        raw_records.insert(
            0,
            _record(
                storage_id=storage_id,
                partition_key=trade_date,
                metadata=_raw_metadata(
                    path=raw_path,
                    partition_key=trade_date,
                    spec=FUND_DAILY_RAW_SPEC,
                ),
            ),
        )
        silver_result = write_etf_daily_silver_partition(
            lake_root_path=lake_root,
            staging_root_path=staging_root,
            duckdb_resource=DuckDBResource(),
            partition_key=trade_date,
            operation_id=f"silver-{trade_date}",
            basic_reference=basic_reference,
        )
        silver_records.insert(
            0,
            _record(
                storage_id=storage_id + 100,
                partition_key=trade_date,
                metadata=_silver_metadata(silver_result),
            ),
        )

    instance = _FakeInstance(
        {
            RAW_TUSHARE_FUND_DAILY_ASSET_KEY: raw_records,
            SILVER_ETF_DAILY_ASSET_KEY: silver_records,
        }
    )
    with DuckDBResource().connect() as connection:
        raw_batch = batch_fund_daily_raw_lake_readiness(
            instance=instance,
            connection=connection,
            lake_root=lake_root,
            trade_dates=trade_dates,
        )
        silver_batch = batch_etf_daily_silver_lake_readiness(
            instance=instance,
            connection=connection,
            lake_root=lake_root,
            trade_dates=trade_dates,
        )

    assert raw_batch.materialization_query_count == 1
    assert silver_batch.materialization_query_count == 1
    assert instance.query_count == 2
    assert all(status.ready for status in raw_batch.statuses)
    assert all(status.ready for status in silver_batch.statuses)
    assert raw_batch.elapsed_ms < 5_000
    assert silver_batch.elapsed_ms < 5_000


def test_readiness_rejects_more_than_ten_dates_without_querying() -> None:
    instance = _FakeInstance({})
    trade_dates = tuple(
        (date(2026, 8, 1) + timedelta(days=offset)).isoformat() for offset in range(11)
    )
    with (
        DuckDBResource().connect() as connection,
        pytest.raises(ValueError, match="exceeds_ten"),
    ):
        batch_fund_daily_raw_lake_readiness(
            instance=instance,
            connection=connection,
            lake_root=Path("/tmp/not-read"),
            trade_dates=trade_dates,
        )
    assert instance.query_count == 0


def test_file_without_materialization_is_a_non_overwritable_failure(
    tmp_path: Path,
) -> None:
    lake_root, _ = make_roots(tmp_path)
    partition_key = "2026-09-01"
    write_raw_fixture(
        lake_root=lake_root,
        spec=FUND_DAILY_RAW_SPEC,
        partition_key=partition_key,
        rows=(_daily_row(partition_key),),
    )
    instance = _FakeInstance({})
    with DuckDBResource().connect() as connection:
        batch = batch_fund_daily_raw_lake_readiness(
            instance=instance,
            connection=connection,
            lake_root=lake_root,
            trade_dates=(partition_key,),
        )
    status = batch.status_for_trade_date(partition_key)
    assert not status.ready
    assert not status.materialized
    assert status.file_exists
    assert status.reason_code == "materialized_check_failed"


def test_latest_bad_materialization_fails_without_falling_back(
    tmp_path: Path,
) -> None:
    lake_root, _ = make_roots(tmp_path)
    partition_key = "2026-09-01"
    path = write_raw_fixture(
        lake_root=lake_root,
        spec=FUND_DAILY_RAW_SPEC,
        partition_key=partition_key,
        rows=(_daily_row(partition_key),),
    )
    good_metadata = _raw_metadata(
        path=path,
        partition_key=partition_key,
        spec=FUND_DAILY_RAW_SPEC,
    )
    bad_metadata = dict(good_metadata)
    bad_metadata["goldenshare/content_hash"] = "0" * 64
    instance = _FakeInstance(
        {
            RAW_TUSHARE_FUND_DAILY_ASSET_KEY: [
                _record(
                    storage_id=2,
                    partition_key=partition_key,
                    metadata=bad_metadata,
                ),
                _record(
                    storage_id=1,
                    partition_key=partition_key,
                    metadata=good_metadata,
                ),
            ]
        }
    )
    with DuckDBResource().connect() as connection:
        batch = batch_fund_daily_raw_lake_readiness(
            instance=instance,
            connection=connection,
            lake_root=lake_root,
            trade_dates=(partition_key,),
        )
    assert batch.status_for_trade_date(partition_key).reason_code == (
        "materialized_check_failed"
    )
    assert instance.query_count == 1


def test_adj_factor_raw_and_silver_use_the_same_readiness_contract(
    tmp_path: Path,
) -> None:
    lake_root, staging_root = make_roots(tmp_path)
    partition_key = "2026-09-01"
    reference = write_basic_reference(
        lake_root=lake_root,
        staging_root=staging_root,
        rows=(basic_row("510330.SH"),),
    )
    raw_path = write_raw_fixture(
        lake_root=lake_root,
        spec=FUND_ADJ_RAW_SPEC,
        partition_key=partition_key,
        rows=(_adj_row(partition_key),),
    )
    silver_result = write_etf_adj_factor_silver_partition(
        lake_root_path=lake_root,
        staging_root_path=staging_root,
        duckdb_resource=DuckDBResource(),
        partition_key=partition_key,
        operation_id="adj-readiness",
        basic_reference=reference,
    )
    instance = _FakeInstance(
        {
            RAW_TUSHARE_FUND_ADJ_ASSET_KEY: [
                _record(
                    storage_id=1,
                    partition_key=partition_key,
                    metadata=_raw_metadata(
                        path=raw_path,
                        partition_key=partition_key,
                        spec=FUND_ADJ_RAW_SPEC,
                    ),
                )
            ],
            SILVER_ETF_ADJ_FACTOR_ASSET_KEY: [
                _record(
                    storage_id=2,
                    partition_key=partition_key,
                    metadata=_silver_metadata(silver_result),
                )
            ],
        }
    )
    with DuckDBResource().connect() as connection:
        raw_batch = batch_fund_adj_raw_lake_readiness(
            instance=instance,
            connection=connection,
            lake_root=lake_root,
            trade_dates=(partition_key,),
        )
        silver_batch = batch_etf_adj_factor_silver_lake_readiness(
            instance=instance,
            connection=connection,
            lake_root=lake_root,
            trade_dates=(partition_key,),
        )
    assert raw_batch.status_for_trade_date(partition_key).ready
    assert silver_batch.status_for_trade_date(partition_key).ready


@pytest.mark.parametrize("day_count", (2, 10))
@pytest.mark.parametrize("missing", (False, True))
def test_adj_coverage_controls_readiness_with_bounded_queries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    day_count: int,
    missing: bool,
) -> None:
    from orchestrator.defs.asset_guards import etf_daily_lake_readiness as readiness

    lake_root, staging_root = make_roots(tmp_path)
    dates = _ten_weekdays()[:day_count]
    rows = (basic_row("510330.SH"),)
    if missing:
        rows += (basic_row("159919.SZ"),)
    reference = write_basic_reference(
        lake_root=lake_root,
        staging_root=staging_root,
        rows=rows,
        eligibility_as_of=date(2026, 9, 2),
    )
    records = []
    snapshots = {}
    for index, trade_date in enumerate(dates):
        raw_path = write_raw_fixture(
            lake_root=lake_root,
            spec=FUND_ADJ_RAW_SPEC,
            partition_key=trade_date,
            rows=(_adj_row(trade_date), _adj_row(trade_date, "160105.SZ")),
        )
        result = write_etf_adj_factor_silver_partition(
            lake_root_path=lake_root,
            staging_root_path=staging_root,
            duckdb_resource=DuckDBResource(),
            partition_key=trade_date,
            operation_id=f"coverage-{index}",
            basic_reference=reference,
        )
        records.insert(
            0,
            _record(
                storage_id=index + 1,
                partition_key=trade_date,
                metadata=_silver_metadata(result),
            ),
        )
        snapshots[raw_path] = raw_path.read_bytes()
        snapshots[result.target_path] = result.target_path.read_bytes()
    instance = _FakeInstance({SILVER_ETF_ADJ_FACTOR_ASSET_KEY: records})
    original = readiness.audit_etf_daily_basic_coverage
    query_count = 0
    call_count = 0

    def counted(connection, **kwargs):
        nonlocal call_count
        call_count += 1

        class Counter:
            def execute(self, *args, **options):
                nonlocal query_count
                query_count += 1
                return connection.execute(*args, **options)

        return original(Counter(), **kwargs)

    monkeypatch.setattr(readiness, "audit_etf_daily_basic_coverage", counted)
    with DuckDBResource().connect() as connection:
        batch = batch_etf_adj_factor_silver_lake_readiness(
            instance=instance,
            connection=connection,
            lake_root=lake_root,
            trade_dates=dates,
        )
    assert instance.query_count == batch.materialization_query_count == 1
    assert call_count == day_count
    assert query_count == 2 * day_count
    assert all(status.ready is (not missing) for status in batch.statuses)
    if missing:
        assert all(
            status.reason_code == "materialized_check_failed"
            for status in batch.statuses
        )
    assert all(path.read_bytes() == value for path, value in snapshots.items())
