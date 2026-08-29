from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from src.foundation.dao.etf_basic_dao import (
    EtfRequestabilitySnapshot,
    EtfRequestTarget,
)
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion import DatasetActionRequest, DatasetActionResolver, DatasetTimeInput
from src.foundation.ingestion import source_client as source_client_module
from src.foundation.ingestion.etf_minute_windows import (
    ETF_MINS_RANGE_WINDOW_MONTHS,
    build_etf_minute_windows,
)
from src.foundation.ingestion.errors import (
    IngestionError,
    IngestionNormalizeError,
    IngestionSourceError,
    IngestionWriteError,
)
from src.foundation.ingestion.execution_plan import (
    PlanUnitSnapshot,
    ValidatedDatasetActionRequest,
)
from src.foundation.ingestion.executor import IngestionExecutor
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


ELIGIBILITY_AS_OF = date(2026, 8, 28)


def _request_target(ts_code: str, *, list_date: date) -> EtfRequestTarget:
    return EtfRequestTarget(
        ts_code=ts_code,
        list_date=list_date,
        exchange="SH" if ts_code.endswith(".SH") else "SZ",
    )


def _resolver(
    mocker,
    targets: list[EtfRequestTarget],
) -> tuple[DatasetActionResolver, SimpleNamespace]:  # type: ignore[no-untyped-def]
    targets_by_code = {target.ts_code: target for target in targets}
    etf_basic = SimpleNamespace(
        load_requestability_snapshot=mocker.Mock(
            return_value=EtfRequestabilitySnapshot(
                as_of_date=ELIGIBILITY_AS_OF,
                exchange=None,
                targets=tuple(sorted(targets, key=lambda target: target.ts_code)),
                serving_row_count=len(targets),
                requestable_count=len(targets),
                excluded_reason_counts={},
            )
        ),
        get_requestable_target=mocker.Mock(
            side_effect=lambda *, ts_code, as_of_date, exchange=None: targets_by_code.get(
                ts_code
            )
        ),
    )
    fake_dao = SimpleNamespace(
        etf_basic=etf_basic,
    )
    mocker.patch("src.foundation.ingestion.unit_planner.DAOFactory", return_value=fake_dao)
    mocker.patch(
        "src.foundation.ingestion.unit_planner._current_china_date",
        return_value=ELIGIBILITY_AS_OF,
    )
    return DatasetActionResolver(mocker.Mock()), etf_basic


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
    filters = {field.name: field for field in definition.input_model.filters}
    assert filters["ts_code"].field_type == "string"
    assert filters["ts_code"].multi_value is True
    assert "逗号分隔" in filters["ts_code"].description
    assert definition.planning.universe_policy == "pool"
    assert definition.planning.universe is not None
    assert [
        (source.type, source.resource)
        for source in definition.planning.universe.sources
    ] == [("core_serving_etf_basic", None)]
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


def test_etf_mins_automatic_point_plan_uses_one_basic_snapshot(mocker) -> None:
    resolver, etf_basic = _resolver(
        mocker,
        [
            _request_target("510500.SH", list_date=date(2013, 3, 15)),
            _request_target("159915.SZ", list_date=date(2011, 12, 5)),
        ],
    )
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
    assert {unit.progress_context["eligibility_as_of"] for unit in plan.units} == {
        "2026-08-28"
    }
    assert {
        unit.progress_context["master_list_date"] for unit in plan.units
    } == {"2011-12-05", "2013-03-15"}
    assert {unit.progress_context["requested_start_date"] for unit in plan.units} == {
        "2026-08-21"
    }
    assert {unit.progress_context["effective_start_date"] for unit in plan.units} == {
        "2026-08-21"
    }
    etf_basic.load_requestability_snapshot.assert_called_once_with(
        as_of_date=ELIGIBILITY_AS_OF,
        exchange=None,
    )
    etf_basic.get_requestable_target.assert_not_called()


def test_etf_mins_explicit_range_clips_before_frequency_windows(mocker) -> None:
    target = _request_target("510300.SH", list_date=date(2025, 2, 10))
    resolver, etf_basic = _resolver(mocker, [target])
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

    assert [
        (
            unit.request_params["freq"],
            unit.request_params["start_date"],
            unit.request_params["end_date"],
        )
        for unit in plan.units
    ] == [
        ("1min", "2025-02-10 09:00:00", "2025-03-31 19:00:00"),
        ("1min", "2025-04-01 09:00:00", "2025-05-10 19:00:00"),
        ("5min", "2025-02-10 09:00:00", "2025-05-10 19:00:00"),
    ]
    assert [unit.progress_context["window_index"] for unit in plan.units] == [1, 2, 1]
    assert [unit.progress_context["window_total"] for unit in plan.units] == [2, 2, 1]
    assert all(
        unit.progress_context["requested_start_date"] == "2025-01-15"
        and unit.progress_context["effective_start_date"] == "2025-02-10"
        and unit.progress_context["master_list_date"] == "2025-02-10"
        for unit in plan.units
    )
    assert all("start=" in unit.unit_id and "end=" in unit.unit_id for unit in plan.units)
    assert [
        (
            date.fromisoformat(str(unit.request_params["start_date"])[:10]),
            date.fromisoformat(str(unit.request_params["end_date"])[:10]),
        )
        for unit in plan.units
        if unit.request_params["freq"] == "1min"
    ] == list(
        build_etf_minute_windows(
            freq="1min",
            start_date=target.list_date,
            end_date=date(2025, 5, 10),
        )
    )
    etf_basic.get_requestable_target.assert_called_once_with(
        ts_code="510300.SH",
        as_of_date=ELIGIBILITY_AS_OF,
        exchange=None,
    )
    etf_basic.load_requestability_snapshot.assert_not_called()


def test_etf_mins_multi_code_range_normalizes_once_and_fans_out_stably(mocker) -> None:
    resolver, etf_basic = _resolver(
        mocker,
        [
            _request_target("510300.SH", list_date=date(2026, 1, 1)),
            _request_target("159915.SZ", list_date=date(2026, 2, 10)),
        ],
    )

    plan = resolver.build_plan(
        DatasetActionRequest(
            dataset_key="etf_mins",
            action="maintain",
            time_input=DatasetTimeInput(
                mode="range",
                start_date=date(2026, 1, 1),
                end_date=date(2026, 3, 15),
            ),
            filters={
                "ts_code": " 510300.sh,159915.sz,510300.SH ",
                "freq": ["5min", "1min"],
            },
        )
    )

    assert [
        (
            unit.request_params["ts_code"],
            unit.request_params["freq"],
            unit.request_params["start_date"],
            unit.request_params["end_date"],
        )
        for unit in plan.units
    ] == [
        ("159915.SZ", "1min", "2026-02-10 09:00:00", "2026-03-15 19:00:00"),
        ("159915.SZ", "5min", "2026-02-10 09:00:00", "2026-03-15 19:00:00"),
        ("510300.SH", "1min", "2026-01-01 09:00:00", "2026-02-28 19:00:00"),
        ("510300.SH", "1min", "2026-03-01 09:00:00", "2026-03-15 19:00:00"),
        ("510300.SH", "5min", "2026-01-01 09:00:00", "2026-03-15 19:00:00"),
    ]
    assert all(isinstance(unit.request_params["ts_code"], str) for unit in plan.units)
    etf_basic.load_requestability_snapshot.assert_called_once_with(
        as_of_date=ELIGIBILITY_AS_OF,
        exchange=None,
    )
    etf_basic.get_requestable_target.assert_not_called()


def test_etf_mins_multi_code_rejects_entire_plan_when_any_code_is_not_requestable(
    mocker,
) -> None:
    resolver, etf_basic = _resolver(
        mocker,
        [_request_target("510300.SH", list_date=date(2020, 1, 1))],
    )

    with pytest.raises(IngestionError, match="当前不可请求") as exc_info:
        resolver.build_plan(
            DatasetActionRequest(
                dataset_key="etf_mins",
                action="maintain",
                time_input=DatasetTimeInput(
                    mode="point",
                    trade_date=date(2026, 8, 21),
                ),
                filters={
                    "ts_code": ["999999.sh", "510300.sh", "888888.sz"],
                    "freq": ["1min"],
                },
            )
        )

    structured = exc_info.value.structured_error
    assert structured.error_code == "etf_not_requestable"
    assert structured.details == {
        "invalid_ts_codes": ["888888.SZ", "999999.SH"],
        "as_of_date": "2026-08-28",
        "exchange": "ALL",
    }
    etf_basic.load_requestability_snapshot.assert_called_once()
    etf_basic.get_requestable_target.assert_not_called()


def test_etf_mins_multi_code_window_before_any_list_date_rejects_entire_plan(
    mocker,
) -> None:
    resolver, etf_basic = _resolver(
        mocker,
        [
            _request_target("159915.SZ", list_date=date(2021, 1, 1)),
            _request_target("510300.SH", list_date=date(2020, 1, 1)),
        ],
    )

    with pytest.raises(IngestionError, match="请求窗口整体早于上市日期") as exc_info:
        resolver.build_plan(
            DatasetActionRequest(
                dataset_key="etf_mins",
                action="maintain",
                time_input=DatasetTimeInput(
                    mode="range",
                    start_date=date(2019, 1, 1),
                    end_date=date(2019, 12, 31),
                ),
                filters={
                    "ts_code": ["510300.SH", "159915.SZ"],
                    "freq": ["1min"],
                },
            )
        )

    assert exc_info.value.structured_error.error_code == "window_before_list_date"
    assert exc_info.value.structured_error.details["ts_code"] == "159915.SZ"
    etf_basic.load_requestability_snapshot.assert_called_once()
    etf_basic.get_requestable_target.assert_not_called()


@pytest.mark.parametrize(
    ("freq", "expected_first_end"),
    (
        ("1min", date(2025, 2, 28)),
        ("5min", date(2025, 12, 31)),
        ("15min", date(2027, 12, 31)),
        ("30min", date(2030, 12, 31)),
        ("60min", date(2034, 12, 31)),
    ),
)
def test_etf_minute_windows_keep_frequency_month_boundaries(
    freq: str,
    expected_first_end: date,
) -> None:
    windows = build_etf_minute_windows(
        freq=freq,
        start_date=date(2025, 1, 15),
        end_date=date(2035, 12, 31),
    )

    assert ETF_MINS_RANGE_WINDOW_MONTHS[freq] in {2, 12, 36, 72, 120}
    assert windows[0] == (date(2025, 1, 15), expected_first_end)
    assert windows[-1][1] == date(2035, 12, 31)


def test_etf_mins_automatic_all_before_list_date_is_zero_unit_and_zero_source_request(
    mocker,
) -> None:
    resolver, etf_basic = _resolver(
        mocker,
        [
            _request_target("510300.SH", list_date=date(2020, 1, 1)),
            _request_target("159915.SZ", list_date=date(2021, 1, 1)),
        ],
    )
    plan = resolver.build_plan(
        DatasetActionRequest(
            dataset_key="etf_mins",
            action="maintain",
            time_input=DatasetTimeInput(
                mode="range",
                start_date=date(2019, 1, 1),
                end_date=date(2019, 12, 31),
            ),
            filters={"freq": ["1min"]},
        )
    )

    assert plan.planning.unit_count == 0
    assert plan.units == ()
    etf_basic.load_requestability_snapshot.assert_called_once()
    etf_basic.get_requestable_target.assert_not_called()

    executor = IngestionExecutor(mocker.Mock())
    executor.source_client.fetch = mocker.Mock(
        side_effect=AssertionError("0-unit plan must not request source")
    )
    summary = executor.run(
        request=ValidatedDatasetActionRequest(
            request_id="etf-mins-zero-unit",
            dataset_key="etf_mins",
            action="maintain",
            run_profile="range_rebuild",
            trigger_source="manual",
            params={"freq": ["1min"]},
            start_date=date(2019, 1, 1),
            end_date=date(2019, 12, 31),
        ),
        definition=_definition(),
        units=plan.units,
    )

    assert (summary.unit_total, summary.unit_done, summary.unit_failed) == (0, 0, 0)
    executor.source_client.fetch.assert_not_called()


@pytest.mark.parametrize(
    "time_input",
    (
        DatasetTimeInput(mode="point", trade_date=date(2019, 12, 31)),
        DatasetTimeInput(
            mode="range",
            start_date=date(2019, 1, 1),
            end_date=date(2019, 12, 31),
        ),
    ),
)
def test_etf_mins_explicit_window_before_list_date_is_structured_error(
    mocker,
    time_input: DatasetTimeInput,
) -> None:
    resolver, etf_basic = _resolver(
        mocker,
        [_request_target("510300.SH", list_date=date(2020, 1, 1))],
    )

    with pytest.raises(IngestionError, match="请求窗口整体早于上市日期") as exc_info:
        resolver.build_plan(
            DatasetActionRequest(
                dataset_key="etf_mins",
                action="maintain",
                time_input=time_input,
                filters={"ts_code": "510300.SH", "freq": ["1min"]},
            )
        )

    structured = exc_info.value.structured_error
    assert structured.error_code == "window_before_list_date"
    assert structured.details["ts_code"] == "510300.SH"
    assert structured.details["master_list_date"] == "2020-01-01"
    etf_basic.get_requestable_target.assert_called_once()
    etf_basic.load_requestability_snapshot.assert_not_called()


@pytest.mark.parametrize(
    ("master_state", "ts_code"),
    (
        ("P", "510500.SH"),
        ("D", "159901.SZ"),
        ("L_WITHOUT_LIST_DATE", "510880.SH"),
        ("L_FUTURE", "159999.SZ"),
        ("OF", "510300.OF"),
        ("MISSING", "510999.SH"),
    ),
)
def test_etf_mins_explicit_non_requestable_master_states_fail_closed(
    mocker,
    master_state: str,
    ts_code: str,
) -> None:
    del master_state
    resolver, etf_basic = _resolver(mocker, [])

    with pytest.raises(IngestionError, match="当前不可请求") as exc_info:
        resolver.build_plan(
            DatasetActionRequest(
                dataset_key="etf_mins",
                action="maintain",
                time_input=DatasetTimeInput(
                    mode="point",
                    trade_date=date(2026, 8, 21),
                ),
                filters={"ts_code": ts_code, "freq": ["1min"]},
            )
        )

    structured = exc_info.value.structured_error
    assert structured.error_code == "etf_not_requestable"
    assert structured.details == {
        "ts_code": ts_code,
        "as_of_date": "2026-08-28",
        "exchange": "ALL",
    }
    etf_basic.get_requestable_target.assert_called_once()
    etf_basic.load_requestability_snapshot.assert_not_called()


def test_etf_mins_automatic_empty_basic_snapshot_reuses_universe_empty(mocker) -> None:
    resolver, etf_basic = _resolver(mocker, [])

    with pytest.raises(IngestionError, match="当前没有可请求 ETF") as exc_info:
        resolver.build_plan(
            DatasetActionRequest(
                dataset_key="etf_mins",
                action="maintain",
                time_input=DatasetTimeInput(
                    mode="point",
                    trade_date=date(2026, 8, 21),
                ),
                filters={"freq": ["1min"]},
            )
        )

    assert exc_info.value.structured_error.error_code == "universe_empty"
    assert exc_info.value.structured_error.details["exchange"] == "ALL"
    etf_basic.load_requestability_snapshot.assert_called_once()
    etf_basic.get_requestable_target.assert_not_called()


@pytest.mark.parametrize(
    ("filters", "message", "error_code"),
    (
        ({"freq": []}, "分钟周期不能为空", "empty_not_allowed"),
        ({"freq": ["90min"]}, "分钟周期不在可选范围内", "invalid_enum"),
    ),
)
def test_etf_mins_planner_rejects_invalid_freq(
    mocker,
    filters: dict[str, object],
    message: str,
    error_code: str,
) -> None:
    resolver, _etf_basic = _resolver(
        mocker,
        [_request_target("510300.SH", list_date=date(2020, 1, 1))],
    )
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
