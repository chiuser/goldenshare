"""Manifest handoff and formal Raw bootstrap for stock nine-turn history."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from orchestrator.defs.duckdb_sql import copy_query_to_parquet, duckdb_string
from orchestrator.defs.paths import raw_stk_nineturn_path
from orchestrator.defs.resources import DuckDBResource


STK_NINETURN_DATASET_ID = "stk_nineturn"
STK_NINETURN_SOURCE_METHOD = "prod_db_readonly"
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
    expected_source_row_count: int
    annual_batches: tuple[int, ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["expected_partition_keys"] = list(self.expected_partition_keys)
        payload["raw_target_paths"] = [str(path) for path in self.raw_target_paths]
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
    partitions = tuple(str(item["trade_date"]) for item in record.get("partitions", ()))
    paths = tuple(Path(str(item["output"])) for item in record.get("partitions", ()))
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
        expected_source_row_count=manifest.source_row_count,
        annual_batches=tuple(sorted({int(key[:4]) for key in partitions})),
    )


def build_stk_nineturn_raw_history(
    *, manifest: StkNineturnProdExportManifest, lake_root: Path,
    duckdb: DuckDBResource, confirm_write: bool = False,
) -> StkNineturnHistoryBuildPlan:
    if not confirm_write:
        raise ValueError("Formal Raw bootstrap requires confirm_write=True.")
    plan = plan_stk_nineturn_raw_history(manifest=manifest, lake_root=lake_root)
    with duckdb.connect() as connection, TemporaryDirectory(prefix="stk_nineturn_raw_") as temp_dir:
        temp_root = Path(temp_dir)
        for source_path, target_path, partition_key in zip(
            manifest.output_paths, plan.raw_target_paths, plan.expected_partition_keys, strict=True
        ):
            temp_path = temp_root / f"{partition_key}.parquet"
            source = duckdb_string(str(source_path))
            connection.execute(copy_query_to_parquet(
                f"""
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
                FROM read_parquet({source}, hive_partitioning=false)
                WHERE CAST(trade_date AS DATE) = DATE '{partition_key}'
                ORDER BY ts_code
                """,
                temp_path,
            ))
            target_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temp_path, target_path)
    return plan


def _require(condition: bool, field: str) -> None:
    if not condition:
        raise ValueError(f"Approved stk_nineturn manifest failed validation: {field}")
