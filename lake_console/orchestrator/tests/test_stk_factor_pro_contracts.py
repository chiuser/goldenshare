"""Independent doc328 field contract and isolated public HTTP registration tests.

The source table below is read only by tests. Production never imports Prod or
reads source Markdown. Local HTTP replies are deliberately small and synthetic;
they do not claim to validate real Tushare pagination or published coverage.
"""

import json
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from pathlib import Path

import pytest

from orchestrator.tushare_download import (
    DownloadError,
    DownloadErrorCode,
    DownloadMode,
    DownloadStatus,
    DownloadTask,
    ObjectTimeRange,
    PagePosition,
    TimeRange,
    TushareDownloader,
)
from orchestrator.tushare_download.contract_registry import (
    ContractRegistry,
    content_digest,
)
from orchestrator.tushare_download.contracts import CONTRACTS
from orchestrator.tushare_download.contracts.stk_factor_pro import (
    SOURCE_FIELDS,
    STK_FACTOR_PRO_CONTRACT,
)
from orchestrator.tushare_download.dataset_transport_mapping import (
    BINDINGS,
    DatasetTransportMapping,
    TransportBinding,
)
from orchestrator.tushare_download.request_builder import RequestBuilder
from orchestrator.tushare_download.source_contract import SourceKind
from orchestrator.tushare_download.task_input import validate_task
from orchestrator.tushare_download.unit_planner import UnitPlanner
from tests.tushare_download.test_tushare_download_http_integration import (
    Reply,
    localhost_source,
)


@pytest.fixture(scope="module")
def document_fields():
    """Independent ordered names/types/descriptions from the actual source doc."""
    document = (
        Path(__file__).resolve().parents[3]
        / "docs/sources/tushare/股票数据/特色数据/0328_股票技术面因子(专业版).md"
    )
    output_table = document.read_text().split("## 输出参数\n", 1)[1]
    rows = []
    for line in output_table.splitlines():
        cells = tuple(value.strip() for value in line.strip().strip("|").split("|"))
        if len(cells) == 4 and cells[1] in ("str", "float"):
            rows.append(cells)
    assert len(rows) == 261
    assert tuple(row[0] for row in rows[:2]) == ("ts_code", "trade_date")
    assert tuple(row[0] for row in rows[-3:]) == (
        "xsii_td4_bfq",
        "xsii_td4_hfq",
        "xsii_td4_qfq",
    )
    return tuple(rows)


def test_complete_source_fields_match_independent_document(document_fields):
    contract = STK_FACTOR_PRO_CONTRACT
    assert contract.fields is SOURCE_FIELDS
    assert contract.field_names == tuple(row[0] for row in document_fields)
    assert len(set(contract.field_names)) == 261
    assert tuple(field.description for field in contract.fields) == tuple(
        row[3] for row in document_fields
    )
    assert tuple(field.source_kind for field in contract.fields) == (
        SourceKind.STRING,
        SourceKind.STRING,
        *((SourceKind.NUMBER,) * 259),
    )
    assert tuple(row[1] for row in document_fields) == (
        "str",
        "str",
        *(("float",) * 259),
    )
    assert tuple(field.nullable for field in contract.fields) == (
        False,
        False,
        *((True,) * 259),
    )
    assert contract.fields[1].format == "YYYYMMDD"
    assert all(field.precision_note for field in contract.fields[2:])
    assert not {"api_name", "fetched_at", "raw_payload"} & set(contract.field_names)
    assert contract.fields[0].source_kind is SourceKind.STRING
    with pytest.raises(FrozenInstanceError):
        contract.version = "2"


def test_formal_registry_and_http_mapping_have_one_current_contract():
    contract = STK_FACTOR_PRO_CONTRACT
    assert CONTRACTS == (contract,)
    assert ContractRegistry(CONTRACTS).resolve("stk_factor_pro") is contract
    assert (contract.dataset_id, contract.source_api_name, contract.version) == (
        "stk_factor_pro",
        "stk_factor_pro",
        "1",
    )
    with pytest.raises(DownloadError) as caught:
        ContractRegistry(CONTRACTS).resolve("stk_factor_pro@1")
    assert caught.value.code is DownloadErrorCode.CONTRACT
    assert len(BINDINGS) == 1
    assert DatasetTransportMapping(BINDINGS).resolve(contract) == TransportBinding(
        "stk_factor_pro",
        "stk_factor_pro",
        kind=1,
        adapter_key="http_pro",
        version="1",
        http_path_rule="base",
    )
    wrong = DatasetTransportMapping((TransportBinding("stk_factor_pro", "daily"),))
    with pytest.raises(DownloadError):
        wrong.resolve(contract)


def test_content_identity_compares_all_source_rules():
    contract = STK_FACTOR_PRO_CONTRACT
    for changed in (
        replace(contract, version="2"),
        replace(contract, fields=contract.fields[1:] + contract.fields[:1]),
        replace(
            contract,
            fields=(replace(contract.fields[0], source_kind=SourceKind.NUMBER),)
            + contract.fields[1:],
        ),
        replace(
            contract,
            fields=(replace(contract.fields[0], description="不同含义"),)
            + contract.fields[1:],
        ),
        replace(
            contract,
            parameters=(replace(contract.parameters[0], required=True),)
            + contract.parameters[1:],
        ),
        replace(
            contract, pagination=replace(contract.pagination, effective_limit=9999)
        ),
    ):
        assert content_digest(contract) != content_digest(changed)
        assert not ContractRegistry.same_content(contract, changed)
    assert ContractRegistry.same_content(
        contract, replace(contract, local_evidence_paths=("another-local-copy",))
    )


def _units(task):
    contract = STK_FACTOR_PRO_CONTRACT
    frozen = validate_task(task, contract, 1048576)
    planner = UnitPlanner(frozen, contract)
    result = []
    while (unit := planner.next_unit()) is not None:
        result.append(unit)
    assert len(result) == planner.total_units
    return result


def test_fixed_modes_dates_and_pagination():
    contract = STK_FACTOR_PRO_CONTRACT
    assert tuple(mode.mode for mode in contract.modes) == (
        DownloadMode.BY_POINT,
        DownloadMode.BY_OBJECT_RANGE,
    )
    assert tuple(rule.name for rule in contract.parameters) == (
        "ts_code",
        "trade_date",
        "start_date",
        "end_date",
    )
    assert all(
        not rule.required and not rule.has_default for rule in contract.parameters
    )
    pagination = contract.pagination
    assert (
        pagination.strategy,
        pagination.effective_limit,
        pagination.offset_start,
        pagination.offset_step,
        pagination.limit_param,
        pagination.offset_param,
        pagination.short_page_ends,
        pagination.empty_page_ends,
        pagination.reliable_total_path,
        pagination.reliable_next_offset_path,
        pagination.truncation_limit,
        pagination.split_time_rule_key,
    ) == (2, 10000, 0, 10000, "limit", "offset", True, True, None, None, None, None)
    time_rule = contract.time_rule()
    assert (
        time_rule.input_format,
        time_rule.source_format,
        time_rule.range_bounds,
    ) == (
        "YYYY-MM-DD",
        "YYYYMMDD",
        "closed",
    )
    assert (time_rule.minimum_step, contract.ordering.time_field) == (1, "trade_date")
    units = _units(
        DownloadTask(
            "stk_factor_pro",
            DownloadMode.BY_POINT,
            points=("2026-10-22", "2026-10-21"),
        )
    )
    assert [unit.point for unit in units] == ["2026-10-21", "2026-10-22"]
    request = RequestBuilder(contract).build_page(
        units[0],
        next(RequestBuilder(contract).iter_inputs(units[0])),
        PagePosition(0, offset=0),
    )
    assert request.api_name == "stk_factor_pro"
    assert dict(request.params) == {
        "trade_date": "20261021",
        "limit": 10000,
        "offset": 0,
    }
    assert request.fields == contract.field_names


def test_history_codes_are_expanded_by_component_with_complete_ranges():
    scope = TimeRange("2026-10-12", "2026-10-16")
    shared = _units(
        DownloadTask(
            "stk_factor_pro",
            DownloadMode.BY_OBJECT_RANGE,
            objects=("000001.SZ", "600000.SH"),
            time_range=scope,
        )
    )
    assert [(unit.object_code, unit.time_range) for unit in shared] == [
        ("000001.SZ", scope),
        ("600000.SH", scope),
    ]
    different = _units(
        DownloadTask(
            "stk_factor_pro",
            DownloadMode.BY_OBJECT_RANGE,
            object_ranges=(
                ObjectTimeRange("000001.SZ", scope),
                ObjectTimeRange("600000.SH", TimeRange("2026-10-15", "2026-10-16")),
            ),
        )
    )
    assert [(unit.object_code, unit.time_range.start) for unit in different] == [
        ("000001.SZ", "2026-10-12"),
        ("600000.SH", "2026-10-15"),
    ]
    builder = RequestBuilder(STK_FACTOR_PRO_CONTRACT)
    assert dict(next(builder.iter_inputs(different[0]))) == {
        "ts_code": "000001.SZ",
        "start_date": "20261012",
        "end_date": "20261016",
    }


@pytest.mark.parametrize(
    "mode",
    [
        DownloadMode.SNAPSHOT,
        DownloadMode.BY_OBJECT,
        DownloadMode.BY_OBJECT_POINT,
        DownloadMode.BY_RANGE,
    ],
)
def test_unregistered_modes_are_rejected(mode):
    with pytest.raises(DownloadError) as caught:
        _units(DownloadTask("stk_factor_pro", mode))
    assert caught.value.code is DownloadErrorCode.CONTRACT


@pytest.mark.parametrize(
    "name",
    [
        "fields",
        "limit",
        "offset",
        "token",
        "base_url",
        "url",
        "path",
        "database",
        "ts_code",
        "trade_date",
        "start_date",
        "end_date",
        "unknown",
    ],
)
def test_business_cannot_override_fields_paging_connection_or_roles(name):
    with pytest.raises(DownloadError) as caught:
        _units(
            DownloadTask(
                "stk_factor_pro",
                DownloadMode.BY_POINT,
                points=("2026-10-21",),
                filters={name: "forbidden"},
            )
        )
    assert caught.value.code is DownloadErrorCode.INPUT


@pytest.mark.parametrize(
    "task",
    [
        DownloadTask("stk_factor_pro", DownloadMode.BY_POINT),
        DownloadTask("stk_factor_pro", DownloadMode.BY_POINT, points=()),
        DownloadTask("stk_factor_pro", DownloadMode.BY_POINT, points=("20261021",)),
        DownloadTask("stk_factor_pro", DownloadMode.BY_POINT, points=("2026-02-30",)),
        DownloadTask(
            "stk_factor_pro",
            DownloadMode.BY_OBJECT_RANGE,
            objects=("000001.SZ", "000001.SZ"),
            time_range=TimeRange("2026-10-12", "2026-10-16"),
        ),
        DownloadTask(
            "stk_factor_pro",
            DownloadMode.BY_OBJECT_RANGE,
            objects=("000001.SZ",),
            time_range=TimeRange("2026-10-16", "2026-10-12"),
        ),
    ],
)
def test_missing_empty_duplicate_and_invalid_time_inputs_are_rejected(task):
    with pytest.raises(DownloadError) as caught:
        _units(task)
    assert caught.value.code is DownloadErrorCode.INPUT


def _reply(fields, code, dates):
    # Deliberately synthetic transport rows, not a live business-value fixture.
    rows = []
    for day in dates:
        values = {
            "ts_code": code,
            "trade_date": day,
            "close": 11,
            "change": -1,
            "adj_factor": 142.0699,
        }
        rows.append([values.get(name) for name in fields])
    return Reply(
        200,
        json.dumps(
            {
                "code": 0,
                "data": {"fields": fields, "items": rows},
            }
        ).encode(),
    )


def test_public_load_uses_formal_registry_and_full_field_http(
    monkeypatch, document_fields
):
    fields = tuple(row[0] for row in document_fields)

    def source(payload, _number):
        assert payload == {
            "api_name": "stk_factor_pro",
            "token": "isolated-token",
            "fields": ",".join(fields),
            "params": {"trade_date": "20261021", "limit": 10000, "offset": 0},
        }
        return _reply(fields, "000001.SZ", ("20261021",))

    with localhost_source(source) as (url, requests):
        monkeypatch.setenv("TUSHARE_TOKEN", "isolated-token")
        monkeypatch.setenv("TUSHARE_BASE_URL", url)
        downloader = TushareDownloader.load()
        with downloader.download(
            DownloadTask(
                "stk_factor_pro",
                DownloadMode.BY_POINT,
                points=("2026-10-21",),
            )
        ) as session:
            results = list(session)
    assert len(requests) == 1
    assert requests[0][0] == "/fixture"
    assert len(results) == 1
    assert results[0].unit.contract_version == "1"
    assert results[0].observed_field_sets == (fields,)
    assert results[0].records[0].values[fields.index("close")] == 11
    assert results[0].records[0].values[fields.index("change")] == -1
    assert results[0].records[0].values[fields.index("adj_factor")] == Decimal(
        "142.0699"
    )
    assert results[0].records[0].values[fields.index("pe")] is None
    assert session.summary.status is DownloadStatus.SUCCEEDED
    assert session.summary.completed_units == session.summary.delivered_units == 1
    assert session.summary.row_count == 1


def test_public_history_fans_out_in_component_and_orders_source_dates(
    monkeypatch, document_fields
):
    fields = tuple(row[0] for row in document_fields)

    def source(payload, number):
        assert payload["api_name"] == "stk_factor_pro"
        assert payload["fields"] == ",".join(fields)
        assert payload["params"] == {
            "ts_code": ("000001.SZ", "600000.SH")[number - 1],
            "start_date": "20261012",
            "end_date": "20261016",
            "limit": 10000,
            "offset": 0,
        }
        return _reply(fields, payload["params"]["ts_code"], ("20261016", "20261012"))

    with localhost_source(source) as (url, requests):
        monkeypatch.setenv("TUSHARE_TOKEN", "isolated-token")
        monkeypatch.setenv("TUSHARE_BASE_URL", url)
        downloader = TushareDownloader.load()
        with downloader.download(
            DownloadTask(
                "stk_factor_pro",
                DownloadMode.BY_OBJECT_RANGE,
                objects=("000001.SZ", "600000.SH"),
                time_range=TimeRange("2026-10-12", "2026-10-16"),
            )
        ) as session:
            results = list(session)
    assert len(requests) == 2
    assert [request[0] for request in requests] == ["/fixture", "/fixture"]
    assert [result.unit.object_code for result in results] == ["000001.SZ", "600000.SH"]
    assert [[record.values[1] for record in result.records] for result in results] == [
        ["20261012", "20261016"],
        ["20261012", "20261016"],
    ]
    assert session.summary.status is DownloadStatus.SUCCEEDED
    assert session.summary.row_count == session.summary.completed_row_count == 4


def test_number_kind_preserves_source_precision_and_rejects_non_source_scalar():
    from orchestrator.tushare_download.source_contract import scalar_matches

    numeric = STK_FACTOR_PRO_CONTRACT.fields[2]
    assert scalar_matches(Decimal("0.1000"), numeric.source_kind, numeric.nullable)
    assert scalar_matches(-1, numeric.source_kind, numeric.nullable)
    assert scalar_matches(None, numeric.source_kind, numeric.nullable)
    for wrong in (True, "1", 0.1, Decimal("NaN"), Decimal("Infinity")):
        assert not scalar_matches(wrong, numeric.source_kind, numeric.nullable)
