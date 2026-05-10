from __future__ import annotations

from datetime import datetime

import pytest

from lake_console.backend.app.cli.main import main
from lake_console.backend.app.services.indicators import IndicatorByDateWriter, StkMinsIndicatorResearchService, calculate_macd
from lake_console.backend.app.services.parquet_writer import read_parquet_rows
from lake_console.backend.app.services.stk_mins_research_service import stable_bucket


def test_indicator_research_rebuild_month_from_by_date(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    _write_indicator_by_date(tmp_path)

    summary = StkMinsIndicatorResearchService(lake_root=tmp_path, bucket_count=4, progress=lambda _: None).rebuild_month(
        indicator="macd",
        params_key="12_26_9",
        freq=30,
        trade_month="2026-04",
    )

    bucket_600000 = stable_bucket(ts_code="600000.SH", bucket_count=4)
    bucket_000001 = stable_bucket(ts_code="000001.SZ", bucket_count=4)
    rows_600000 = read_parquet_rows(_research_file(tmp_path, bucket=bucket_600000))
    rows_000001 = read_parquet_rows(_research_file(tmp_path, bucket=bucket_000001))
    all_rows = rows_600000 if bucket_600000 == bucket_000001 else rows_600000 + rows_000001
    assert summary["operation"] == "research_stk_mins_indicator"
    assert summary["source_rows"] == 4
    assert summary["written_rows"] == 4
    assert summary["bucket_count"] == 4
    assert sorted(row["ts_code"] for row in all_rows) == ["000001.SZ", "000001.SZ", "600000.SH", "600000.SH"]
    assert all(row["params_key"] == "12_26_9" for row in all_rows)


def test_indicator_research_rebuild_month_requires_by_date_source(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="缺少可重排指标 by_date 文件"):
        StkMinsIndicatorResearchService(lake_root=tmp_path, bucket_count=4, progress=lambda _: None).rebuild_month(
            indicator="macd",
            params_key="12_26_9",
            freq=30,
            trade_month="2026-04",
        )


def test_rebuild_stk_mins_indicator_research_cli(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    _write_indicator_by_date(tmp_path)

    exit_code = main(
        [
            "rebuild-stk-mins-indicator-research",
            "--lake-root",
            str(tmp_path),
            "--indicator",
            "macd",
            "--freq",
            "30",
            "--trade-month",
            "2026-04",
            "--bucket-count",
            "4",
        ]
    )

    assert exit_code == 0
    assert (
        tmp_path
        / "research"
        / "stk_mins_indicators_by_symbol_month"
        / "indicator=macd"
        / "params_key=12_26_9"
        / "freq=30"
        / "trade_month=2026-04"
    ).exists()


def test_rebuild_stk_mins_indicator_research_range_cli(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    _write_indicator_by_date(tmp_path)

    exit_code = main(
        [
            "rebuild-stk-mins-indicator-research-range",
            "--lake-root",
            str(tmp_path),
            "--indicator",
            "macd",
            "--freq",
            "30",
            "--start-month",
            "2026-04",
            "--end-month",
            "2026-04",
            "--bucket-count",
            "4",
        ]
    )

    assert exit_code == 0
    assert (
        tmp_path
        / "research"
        / "stk_mins_indicators_by_symbol_month"
        / "indicator=macd"
        / "params_key=12_26_9"
        / "freq=30"
        / "trade_month=2026-04"
    ).exists()


def _write_indicator_by_date(tmp_path) -> None:
    rows_600000 = calculate_macd(
        [
            _bar("600000.SH", "2026-04-24 10:00:00", 10.0),
            _bar("600000.SH", "2026-04-27 10:00:00", 10.5),
        ]
    ).rows
    rows_000001 = calculate_macd(
        [
            _bar("000001.SZ", "2026-04-24 10:00:00", 8.0),
            _bar("000001.SZ", "2026-04-27 10:00:00", 8.2),
        ]
    ).rows
    IndicatorByDateWriter(lake_root=tmp_path).write_rows(
        rows_600000 + rows_000001,
        indicator="macd",
        params_key="12_26_9",
        freq=30,
        run_id="test-indicator-research-source",
    )


def _bar(ts_code: str, trade_time: str, close: float) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "freq": 30,
        "trade_time": datetime.fromisoformat(trade_time),
        "close": close,
    }


def _research_file(tmp_path, *, bucket: int):
    return (
        tmp_path
        / "research"
        / "stk_mins_indicators_by_symbol_month"
        / "indicator=macd"
        / "params_key=12_26_9"
        / "freq=30"
        / "trade_month=2026-04"
        / f"bucket={bucket}"
        / "part-000.parquet"
    )
