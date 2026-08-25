from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion import DatasetActionRequest, DatasetActionResolver, DatasetTimeInput
from src.foundation.ingestion import source_client as source_client_module
from src.foundation.ingestion.errors import (
    IngestionError,
    IngestionNormalizeError,
    IngestionSourceError,
    IngestionWriteError,
)
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot
from src.foundation.ingestion.normalizer import DatasetNormalizer, NormalizedBatch
from src.foundation.ingestion.request_builders import _etf_mins_params
from src.foundation.ingestion.row_transforms import _etf_mins_row_transform
from src.foundation.ingestion.source_client import DatasetSourceClient, SourceFetchResult
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.raw.raw_etf_minute_bar import RawEtfMinuteBar
from src.foundation.models.raw.raw_stk_mins import RawStkMins
from src.ops.action_catalog import action_is_schedulable, list_workflow_definitions
from src.ops.catalog.dataset_catalog_views import OPS_DATASET_DEFAULT_VIEW
from src.ops.services.schedule_automation_capability_resolver import (
    ScheduleAutomationCapabilityResolver,
)


class _PagedConnector:
    def __init__(self, page_sizes: dict[int, int], *, freq: str = "1min") -> None:
        self.page_sizes = page_sizes
        self.freq = freq
        self.calls: list[dict[str, object]] = []

    def call(self, api_name: str, params=None, fields=None):  # type: ignore[no-untyped-def]
        params_dict = dict(params or {})
        self.calls.append(
            {"api_name": api_name, "params": params_dict, "fields": tuple(fields or ())}
        )
        row_count = self.page_sizes.get(int(params_dict.get("offset") or 0), 0)
        return [
            {"ts_code": "510300.SH", "freq": self.freq, "trade_time": f"row-{index}"}
            for index in range(row_count)
        ]


class _RawDao:
    model = RawEtfMinuteBar

    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    def bulk_upsert(self, rows: list[dict], conflict_columns=None):  # type: ignore[no-untyped-def]
        self.calls.append(rows)
        return len(rows)


class _StkMinsRawDao(_RawDao):
    model = RawStkMins


def _definition():  # type: ignore[no-untyped-def]
    return get_dataset_definition("etf_mins")


def _resolver(mocker, pool_codes: list[str]) -> DatasetActionResolver:  # type: ignore[no-untyped-def]
    fake_dao = SimpleNamespace(
        etf_series_active=SimpleNamespace(
            list_active_codes=mocker.Mock(return_value=pool_codes)
        )
    )
    mocker.patch("src.foundation.ingestion.unit_planner.DAOFactory", return_value=fake_dao)
    return DatasetActionResolver(mocker.Mock())


def test_etf_mins_definition_is_raw_only_and_exposes_manual_schedule_contract() -> None:
    definition = _definition()

    assert definition.source.api_name == "etf_mins"
    assert definition.source.source_fields == (
        "ts_code",
        "freq",
        "trade_time",
        "open",
        "close",
        "high",
        "low",
        "vol",
        "amount",
        "vwap",
        "exchange",
    )
    assert definition.storage.raw_table == "raw_tushare.etf_minute_bar"
    assert definition.storage.serving_table is None
    assert definition.storage.layer_plan == "raw-only"
    assert definition.storage.write_path == "raw_only_upsert"
    assert definition.planning.page_limit == 8000
    assert definition.planning.max_source_rows_per_unit == 24000
    assert definition.planning.fetch_concurrency == 2
    assert definition.quality.reject_policy == "fail_unit_on_any_rejection"
    assert definition.quality.batch_unique_key_fields == ("ts_code", "freq", "trade_time")
    capability = definition.capabilities.get_action("maintain")
    assert capability is not None
    assert capability.manual_enabled is True
    assert capability.schedule_enabled is True
    assert capability.supported_time_modes == ("point", "range")
    assert any(
        item.dataset_key == "etf_mins"
        and item.group_key == "etf_fund"
        and item.item_order == 70
        for item in OPS_DATASET_DEFAULT_VIEW.items
    )


def test_etf_mins_is_schedulable_but_not_registered_in_any_workflow() -> None:
    assert action_is_schedulable("dataset_action", "etf_mins.maintain") is True
    capability = ScheduleAutomationCapabilityResolver().resolve(
        target_type="dataset_action",
        target_key="etf_mins.maintain",
    )
    assert capability is not None
    assert capability.time_input_contract is not None
    assert capability.time_input_contract.supported_modes == ("point", "range")
    assert all(
        step.dataset_key != "etf_mins"
        for workflow in list_workflow_definitions()
        for step in workflow.steps
    )


def test_etf_mins_point_plan_uses_active_pool_and_selected_freq_order(mocker) -> None:
    resolver = _resolver(mocker, ["510500.SH", "159915.SZ"])
    plan = resolver.build_plan(
        DatasetActionRequest(
            dataset_key="etf_mins",
            action="maintain",
            time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 8, 21)),
            filters={"freq": ["60min", "1min"]},
        )
    )

    assert plan.planning.unit_count == 4
    assert [
        (unit.request_params["ts_code"], unit.request_params["freq"])
        for unit in plan.units
    ] == [
        ("159915.SZ", "1min"),
        ("159915.SZ", "60min"),
        ("510500.SH", "1min"),
        ("510500.SH", "60min"),
    ]
    assert all(unit.request_params["start_date"] == "2026-08-21 09:00:00" for unit in plan.units)
    assert all(unit.request_params["end_date"] == "2026-08-21 19:00:00" for unit in plan.units)
    assert {unit.max_source_rows_per_unit for unit in plan.units} == {24000}
    assert {unit.progress_context["window_index"] for unit in plan.units} == {1}
    assert {unit.progress_context["window_total"] for unit in plan.units} == {1}


def test_etf_mins_range_uses_frequency_specific_calendar_month_windows(mocker) -> None:
    resolver = _resolver(mocker, ["510300.SH"])
    plan = resolver.build_plan(
        DatasetActionRequest(
            dataset_key="etf_mins",
            action="maintain",
            time_input=DatasetTimeInput(
                mode="range",
                start_date=date(2025, 1, 15),
                end_date=date(2025, 5, 10),
            ),
            filters={"ts_code": "510300.sh", "freq": ["1min", "5min"]},
        )
    )

    assert [(unit.request_params["freq"], unit.request_params["start_date"], unit.request_params["end_date"]) for unit in plan.units] == [
        ("1min", "2025-01-15 09:00:00", "2025-02-28 19:00:00"),
        ("1min", "2025-03-01 09:00:00", "2025-04-30 19:00:00"),
        ("1min", "2025-05-01 09:00:00", "2025-05-10 19:00:00"),
        ("5min", "2025-01-15 09:00:00", "2025-05-10 19:00:00"),
    ]
    assert [unit.progress_context["window_index"] for unit in plan.units] == [1, 2, 3, 1]
    assert [unit.progress_context["window_total"] for unit in plan.units] == [3, 3, 3, 1]
    assert all("start=" in unit.unit_id and "end=" in unit.unit_id for unit in plan.units)


@pytest.mark.parametrize(
    ("pool_codes", "filters", "message", "error_code"),
    (
        ([], {"freq": ["1min"]}, "先初始化 etf_mins ETF 激活池", "universe_empty"),
        (["510300.OF"], {"freq": ["1min"]}, "只允许 .SH/.SZ", "invalid_enum"),
        (["510300.SH"], {"ts_code": "159915.SZ", "freq": ["1min"]}, "未配置到 etf_mins 激活池", "invalid_enum"),
        (["510300.SH"], {"freq": []}, "分钟周期不能为空", "empty_not_allowed"),
        (["510300.SH"], {"freq": ["90min"]}, "分钟周期不在可选范围内", "invalid_enum"),
    ),
)
def test_etf_mins_planner_rejects_invalid_pool_code_and_freq(
    mocker,
    pool_codes: list[str],
    filters: dict[str, object],
    message: str,
    error_code: str,
) -> None:
    resolver = _resolver(mocker, pool_codes)
    with pytest.raises(IngestionError, match=message) as exc_info:
        resolver.build_plan(
            DatasetActionRequest(
                dataset_key="etf_mins",
                action="maintain",
                time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 8, 21)),
                filters=filters,
            )
        )
    structured = getattr(exc_info.value, "structured_error", None)
    assert structured is not None
    assert structured.error_code == error_code


def test_etf_mins_request_builder_emits_only_source_contract_params() -> None:
    assert _etf_mins_params(
        SimpleNamespace(),
        None,
        {
            "ts_code": "510300.sh",
            "freq": "5min",
            "window_start": "2026-08-21 09:00:00",
            "window_end": "2026-08-21 19:00:00",
        },
    ) == {
        "ts_code": "510300.SH",
        "freq": "5min",
        "start_date": "2026-08-21 09:00:00",
        "end_date": "2026-08-21 19:00:00",
    }


def _unit() -> PlanUnitSnapshot:
    return PlanUnitSnapshot(
        unit_id="etf-mins-u1",
        dataset_key="etf_mins",
        source_key="tushare",
        trade_date=None,
        request_params={
            "ts_code": "510300.SH",
            "freq": "1min",
            "start_date": "2026-08-21 09:00:00",
            "end_date": "2026-08-21 19:00:00",
        },
        progress_context={},
        pagination_policy="offset_limit",
        page_limit=8000,
        max_source_rows_per_unit=24000,
    )


def test_etf_mins_source_accepts_three_pages_and_empty_boundary_probe(monkeypatch) -> None:
    connector = _PagedConnector({0: 8000, 8000: 8000, 16000: 8000, 24000: 0})
    monkeypatch.setattr(source_client_module, "create_source_connector", lambda _key: connector)

    result = DatasetSourceClient().fetch(definition=_definition(), unit=_unit())

    assert len(result.rows_raw) == 24000
    assert [call["params"]["offset"] for call in connector.calls] == [0, 8000, 16000, 24000]
    assert {call["api_name"] for call in connector.calls} == {"etf_mins"}
    assert {call["fields"] for call in connector.calls} == {
        _definition().source.source_fields
    }
    assert result.pagination_diagnostics["terminal_offset"] == 24000
    assert result.pagination_diagnostics["terminal_page_rows"] == 0


def test_etf_mins_empty_source_result_is_a_successful_zero_row_unit(monkeypatch) -> None:
    connector = _PagedConnector({0: 0})
    monkeypatch.setattr(source_client_module, "create_source_connector", lambda _key: connector)

    result = DatasetSourceClient().fetch(definition=_definition(), unit=_unit())

    assert result.rows_raw == []
    assert result.request_count == 1
    assert result.pagination_diagnostics["terminal_offset"] == 0
    assert result.pagination_diagnostics["terminal_page_rows"] == 0


def test_etf_mins_source_rejects_data_beyond_24000_rows(monkeypatch) -> None:
    connector = _PagedConnector({0: 8000, 8000: 8000, 16000: 8000, 24000: 1})
    monkeypatch.setattr(source_client_module, "create_source_connector", lambda _key: connector)

    with pytest.raises(IngestionSourceError) as exc_info:
        DatasetSourceClient().fetch(definition=_definition(), unit=_unit())

    assert exc_info.value.structured_error.error_code == "source_rows_exceeded"
    assert exc_info.value.structured_error.details["offset"] == 24000


def test_etf_mins_source_rejects_mismatched_returned_freq(monkeypatch) -> None:
    connector = _PagedConnector({0: 1}, freq="5min")
    monkeypatch.setattr(source_client_module, "create_source_connector", lambda _key: connector)

    with pytest.raises(IngestionSourceError) as exc_info:
        DatasetSourceClient().fetch(definition=_definition(), unit=_unit())

    assert exc_info.value.structured_error.error_code == "source_variant_mismatch"
    assert exc_info.value.structured_error.details["field_name"] == "freq"


def test_etf_mins_transform_preserves_price_precision_and_source_freq() -> None:
    transformed = _etf_mins_row_transform(
        {
            "ts_code": "510300.sh",
            "freq": "1min",
            "trade_time": "2026-08-21 09:31:00",
            "open": "4.123",
            "close": "4.126",
            "high": "4.127",
            "low": "4.121",
            "vol": "12345.0",
            "amount": "50999.88",
            "vwap": "4.1256",
            "exchange": "xshg",
        }
    )

    assert transformed == {
        "ts_code": "510300.SH",
        "freq": "1min",
        "trade_time": datetime(2026, 8, 21, 9, 31),
        "open": 4.123,
        "close": 4.126,
        "high": 4.127,
        "low": 4.121,
        "vol": 12345,
        "amount": 50999.88,
        "vwap": 4.1256,
        "exchange": "XSHG",
    }


@pytest.mark.parametrize("freq", ("1min", "5min", "15min", "30min", "60min"))
def test_etf_mins_transform_preserves_each_supported_source_freq(freq: str) -> None:
    transformed = _etf_mins_row_transform(
        {
            "ts_code": "510300.SH",
            "freq": freq,
            "trade_time": "2026-08-21 09:31:00",
        }
    )

    assert transformed["freq"] == freq


@pytest.mark.parametrize(
    "trade_time",
    (
        "2026-08-21 09:30:00",
        "2026-08-21 11:30:00",
        "2026-08-21 13:00:00",
        "2026-08-21 15:00:00",
    ),
)
def test_etf_mins_transform_accepts_trading_session_boundaries(trade_time: str) -> None:
    transformed = _etf_mins_row_transform(
        {"ts_code": "510300.SH", "freq": "1min", "trade_time": trade_time}
    )

    assert transformed["trade_time"] == datetime.fromisoformat(trade_time)


@pytest.mark.parametrize(
    "trade_time",
    (
        "2026-08-21 09:29:59",
        "2026-08-21 11:30:01",
        "2026-08-21 12:00:00",
        "2026-08-21 15:00:01",
    ),
)
def test_etf_mins_transform_rejects_break_and_out_of_session_rows(trade_time: str) -> None:
    with pytest.raises(ValueError, match="不在交易时段内"):
        _etf_mins_row_transform(
            {"ts_code": "510300.SH", "freq": "1min", "trade_time": trade_time}
        )


def test_etf_mins_duplicate_identity_fails_normalization() -> None:
    row = {
        "ts_code": "510300.SH",
        "freq": "1min",
        "trade_time": "2026-08-21 09:31:00",
        "open": 4.1,
        "close": 4.2,
        "high": 4.3,
        "low": 4.0,
        "vol": 100,
        "amount": 420,
        "vwap": 4.2,
        "exchange": "XSHG",
    }
    with pytest.raises(IngestionNormalizeError) as exc_info:
        DatasetNormalizer().normalize(
            definition=_definition(),
            fetch_result=SourceFetchResult(
                unit_id="duplicate",
                request_count=1,
                retry_count=0,
                latency_ms=1,
                rows_raw=[dict(row), dict(row)],
            ),
        )
    assert exc_info.value.structured_error.error_code == "normalize.batch_unique_key_duplicate"


def test_fail_any_rejection_stops_before_dao_but_record_policy_keeps_existing_behavior(mocker) -> None:
    etf_raw_dao = _RawDao()
    mocker.patch(
        "src.foundation.ingestion.writer.DAOFactory",
        return_value=SimpleNamespace(raw_etf_minute_bar=etf_raw_dao),
    )
    writer = DatasetWriter(session=mocker.Mock())
    rejected_batch = NormalizedBatch(
        unit_id="etf-rejected",
        rows_normalized=[{"ts_code": "510300.SH", "freq": "1min", "trade_time": datetime(2026, 8, 21, 9, 31)}],
        rows_rejected=1,
        rejected_reasons={"normalize.row_transform_failed": 1},
        rejected_samples={"normalize.row_transform_failed": [{"ts_code": "510300.SH"}]},
    )

    with pytest.raises(IngestionWriteError) as exc_info:
        writer.write(definition=_definition(), batch=rejected_batch)
    assert exc_info.value.structured_error.error_code == "write.unit_rows_rejected"
    assert etf_raw_dao.calls == []

    stk_raw_dao = _StkMinsRawDao()
    mocker.patch(
        "src.foundation.ingestion.writer.DAOFactory",
        return_value=SimpleNamespace(raw_stk_mins=stk_raw_dao),
    )
    stk_writer = DatasetWriter(session=mocker.Mock())
    stk_batch = NormalizedBatch(
        unit_id="stk-partial",
        rows_normalized=[{"ts_code": "600000.SH", "freq": 1, "trade_time": datetime(2026, 8, 21, 9, 31)}],
        rows_rejected=1,
        rejected_reasons={"normalize.invalid_date": 1},
    )
    result = stk_writer.write(definition=get_dataset_definition("stk_mins"), batch=stk_batch)
    assert result.rows_written == 1
    assert stk_raw_dao.calls == [stk_batch.rows_normalized]


def test_etf_mins_clean_batch_writes_once_through_raw_only_path(mocker) -> None:
    raw_dao = _RawDao()
    mocker.patch(
        "src.foundation.ingestion.writer.DAOFactory",
        return_value=SimpleNamespace(raw_etf_minute_bar=raw_dao),
    )
    batch = NormalizedBatch(
        unit_id="etf-clean",
        rows_normalized=[
            {
                "ts_code": "510300.SH",
                "freq": "1min",
                "trade_time": datetime(2026, 8, 21, 9, 31),
            }
        ],
        rows_rejected=0,
        rejected_reasons={},
    )

    result = DatasetWriter(session=mocker.Mock()).write(definition=_definition(), batch=batch)

    assert result.rows_written == 1
    assert raw_dao.calls == [batch.rows_normalized]
