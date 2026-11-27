"""Phase A fixtures use the location table and the audited DG time positions."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from datetime import date, datetime, timezone
from pathlib import Path
import socket

import pytest

from goldenshare_technical_indicators import CalculationRequest
from goldenshare_technical_indicators.calculation.history import HistoryRequirement
from goldenshare_technical_indicators.calculation.indicators import create_builtin_registry
from goldenshare_technical_indicators.configuration.datasets import DATASET_LOCATIONS, MARKET_DATASETS
from goldenshare_technical_indicators.discovery import SourceCapability, describe_calculation, list_calculations
from goldenshare_technical_indicators.errors import ResourceLimitError, SourceUnsupportedError
from goldenshare_technical_indicators.request_parser import CalculationRequestParser, _build_read_requirement
from src.foundation.config.settings import Settings, technical_indicator_config_from_settings


ROOT = "/Volumes/datasource/data_lake"
DAY = datetime(2026, 11, 16, 16, tzinfo=timezone.utc)
MINUTE = datetime(2026, 11, 17, 1, 35, tzinfo=timezone.utc)
MA3 = {"calculation_id": "ma", "parameters": {"period": 3}}


def config(backend, locations=None):
    settings = Settings(_env_file=None, GOLDENSHARE_LAKE_ROOT=ROOT)
    return technical_indicator_config_from_settings(settings, data_location=backend, dataset_locations=locations)


def stock(period="day", **kwargs):
    return CalculationRequest(**(dict(
        security_type="stock", ts_code="600519.SH", period=period, adjustment="none",
        start=DAY, end=DAY, calculations=(MA3,),
    ) | kwargs))


def index(period="day", **kwargs):
    return CalculationRequest(**(dict(
        security_type="index", ts_code="000001.SH", period=period, adjustment="none",
        start=MINUTE, end=MINUTE, calculations=(MA3,),
    ) | kwargs))


def enable(*dataset_ids, backend):
    locations = deepcopy(DATASET_LOCATIONS)
    for dataset_id in dataset_ids:
        locations[dataset_id][backend]["enabled_adjustments"] = ["none"]
    return locations


@pytest.mark.parametrize("backend", ("dg", "prod_pg"))
def test_parser_and_discovery_share_backend_and_build_read_instruction(backend, monkeypatch):
    # 2026-11-17 daily contracts for 600519.SH and 000001.SH.
    cfg = config(backend, enable("stock_daily", "index_daily", backend=backend))
    registry = create_builtin_registry()
    parser = CalculationRequestParser(cfg, registry)
    history = HistoryRequirement(frozenset({"close"}), 2, 2, False, (), "MA3")

    def unexpected_io(*args, **kwargs):
        pytest.fail("The parser must not open a file or connection")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", unexpected_io)
        patch.setattr(socket.socket, "connect", unexpected_io)
        flags = describe_calculation(registry, "ma", config=cfg).source_capabilities
        assert flags == (
            SourceCapability("stock", "day", "none", "stock_daily"),
            SourceCapability("index", "day", "none", "index_daily"),
        )
        assert list_calculations(registry, config=cfg)
        daily = parser.parse(stock())
        index_daily = parser.parse(index())
        read_daily = _build_read_requirement(daily, history, batch_rows=cfg.batch_rows)
        read_index = _build_read_requirement(index_daily, history, batch_rows=cfg.batch_rows)
    assert {field.name for field in fields(read_daily)} == {
        "target", "ts_code", "period", "start", "end", "history", "batch_rows", "target_adjustment", "max_output_rows",
        "latest_rows", "include_source_facts", "require_current_period_end_date",
    }
    assert read_daily.max_output_rows is read_index.max_output_rows is None
    assert not read_daily.require_current_period_end_date and not read_index.require_current_period_end_date
    assert (read_daily.start, read_daily.end) == (date(2026, 11, 17), date(2026, 11, 17))
    assert (read_index.start, read_index.end) == (read_daily.start, read_daily.end)
    assert read_daily.history is history
    assert read_daily.batch_rows == 8192
    assert read_daily.target_adjustment == "none"
    # MA declares its internal window_mean dependency before the public node.
    assert [node.definition.calculation_id for node in daily.plan.nodes] == ["window_mean", "ma"]
    assert daily.plan.nodes[1].parameters == (("period", 3),)
    assert daily.plan.instances == ((0, 1),)
    assert daily.target.backend == index_daily.target.backend == backend
    if backend == "dg":
        assert daily.target.location == {
            "path_template": ROOT + "/silver/quote/stock_daily/trade_date={trade_date}/part-000.parquet",
        }
        assert index_daily.target.location == {
            "path_template": ROOT + "/silver/index_daily/trade_date={trade_date}/part-000.parquet",
        }
    else:
        assert daily.target.location == {"schema": "core_serving", "relation": "equity_daily_bar", "filters": {}}
        assert index_daily.target.location == {
            "schema": "core_serving", "relation": "index_daily_serving", "filters": {},
        }


def test_registered_locations_are_not_enabled_and_do_not_fall_back():
    registry = create_builtin_registry()
    locations = enable("stock_daily", "index_mins_90m", backend="dg")
    pg = config("prod_pg", locations)
    parser = CalculationRequestParser(pg, registry)
    assert not describe_calculation(registry, "ma", config=pg).source_supported
    for request in (stock(), index("90m")):
        with pytest.raises(SourceUnsupportedError):
            parser.parse(request)
    with pytest.raises(SourceUnsupportedError, match="not registered"):
        CalculationRequestParser(replace(pg, market_datasets={}), registry).parse(stock())
    dg = config("dg", locations)
    assert CalculationRequestParser(dg, registry).parse(index("90m")).target.backend == "dg"
    with pytest.raises(SourceUnsupportedError):
        CalculationRequestParser(dg, registry).parse(stock(adjustment="qfq"))
    assert all(not config_obj.enabled_adjustments(dataset_id)
               for config_obj in (config("dg"), config("prod_pg"))
               for dataset_id in MARKET_DATASETS.values())


def test_mapping_snapshots_and_physical_filter_types():
    locations = enable("stock_mins_5m", backend="prod_pg")
    selected = config("prod_pg", locations)
    locations["stock_mins_5m"]["prod_pg"]["enabled_adjustments"].clear()
    locations["stock_mins_5m"]["prod_pg"]["filters"]["freq"] = "5min"
    target = selected.resolve_dataset_location("stock_mins_5m")
    assert target.location["filters"] == {"freq": 5}
    assert selected.enabled_adjustments("stock_mins_5m") == {"none"}
    assert selected.resolve_dataset_location("stock_weekly").location["filters"] == {"freq": "week"}
    assert selected.resolve_dataset_location("stock_monthly").location["filters"] == {"freq": "month"}
    assert config("dg").resolve_dataset_location("index_weekly").location["path_template"].endswith(
        "/silver/index_weekly/full/part-000.parquet",
    )
    with pytest.raises(TypeError):
        target.location["filters"]["freq"] = "5min"
    with pytest.raises(FrozenInstanceError):
        target.backend = "dg"


@pytest.mark.parametrize("location", [
    {"relative_path": "../escape.parquet"},
    {"relative_path": "/absolute/file.parquet"},
    {"relative_path": "silver/{trade_date.__class__}/file.parquet"},
    {"relative_path": "silver/{freq}/file.parquet"},
    {"relative_path": "silver/{freq}/file.parquet", "partitions": {"freq": ".."}},
])
def test_invalid_dg_location_is_rejected_without_resolution(location):
    with pytest.raises(ValueError):
        config("dg", {"stock_daily": {"dg": location, "prod_pg": None}})


def test_environment_and_config_validation_do_not_guess():
    settings = Settings(_env_file=None, APP_ENV="dev")
    with pytest.raises(TypeError):
        technical_indicator_config_from_settings(settings)
    with pytest.raises(ValueError, match="data_location"):
        config("dev")
    with pytest.raises(ValueError, match="absolute"):
        replace(config("dg"), goldenshare_lake_root="")
    with pytest.raises(ValueError, match="market dataset"):
        replace(config("prod_pg"), market_datasets={("stock", "day"): "absent"})
    locations = deepcopy(DATASET_LOCATIONS)
    locations["index_daily"]["prod_pg"]["relation"] = "index_daily_serving; drop table"
    with pytest.raises(ValueError, match="schema and relation"):
        config("prod_pg", locations)
    locations = enable("index_daily", backend="prod_pg")
    locations["index_daily"]["prod_pg"]["enabled_adjustments"] = ("qfq",)
    with pytest.raises(ValueError, match="Adjustment is unsupported"):
        config("prod_pg", locations)


def test_stage_a_enforces_item_limit_and_leaves_target_count_to_reader():
    cfg = replace(config("dg", enable("stock_daily", backend="dg")), max_indicator_instances=2, max_output_rows=1)
    parser = CalculationRequestParser(cfg, create_builtin_registry())
    request = stock(end=datetime(2026, 11, 18, tzinfo=timezone.utc), calculations=(MA3, MA3))
    assert parser.parse(request).plan.instances == ((0, 1), (1, 1))
    with pytest.raises(ResourceLimitError, match="max_indicator_instances"):
        parser.parse(replace(request, calculations=(MA3, MA3, MA3)))


def test_latest_rows_uses_enabled_dg_datasets_and_the_configured_limit():
    registry = create_builtin_registry()
    locations = enable("stock_daily", "index_daily", "index_weekly", "index_monthly", backend="dg")
    cfg = replace(config("dg", locations), max_output_rows=2)
    parser = CalculationRequestParser(cfg, registry)
    request = stock(start=None, latest_rows=2)
    history = HistoryRequirement(frozenset({"close"}), 2, 2, False, (), "MA3")
    read = _build_read_requirement(parser.parse(request), history, batch_rows=cfg.batch_rows)
    assert (read.start, read.end, read.latest_rows, read.output_limit(cfg)) == (
        None, date(2026, 11, 17), 2, 2,
    )
    assert parser.parse(index(period="day", start=None, latest_rows=2)).target.dataset_id == "index_daily"
    assert parser.parse(index(period="week", start=None, latest_rows=2)).target.dataset_id == "index_weekly"
    assert parser.parse(index(period="month", start=None, latest_rows=2)).target.dataset_id == "index_monthly"
    with pytest.raises(ResourceLimitError, match="max_output_rows"):
        parser.parse(replace(request, latest_rows=3))
    prod = CalculationRequestParser(config("prod_pg", enable("stock_daily", backend="prod_pg")), registry)
    with pytest.raises(SourceUnsupportedError, match="selected DG market datasets"):
        prod.parse(request)
