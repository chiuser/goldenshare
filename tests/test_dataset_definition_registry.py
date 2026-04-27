from __future__ import annotations

import inspect
from dataclasses import MISSING, fields

from src.foundation.datasets.definitions import ALL_DATASET_ROWS
import src.foundation.datasets.definitions._builder as definition_builder
from src.foundation.datasets.models import DatasetSourceDefinition, DatasetStorageDefinition, DatasetTransactionDefinition
from src.foundation.datasets.registry import get_dataset_definition, list_dataset_definitions
from src.foundation.ingestion.runtime_registry import DATASET_RUNTIME_REGISTRY
import src.ops.dataset_definition_projection as dataset_definition_projection


def test_dataset_definition_registry_is_not_runtime_contract_projection() -> None:
    import inspect

    import src.foundation.datasets.registry as registry

    assert not hasattr(registry, "_from_contract")
    assert "services.sync" not in inspect.getsource(registry)


def test_dataset_definition_registry_covers_runtime_registry() -> None:
    definition_keys = {definition.dataset_key for definition in list_dataset_definitions()}
    runtime_keys = set(DATASET_RUNTIME_REGISTRY)

    assert definition_keys == runtime_keys
    assert len(definition_keys) == 57


def test_dataset_definition_projects_core_dataset_facts() -> None:
    definition = get_dataset_definition("dc_hot")

    assert definition.identity.display_name == "东方财富热榜"
    assert definition.source.api_name == "dc_hot"
    assert definition.date_model.input_shape == "trade_date_or_start_end"
    assert definition.storage.raw_table == "raw_tushare.dc_hot"
    assert definition.storage.target_table == "core_serving.dc_hot"
    assert definition.capabilities.get_action("maintain") is not None
    assert definition.planning.enum_fanout_defaults["hot_type"] == ("人气榜", "飙升榜")


def test_dataset_definition_owns_dc_board_type_filter() -> None:
    definition = get_dataset_definition("dc_member")
    idx_type = next(field for field in definition.input_model.filters if field.name == "idx_type")

    assert idx_type.display_name == "板块类型"
    assert idx_type.field_type == "list"
    assert idx_type.multi_value is True
    assert idx_type.enum_values == ("行业板块", "概念板块", "地域板块")


def test_dataset_definition_identity_does_not_keep_legacy_job_aliases() -> None:
    legacy_prefixes = ("sync_", "back" + "fill_")
    for definition in list_dataset_definitions():
        assert not any(alias.startswith(legacy_prefixes) for alias in definition.identity.aliases)


def test_dataset_definition_owns_logical_dataset_grouping() -> None:
    moneyflow = get_dataset_definition("moneyflow")
    biying_moneyflow = get_dataset_definition("biying_moneyflow")
    biying_equity_daily = get_dataset_definition("biying_equity_daily")

    assert moneyflow.logical_key == "moneyflow"
    assert moneyflow.logical_priority == 100
    assert biying_moneyflow.logical_key == "moneyflow"
    assert biying_moneyflow.logical_priority == 200
    assert biying_equity_daily.logical_key == "biying_equity_daily"


def test_dataset_definition_storage_raw_table_is_explicit_fact() -> None:
    missing = [
        row["identity"]["dataset_key"]
        for row in ALL_DATASET_ROWS
        if not str(row["storage"].get("raw_table") or "").strip()
    ]

    assert not missing
    assert get_dataset_definition("biying_equity_daily").storage.raw_table == "raw_biying.equity_daily"
    assert get_dataset_definition("limit_list_d").storage.raw_table == "raw_tushare.limit_list"
    assert get_dataset_definition("stk_holdernumber").storage.raw_table == "raw_tushare.holdernumber"
    assert get_dataset_definition("stk_period_bar_week").storage.raw_table == "raw_tushare.stk_period_bar"
    assert get_dataset_definition("stk_period_bar_adj_month").storage.raw_table == "raw_tushare.stk_period_bar_adj"


def test_dataset_definition_storage_layer_facts_are_explicit() -> None:
    missing_delivery_mode = [
        row["identity"]["dataset_key"]
        for row in ALL_DATASET_ROWS
        if not str(row["storage"].get("delivery_mode") or "").strip()
    ]
    missing_layer_plan = [
        row["identity"]["dataset_key"]
        for row in ALL_DATASET_ROWS
        if not str(row["storage"].get("layer_plan") or "").strip()
    ]
    missing_std_table = [
        row["identity"]["dataset_key"]
        for row in ALL_DATASET_ROWS
        if "std_table" not in row["storage"]
    ]
    missing_serving_table = [
        row["identity"]["dataset_key"]
        for row in ALL_DATASET_ROWS
        if "serving_table" not in row["storage"]
    ]

    assert not missing_delivery_mode
    assert not missing_layer_plan
    assert not missing_std_table
    assert not missing_serving_table
    assert get_dataset_definition("daily").storage.delivery_mode == "single_source_serving"
    assert get_dataset_definition("stock_basic").storage.delivery_mode == "multi_source_fusion"
    assert get_dataset_definition("stock_basic").storage.std_table == "core_multi.security_std"
    assert get_dataset_definition("daily").storage.serving_table == "core_serving.equity_daily_bar"
    assert get_dataset_definition("stk_mins").storage.layer_plan == "raw-only"
    assert get_dataset_definition("stk_mins").storage.serving_table is None


def test_dataset_definition_source_keys_are_explicit_fact() -> None:
    missing = [
        row["identity"]["dataset_key"]
        for row in ALL_DATASET_ROWS
        if not row["source"].get("source_keys")
    ]

    assert not missing
    assert get_dataset_definition("daily").source.source_keys == ("tushare",)
    assert get_dataset_definition("biying_equity_daily").source.source_keys == ("biying",)
    assert get_dataset_definition("stock_basic").source.source_keys == ("biying", "tushare")


def test_dataset_definition_builder_does_not_infer_storage_raw_table() -> None:
    builder_source = inspect.getsource(definition_builder)
    projection_source = inspect.getsource(dataset_definition_projection)

    assert not hasattr(definition_builder, "_infer_raw_table")
    assert "setdefault(\"raw_table\"" not in builder_source
    assert "startswith(\"biying_\")" not in builder_source
    assert "_delivery_mode_from_definition" not in projection_source
    assert "_layer_plan(" not in projection_source
    assert "_std_table_hint" not in projection_source
    assert "_serving_table" not in projection_source
    raw_table_field = next(item for item in fields(DatasetStorageDefinition) if item.name == "raw_table")
    assert raw_table_field.default is MISSING
    delivery_mode_field = next(item for item in fields(DatasetStorageDefinition) if item.name == "delivery_mode")
    layer_plan_field = next(item for item in fields(DatasetStorageDefinition) if item.name == "layer_plan")
    std_table_field = next(item for item in fields(DatasetStorageDefinition) if item.name == "std_table")
    serving_table_field = next(item for item in fields(DatasetStorageDefinition) if item.name == "serving_table")
    assert delivery_mode_field.default is MISSING
    assert layer_plan_field.default is MISSING
    assert std_table_field.default is MISSING
    assert serving_table_field.default is MISSING


def test_dataset_definition_builder_does_not_infer_source_keys() -> None:
    builder_source = inspect.getsource(definition_builder)
    projection_source = inspect.getsource(dataset_definition_projection)

    assert "source_key_default.lower())" not in builder_source
    assert "field.name != \"source_key\"" not in projection_source
    assert "_source_keys_from_definition" not in projection_source
    source_keys_field = next(item for item in fields(DatasetSourceDefinition) if item.name == "source_keys")
    assert source_keys_field.default is MISSING


def test_dataset_definition_transaction_policy_is_explicit_fact() -> None:
    missing_transaction = [
        row["identity"]["dataset_key"]
        for row in ALL_DATASET_ROWS
        if "transaction" not in row
    ]
    missing_commit_policy = [
        row["identity"]["dataset_key"]
        for row in ALL_DATASET_ROWS
        if "transaction" in row and "commit_policy" not in row["transaction"]
    ]

    assert not missing_transaction
    assert not missing_commit_policy
    assert "row.get(\"transaction\", {})" not in inspect.getsource(definition_builder)
    commit_policy_field = next(item for item in fields(DatasetTransactionDefinition) if item.name == "commit_policy")
    assert commit_policy_field.default is MISSING
    assert {definition.transaction.commit_policy for definition in list_dataset_definitions()} == {"unit"}
