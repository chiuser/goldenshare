import tempfile
import unittest
from pathlib import Path

import duckdb

from orchestrator.defs.bootstrap import bootstrap_partition_to_raw
from orchestrator.defs.bootstrap.specs.adj_factor import adj_factor_bootstrap_spec
from orchestrator.defs.duckdb_sql import (
    ADJ_FACTOR_RAW_REQUIRED_COLUMNS,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.metadata import (
    DAGSTER_ROW_COUNT_METADATA_KEY,
    DAGSTER_URI_METADATA_KEY,
    OBSERVED_COLUMNS_METADATA_KEY,
)


PARTITION_KEY = "2009-01-05"


def _old_adj_factor_path(old_lake_root: Path) -> Path:
    return (
        old_lake_root
        / "raw_tushare"
        / "adj_factor"
        / f"trade_date={PARTITION_KEY}"
        / "part-000.parquet"
    )


def _write_old_adj_factor_file(
    old_lake_root: Path,
    *,
    trade_date_expression: str,
    include_rows: bool = True,
) -> Path:
    path = _old_adj_factor_path(old_lake_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    where_clause = "" if include_rows else "WHERE false"
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT
                '000001.SZ'::VARCHAR AS ts_code,
                {trade_date_expression} AS trade_date,
                1.234::DOUBLE AS adj_factor
              {where_clause}
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )
    return path


def _read_bootstrapped_rows(target_path: Path) -> list[tuple[str, str, float]]:
    with duckdb.connect(database=":memory:") as connection:
        return connection.execute(
            f"""
            SELECT ts_code, trade_date, adj_factor
            FROM {read_parquet(target_path, hive_partitioning=False)}
            ORDER BY ts_code
            """
        ).fetchall()


def _read_bootstrapped_columns(target_path: Path) -> tuple[str, ...]:
    with duckdb.connect(database=":memory:") as connection:
        rows = connection.execute(
            f"DESCRIBE SELECT * FROM {read_parquet(target_path, hive_partitioning=False)}"
        ).fetchall()
    return tuple(row[0] for row in rows)


class AdjFactorBootstrapSpecTests(unittest.TestCase):
    def test_adj_factor_bootstrap_spec_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "data_lake"
            old_lake_root = Path(temp_dir) / "old_lake"
            spec = adj_factor_bootstrap_spec(
                lake_root=lake_root,
                old_lake_root=old_lake_root,
            )

        self.assertEqual(spec.dataset_key, "raw_tushare_adj_factor")
        self.assertEqual(spec.layer, "raw")
        self.assertEqual(spec.partition_type, "trade_date")
        self.assertEqual(spec.empty_policy, "require_positive")
        self.assertEqual(spec.business_key, ("ts_code", "trade_date"))
        self.assertEqual(spec.source_fields, ADJ_FACTOR_RAW_REQUIRED_COLUMNS)
        self.assertEqual(spec.target_raw_fields, ADJ_FACTOR_RAW_REQUIRED_COLUMNS)
        self.assertEqual(
            spec.old_lake_path_pattern,
            str(
                old_lake_root
                / "raw_tushare"
                / "adj_factor"
                / "trade_date={partition_key}"
                / "part-000.parquet"
            ),
        )
        self.assertEqual(
            spec.target_path_pattern,
            str(
                lake_root
                / "raw"
                / "tushare"
                / "adj_factor"
                / "trade_date={partition_key}"
                / "part-000.parquet"
            ),
        )

    def test_bootstrap_partition_normalizes_date_trade_date_to_raw_contract(
        self,
    ) -> None:
        rows, columns, metadata = self._bootstrap_sample(
            trade_date_expression="DATE '2009-01-05'"
        )

        self.assertEqual(rows, [("000001.SZ", "20090105", 1.234)])
        self.assertEqual(columns, ADJ_FACTOR_RAW_REQUIRED_COLUMNS)
        self.assertEqual(metadata[DAGSTER_ROW_COUNT_METADATA_KEY], 1)
        self.assertEqual(
            metadata[OBSERVED_COLUMNS_METADATA_KEY],
            list(ADJ_FACTOR_RAW_REQUIRED_COLUMNS),
        )
        self.assertEqual(
            metadata["goldenshare/bootstrap_spec"],
            "raw_tushare_adj_factor",
        )
        self.assertEqual(metadata["goldenshare/partition_key"], PARTITION_KEY)
        self.assertEqual(metadata["goldenshare/empty_policy"], "require_positive")
        self.assertTrue(metadata[DAGSTER_URI_METADATA_KEY].endswith("part-000.parquet"))

    def test_bootstrap_partition_keeps_yyyymmdd_string_trade_date(self) -> None:
        rows, columns, _metadata = self._bootstrap_sample(
            trade_date_expression="'20090105'::VARCHAR"
        )

        self.assertEqual(rows, [("000001.SZ", "20090105", 1.234)])
        self.assertEqual(columns, ADJ_FACTOR_RAW_REQUIRED_COLUMNS)

    def test_bootstrap_partition_rejects_empty_required_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "data_lake"
            old_lake_root = Path(temp_dir) / "old_lake"
            _write_old_adj_factor_file(
                old_lake_root,
                trade_date_expression="DATE '2009-01-05'",
                include_rows=False,
            )
            spec = adj_factor_bootstrap_spec(
                lake_root=lake_root,
                old_lake_root=old_lake_root,
            )
            target_path = spec.target_path(PARTITION_KEY)

            with self.assertRaisesRegex(
                ValueError,
                "Bootstrap produced no rows for required dataset: raw_tushare_adj_factor",
            ):
                bootstrap_partition_to_raw(
                    spec,
                    PARTITION_KEY,
                    DuckDBResource(),
                )

            self.assertFalse(target_path.exists())
            self.assertFalse(target_path.with_name("part-000.parquet.tmp").exists())

    def _bootstrap_sample(
        self,
        *,
        trade_date_expression: str,
    ) -> tuple[list[tuple[str, str, float]], tuple[str, ...], dict[str, object]]:
        with tempfile.TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "data_lake"
            old_lake_root = Path(temp_dir) / "old_lake"
            _write_old_adj_factor_file(
                old_lake_root,
                trade_date_expression=trade_date_expression,
            )
            spec = adj_factor_bootstrap_spec(
                lake_root=lake_root,
                old_lake_root=old_lake_root,
            )

            metadata = bootstrap_partition_to_raw(
                spec,
                PARTITION_KEY,
                DuckDBResource(),
            )
            target_path = spec.target_path(PARTITION_KEY)
            rows = _read_bootstrapped_rows(target_path)
            columns = _read_bootstrapped_columns(target_path)

        return rows, columns, metadata


if __name__ == "__main__":
    unittest.main()
