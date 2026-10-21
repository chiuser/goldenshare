from dataclasses import replace

import pytest

from orchestrator.tushare_download import DownloadError, DownloadTask
from orchestrator.tushare_download import DownloadErrorCode as C
from orchestrator.tushare_download import DownloadMode as M
from orchestrator.tushare_download.request_builder import RequestBuilder
from orchestrator.tushare_download.source_contract import (
    EnumRule,
    ModeRule,
)
from orchestrator.tushare_download.task_input import validate_task
from orchestrator.tushare_download.unit_planner import UnitPlanner

from .fixtures import build, contract, rows


@pytest.mark.parametrize("independent,expected_units", [(False, 1), (True, 2)])
def test_enum_order_and_request_origin_without_adding_source_columns(
    independent, expected_units
):
    mode = ModeRule(
        M.SNAPSHOT,
        enum_dimensions=(EnumRule("exchange", ("A", "B")),),
        unit_enum_dimensions=("exchange",) if independent else (),
    )
    definition = contract(modes=(mode,))
    downloader, calls, _, _ = build(
        lambda request, attempt: rows(), definition=definition
    )
    task = DownloadTask(
        definition.contract_name, M.SNAPSHOT, enum_values={"exchange": ("B", "A")}
    )
    with downloader.download(task) as session:
        results = list(session)
    assert len(results) == expected_units
    assert [dict(r.params)["exchange"] for r in calls] == ["A", "B"]
    assert all(
        "exchange" not in record.fields
        for result in results
        for record in result.records
    )
    if not independent:
        assert [r.request_input_index for r in results[0].records] == [0, 1]
        assert [dict(x)["exchange"] for x in results[0].request_inputs] == ["A", "B"]


def test_enum_empty_duplicates_and_unknown_values_rejected():
    definition = contract(
        modes=(
            ModeRule(M.SNAPSHOT, enum_dimensions=(EnumRule("exchange", ("A", "B")),)),
        )
    )
    for selection in ((), ("A", "A"), ("C",)):
        with pytest.raises(DownloadError):
            validate_task(
                DownloadTask(
                    definition.contract_name,
                    M.SNAPSHOT,
                    enum_values={"exchange": selection},
                ),
                definition,
                1048576,
            )


def test_required_and_default_are_separate_and_complete_fields_are_mandatory():
    definition = contract()
    definition = replace(
        definition,
        parameters=tuple(
            replace(p, required=True) if p.name == "extra" else p
            for p in definition.parameters
        ),
    )
    downloader, calls, _, _ = build(definition=definition)
    with (
        pytest.raises(DownloadError),
        downloader.download(
            DownloadTask(definition.contract_name, M.SNAPSHOT)
        ) as session,
    ):
        next(session)
    assert calls == []
    with downloader.download(
        DownloadTask(definition.contract_name, M.SNAPSHOT, filters={"extra": "value"})
    ) as session:
        results = list(session)
    assert len(results) == 1 and calls[0].fields == definition.field_names
    defaulted = replace(
        definition,
        parameters=tuple(
            replace(p, has_default=True, default=None, nullable=True)
            if p.name == "extra"
            else p
            for p in definition.parameters
        ),
    )
    frozen = validate_task(
        DownloadTask(defaulted.contract_name, M.SNAPSHOT), defaulted, 1048576
    )
    unit = UnitPlanner(frozen, defaulted).next_unit()
    assert dict(next(RequestBuilder(defaulted).iter_inputs(unit)))["extra"] is None


@pytest.mark.parametrize(
    "name",
    [
        "fields",
        "limit",
        "offset",
        "token",
        "base_url",
        "database",
        "path",
        "ts_code",
        "trade_date",
    ],
)
def test_filters_cannot_override_roles_or_transport_storage_policy(name):
    definition = contract()
    with pytest.raises(DownloadError) as caught:
        validate_task(
            DownloadTask(definition.contract_name, M.SNAPSHOT, filters={name: "bad"}),
            definition,
            1048576,
        )
    assert caught.value.code == C.INPUT


def test_input_is_frozen_and_large_input_is_rejected_before_unbounded_copy():
    points = ["2018-07-18"]
    filters = {"exchange": "SSE"}
    downloader, calls, _, _ = build()
    with downloader.download(
        DownloadTask("fixture.daily@1", M.BY_POINT, points=points, filters=filters)
    ) as session:
        points.append("2018-07-17")
        filters["exchange"] = "changed"
        results = list(session)
    assert len(results) == len(calls) == 1
    assert dict(calls[0].params)["exchange"] == "SSE"
    with pytest.raises(DownloadError) as caught:
        validate_task(
            DownloadTask("fixture.daily@1", M.BY_OBJECT, objects=("X" * 1025,)),
            contract(),
            1024,
        )
    assert caught.value.code == C.CAPACITY


@pytest.mark.parametrize(
    "mode,inputs", [(M.SNAPSHOT, {}), (M.BY_OBJECT, {"objects": ("A",)})]
)
def test_other_modes_time_defaults_cannot_silently_restrict_no_time_download(
    mode, inputs
):
    definition = contract()
    definition = replace(
        definition,
        parameters=tuple(
            replace(p, has_default=True, default="20180718")
            if p.name == "trade_date"
            else p
            for p in definition.parameters
        ),
    )
    downloader, calls, _, _ = build(definition=definition)
    with downloader.download(
        DownloadTask(definition.contract_name, mode, **inputs)
    ) as session:
        assert len(list(session)) == 1
    params = dict(calls[0].params)
    assert (
        "trade_date" not in params
        and "start_date" not in params
        and "end_date" not in params
    )
