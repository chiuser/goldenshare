"""Raw 合同与隔离源响应；不连接 Prod、Tushare 或正式 Dagster。"""

import importlib
import io
import json
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from threading import get_ident
from unittest.mock import Mock

import dagster as dg
import duckdb
import pytest

from orchestrator.defs.assets import index_period as assets
from orchestrator.defs.catalog.lake_assets import (
    PartitionPhysicalLayout,
    get_partition_model_definition,
    list_lake_asset_catalog_entries,
)
from orchestrator.defs.io.index_period_writer import (
    download_index_period_rows,
    index_period_end,
)
from orchestrator.defs.partitions import cn_a_index_months, cn_a_index_week_ends
from orchestrator.defs.paths import (
    raw_index_monthly_path,
    raw_index_weekly_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.prod_db.index_period import (
    open_prod_index_period_rows,
    prod_index_period_query,
)
from orchestrator.defs.run_contracts.asset_column_schemas import RAW_INDEX_WEEKLY_SCHEMA
from orchestrator.defs.run_contracts.index_period import (
    INDEX_MONTHLY,
    INDEX_WEEKLY,
    index_period_codes,
)
from orchestrator.source_readiness.tushare.index_period import (
    index_period_source_published,
)
from orchestrator.tushare_download import (
    DownloadMode,
    DownloadTask,
    TushareDownloader,
    download_api,
    http_transport,
)
from orchestrator.tushare_download.configuration import (
    ConfigurationLoader,
    ConfigurationSnapshot,
)
from orchestrator.tushare_download.contract_registry import ContractRegistry
from orchestrator.tushare_download.contracts import CONTRACTS
from orchestrator.tushare_download.contracts.index_monthly import INDEX_MONTHLY_CONTRACT
from orchestrator.tushare_download.contracts.index_weekly import INDEX_WEEKLY_CONTRACT
from tests.tushare_download.fixtures import build

# 独立字段预期来自本地源文档171/172；数值来自方案§2已接受的000680周线样本。
# 其他代码、日期复用这些数值时，仅用于人工合同样本，不声称是真实行情。
FIELDS = (
    "ts_code",
    "trade_date",
    "close",
    "open",
    "high",
    "low",
    "pre_close",
    "change",
    "pct_chg",
    "vol",
    "amount",
)
NUMBERS = tuple(
    Decimal(value)
    for value in (
        "2338.1344",
        "2350.4203",
        "2565.1536",
        "2302.9874",
        "2343.6595",
        "-5.5251",
        "-0.0024",
        "37226008500",
        "2922268798699",
    )
)
EXPECTED_CODES = (
    "000001.SH",
    "399001.SZ",
    "399006.SZ",
    "000688.SH",
    "000300.SH",
    "000905.SH",
    "000852.SH",
    "899050.BJ",
    "000510.SH",
    "000016.SH",
    "000680.SH",
)


def row(code, day):
    return (code, day, *NUMBERS)


def fake_source(monkeypatch, period, responder=None):
    definition = (
        INDEX_WEEKLY_CONTRACT if period == INDEX_WEEKLY else INDEX_MONTHLY_CONTRACT
    )

    def default(request, attempt):
        params = dict(request.params)
        return (
            ()
            if params["ts_code"] == "899050.BJ"
            else (row(params["ts_code"], params["trade_date"]),)
        )

    downloader, calls, transports, _ = build(
        responder or default, definition=definition
    )
    creation_threads = []

    def load(cls):
        creation_threads.append(get_ident())
        return downloader

    monkeypatch.setattr(TushareDownloader, "load", classmethod(load))
    return calls, transports, creation_threads


def calendar(connection, root, *, closed=()):
    # 真实生产者字段：calendar.py / SILVER_TRADE_CALENDAR_SCHEMA。
    # 日期和休市设置是明确的人工边界样本，不是交易日历审计。
    path = silver_trade_calendar_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection.execute("""CREATE TEMP TABLE calendar AS
        SELECT 'SSE'::VARCHAR exchange, day::DATE trade_date,
               (isodow(day)<6) AS is_open, NULL::DATE pretrade_date
        FROM generate_series(DATE '2026-06-01', DATE '2026-08-31', INTERVAL 1 DAY) t(day)""")
    if closed:
        connection.execute(
            "UPDATE calendar SET is_open=false WHERE trade_date IN (SELECT unnest(?::DATE[]))",
            [closed],
        )
    connection.execute(f"COPY calendar TO '{path}' (FORMAT PARQUET)")
    return path


@pytest.mark.parametrize(
    "period,definition,partition",
    [
        (INDEX_WEEKLY, INDEX_WEEKLY_CONTRACT, cn_a_index_week_ends),
        (INDEX_MONTHLY, INDEX_MONTHLY_CONTRACT, cn_a_index_months),
    ],
)
def test_complete_contract_and_source_request(
    monkeypatch, period, definition, partition
):
    ContractRegistry(CONTRACTS)
    assert tuple(field.name for field in definition.fields) == FIELDS
    assert tuple(column.type for column in RAW_INDEX_WEEKLY_SCHEMA) == (
        "VARCHAR",
        "VARCHAR",
        *("DECIMAL(18,4)",) * 6,
        "DECIMAL(10,4)",
        "DECIMAL(20,4)",
        "DECIMAL(20,4)",
    )
    assert definition.version == "1"
    assert tuple(mode.mode for mode in definition.modes) == (
        DownloadMode.BY_OBJECT_POINT,
    )
    assert "index_daily" not in {contract.contract_name for contract in CONTRACTS}
    assert index_period_codes() == EXPECTED_CODES
    calls, transports, threads = fake_source(monkeypatch, period)
    rows = download_index_period_rows(
        period,
        date(2026, 7, 3),
        codes=EXPECTED_CODES,
        required_codes=tuple(c for c in EXPECTED_CODES if c != "899050.BJ"),
    )
    assert len(rows) == 10
    assert len(calls) == 11
    assert [dict(call.params) for call in calls] == [
        {"ts_code": code, "trade_date": "20260703", "limit": 1000, "offset": 0}
        for code in EXPECTED_CODES
    ]
    assert all(call.fields == FIELDS for call in calls)
    assert transports[0].closed == 1
    assert threads == [get_ident()]
    asset = (
        assets.raw_index_weekly if period == INDEX_WEEKLY else assets.raw_index_monthly
    )
    assert asset.partitions_def == partition
    entries = {entry.asset_key: entry for entry in list_lake_asset_catalog_entries()}
    entry = entries[period.raw_asset]
    assert entry.event_policy.value == "dagster_run_only"
    assert entries[period.silver_asset].event_policy.value == "dagster_run_only"
    model = get_partition_model_definition(entry.partition_model)
    assert model.physical_layout == PartitionPhysicalLayout.SINGLE_FILE
    assert model.dagster_partition_dimension == (
        "week_end_date" if period == INDEX_WEEKLY else "month"
    )
    assert (
        entry.path_template
        == f"data_lake/raw/{period.dataset_id}/full/part-000.parquet"
    )
    assert entry.blocking_check_names == (period.raw_check,)
    spec = asset.get_asset_spec()
    assert spec.metadata["goldenshare/path_template"] == entry.path_template
    assert spec.metadata["goldenshare/dataset_id"] == period.dataset_id
    assert spec.metadata["goldenshare/source_system"] == "tushare"
    assert spec.metadata["goldenshare/data_contract"] == f"{period.dataset_id}_raw_v1"
    assert spec.metadata["goldenshare/source_doc"] == period.source_doc
    assert spec.metadata["goldenshare/source_api"] == period.dataset_id
    assert spec.group_name == entry.group_name == "index"
    assert {check.name for check in asset.check_specs} == {period.raw_check}
    assert all(
        check.blocking and check.partitions_def == partition
        for check in asset.check_specs
    )
    assert tuple(
        (col.name, col.type)
        for col in spec.metadata["dagster/column_schema"].schema.columns
    ) == tuple((col.name, col.type) for col in entry.column_schema)
    assert {"silver_index_weekly", "silver_index_monthly"} <= entries.keys()


@pytest.mark.parametrize(
    "period,key,end",
    [
        (INDEX_WEEKLY, "2026-07-02", date(2026, 7, 2)),
        (INDEX_MONTHLY, "2026-07", date(2026, 7, 31)),
    ],
)
def test_calendar_defines_actual_period_end(tmp_path, period, key, end):
    with duckdb.connect() as connection:
        path = calendar(connection, tmp_path, closed=(date(2026, 7, 3),))
        assert index_period_end(connection, path, period, key) == end
        with pytest.raises(ValueError):
            index_period_end(
                connection,
                path,
                period,
                "2026-07-03" if period == INDEX_WEEKLY else "202607",
            )


@pytest.mark.parametrize("period", [INDEX_WEEKLY, INDEX_MONTHLY])
def test_source_probe_uses_one_full_component_unit(monkeypatch, period):
    calls, transports, _ = fake_source(monkeypatch, period)
    assert index_period_source_published(period, date(2026, 7, 3)) is True
    assert len(calls) == 1 and calls[0].fields == FIELDS
    assert transports[0].closed == 1
    calls, transports, _ = fake_source(monkeypatch, period, lambda *_: ())
    assert index_period_source_published(period, date(2026, 7, 3)) is False
    assert len(calls) == 1 and transports[0].closed == 1


@pytest.mark.parametrize("period", [INDEX_WEEKLY, INDEX_MONTHLY])
@pytest.mark.parametrize("layer,count", [("raw", 11), ("serving", 10)])
def test_prod_scope_projection_and_readonly_context(period, layer, count):
    sql, parameters = prod_index_period_query(period, layer)
    assert len(parameters[0]) == count
    assert ("000680.SH" in parameters[0]) == (layer == "raw")
    assert "WHERE ts_code = ANY(%s)" in sql and "SELECT *" not in sql
    assert all(
        name not in sql
        for name in (
            "api_name",
            "fetched_at",
            "raw_payload",
            "created_at",
            "updated_at",
        )
    )
    assert (
        "to_char(trade_date, 'YYYYMMDD')" in sql
        if layer == "raw"
        else '"period_start_date"' in sql
    )
    resource = Mock()
    cursor = Mock()

    @contextmanager
    def readonly():
        connection = Mock()
        connection.cursor.return_value.__enter__ = Mock(return_value=cursor)
        connection.cursor.return_value.__exit__ = Mock(return_value=False)
        yield connection

    resource.connect_readonly_transaction = readonly
    with open_prod_index_period_rows(resource, period=period, layer=layer) as observed:
        assert observed is cursor
    cursor.execute.assert_called_once_with(sql, parameters)
    resource.connect.assert_not_called()


def test_definitions_import_has_no_credentials_or_connections(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("定义导入不得创建下载器或读取凭据")

    monkeypatch.setattr(ConfigurationLoader, "load_configuration", forbidden)
    importlib.reload(assets)
    importlib.import_module("orchestrator.defs.jobs.index_period_update")
    assert not any(
        isinstance(value, dg.SensorDefinition) for value in vars(assets).values()
    )
    assert (
        raw_index_weekly_path(Path("/tmp/lake"))
        .as_posix()
        .endswith("raw/index_weekly/full/part-000.parquet")
    )
    assert (
        raw_index_monthly_path(Path("/tmp/lake"))
        .as_posix()
        .endswith("raw/index_monthly/full/part-000.parquet")
    )


@pytest.mark.parametrize("period", [INDEX_WEEKLY, INDEX_MONTHLY])
def test_real_http_encoder_parser_with_isolated_response(monkeypatch, period):
    # 只替换HTTP连接。运行现行RequestBuilder、HTTP编码/解析、分页及完整unit交付。
    payloads = []

    class Response(io.BytesIO):
        status = 200
        chunked = False

        def getheader(self, key):
            return None

        def isclosed(self):
            return self.closed

    class Connection:
        sock = None

        def __init__(self, *args, **kwargs):
            pass

        def request(self, method, path, *, body, headers):
            payloads.append(json.loads(body))

        def getresponse(self):
            return Response(
                (
                    '{"code":0,"data":{"fields":'
                    + json.dumps(FIELDS)
                    + ',"items":[["000680.SH","20260703",2338.1344,2350.4203,2565.1536,2302.9874,2343.6595,-5.5251,-0.0024,37226008500,2922268798699]]}}'
                ).encode()
            )

        def close(self):
            pass

    monkeypatch.setattr(http_transport.http.client, "HTTPConnection", Connection)
    monkeypatch.setattr(
        download_api.ConfigurationLoader,
        "load_configuration",
        lambda: ConfigurationSnapshot("isolated", "http://127.0.0.1:1"),
    )
    result = download_index_period_rows(
        period, date(2026, 7, 3), codes=("000680.SH",), required_codes=("000680.SH",)
    )
    assert result == [row("000680.SH", "20260703")]
    assert payloads[0]["api_name"] == period.dataset_id
    assert payloads[0]["fields"] == ",".join(FIELDS)
    assert payloads[0]["params"] == {
        "ts_code": "000680.SH",
        "trade_date": "20260703",
        "limit": 1000,
        "offset": 0,
    }


@pytest.mark.parametrize(
    "task",
    [
        DownloadTask("index_weekly", DownloadMode.SNAPSHOT),
        DownloadTask(
            "index_weekly",
            DownloadMode.BY_OBJECT_POINT,
            objects=EXPECTED_CODES,
            points=("2026-07",),
        ),
        DownloadTask(
            "index_weekly",
            DownloadMode.BY_OBJECT_POINT,
            objects=None,
            points=("2026-07-03",),
        ),
    ],
)
def test_reject_unbounded_or_wrong_time_before_source(task):
    from orchestrator.tushare_download import DownloadError

    downloader, calls, _, _ = build(definition=INDEX_WEEKLY_CONTRACT)
    with pytest.raises(DownloadError), downloader.download(task) as session:
        list(session)
    assert calls == []


@pytest.mark.parametrize(
    "period,partition",
    [(INDEX_WEEKLY, cn_a_index_week_ends), (INDEX_MONTHLY, cn_a_index_months)],
)
def test_silver_catalog_schema_and_dependencies(period, partition):
    from orchestrator.defs.bootstrap import index_period_history
    from orchestrator.defs.jobs import index_period_update

    entry = next(
        e
        for e in list_lake_asset_catalog_entries()
        if e.asset_key == period.silver_asset
    )
    asset = (
        assets.silver_index_weekly
        if period == INDEX_WEEKLY
        else assets.silver_index_monthly
    )
    spec = asset.get_asset_spec()
    assert asset.partitions_def == partition
    assert spec.metadata["goldenshare/source_system"] == "derived"
    assert (
        spec.metadata["goldenshare/data_contract"] == period.dataset_id + "_silver_v1"
    )
    assert (
        spec.metadata["goldenshare/path_template"]
        == entry.path_template
        == f"data_lake/silver/{period.dataset_id}/full/part-000.parquet"
    )
    expected_names = (
        "ts_code",
        "period_start_date",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "change_amount",
        "pct_chg",
        "vol",
        "amount",
    )
    expected_types = (
        "VARCHAR",
        "DATE",
        "DATE",
        *("DECIMAL(18,4)",) * 6,
        "DECIMAL(12,4)",
        "DECIMAL(20,6)",
        "DECIMAL(20,7)",
    )
    actual = spec.metadata["dagster/column_schema"].schema.columns
    assert tuple(c.name for c in actual) == expected_names
    assert tuple(c.type for c in actual) == expected_types
    assert tuple((c.name, c.type) for c in entry.column_schema) == tuple(
        zip(expected_names, expected_types, strict=True)
    )
    assert {dep.asset_key.to_user_string() for dep in spec.deps} == {
        "silver_index_daily",
        period.raw_asset,
        "silver_trade_calendar",
        "silver_index_basic",
    }
    assert entry.blocking_check_names == (period.silver_check,)
    assert all(c.blocking and c.partitions_def == partition for c in asset.check_specs)
    assert not any(
        isinstance(value, (dg.JobDefinition, dg.OpDefinition, dg.AssetsDefinition))
        for value in vars(index_period_history).values()
    )
    jobs = {
        value.name
        for value in vars(index_period_update).values()
        if isinstance(value, type(index_period_update.raw_index_weekly_update_job))
    }
    assert jobs == {
        "raw_index_weekly_update_job",
        "raw_index_monthly_update_job",
        "silver_index_weekly_update_job",
        "silver_index_monthly_update_job",
    }
