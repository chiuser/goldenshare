import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from orchestrator.defs.assets.stk_nineturn import raw_tushare_stk_nineturn
from orchestrator.defs.jobs.stk_nineturn_update import raw_stk_nineturn_update_job
from orchestrator.defs.paths import raw_stk_nineturn_path
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResult,
)
from orchestrator.defs.stk_nineturn_contract import RAW_STK_NINETURN_COLUMNS


PARTITION_KEY = "2026-07-09"


class _AssetContext:
    partition_key = PARTITION_KEY


class _FakeTushare:
    def __init__(self, pages: dict[int, list[dict[str, object]]]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, dict[str, object], tuple[str, ...]]] = []

    def call(self, api_name, params, fields):
        normalized_fields = tuple(fields)
        request_params = dict(params)
        self.calls.append((api_name, request_params, normalized_fields))
        return TushareResult(
            rows=self.pages.get(int(request_params["offset"]), []),
            columns=normalized_fields,
            metadata={},
        )


def _prepare_lake_root(root: Path) -> None:
    for layer in ("raw", "silver", "gold"):
        (root / layer).mkdir(parents=True, exist_ok=True)


def _raw_row(index: int = 0) -> dict[str, object]:
    return {
        "ts_code": f"{index:06d}.SZ",
        "trade_date": "2026-07-09 00:00:00",
        "freq": "daily",
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "vol": 100.0,
        "amount": 1000.0,
        "up_count": 0.0,
        "down_count": 3.0,
        "nine_up_turn": None,
        "nine_down_turn": None,
    }


class StkNineturnAssetTests(unittest.TestCase):
    def test_raw_asset_uses_explicit_daily_contract_and_writes_date(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _prepare_lake_root(root)
            tushare = _FakeTushare({0: [_raw_row()]})

            result = raw_tushare_stk_nineturn.op.compute_fn.decorated_fn(
                _AssetContext(),
                LakeRootResource(root_path=str(root)),
                DuckDBResource(),
                tushare,
            )

            self.assertEqual(len(tushare.calls), 1)
            api_name, params, fields = tushare.calls[0]
            self.assertEqual(api_name, "stk_nineturn")
            self.assertEqual(
                params,
                {
                    "trade_date": "2026-07-09 00:00:00",
                    "freq": "daily",
                    "limit": 6000,
                    "offset": 0,
                },
            )
            self.assertEqual(fields, RAW_STK_NINETURN_COLUMNS)

            target_path = raw_stk_nineturn_path(root, PARTITION_KEY)
            self.assertTrue(target_path.exists())
            with DuckDBResource().connect() as connection:
                observed = connection.execute(
                    f"""
                    SELECT
                      CAST(trade_date AS VARCHAR),
                      typeof(trade_date),
                      ts_code,
                      freq
                    FROM read_parquet('{target_path.as_posix()}', hive_partitioning=false)
                    """
                ).fetchone()
            self.assertEqual(observed, (PARTITION_KEY, "DATE", "000000.SZ", "daily"))
            self.assertEqual(result.metadata["dagster/row_count"], 1)

    def test_raw_asset_paginates_at_project_page_size(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            _prepare_lake_root(Path(temporary_dir))
            first_page = [_raw_row(index) for index in range(6000)]
            second_page = [_raw_row(6000)]
            tushare = _FakeTushare({0: first_page, 6000: second_page})

            raw_tushare_stk_nineturn.op.compute_fn.decorated_fn(
                _AssetContext(),
                LakeRootResource(root_path=temporary_dir),
                DuckDBResource(),
                tushare,
            )

            self.assertEqual([call[1]["offset"] for call in tushare.calls], [0, 6000])
            self.assertEqual([call[1]["limit"] for call in tushare.calls], [6000, 6000])
            with DuckDBResource().connect() as connection:
                row_count = connection.execute(
                    f"""
                    SELECT count(*)
                    FROM read_parquet(
                      '{raw_stk_nineturn_path(Path(temporary_dir), PARTITION_KEY).as_posix()}',
                      hive_partitioning=false
                    )
                    """
                ).fetchone()[0]
            self.assertEqual(row_count, 6001)

    def test_raw_asset_rejects_empty_source_without_writing_file(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _prepare_lake_root(root)
            with self.assertRaisesRegex(RuntimeError, "returned 0 rows"):
                raw_tushare_stk_nineturn.op.compute_fn.decorated_fn(
                    _AssetContext(),
                    LakeRootResource(root_path=str(root)),
                    DuckDBResource(),
                    _FakeTushare({0: []}),
                )

            self.assertFalse(raw_stk_nineturn_path(root, PARTITION_KEY).exists())

    def test_raw_job_selects_only_raw_asset_and_its_checks(self) -> None:
        selection = repr(raw_stk_nineturn_update_job.selection)

        self.assertIn("raw_tushare_stk_nineturn", selection)
        self.assertNotIn("silver_stock_nineturn_daily", selection)


if __name__ == "__main__":
    unittest.main()
