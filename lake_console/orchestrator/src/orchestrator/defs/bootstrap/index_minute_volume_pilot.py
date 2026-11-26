"""Prepare the approved DG index minute volume pilot in staging."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from uuid import UUID

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.io.cn_a_gold_minute_bars import (
    build_canonical_gold_minute_select_sql,
)
from orchestrator.defs.io.minute_partition_writer import MinutePartitionPublication
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    gold_index_mins_path,
    gold_major_index_mins_path,
    raw_index_mins_path,
    raw_major_index_mins_path,
    silver_index_mins_path,
    silver_major_index_mins_path,
)

CODE = "000001.SH"
DAY = "2026-11-24"
SHARES = 49_352_629_600


def _stage_candidate(
    old, target, inputs, volume_sql, dataset, freq, run_id, expected_rows, *, parameters=(),
):
    started = perf_counter()
    original = read_parquet(old)
    with connect_configured_duckdb(temp_policy="existing_no_spill") as db:
        db.execute(f"CREATE TEMP TABLE repair_volume AS {volume_sql}", parameters)
        rows, unique, shares = db.execute("""
            SELECT count(*), count(DISTINCT (ts_code, trade_time)), sum(vol)
            FROM repair_volume
        """).fetchone()
        if rows != unique or rows != expected_rows or shares != SHARES:
            raise ValueError(f"Volume inputs differ from the confirmed pilot: {old}")
        matched, scaled = db.execute(f"""
            SELECT count(*), count(*) FILTER (WHERE old.vol * 100 = repair.vol)
            FROM {original} old JOIN repair_volume repair USING (ts_code, trade_time)
        """).fetchone()
        if (matched, scaled) != (rows, rows):
            raise ValueError(f"Original volume or time keys differ from the pilot: {old}")

        select = f"""
            SELECT old.* REPLACE (coalesce(repair.vol, old.vol) AS vol)
            FROM {original} old LEFT JOIN repair_volume repair USING (ts_code, trade_time)
            ORDER BY old.ts_code, old.trade_time
        """
        row_count = db.execute(f"SELECT count(*) FROM {original}").fetchone()[0]

        def build(path):
            db.execute(copy_query_to_parquet(select, path))
            _audit_candidate(db, original, path)
            return {"row_count": row_count}

        if dataset is not None:
            publication = MinutePartitionPublication(
                dataset=dataset, target=target, day=DAY, freq=freq,
                publication_id=run_id, source_paths=(old, *inputs),
            )
            publication.run(build)
            reused = publication.reused
        else:
            reused = target.exists()
            if not reused:
                target.parent.mkdir(parents=True, exist_ok=True)
                with TemporaryDirectory(dir=target.parent) as directory:
                    candidate = Path(directory) / target.name
                    build(candidate)
                    candidate.replace(target)

        if reused:
            _audit_candidate(db, original, target)
        return {
            "source": str(old), "candidate": str(target), "total_rows": row_count,
            "target_rows": rows, "volume": shares, "source_bytes": old.stat().st_size,
            "candidate_bytes": target.stat().st_size, "reused": reused,
            "elapsed_ms": round((perf_counter() - started) * 1000, 2),
        }


def _audit_candidate(db, original, candidate):
    staged = read_parquet(candidate)
    if db.execute(f"DESCRIBE SELECT * FROM {original}").fetchall() != db.execute(
        f"DESCRIBE SELECT * FROM {staged}"
    ).fetchall():
        raise ValueError(f"Candidate schema differs: {candidate}")
    differences = db.execute(f"""
        SELECT count(*) FROM (
            (SELECT * EXCLUDE(vol) FROM {original} EXCEPT ALL SELECT * EXCLUDE(vol) FROM {staged})
            UNION ALL
            (SELECT * EXCLUDE(vol) FROM {staged} EXCEPT ALL SELECT * EXCLUDE(vol) FROM {original})
        )
    """).fetchone()[0]
    wrong_volume = db.execute(f"""
        SELECT count(*) FROM {staged} candidate
        JOIN {original} old USING (ts_code, trade_time)
        LEFT JOIN repair_volume repair USING (ts_code, trade_time)
        WHERE candidate.vol IS DISTINCT FROM coalesce(repair.vol, old.vol)
    """).fetchone()[0]
    if differences or wrong_volume:
        raise ValueError(f"Candidate differs beyond the agreed volume update: {candidate}")


def prepare_pilot(*, prod_rows: Path, run_id: UUID) -> list[dict]:
    root = Path(DEFAULT_LAKE_ROOT)
    stage_root = Path(DEFAULT_LAKE_STAGING_ROOT) / "index_minute_volume_pilot" / run_id.hex
    rows = [
        (code, datetime.fromisoformat(stamp), volume)
        for code, stamp, volume in json.loads(prod_rows.read_text())
    ]
    if len(rows) != 9 or any(code != CODE or stamp.date().isoformat() != DAY for code, stamp, _ in rows):
        raise ValueError("Prod readback is outside the approved 9-row pilot")

    def source(path, multiplier=1):
        return f"""
            SELECT ts_code, trade_time, vol * {multiplier} AS vol
            FROM {read_parquet(path)} WHERE ts_code='{CODE}'
        """

    def stage(path, inputs, volume_sql, dataset, freq, expected, *, parameters=()):
        old = path(root, f"{freq}min", DAY)
        target = stage_root / old.relative_to(root)
        result = _stage_candidate(
            old, target, inputs, volume_sql, dataset, freq, run_id.hex, expected,
            parameters=parameters,
        )
        results.append(result)
        return target

    results = []
    prod_volume = """
        SELECT unnest(?)::VARCHAR AS ts_code, unnest(?)::TIMESTAMP AS trade_time,
               unnest(?)::DOUBLE AS vol
    """
    raw = stage(
        raw_index_mins_path, [prod_rows], prod_volume, "raw_index_mins", 30, 9,
        parameters=tuple(list(column) for column in zip(*rows, strict=True)),
    )
    major_raw = raw_major_index_mins_path(root, "30min", DAY)
    for silver_path, gold_path, inputs, volume_sql, dataset in (
        (silver_index_mins_path, gold_index_mins_path, [raw], source(raw), "silver_index_mins"),
        (silver_major_index_mins_path, gold_major_index_mins_path, [major_raw], source(major_raw, 100),
         "silver_major_index_mins"),
    ):
        silver = stage(silver_path, inputs, volume_sql, dataset, 30, 9)
        derived = build_canonical_gold_minute_select_sql(
            source_relation_sql=f"SELECT * FROM {read_parquet(silver)} WHERE ts_code='{CODE}'",
            target_freq=90,
            partition_key=DAY,
        )
        projection = f"SELECT ts_code, trade_time, vol FROM ({derived})"
        stage(silver_path, [silver], projection, dataset, 90, 3)
        stage(gold_path, [silver], projection, None, 90, 3)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prod-rows", required=True, type=Path)
    parser.add_argument("--run-id", required=True, type=UUID)
    args = parser.parse_args()
    print(json.dumps(prepare_pilot(prod_rows=args.prod_rows, run_id=args.run_id), ensure_ascii=False))


if __name__ == "__main__":
    main()
