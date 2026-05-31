import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from orchestrator.defs.assets import stk_mins
from orchestrator.defs.checks import stk_mins_checks
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.paths import (
    raw_stk_mins_path,
    silver_namechange_path,
    silver_stk_mins_path,
    silver_stock_basic_path,
    silver_stock_daily_path,
    silver_stock_identity_map_path,
    silver_stock_suspend_daily_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.sensors import readiness


PARTITION_KEY = "2014-06-03"


class _LakeRoot:
    def __init__(self, root: Path):
        self._root = root

    def root(self) -> Path:
        return self._root


class _CheckContext:
    def __init__(self, partition_key: str = PARTITION_KEY) -> None:
        self.partition_key = partition_key


def _check_names(check_definitions) -> tuple[str, ...]:
    names = []
    for check_definition in check_definitions:
        check_key = next(iter(check_definition.check_keys))
        names.append(check_key.name)
    return tuple(sorted(names))


def _write_rows(
    path: Path,
    *,
    column_types: dict[str, str],
    rows: list[dict[str, object]],
    order_by: str = "1",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = tuple(column_types)
    with DuckDBResource().connect() as connection:
        column_defs = ", ".join(
            f'"{column}" {column_types[column]}' for column in columns
        )
        connection.execute(f"CREATE TEMP TABLE rows_to_write ({column_defs})")
        if rows:
            placeholders = ", ".join("?" for _column in columns)
            values = [[row.get(column) for column in columns] for row in rows]
            connection.executemany(
                f"INSERT INTO rows_to_write VALUES ({placeholders})",
                values,
            )
        select_columns = ", ".join(
            f'CAST("{column}" AS {column_types[column]}) AS "{column}"'
            for column in columns
        )
        connection.execute(
            copy_query_to_parquet(
                f"""
                SELECT {select_columns}
                FROM rows_to_write
                ORDER BY {order_by}
                """,
                path,
            )
        )


def _read_rows(path: Path) -> list[dict[str, object]]:
    with DuckDBResource().connect() as connection:
        rows = connection.execute(
            f"""
            SELECT *
            FROM {read_parquet(path, hive_partitioning=False)}
            ORDER BY ts_code, trade_time
            """
        ).fetchall()
        columns = [
            row[0]
            for row in connection.execute(
                f"DESCRIBE SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
            ).fetchall()
        ]
    return [dict(zip(columns, row, strict=True)) for row in rows]


def _raw_row(
    ts_code: str,
    trade_time: str,
    *,
    freq: int = 1,
    open_: float = 10.0,
    high: float = 10.0,
    low: float = 10.0,
    close: float = 10.0,
    vol: int = 100,
    amount: float = 1000.0,
    exchange: str = "XSHG",
    vwap: float = 10.0,
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "freq": freq,
        "trade_time": trade_time,
        "open": open_,
        "close": close,
        "high": high,
        "low": low,
        "vol": vol,
        "amount": amount,
        "exchange": exchange,
        "vwap": vwap,
    }


def _write_raw(
    lake_root: Path,
    freq: int,
    partition_key: str,
    rows: list[dict[str, object]],
) -> Path:
    path = raw_stk_mins_path(lake_root, freq, partition_key)
    _write_rows(
        path,
        column_types=stk_mins.STK_MINS_RAW_COLUMN_TYPES,
        rows=rows,
        order_by="ts_code, trade_time",
    )
    return path


def _write_identity_map(lake_root: Path, rows: list[dict[str, object]]) -> Path:
    path = silver_stock_identity_map_path(lake_root)
    _write_rows(
        path,
        column_types={
            "latest_ts_code": "VARCHAR",
            "source_ts_code": "VARCHAR",
            "valid_from": "DATE",
            "valid_to": "DATE",
            "effective_list_date": "DATE",
            "effective_delist_date": "DATE",
            "identity_source": "VARCHAR",
            "confidence": "VARCHAR",
            "reason": "VARCHAR",
            "created_at": "TIMESTAMP WITH TIME ZONE",
        },
        rows=rows,
        order_by="source_ts_code",
    )
    return path


def _identity_row(
    ts_code: str,
    *,
    source_ts_code: str | None = None,
    valid_from: str = "2000-01-01",
    valid_to: str | None = None,
) -> dict[str, object]:
    return {
        "latest_ts_code": ts_code,
        "source_ts_code": source_ts_code or ts_code,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "effective_list_date": "2000-01-01",
        "effective_delist_date": None,
        "identity_source": "current_code",
        "confidence": "high",
        "reason": "test",
        "created_at": "2026-05-31 00:00:00+08",
    }


def _write_stock_daily(
    lake_root: Path,
    partition_key: str,
    codes: tuple[str, ...],
) -> Path:
    path = silver_stock_daily_path(lake_root, partition_key)
    rows = [{"ts_code": code, "trade_date": partition_key} for code in codes]
    _write_rows(
        path,
        column_types={"ts_code": "VARCHAR", "trade_date": "DATE"},
        rows=rows,
        order_by="ts_code",
    )
    return path


def _write_suspend(
    lake_root: Path,
    partition_key: str,
    rows: list[dict[str, object]] | None = None,
) -> Path:
    path = silver_stock_suspend_daily_path(lake_root, partition_key)
    _write_rows(
        path,
        column_types={
            "ts_code": "VARCHAR",
            "trade_date": "DATE",
            "suspend_type": "VARCHAR",
            "suspend_timing": "VARCHAR",
        },
        rows=rows or [],
        order_by="ts_code",
    )
    return path


def _write_stock_basic(lake_root: Path, codes: tuple[str, ...]) -> Path:
    path = silver_stock_basic_path(lake_root)
    rows = [{"ts_code": code, "name": f"name-{code}"} for code in codes]
    _write_rows(
        path,
        column_types={"ts_code": "VARCHAR", "name": "VARCHAR"},
        rows=rows,
        order_by="ts_code",
    )
    return path


def _write_namechange(
    lake_root: Path,
    rows: list[dict[str, object]] | None = None,
) -> Path:
    path = silver_namechange_path(lake_root)
    _write_rows(
        path,
        column_types={
            "ts_code": "VARCHAR",
            "name": "VARCHAR",
            "start_date": "DATE",
            "end_date": "DATE",
        },
        rows=rows or [],
        order_by="ts_code, start_date",
    )
    return path


def _write_common_inputs(
    lake_root: Path,
    partition_key: str,
    *,
    identity_rows: list[dict[str, object]],
    daily_codes: tuple[str, ...],
    basic_codes: tuple[str, ...] | None = None,
    suspend_rows: list[dict[str, object]] | None = None,
    namechange_rows: list[dict[str, object]] | None = None,
) -> None:
    _write_identity_map(lake_root, identity_rows)
    _write_stock_daily(lake_root, partition_key, daily_codes)
    _write_suspend(lake_root, partition_key, rows=suspend_rows)
    _write_stock_basic(lake_root, basic_codes or daily_codes)
    _write_namechange(lake_root, namechange_rows)


def _write_silver_for_check(
    lake_root: Path,
    partition_key: str,
    rows: list[dict[str, object]],
    *,
    freq: int = 1,
) -> Path:
    path = silver_stk_mins_path(lake_root, freq, partition_key)
    _write_rows(
        path,
        column_types=stk_mins.STK_MINS_SILVER_COLUMN_TYPES,
        rows=rows,
        order_by="ts_code, trade_time",
    )
    return path


def _silver_row(
    ts_code: str = "600000.SH",
    *,
    partition_key: str = PARTITION_KEY,
    trade_time: str | None = None,
    freq: int = 1,
    open_: float = 10.0,
    high: float = 10.0,
    low: float = 10.0,
    close: float = 10.0,
    vol: float = 100.0,
    amount: float = 1000.0,
    exchange: str = "SSE",
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "freq": freq,
        "trade_date": partition_key,
        "trade_time": trade_time or f"{partition_key} 09:30:00",
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "vol": vol,
        "amount": amount,
        "exchange": exchange,
    }


class StkMinsSilverM5BContractTests(unittest.TestCase):
    def test_one_minute_standardization_applies_seed_mapping_and_suspension_rules(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            _write_raw(
                lake_root,
                1,
                PARTITION_KEY,
                [
                    _raw_row(
                        "600463.SH",
                        "2014-06-03 09:32:00",
                        open_=1.0,
                        high=1.0,
                        low=0.0,
                        close=1.0,
                    ),
                    _raw_row(
                        "600000.SH",
                        "2014-06-03 09:30:00",
                        vol=50,
                        amount=999.0,
                    ),
                    _raw_row(
                        "000001.SZ",
                        "2014-06-03 09:30:00",
                        open_=0.0,
                        high=0.0,
                        low=0.0,
                        close=0.0,
                        vol=0,
                        amount=0.0,
                        exchange="XSHE",
                        vwap=0.0,
                    ),
                ],
            )
            _write_common_inputs(
                lake_root,
                PARTITION_KEY,
                identity_rows=[
                    _identity_row("600463.SH"),
                    _identity_row("600000.SH"),
                    _identity_row("000001.SZ"),
                ],
                daily_codes=("600463.SH", "600000.SH"),
                suspend_rows=[
                    {
                        "ts_code": "000001.SZ",
                        "trade_date": PARTITION_KEY,
                        "suspend_type": "S",
                        "suspend_timing": None,
                    }
                ],
            )

            result = stk_mins.write_silver_stk_mins_partition(
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                freq=1,
                partition_key=PARTITION_KEY,
            )

            self.assertEqual(result.row_count, 2)
            self.assertEqual(result.full_day_suspend_deleted_row_count, 1)
            self.assertEqual(result.price_correction_row_count, 1)
            self.assertEqual(result.vol_amount_normalized_row_count, 1)
            self.assertEqual(result.observed_columns, stk_mins.STK_MINS_SILVER_COLUMNS)

            rows = _read_rows(result.silver_file_path)
            corrected = next(row for row in rows if row["ts_code"] == "600463.SH")
            self.assertEqual(corrected["open"], 7.48)
            self.assertEqual(corrected["high"], 7.5)
            self.assertEqual(corrected["low"], 7.48)
            self.assertEqual(corrected["close"], 7.5)
            self.assertEqual(corrected["exchange"], "SSE")
            normalized = next(row for row in rows if row["ts_code"] == "600000.SH")
            self.assertEqual(normalized["vol"], 0.0)
            self.assertEqual(normalized["amount"], 0.0)
            self.assertNotIn("source_ts_code", rows[0])
            self.assertNotIn("vwap", rows[0])

    def test_non_correction_date_does_not_load_price_correction_catalog(self) -> None:
        partition_key = "2026-05-29"
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            _write_raw(
                lake_root,
                1,
                partition_key,
                [_raw_row("600000.SH", "2026-05-29 09:30:00")],
            )
            _write_common_inputs(
                lake_root,
                partition_key,
                identity_rows=[_identity_row("600000.SH")],
                daily_codes=("600000.SH",),
            )

            with patch(
                "orchestrator.defs.assets.stk_mins.load_stk_mins_price_correction_catalog",
                side_effect=AssertionError("catalog should not be loaded"),
            ):
                result = stk_mins.write_silver_stk_mins_partition(
                    lake_root=lake_root,
                    duckdb=DuckDBResource(),
                    freq=1,
                    partition_key=partition_key,
                )

            self.assertEqual(result.row_count, 1)

    def test_coarse_price_anomaly_is_recomputed_from_one_minute_window(self) -> None:
        partition_key = "2026-05-29"
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            _write_raw(
                lake_root,
                1,
                partition_key,
                [
                    _raw_row("600000.SH", "2026-05-29 09:31:00", open_=1, high=2, low=1, close=2, vol=100, amount=100),
                    _raw_row("600000.SH", "2026-05-29 09:32:00", open_=2, high=3, low=2, close=3, vol=200, amount=400),
                    _raw_row("600000.SH", "2026-05-29 09:33:00", open_=3, high=5, low=3, close=4, vol=300, amount=900),
                    _raw_row("600000.SH", "2026-05-29 09:34:00", open_=4, high=6, low=4, close=5, vol=400, amount=1600),
                    _raw_row("600000.SH", "2026-05-29 09:35:00", open_=5, high=7, low=5, close=6, vol=500, amount=2500),
                ],
            )
            _write_raw(
                lake_root,
                5,
                partition_key,
                [
                    _raw_row(
                        "600000.SH",
                        "2026-05-29 09:35:00",
                        freq=5,
                        open_=0.0,
                        high=0.0,
                        low=0.0,
                        close=0.0,
                        vol=0,
                        amount=0.0,
                        vwap=0.0,
                    ),
                    _raw_row(
                        "000001.SZ",
                        "2026-05-29 09:35:00",
                        freq=5,
                        open_=9.0,
                        high=9.0,
                        low=9.0,
                        close=9.0,
                        vol=100,
                        amount=900.0,
                        exchange="XSHE",
                    ),
                ],
            )
            _write_common_inputs(
                lake_root,
                partition_key,
                identity_rows=[_identity_row("600000.SH"), _identity_row("000001.SZ")],
                daily_codes=("600000.SH", "000001.SZ"),
            )

            result = stk_mins.write_silver_stk_mins_partition(
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                freq=5,
                partition_key=partition_key,
            )

            self.assertEqual(result.recomputed_row_count, 1)
            rows = _read_rows(result.silver_file_path)
            recomputed = next(row for row in rows if row["ts_code"] == "600000.SH")
            self.assertEqual(recomputed["open"], 1.0)
            self.assertEqual(recomputed["high"], 7.0)
            self.assertEqual(recomputed["low"], 1.0)
            self.assertEqual(recomputed["close"], 6.0)
            self.assertEqual(recomputed["vol"], 1500.0)
            self.assertEqual(recomputed["amount"], 5500.0)
            untouched = next(row for row in rows if row["ts_code"] == "000001.SZ")
            self.assertEqual(untouched["open"], 9.0)
            self.assertEqual(untouched["exchange"], "SZSE")

    def test_coarse_price_anomaly_without_one_minute_basis_fails(self) -> None:
        partition_key = "2026-05-29"
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            _write_raw(
                lake_root,
                1,
                partition_key,
                [_raw_row("000001.SZ", "2026-05-29 09:35:00", exchange="XSHE")],
            )
            _write_raw(
                lake_root,
                5,
                partition_key,
                [
                    _raw_row(
                        "600000.SH",
                        "2026-05-29 09:35:00",
                        freq=5,
                        open_=0.0,
                        high=0.0,
                        low=0.0,
                        close=0.0,
                        vol=0,
                        amount=0.0,
                        vwap=0.0,
                    )
                ],
            )
            _write_common_inputs(
                lake_root,
                partition_key,
                identity_rows=[_identity_row("600000.SH"), _identity_row("000001.SZ")],
                daily_codes=("600000.SH", "000001.SZ"),
            )

            with self.assertRaisesRegex(RuntimeError, "could not be recomputed"):
                stk_mins.write_silver_stk_mins_partition(
                    lake_root=lake_root,
                    duckdb=DuckDBResource(),
                    freq=5,
                    partition_key=partition_key,
                )

    def test_identity_mapping_duplicate_same_value_is_deduped_but_conflict_fails(
        self,
    ) -> None:
        partition_key = "2026-05-29"
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            same_time = "2026-05-29 09:30:00"
            _write_raw(
                lake_root,
                1,
                partition_key,
                [
                    _raw_row("000022.SZ", same_time, exchange="XSHE"),
                    _raw_row("001872.SZ", same_time, exchange="XSHE"),
                ],
            )
            _write_common_inputs(
                lake_root,
                partition_key,
                identity_rows=[
                    _identity_row("001872.SZ", source_ts_code="000022.SZ"),
                    _identity_row("001872.SZ"),
                ],
                daily_codes=("001872.SZ",),
            )

            result = stk_mins.write_silver_stk_mins_partition(
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                freq=1,
                partition_key=partition_key,
            )
            self.assertEqual(result.duplicate_removed_count, 1)
            self.assertEqual(result.row_count, 1)

        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            _write_raw(
                lake_root,
                1,
                partition_key,
                [
                    _raw_row("000022.SZ", same_time, open_=10.0, exchange="XSHE"),
                    _raw_row(
                        "001872.SZ",
                        same_time,
                        open_=11.0,
                        high=11.0,
                        low=10.0,
                        close=10.0,
                        exchange="XSHE",
                    ),
                ],
            )
            _write_common_inputs(
                lake_root,
                partition_key,
                identity_rows=[
                    _identity_row("001872.SZ", source_ts_code="000022.SZ"),
                    _identity_row("001872.SZ"),
                ],
                daily_codes=("001872.SZ",),
            )

            with self.assertRaisesRegex(RuntimeError, "conflicting duplicate keys"):
                stk_mins.write_silver_stk_mins_partition(
                    lake_root=lake_root,
                    duckdb=DuckDBResource(),
                    freq=1,
                    partition_key=partition_key,
                )

    def test_identity_mapping_valid_window_is_required(self) -> None:
        partition_key = "2026-05-29"
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            _write_raw(
                lake_root,
                1,
                partition_key,
                [_raw_row("600000.SH", "2026-05-29 09:30:00")],
            )
            _write_common_inputs(
                lake_root,
                partition_key,
                identity_rows=[_identity_row("600000.SH", valid_from="2026-05-30")],
                daily_codes=("600000.SH",),
            )

            with self.assertRaisesRegex(RuntimeError, "identity mapping missing"):
                stk_mins.write_silver_stk_mins_partition(
                    lake_root=lake_root,
                    duckdb=DuckDBResource(),
                    freq=1,
                    partition_key=partition_key,
                )

    def test_target_exists_requires_explicit_overwrite(self) -> None:
        partition_key = "2026-05-29"
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            _write_raw(
                lake_root,
                1,
                partition_key,
                [_raw_row("600000.SH", "2026-05-29 09:30:00")],
            )
            _write_common_inputs(
                lake_root,
                partition_key,
                identity_rows=[_identity_row("600000.SH")],
                daily_codes=("600000.SH",),
            )
            stk_mins.write_silver_stk_mins_partition(
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                freq=1,
                partition_key=partition_key,
            )

            with self.assertRaisesRegex(FileExistsError, "already exists"):
                stk_mins.write_silver_stk_mins_partition(
                    lake_root=lake_root,
                    duckdb=DuckDBResource(),
                    freq=1,
                    partition_key=partition_key,
                )

            result = stk_mins.write_silver_stk_mins_partition(
                lake_root=lake_root,
                duckdb=DuckDBResource(),
                freq=1,
                partition_key=partition_key,
                overwrite=True,
            )
            self.assertEqual(result.row_count, 1)

    def test_silver_check_helpers_pass_for_valid_partition(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory)
            _write_silver_for_check(lake_root, PARTITION_KEY, [_silver_row()])
            _write_common_inputs(
                lake_root,
                PARTITION_KEY,
                identity_rows=[_identity_row("600000.SH")],
                daily_codes=("600000.SH",),
            )
            context = _CheckContext()
            resources = {
                "context": context,
                "lake_root": _LakeRoot(lake_root),
                "duckdb": DuckDBResource(),
                "freq": 1,
            }

            for check_helper in (
                stk_mins_checks._silver_file_exists_and_row_count_positive,
                stk_mins_checks._silver_schema_matches_contract,
                stk_mins_checks._silver_freq_and_partition_match,
                stk_mins_checks._silver_unique_ts_code_trade_time,
                stk_mins_checks._silver_price_sanity,
                stk_mins_checks._silver_volume_amount_sanity,
                stk_mins_checks._silver_exchange_matches_suffix,
                stk_mins_checks._silver_codes_exist_in_stock_daily,
                stk_mins_checks._silver_no_full_day_suspend_structural_rows,
                stk_mins_checks._silver_name_timeline_covered,
            ):
                with self.subTest(check_helper=check_helper.__name__):
                    self.assertTrue(check_helper(**resources).passed)

    def test_silver_check_helpers_fail_for_core_bad_cases(self) -> None:
        bad_cases = (
            (
                "price",
                [_silver_row(open_=0.0)],
                stk_mins_checks._silver_price_sanity,
            ),
            (
                "volume",
                [_silver_row(vol=50.0)],
                stk_mins_checks._silver_volume_amount_sanity,
            ),
            (
                "exchange",
                [_silver_row(exchange="XSHG")],
                stk_mins_checks._silver_exchange_matches_suffix,
            ),
            (
                "daily",
                [_silver_row(ts_code="600001.SH")],
                stk_mins_checks._silver_codes_exist_in_stock_daily,
            ),
            (
                "suspend",
                [_silver_row()],
                stk_mins_checks._silver_no_full_day_suspend_structural_rows,
            ),
            (
                "name",
                [_silver_row(ts_code="600002.SH")],
                stk_mins_checks._silver_name_timeline_covered,
            ),
        )
        for case_name, rows, check_helper in bad_cases:
            with self.subTest(case_name=case_name):
                with TemporaryDirectory() as directory:
                    lake_root = Path(directory)
                    _write_silver_for_check(lake_root, PARTITION_KEY, rows)
                    suspend_rows = []
                    daily_codes = ("600000.SH",)
                    basic_codes = ("600000.SH",)
                    if case_name == "suspend":
                        suspend_rows = [
                            {
                                "ts_code": "600000.SH",
                                "trade_date": PARTITION_KEY,
                                "suspend_type": "S",
                                "suspend_timing": None,
                            }
                        ]
                    _write_common_inputs(
                        lake_root,
                        PARTITION_KEY,
                        identity_rows=[_identity_row("600000.SH")],
                        daily_codes=daily_codes,
                        basic_codes=basic_codes,
                        suspend_rows=suspend_rows,
                    )
                    result = check_helper(
                        context=_CheckContext(),
                        lake_root=_LakeRoot(lake_root),
                        duckdb=DuckDBResource(),
                        freq=1,
                    )
                    self.assertFalse(result.passed)

    def test_readiness_check_names_match_silver_stk_mins_check_definitions(self) -> None:
        first_asset_check_definitions = stk_mins_checks.SILVER_STK_MINS_CHECK_DEFINITIONS[
            : len(stk_mins_checks.SILVER_STK_MINS_CHECK_NAMES)
        ]

        self.assertEqual(
            tuple(sorted(readiness.SILVER_STK_MINS_CHECKS)),
            _check_names(first_asset_check_definitions),
        )


if __name__ == "__main__":
    unittest.main()
