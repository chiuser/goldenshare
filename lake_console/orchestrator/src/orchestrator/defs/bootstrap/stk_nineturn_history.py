"""Manifest handoff and formal Raw bootstrap for stock nine-turn history."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from orchestrator.defs.duckdb_sql import copy_query_to_parquet, duckdb_string
from orchestrator.defs.paths import (
    raw_stk_nineturn_path,
    silver_stock_daily_path,
    silver_stock_identity_map_path,
    silver_stock_nineturn_daily_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.stk_nineturn_contract import (
    build_stk_nineturn_path_plan,
    build_silver_stock_nineturn_daily_batch_select_sql,
    load_raw_stk_nineturn_metrics,
    load_silver_stock_nineturn_daily_metrics,
)


STK_NINETURN_DATASET_ID = "stk_nineturn"
STK_NINETURN_SOURCE_METHOD = "prod-raw-db"
STK_NINETURN_HISTORY_START_DATE = "2023-01-03"
STK_NINETURN_RAW_COLUMNS = (
    "ts_code", "trade_date", "freq", "open", "high", "low", "close",
    "vol", "amount", "up_count", "down_count", "nine_up_turn",
    "nine_down_turn",
)


@dataclass(frozen=True, slots=True)
class StkNineturnProdExportManifest:
    run_id: str
    dataset_id: str
    source_method: str
    mode: str
    start_date: str
    end_date: str
    partition_keys: tuple[str, ...]
    source_row_count: int
    written_row_count: int
    skipped_partition_keys: tuple[str, ...]
    output_paths: tuple[Path, ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["partition_keys"] = list(self.partition_keys)
        payload["skipped_partition_keys"] = list(self.skipped_partition_keys)
        payload["output_paths"] = [str(path) for path in self.output_paths]
        return payload


@dataclass(frozen=True, slots=True)
class StkNineturnHistoryBuildPlan:
    run_id: str
    start_date: str
    end_date: str
    expected_partition_keys: tuple[str, ...]
    raw_target_paths: tuple[Path, ...]
    silver_target_paths: tuple[Path, ...]
    expected_source_row_count: int
    annual_batches: tuple[int, ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["expected_partition_keys"] = list(self.expected_partition_keys)
        payload["raw_target_paths"] = [str(path) for path in self.raw_target_paths]
        payload["silver_target_paths"] = [str(path) for path in self.silver_target_paths]
        payload["annual_batches"] = list(self.annual_batches)
        return payload


def load_stk_nineturn_prod_export_manifest(
    *, manifest_path: Path, run_id: str,
) -> StkNineturnProdExportManifest:
    """Load and validate only the approved prod export record."""
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Missing nine-turn export manifest: {manifest_path}")
    records = []
    with manifest_path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                if record.get("run_id") == run_id:
                    records.append(record)
    if len(records) != 1:
        raise ValueError(f"Expected exactly one manifest record for {run_id!r}.")
    record = records[0]
    _require(record.get("dataset_key") == STK_NINETURN_DATASET_ID, "dataset_id")
    _require(record.get("source") == STK_NINETURN_SOURCE_METHOD, "source_method")
    _require(record.get("mode") == "range_rebuild", "mode")
    _require(record.get("start_date") == STK_NINETURN_HISTORY_START_DATE, "start_date")
    partition_records = tuple(
        sorted(record.get("partitions", ()), key=lambda item: str(item["trade_date"]))
    )
    partitions = tuple(str(item["trade_date"]) for item in partition_records)
    paths = tuple(Path(str(item["output"])) for item in partition_records)
    _require(bool(partitions), "partition_keys")
    _require(not record.get("skipped_partitions"), "skipped_partitions")
    _require(int(record.get("fetched_rows", 0)) == int(record.get("written_rows", 0)), "row_counts")
    _require(all(path.is_file() for path in paths), "output_paths")
    return StkNineturnProdExportManifest(
        run_id=run_id,
        dataset_id=STK_NINETURN_DATASET_ID,
        source_method=STK_NINETURN_SOURCE_METHOD,
        mode="range_rebuild",
        start_date=str(record["start_date"]),
        end_date=str(record["end_date"]),
        partition_keys=partitions,
        source_row_count=int(record["fetched_rows"]),
        written_row_count=int(record["written_rows"]),
        skipped_partition_keys=(),
        output_paths=paths,
    )


def plan_stk_nineturn_raw_history(
    *, manifest: StkNineturnProdExportManifest, lake_root: Path,
) -> StkNineturnHistoryBuildPlan:
    partitions = tuple(sorted(manifest.partition_keys))
    return StkNineturnHistoryBuildPlan(
        run_id=manifest.run_id,
        start_date=manifest.start_date,
        end_date=manifest.end_date,
        expected_partition_keys=partitions,
        raw_target_paths=tuple(raw_stk_nineturn_path(lake_root, key) for key in partitions),
        silver_target_paths=tuple(
            silver_stock_nineturn_daily_path(lake_root, key) for key in partitions
        ),
        expected_source_row_count=manifest.source_row_count,
        annual_batches=tuple(sorted({int(key[:4]) for key in partitions})),
    )


def build_stk_nineturn_raw_history(
    *, manifest: StkNineturnProdExportManifest, lake_root: Path,
    duckdb_resource: DuckDBResource, confirm_write: bool = False,
) -> StkNineturnHistoryBuildPlan:
    if not confirm_write:
        raise ValueError("Formal Raw bootstrap requires confirm_write=True.")
    plan = plan_stk_nineturn_raw_history(manifest=manifest, lake_root=lake_root)
    sources_by_year: dict[int, list[tuple[str, Path]]] = {}
    for partition_key, source_path in zip(
        plan.expected_partition_keys, manifest.output_paths, strict=True
    ):
        sources_by_year.setdefault(int(partition_key[:4]), []).append(
            (partition_key, source_path)
        )
    with duckdb_resource.connect() as connection, TemporaryDirectory(
        dir=str(lake_root), prefix=".stk_nineturn_raw_"
    ) as temp_dir:
        temp_root = Path(temp_dir)
        for year, year_sources in sorted(sources_by_year.items()):
            table_name = f"nineturn_raw_{year}"
            source_sql = ", ".join(duckdb_string(str(path)) for _, path in year_sources)
            connection.execute(
                f"""
                CREATE OR REPLACE TEMP TABLE {table_name} AS
                SELECT CAST(ts_code AS VARCHAR) AS ts_code,
                       CAST(trade_date AS DATE) AS trade_date,
                       CAST(freq AS VARCHAR) AS freq,
                       CAST(open AS DOUBLE) AS open,
                       CAST(high AS DOUBLE) AS high,
                       CAST(low AS DOUBLE) AS low,
                       CAST(close AS DOUBLE) AS close,
                       CAST(vol AS DOUBLE) AS vol,
                       CAST(amount AS DOUBLE) AS amount,
                       CAST(up_count AS DOUBLE) AS up_count,
                       CAST(down_count AS DOUBLE) AS down_count,
                       CAST(nine_up_turn AS VARCHAR) AS nine_up_turn,
                       CAST(nine_down_turn AS VARCHAR) AS nine_down_turn
                FROM read_parquet([{source_sql}], hive_partitioning=false, union_by_name=true)
                """
            )
            year_temp_root = temp_root / str(year)
            year_temp_root.mkdir()
            for partition_key, _source_path in year_sources:
                temp_path = year_temp_root / f"{partition_key}.parquet"
                connection.execute(copy_query_to_parquet(
                    f"SELECT * FROM {table_name} WHERE trade_date = DATE '{partition_key}' ORDER BY ts_code",
                    temp_path,
                ))
                target_path = raw_stk_nineturn_path(lake_root, partition_key)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(temp_path, target_path)
    return plan


def build_stk_nineturn_silver_history(
    *, manifest: StkNineturnProdExportManifest, lake_root: Path,
    duckdb_resource: DuckDBResource, confirm_write: bool = False,
) -> StkNineturnHistoryBuildPlan:
    """Build Silver with one canonical mapping query per year."""
    if not confirm_write:
        raise ValueError("Formal Silver bootstrap requires confirm_write=True.")
    identity_map_path = silver_stock_identity_map_path(lake_root)
    if not identity_map_path.is_file():
        raise FileNotFoundError(f"Missing identity map: {identity_map_path}")
    plan = plan_stk_nineturn_raw_history(manifest=manifest, lake_root=lake_root)
    sources_by_year: dict[int, list[Path]] = {}
    dates_by_year: dict[int, list[str]] = {}
    for key, source_path in zip(
        plan.expected_partition_keys, plan.raw_target_paths, strict=True
    ):
        year = int(key[:4])
        sources_by_year.setdefault(year, []).append(source_path)
        dates_by_year.setdefault(year, []).append(key)

    with duckdb_resource.connect() as connection, TemporaryDirectory(
        dir=str(lake_root), prefix=".stk_nineturn_silver_"
    ) as temp_dir:
        temp_root = Path(temp_dir)
        for year in sorted(sources_by_year):
            table_name = f"nineturn_silver_{year}"
            query = build_silver_stock_nineturn_daily_batch_select_sql(
                raw_paths=tuple(sources_by_year[year]),
                identity_map_path=identity_map_path,
            )
            connection.execute(f"CREATE OR REPLACE TEMP TABLE {table_name} AS {query}")
            year_temp_root = temp_root / str(year)
            year_temp_root.mkdir()
            for trade_date in dates_by_year[year]:
                temporary_path = year_temp_root / f"{trade_date}.parquet"
                connection.execute(copy_query_to_parquet(
                    f"SELECT * FROM {table_name} WHERE trade_date = DATE '{trade_date}' ORDER BY ts_code",
                    temporary_path,
                ))
                target_path = silver_stock_nineturn_daily_path(lake_root, trade_date)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(temporary_path, target_path)
    return plan


@dataclass(frozen=True, slots=True)
class StkNineturnFileAudit:
    expected_partition_count: int
    raw_partition_count: int
    silver_partition_count: int
    raw_row_count: int
    silver_row_count: int
    prod_source_row_count: int
    unmapped_source_code_count: int
    canonical_duplicate_key_count: int
    market_value_conflict_key_count: int
    count_signal_conflict_key_count: int
    stock_daily_warmup_gap_count: int
    raw_failed_partition_count: int
    silver_failed_partition_count: int
    missing_raw_partition_keys: tuple[str, ...]
    missing_silver_partition_keys: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["missing_raw_partition_keys"] = list(self.missing_raw_partition_keys)
        payload["missing_silver_partition_keys"] = list(self.missing_silver_partition_keys)
        return payload


def audit_stk_nineturn_formal_files(
    *, manifest: StkNineturnProdExportManifest, lake_root: Path,
    duckdb_resource: DuckDBResource,
) -> StkNineturnFileAudit:
    """Read-only file/row audit for promoted Raw and Silver partitions."""
    expected = tuple(sorted(manifest.partition_keys))
    raw_paths = tuple(raw_stk_nineturn_path(lake_root, key) for key in expected)
    silver_paths = tuple(silver_stock_nineturn_daily_path(lake_root, key) for key in expected)
    missing_raw = tuple(key for key, path in zip(expected, raw_paths, strict=True) if not path.is_file())
    missing_silver = tuple(key for key, path in zip(expected, silver_paths, strict=True) if not path.is_file())
    raw_plans = tuple(
        build_stk_nineturn_path_plan(trade_date=key, path=path)
        for key, path in zip(expected, raw_paths, strict=True)
    )
    silver_plans = tuple(
        build_stk_nineturn_path_plan(trade_date=key, path=path)
        for key, path in zip(expected, silver_paths, strict=True)
    )
    with duckdb_resource.connect() as connection:
        raw_count = _count_rows(connection, tuple(path for path in raw_paths if path.is_file()))
        silver_count = _count_rows(connection, tuple(path for path in silver_paths if path.is_file()))
        raw_metrics = load_raw_stk_nineturn_metrics(connection, path_plans=raw_plans)
        silver_metrics = load_silver_stock_nineturn_daily_metrics(
            connection,
            raw_path_plans=raw_plans,
            silver_path_plans=silver_plans,
            identity_map_path=silver_stock_identity_map_path(lake_root),
        )
        stock_daily_paths = tuple(
            silver_stock_daily_path(lake_root, key)
            for key in expected
            if silver_stock_daily_path(lake_root, key).is_file()
        )
        warmup_gap_count = _count_stock_daily_warmup_gaps(
            connection, stock_daily_paths, tuple(path for path in silver_paths if path.is_file())
        )
    return StkNineturnFileAudit(
        expected_partition_count=len(expected),
        raw_partition_count=len(expected) - len(missing_raw),
        silver_partition_count=len(expected) - len(missing_silver),
        raw_row_count=raw_count,
        silver_row_count=silver_count,
        prod_source_row_count=manifest.source_row_count,
        unmapped_source_code_count=sum(m.unmapped_source_code_count for m in silver_metrics.values()),
        canonical_duplicate_key_count=sum(m.canonical_duplicate_key_count for m in silver_metrics.values()),
        market_value_conflict_key_count=sum(m.market_value_conflict_key_count for m in silver_metrics.values()),
        count_signal_conflict_key_count=sum(m.count_signal_conflict_key_count for m in silver_metrics.values()),
        stock_daily_warmup_gap_count=warmup_gap_count,
        raw_failed_partition_count=sum(bool(m.row_count == 0 or m.null_key_count or m.duplicate_key_count) for m in raw_metrics.values()),
        silver_failed_partition_count=sum(bool(m.row_count == 0 or m.unmapped_source_code_count or m.market_value_conflict_key_count) for m in silver_metrics.values()),
        missing_raw_partition_keys=missing_raw,
        missing_silver_partition_keys=missing_silver,
    )


def _require(condition: bool, field: str) -> None:
    if not condition:
        raise ValueError(f"Approved stk_nineturn manifest failed validation: {field}")


def _count_rows(connection, paths: tuple[Path, ...]) -> int:
    if not paths:
        return 0
    path_sql = ", ".join(duckdb_string(path) for path in paths)
    return int(connection.execute(
        f"SELECT count(*) FROM read_parquet([{path_sql}], hive_partitioning=false, union_by_name=true)"
    ).fetchone()[0])


def _count_stock_daily_warmup_gaps(
    connection, stock_daily_paths: tuple[Path, ...], nineturn_paths: tuple[Path, ...]
) -> int:
    if not stock_daily_paths or not nineturn_paths:
        return 0
    daily_sql = ", ".join(duckdb_string(path) for path in stock_daily_paths)
    nineturn_sql = ", ".join(duckdb_string(path) for path in nineturn_paths)
    return int(connection.execute(
        f"""
        SELECT count(*)
        FROM read_parquet([{daily_sql}], hive_partitioning=false, union_by_name=true) daily
        LEFT JOIN read_parquet([{nineturn_sql}], hive_partitioning=false, union_by_name=true) nine
          ON daily.ts_code = nine.ts_code
         AND CAST(daily.trade_date AS DATE) = CAST(nine.trade_date AS DATE)
        WHERE nine.ts_code IS NULL
        """
    ).fetchone()[0])
