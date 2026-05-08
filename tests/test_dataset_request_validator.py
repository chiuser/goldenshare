from __future__ import annotations

from datetime import date

import pytest

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.errors import IngestionValidationError
from src.foundation.ingestion.execution_plan import DatasetActionRequest, DatasetTimeInput
from src.foundation.ingestion.validator import DatasetRequestValidator


def _validate(*, dataset_key: str, run_profile: str, time_input: DatasetTimeInput, filters: dict | None = None):
    definition = get_dataset_definition(dataset_key)
    return DatasetRequestValidator().validate(
        request=DatasetActionRequest(
            dataset_key=dataset_key,
            action="maintain",
            time_input=time_input,
            filters=filters or {},
        ),
        definition=definition,
        run_profile=run_profile,
    )


def test_snapshot_refresh_rejects_time_anchor() -> None:
    with pytest.raises(IngestionValidationError) as exc_info:
        _validate(
            dataset_key="stock_basic",
            run_profile="snapshot_refresh",
            time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 24)),
        )

    assert exc_info.value.structured_error.error_code == "time_anchor_not_allowed"


def test_snapshot_refresh_rejects_dataset_without_declared_none_mode() -> None:
    with pytest.raises(IngestionValidationError) as exc_info:
        _validate(
            dataset_key="daily",
            run_profile="snapshot_refresh",
            time_input=DatasetTimeInput(mode="none"),
        )

    assert exc_info.value.structured_error.error_code == "run_profile_unsupported"


def test_validator_rejects_forbidden_sentinel_input() -> None:
    with pytest.raises(IngestionValidationError) as exc_info:
        _validate(
            dataset_key="dc_hot",
            run_profile="point_incremental",
            time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 24)),
            filters={"market": "__ALL__"},
        )

    assert exc_info.value.structured_error.error_code == "invalid_enum"


@pytest.mark.parametrize(
    ("dataset_key", "market"),
    [
        ("dc_hot", "美股市场"),
        ("ths_hot", "美股"),
    ],
)
def test_validator_rejects_us_hot_market_when_env_switch_is_disabled(dataset_key: str, market: str) -> None:
    with pytest.raises(IngestionValidationError) as exc_info:
        _validate(
            dataset_key=dataset_key,
            run_profile="point_incremental",
            time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 24)),
            filters={"market": market},
        )

    assert exc_info.value.structured_error.error_code == "invalid_enum"


def test_validator_accepts_dc_member_multi_select_filter() -> None:
    validated = _validate(
        dataset_key="dc_member",
        run_profile="point_incremental",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 24)),
        filters={"idx_type": ["概念板块", "行业板块"]},
    )

    assert validated.trade_date == date(2026, 4, 24)
    assert validated.params["idx_type"] == ["概念板块", "行业板块"]


def test_validator_accepts_normalized_month_key_for_month_window_dataset() -> None:
    validated = _validate(
        dataset_key="broker_recommend",
        run_profile="point_incremental",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 30)),
        filters={"month": "202604"},
    )

    assert validated.params["month"] == "202604"


def test_validator_accepts_namechange_snapshot_without_time_anchor() -> None:
    validated = _validate(
        dataset_key="namechange",
        run_profile="snapshot_refresh",
        time_input=DatasetTimeInput(mode="none"),
        filters={"ts_code": "000001.SZ"},
    )

    assert validated.trade_date is None
    assert validated.start_date is None
    assert validated.end_date is None
    assert validated.params["ts_code"] == "000001.SZ"


def test_validator_rejects_namechange_point_mode() -> None:
    with pytest.raises(IngestionValidationError) as exc_info:
        _validate(
            dataset_key="namechange",
            run_profile="point_incremental",
            time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 24)),
        )

    assert exc_info.value.structured_error.error_code == "run_profile_unsupported"


def test_validator_accepts_st_snapshot_without_time_anchor() -> None:
    validated = _validate(
        dataset_key="st",
        run_profile="snapshot_refresh",
        time_input=DatasetTimeInput(mode="none"),
        filters={"ts_code": "000001.SZ"},
    )

    assert validated.trade_date is None
    assert validated.start_date is None
    assert validated.end_date is None
    assert validated.params["ts_code"] == "000001.SZ"


def test_validator_rejects_st_point_mode() -> None:
    with pytest.raises(IngestionValidationError) as exc_info:
        _validate(
            dataset_key="st",
            run_profile="point_incremental",
            time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 24)),
        )

    assert exc_info.value.structured_error.error_code == "run_profile_unsupported"
