from __future__ import annotations

from pathlib import Path

import pytest

import orchestrator.defs.run_contracts.major_index_mins_technical as technical_contract
from orchestrator.defs.catalog import PartitionModel, get_lake_asset_catalog_entry
from orchestrator.defs.paths import (
    gold_major_index_mins_technical_path,
    gold_major_index_mins_technical_staging_path,
    gold_major_index_mins_technical_state_path,
    gold_major_index_mins_technical_state_staging_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_MAJOR_INDEX_MINS_TECHNICAL_SCHEMA,
    GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import DataDomain
from orchestrator.defs.run_contracts.major_index_mins_technical import (
    INDICATOR_VERSION,
    MA_PERIODS,
    MAJOR_INDEX_MINS_TECHNICAL_FREQS,
    PARAMS_KEY,
    MajorIndexMinsTechnicalContractError,
    expected_major_index_mins_technical_codes,
    major_index_mins_technical_asset_key,
    major_index_mins_technical_checks,
    major_index_mins_technical_state_asset_key,
    major_index_mins_technical_state_checks,
    normalize_major_index_mins_technical_freq,
)


def test_contract_freezes_frequencies_parameters_and_schemas() -> None:
    assert MAJOR_INDEX_MINS_TECHNICAL_FREQS == (1, 5, 15, 30, 60, 90, 120)
    assert MA_PERIODS == (5, 10, 20, 30, 60, 90, 250)
    assert PARAMS_KEY == (
        "ma_5_10_20_30_60_90_250__boll_20_2__macd_12_26_9__kdj_9_3_3"
    )
    assert INDICATOR_VERSION == 1
    assert len(GOLD_MAJOR_INDEX_MINS_TECHNICAL_SCHEMA) == 23
    assert len(GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_SCHEMA) == 11
    assert tuple(column.name for column in GOLD_MAJOR_INDEX_MINS_TECHNICAL_SCHEMA[:4]) == (
        "ts_code",
        "freq",
        "trade_date",
        "trade_time",
    )


def test_minute_technical_scope_reuses_silver_scope_not_daily_seed() -> None:
    current_codes = expected_major_index_mins_technical_codes("2026-08-04")
    historical_codes = expected_major_index_mins_technical_codes("2009-01-05")

    assert len(current_codes) == 10
    assert "000680.SH" in current_codes
    assert "899050.BJ" not in current_codes
    assert 0 < len(historical_codes) < len(current_codes)
    assert "899050.BJ" not in historical_codes


def test_minute_technical_scope_delegates_to_silver_contract(monkeypatch) -> None:
    expected_codes = ("TEST001.SH", "TEST002.SZ")
    observed_dates: list[str] = []

    def fake_effective_silver_codes_for_date(trade_date: str) -> tuple[str, ...]:
        observed_dates.append(trade_date)
        return expected_codes

    monkeypatch.setattr(
        technical_contract,
        "effective_silver_codes_for_date",
        fake_effective_silver_codes_for_date,
    )

    assert technical_contract.expected_major_index_mins_technical_codes(
        "2026-08-04"
    ) == expected_codes
    assert observed_dates == ["2026-08-04"]


@pytest.mark.parametrize("value", [0, 10, 240, "1min", "01", 1.0, True])
def test_frequency_normalizer_rejects_unsupported_or_ambiguous_values(
    value: object,
) -> None:
    with pytest.raises(MajorIndexMinsTechnicalContractError):
        normalize_major_index_mins_technical_freq(value)


def test_paths_and_catalog_cover_seven_technical_and_state_assets() -> None:
    root = Path("data_lake")

    for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS:
        technical_key = major_index_mins_technical_asset_key(freq)
        state_key = major_index_mins_technical_state_asset_key(freq)
        technical_entry = get_lake_asset_catalog_entry(technical_key)
        state_entry = get_lake_asset_catalog_entry(state_key)

        assert technical_entry.data_domain is DataDomain.DERIVED_METRIC
        assert technical_entry.partition_model is (
            PartitionModel.TRADE_DATE_PARTITION_GOLD_MAJOR_INDEX_MINS_TECHNICAL
        )
        assert technical_entry.blocking_check_names == (
            major_index_mins_technical_checks(freq)
        )
        assert state_entry.partition_model is (
            PartitionModel.TRADE_DATE_PARTITION_GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE
        )
        assert state_entry.blocking_check_names == (
            major_index_mins_technical_state_checks(freq)
        )

        assert gold_major_index_mins_technical_path(
            root, freq, "2026-08-04"
        ).as_posix().endswith(
            f"major_index_mins_technical/freq={freq}/"
            "trade_date=2026-08-04/part-000.parquet"
        )
        assert gold_major_index_mins_technical_state_path(
            root, freq, "2026-08-04"
        ).as_posix().endswith(
            f"major_index_mins_technical_state/freq={freq}/"
            "trade_date=2026-08-04/part-000.parquet"
        )


def test_staging_paths_reject_path_traversal() -> None:
    root = Path("data_lake")

    assert "run_id=run-1" in gold_major_index_mins_technical_staging_path(
        root, "run-1", 90, "2026-08-04"
    ).as_posix()
    assert "run_id=run-1" in gold_major_index_mins_technical_state_staging_path(
        root, "run-1", 120, "2026-08-04"
    ).as_posix()
    with pytest.raises(ValueError, match="safe non-empty"):
        gold_major_index_mins_technical_staging_path(
            root, "../unsafe", 90, "2026-08-04"
        )
    with pytest.raises(ValueError, match="safe non-empty"):
        gold_major_index_mins_technical_state_staging_path(
            root, "", 120, "2026-08-04"
        )
