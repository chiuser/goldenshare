from __future__ import annotations

import inspect
from dataclasses import MISSING, fields

from src.foundation.datasets.definitions import ALL_DATASET_ROWS
import src.foundation.datasets.definitions._builder as definition_builder
from src.foundation.datasets.freshness_policies import FRESHNESS_POLICY_BY_DATASET
from src.foundation.datasets.models import DatasetSourceDefinition, DatasetStorageDefinition, DatasetTransactionDefinition
from src.foundation.datasets.registry import get_dataset_definition, list_dataset_definitions
from src.foundation.config.settings import get_settings
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
    assert len(definition_keys) == 72


def test_dataset_definition_registry_covers_freshness_policy_mapping() -> None:
    definition_keys = {definition.dataset_key for definition in list_dataset_definitions()}

    assert definition_keys == set(FRESHNESS_POLICY_BY_DATASET)
    for definition in list_dataset_definitions():
        assert definition.observability.freshness_policy == FRESHNESS_POLICY_BY_DATASET[definition.dataset_key]


def test_dataset_definition_projects_core_dataset_facts() -> None:
    definition = get_dataset_definition("dc_hot")

    assert definition.identity.display_name == "东方财富热榜"
    assert definition.source.api_name == "dc_hot"
    assert definition.date_model.input_shape == "trade_date_or_start_end"
    assert definition.storage.raw_table == "raw_tushare.dc_hot"
    assert definition.storage.target_table == "core_serving.dc_hot"
    assert definition.capabilities.get_action("maintain") is not None
    assert definition.planning.enum_fanout_defaults["hot_type"] == ("人气榜", "飙升榜")


def test_dataset_definition_projects_ths_daily_valuation_fields() -> None:
    definition = get_dataset_definition("ths_daily")

    assert {"pe_ttm", "pb_mrq"}.issubset(set(definition.source.source_fields))
    assert {"pe_ttm", "pb_mrq"}.issubset(set(definition.normalization.decimal_fields))
    assert definition.normalization.required_fields == ("trade_date", "ts_code")
    assert definition.storage.conflict_columns is None
    assert definition.storage.raw_table == "raw_tushare.ths_daily"
    assert definition.storage.target_table == "core_serving.ths_daily"


def test_dataset_definition_projects_adj_factor_subject_completeness_facts() -> None:
    definition = get_dataset_definition("adj_factor")

    assert definition.completeness.scope == "date_subject_matrix"
    assert definition.completeness.subject_kind == "stock"
    assert definition.completeness.subject_key_fields == ("ts_code",)
    assert definition.completeness.actual_key_fields == ("ts_code",)
    assert definition.completeness.universe_strategy == "stock_basic_active_lifecycle"
    assert definition.completeness.universe_source_table == "core_serving.security_serving"
    assert definition.completeness.universe_key_field == "ts_code"
    assert definition.completeness.universe_name_field == "name"
    assert definition.completeness.lifecycle_start_field == "list_date"
    assert definition.completeness.lifecycle_end_field == "delist_date"
    assert definition.completeness.status_field == "list_status"
    assert definition.completeness.active_status_values == ("L",)


def test_dataset_definition_subject_matrix_scope_is_not_inferred_from_ts_code() -> None:
    matrix_keys = {
        definition.dataset_key
        for definition in list_dataset_definitions()
        if definition.completeness.scope == "date_subject_matrix"
    }

    assert matrix_keys == {"adj_factor"}
    for definition in list_dataset_definitions():
        if not definition.date_model.audit_applicable:
            assert definition.completeness.scope == "not_applicable"


def test_event_datasets_do_not_use_subject_matrix_completeness() -> None:
    event_dataset_keys = {
        "block_trade",
        "broker_recommend",
        "dc_hot",
        "kpl_list",
        "limit_cpt_list",
        "limit_list_d",
        "limit_list_ths",
        "limit_step",
        "stock_st",
        "suspend_d",
        "ths_hot",
        "top_list",
    }

    for dataset_key in event_dataset_keys:
        assert get_dataset_definition(dataset_key).completeness.scope != "date_subject_matrix"


def test_dataset_definition_projects_stock_auction_facts() -> None:
    open_definition = get_dataset_definition("stk_auction_o")
    close_definition = get_dataset_definition("stk_auction_c")

    assert open_definition.identity.display_name == "股票开盘集合竞价"
    assert close_definition.identity.display_name == "股票收盘集合竞价"
    for definition in (open_definition, close_definition):
        assert definition.domain.domain_key == "equity_market"
        assert definition.source.source_fields == (
            "ts_code",
            "trade_date",
            "close",
            "open",
            "high",
            "low",
            "vol",
            "amount",
            "vwap",
        )
        assert definition.date_model.date_axis == "trade_open_day"
        assert definition.date_model.bucket_rule == "every_open_day"
        assert definition.date_model.input_shape == "trade_date_or_start_end"
        assert definition.date_model.audit_applicable is True
        assert definition.planning.universe_policy == "no_pool"
        assert definition.planning.pagination_policy == "offset_limit"
        assert definition.planning.page_limit == 10000
        assert definition.planning.unit_builder_key == "generic"
        assert definition.observability.freshness_policy == "continuous_open_day"
        assert definition.capabilities.get_action("maintain").supported_time_modes == ("point", "range")

    assert open_definition.source.api_name == "stk_auction_o"
    assert open_definition.source.request_builder_key == "_stk_auction_o_params"
    assert open_definition.storage.raw_table == "raw_tushare.stk_auction_o"
    assert open_definition.storage.target_table == "core_serving.equity_auction_open"
    assert close_definition.source.api_name == "stk_auction_c"
    assert close_definition.source.request_builder_key == "_stk_auction_c_params"
    assert close_definition.storage.raw_table == "raw_tushare.stk_auction_c"
    assert close_definition.storage.target_table == "core_serving.equity_auction_close"


def test_us_hot_markets_are_disabled_by_default(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("GOLDENSHARE_ENV_FILE", str(env_file))
    get_settings.cache_clear()
    list_dataset_definitions.cache_clear()
    try:
        dc_hot = get_dataset_definition("dc_hot")
        ths_hot = get_dataset_definition("ths_hot")

        dc_market = next(field for field in dc_hot.input_model.filters if field.name == "market")
        ths_market = next(field for field in ths_hot.input_model.filters if field.name == "market")
        assert "美股市场" not in dc_market.enum_values
        assert "美股市场" not in dc_hot.planning.enum_fanout_defaults["market"]
        assert "美股" not in ths_market.enum_values
        assert "美股" not in ths_hot.planning.enum_fanout_defaults["market"]
    finally:
        get_settings.cache_clear()
        list_dataset_definitions.cache_clear()


def test_us_hot_markets_can_be_enabled_by_env(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("TUSHARE_ENABLE_US_HOT_MARKETS=true\n", encoding="utf-8")
    monkeypatch.setenv("GOLDENSHARE_ENV_FILE", str(env_file))
    get_settings.cache_clear()
    list_dataset_definitions.cache_clear()
    try:
        dc_hot = get_dataset_definition("dc_hot")
        ths_hot = get_dataset_definition("ths_hot")

        dc_market = next(field for field in dc_hot.input_model.filters if field.name == "market")
        ths_market = next(field for field in ths_hot.input_model.filters if field.name == "market")
        assert "美股市场" in dc_market.enum_values
        assert "美股市场" in dc_hot.planning.enum_fanout_defaults["market"]
        assert "美股" in ths_market.enum_values
        assert "美股" in ths_hot.planning.enum_fanout_defaults["market"]
    finally:
        get_settings.cache_clear()
        list_dataset_definitions.cache_clear()


def test_top_list_definition_uses_split_raw_and_serving_conflict_keys() -> None:
    definition = get_dataset_definition("top_list")

    assert definition.storage.target_table == "core_serving.equity_top_list"
    assert definition.storage.raw_conflict_columns == ("ts_code", "trade_date", "reason", "payload_hash")
    assert definition.storage.conflict_columns == ("ts_code", "trade_date", "reason_hash")
    assert definition.storage.serving_conflict_resolution_policy == "top_list_variant_resolution_v1"


def test_index_weight_declares_minimal_universe_pool() -> None:
    definition = get_dataset_definition("index_weight")

    assert definition.planning.universe_policy == "pool"
    assert definition.planning.universe is not None
    assert definition.planning.universe.request_field == "index_code"
    assert definition.planning.universe.override_fields == ("index_code",)
    assert [(source.type, source.resource) for source in definition.planning.universe.sources] == [
        ("ops_index_series_active", "index_weight"),
        ("core_index_basic_active", None),
    ]


def test_stk_period_bar_definitions_use_calendar_source_anchors() -> None:
    weekly = get_dataset_definition("stk_period_bar_week")
    monthly = get_dataset_definition("stk_period_bar_month")
    adj_weekly = get_dataset_definition("stk_period_bar_adj_week")
    adj_monthly = get_dataset_definition("stk_period_bar_adj_month")
    index_weekly = get_dataset_definition("index_weekly")
    index_monthly = get_dataset_definition("index_monthly")

    assert weekly.date_model.date_axis == "natural_day"
    assert weekly.date_model.bucket_rule == "week_friday"
    assert weekly.date_model.selection_rule() == "week_friday"
    assert weekly.date_model.bucket_window_rule == "iso_week"
    assert weekly.date_model.bucket_applicability_rule == "requires_open_trade_day_in_bucket"
    assert weekly.storage.row_identity_filters == {"freq": "week"}
    assert adj_weekly.date_model.date_axis == "natural_day"
    assert adj_weekly.date_model.bucket_rule == "week_friday"
    assert adj_weekly.date_model.bucket_window_rule == "iso_week"
    assert adj_weekly.date_model.bucket_applicability_rule == "requires_open_trade_day_in_bucket"
    assert adj_weekly.storage.row_identity_filters == {"freq": "week"}
    assert monthly.date_model.date_axis == "natural_day"
    assert monthly.date_model.bucket_rule == "month_last_calendar_day"
    assert monthly.date_model.selection_rule() == "month_end"
    assert monthly.date_model.bucket_window_rule == "natural_month"
    assert monthly.date_model.bucket_applicability_rule == "requires_open_trade_day_in_bucket"
    assert monthly.storage.row_identity_filters == {"freq": "month"}
    assert adj_monthly.date_model.date_axis == "natural_day"
    assert adj_monthly.date_model.bucket_rule == "month_last_calendar_day"
    assert adj_monthly.date_model.bucket_window_rule == "natural_month"
    assert adj_monthly.date_model.bucket_applicability_rule == "requires_open_trade_day_in_bucket"
    assert adj_monthly.storage.row_identity_filters == {"freq": "month"}
    assert index_weekly.date_model.bucket_rule == "week_last_open_day"
    assert index_weekly.date_model.bucket_applicability_rule == "always"
    assert index_monthly.date_model.bucket_rule == "month_last_open_day"
    assert index_monthly.date_model.bucket_applicability_rule == "always"


def test_no_time_dataset_definitions_do_not_expose_time_inputs() -> None:
    no_time_definitions = [
        definition
        for definition in list_dataset_definitions()
        if definition.date_model.input_shape == "none"
    ]

    assert {definition.dataset_key for definition in no_time_definitions} == {
        "bse_mapping",
        "etf_basic",
        "etf_index",
        "hk_basic",
        "index_basic",
        "namechange",
        "st",
        "stock_basic",
        "stock_company",
        "ths_index",
        "ths_member",
        "us_basic",
    }
    for definition in no_time_definitions:
        action = definition.capabilities.get_action("maintain")

        assert definition.date_model.date_axis == "none"
        assert definition.date_model.window_mode == "none"
        assert definition.input_model.time_fields == ()
        assert action is not None
        assert action.supported_time_modes == ("none",)


def test_dataset_definition_projects_cctv_news_facts() -> None:
    definition = get_dataset_definition("cctv_news")

    assert definition.identity.display_name == "新闻联播文字稿"
    assert definition.domain.domain_key == "news"
    assert definition.domain.domain_display_name == "新闻资讯"
    assert definition.source.api_name == "cctv_news"
    assert definition.date_model.input_shape == "trade_date_or_start_end"
    assert definition.date_model.observed_field == "date"
    assert definition.storage.raw_table == "raw_tushare.cctv_news"
    assert definition.storage.target_table == "core_serving_light.cctv_news"
    assert definition.storage.delivery_mode == "raw_with_serving_light_view"
    assert definition.planning.pagination_policy == "offset_limit"
    assert definition.planning.page_limit == 400


def test_dataset_definition_projects_major_news_facts() -> None:
    definition = get_dataset_definition("major_news")

    assert definition.identity.display_name == "新闻通讯"
    assert definition.domain.domain_key == "news"
    assert definition.domain.domain_display_name == "新闻资讯"
    assert definition.source.api_name == "major_news"
    assert definition.source.source_fields == ("title", "content", "pub_time", "src", "url")
    assert definition.date_model.input_shape == "trade_date_or_start_end"
    assert definition.date_model.observed_field == "pub_time"
    assert definition.date_model.audit_applicable is False
    assert definition.storage.raw_table == "raw_tushare.major_news"
    assert definition.storage.target_table == "core_serving_light.major_news"
    assert definition.storage.delivery_mode == "raw_with_serving_light_view"
    assert definition.planning.enum_fanout_fields == ("src",)
    assert definition.planning.enum_fanout_defaults["src"] == (
        "新华网",
        "凤凰财经",
        "同花顺",
        "新浪财经",
        "华尔街见闻",
        "中证网",
        "财新网",
        "第一财经",
        "财联社",
    )
    assert definition.planning.pagination_policy == "offset_limit"
    assert definition.planning.page_limit == 400
    assert definition.normalization.date_fields == ()
    assert definition.normalization.required_fields == ("src", "pub_time", "row_key_hash")
    assert definition.quality.required_fields == ("src", "pub_time", "row_key_hash")


def test_dataset_definition_projects_news_facts() -> None:
    definition = get_dataset_definition("news")

    assert definition.identity.display_name == "新闻快讯"
    assert definition.domain.domain_key == "news"
    assert definition.domain.domain_display_name == "新闻资讯"
    assert definition.source.api_name == "news"
    assert definition.source.source_fields == ("datetime", "content", "title", "channels", "score")
    assert definition.date_model.input_shape == "trade_date_or_start_end"
    assert definition.date_model.observed_field == "news_time"
    assert definition.date_model.audit_applicable is False
    assert definition.storage.raw_table == "raw_tushare.news"
    assert definition.storage.target_table == "core_serving_light.news"
    assert definition.storage.delivery_mode == "raw_with_serving_light_view"
    assert definition.planning.universe_policy == "no_pool"
    assert definition.planning.enum_fanout_fields == ("src",)
    assert definition.planning.enum_fanout_defaults["src"] == (
        "sina",
        "wallstreetcn",
        "10jqka",
        "eastmoney",
        "yuncaijing",
        "fenghuang",
        "jinrongjie",
        "cls",
        "yicai",
    )
    assert definition.planning.pagination_policy == "offset_limit"
    assert definition.planning.page_limit == 1500
    assert definition.normalization.date_fields == ()
    assert definition.normalization.required_fields == ("src", "news_time", "row_key_hash")
    assert definition.quality.required_fields == ("src", "news_time", "row_key_hash")


def test_dataset_definition_projects_anns_d_facts() -> None:
    definition = get_dataset_definition("anns_d")

    assert definition.identity.display_name == "上市公司公告"
    assert definition.domain.domain_key == "news"
    assert definition.source.api_name == "anns_d"
    assert definition.source.source_fields == ("ann_date", "ts_code", "name", "title", "url", "rec_time")
    assert definition.date_model.input_shape == "trade_date_or_start_end"
    assert definition.date_model.bucket_rule == "not_applicable"
    assert definition.date_model.observed_field == "ann_date"
    assert definition.date_model.audit_applicable is False
    assert definition.storage.raw_table == "raw_tushare.anns_d"
    assert definition.storage.target_table == "core_serving_light.anns_d"
    assert definition.storage.delivery_mode == "raw_with_serving_light_view"
    assert definition.planning.unit_builder_key == "generic"
    assert definition.planning.page_limit == 2000
    assert definition.normalization.date_fields == ("ann_date",)
    assert definition.normalization.required_fields == ("ann_date", "ts_code", "title", "url", "rec_time", "row_key_hash")


def test_dataset_definition_projects_irm_qa_facts() -> None:
    sh = get_dataset_definition("irm_qa_sh")
    sz = get_dataset_definition("irm_qa_sz")

    assert sh.identity.display_name == "上证E互动问答"
    assert sh.domain.domain_key == "news"
    assert sh.source.api_name == "irm_qa_sh"
    assert sh.source.source_fields == ("ts_code", "name", "trade_date", "q", "a", "pub_time")
    assert sh.date_model.input_shape == "trade_date_or_start_end"
    assert sh.date_model.bucket_rule == "not_applicable"
    assert sh.date_model.observed_field == "pub_time"
    assert sh.storage.raw_table == "raw_tushare.irm_qa_sh"
    assert sh.storage.target_table == "core_serving_light.irm_qa_sh"
    assert sh.planning.unit_builder_key == "generic"
    assert sh.planning.page_limit == 3000
    assert sh.normalization.date_fields == ("trade_date",)
    assert sh.normalization.required_fields == ("ts_code", "trade_date", "q", "a", "row_key_hash")

    assert sz.identity.display_name == "深证互动易问答"
    assert sz.domain.domain_key == "news"
    assert sz.source.api_name == "irm_qa_sz"
    assert sz.source.source_fields == ("ts_code", "name", "trade_date", "q", "a", "pub_time", "industry")
    assert sz.date_model.input_shape == "trade_date_or_start_end"
    assert sz.date_model.bucket_rule == "not_applicable"
    assert sz.storage.raw_table == "raw_tushare.irm_qa_sz"
    assert sz.storage.target_table == "core_serving_light.irm_qa_sz"
    assert sz.planning.unit_builder_key == "generic"
    assert sz.planning.page_limit == 3000
    assert sz.normalization.date_fields == ("trade_date",)
    assert sz.normalization.required_fields == ("ts_code", "trade_date", "q", "a", "row_key_hash")


def test_dataset_definition_projects_research_report_facts() -> None:
    definition = get_dataset_definition("research_report")

    assert definition.identity.display_name == "券商研究报告"
    assert definition.domain.domain_key == "equity_market"
    assert definition.source.api_name == "research_report"
    assert definition.source.source_fields == (
        "trade_date",
        "abstr",
        "title",
        "report_type",
        "author",
        "name",
        "ts_code",
        "inst_csname",
        "ind_name",
        "url",
        "report_code",
    )
    assert definition.date_model.input_shape == "trade_date_or_start_end"
    assert definition.date_model.bucket_rule == "not_applicable"
    assert definition.date_model.observed_field == "trade_date"
    assert definition.date_model.audit_applicable is False
    assert definition.storage.raw_table == "raw_tushare.research_report"
    assert definition.storage.target_table == "core_serving_light.research_report"
    assert definition.storage.delivery_mode == "raw_with_serving_light_view"
    assert definition.storage.conflict_columns == ("row_key_hash",)
    assert definition.planning.enum_fanout_fields == ("report_type",)
    assert definition.planning.enum_fanout_defaults == {}
    assert definition.planning.page_limit == 1000
    report_type = next(field for field in definition.input_model.filters if field.name == "report_type")
    assert report_type.field_type == "list"
    assert report_type.multi_value is True
    assert report_type.enum_values == ("个股研报", "行业研报")
    assert definition.normalization.date_fields == ("trade_date",)
    assert definition.normalization.required_fields == ("url", "row_key_hash")


def test_dataset_definition_projects_bse_mapping_facts() -> None:
    definition = get_dataset_definition("bse_mapping")

    assert definition.identity.display_name == "北交所新旧代码对照"
    assert definition.domain.domain_key == "reference_data"
    assert definition.source.api_name == "bse_mapping"
    assert definition.date_model.input_shape == "none"
    assert definition.storage.raw_table == "raw_tushare.bse_mapping"
    assert definition.storage.target_table == "core_serving_light.bse_mapping"
    assert definition.storage.delivery_mode == "raw_with_serving_light_view"
    assert definition.planning.page_limit == 1000
    assert definition.normalization.date_fields == ("list_date",)
    assert definition.normalization.required_fields == ("o_code", "n_code")


def test_dataset_definition_projects_bak_basic_facts() -> None:
    definition = get_dataset_definition("bak_basic")

    assert definition.identity.display_name == "股票历史基础列表"
    assert definition.domain.domain_key == "reference_data"
    assert definition.observability.freshness_policy == "continuous_open_day"
    assert definition.source.api_name == "bak_basic"
    assert definition.date_model.input_shape == "trade_date_or_start_end"
    assert definition.date_model.observed_field == "trade_date"
    assert definition.storage.raw_table == "raw_tushare.bak_basic"
    assert definition.storage.target_table == "core_serving_light.bak_basic"
    assert definition.storage.delivery_mode == "raw_with_serving_light_view"
    assert definition.planning.page_limit == 7000
    assert definition.planning.unit_builder_key == "generic"
    assert definition.normalization.date_fields == ("trade_date", "list_date")
    assert definition.normalization.required_fields == ("trade_date", "ts_code")


def test_dataset_definition_projects_dc_daily_category_identity() -> None:
    definition = get_dataset_definition("dc_daily")

    assert "category" in definition.source.source_fields
    assert definition.storage.conflict_columns == ("ts_code", "trade_date", "category")
    assert definition.normalization.required_fields == ("trade_date", "ts_code", "category")
    assert definition.quality.required_fields == ("trade_date", "ts_code", "category")


def test_dataset_definition_projects_stock_company_facts() -> None:
    definition = get_dataset_definition("stock_company")

    assert definition.identity.display_name == "上市公司基本信息"
    assert definition.domain.domain_key == "reference_data"
    assert definition.source.api_name == "stock_company"
    assert definition.date_model.input_shape == "none"
    assert definition.storage.raw_table == "raw_tushare.stock_company"
    assert definition.storage.target_table == "core_serving_light.stock_company"
    assert definition.storage.delivery_mode == "raw_with_serving_light_view"
    assert definition.planning.page_limit == 4500
    assert definition.planning.enum_fanout_defaults["exchange"] == ("SSE", "SZSE", "BSE")
    assert definition.normalization.date_fields == ("setup_date", "ann_date")
    assert definition.normalization.required_fields == ("ts_code", "exchange")


def test_dataset_definition_projects_namechange_facts() -> None:
    definition = get_dataset_definition("namechange")

    assert definition.identity.display_name == "股票曾用名"
    assert definition.domain.domain_key == "reference_data"
    assert definition.observability.freshness_policy == "snapshot_run_trace"
    assert definition.source.api_name == "namechange"
    assert definition.date_model.bucket_rule == "not_applicable"
    assert definition.date_model.selection_rule() == "none"
    assert definition.date_model.input_shape == "none"
    assert definition.date_model.window_mode == "none"
    assert definition.date_model.observed_field is None
    assert definition.storage.raw_table == "raw_tushare.namechange"
    assert definition.storage.target_table == "core_serving_light.namechange"
    assert definition.storage.delivery_mode == "raw_with_serving_light_view"
    assert definition.planning.page_limit == 1000
    assert definition.planning.unit_builder_key == "generic"
    assert definition.normalization.date_fields == ("start_date", "end_date", "ann_date")
    assert definition.normalization.required_fields == ("ts_code", "name", "start_date", "row_key_hash")
    action = definition.capabilities.get_action("maintain")
    assert action is not None
    assert action.supported_time_modes == ("none",)


def test_dataset_definition_projects_st_facts() -> None:
    definition = get_dataset_definition("st")

    assert definition.identity.display_name == "ST 风险警示事件"
    assert definition.domain.domain_key == "reference_data"
    assert definition.observability.freshness_policy == "snapshot_run_trace"
    assert definition.source.api_name == "st"
    assert definition.date_model.bucket_rule == "not_applicable"
    assert definition.date_model.selection_rule() == "none"
    assert definition.date_model.input_shape == "none"
    assert definition.date_model.window_mode == "none"
    assert definition.date_model.observed_field is None
    assert definition.input_model.time_fields == ()
    assert [field.name for field in definition.input_model.filters] == ["ts_code"]
    assert definition.storage.raw_table == "raw_tushare.st"
    assert definition.storage.target_table == "core_serving_light.st"
    assert definition.storage.delivery_mode == "raw_with_serving_light_view"
    assert definition.planning.page_limit == 1000
    assert definition.planning.unit_builder_key == "generic"
    assert definition.normalization.date_fields == ("pub_date", "imp_date")
    assert definition.normalization.required_fields == ("ts_code", "pub_date", "st_tpye", "row_key_hash")
    action = definition.capabilities.get_action("maintain")
    assert action is not None
    assert action.supported_time_modes == ("none",)


def test_dataset_definition_owns_dc_board_type_filter() -> None:
    definition = get_dataset_definition("dc_member")
    idx_type = next(field for field in definition.input_model.filters if field.name == "idx_type")

    assert idx_type.display_name == "板块类型"
    assert idx_type.field_type == "list"
    assert idx_type.multi_value is True
    assert idx_type.enum_values == ("行业板块", "概念板块", "地域板块")


def test_dataset_definition_removes_dead_exchange_filter_from_target_daily_datasets() -> None:
    target_keys = (
        "daily",
        "adj_factor",
        "cyq_perf",
        "fund_daily",
        "index_daily",
        "index_daily_basic",
    )

    for dataset_key in target_keys:
        definition = get_dataset_definition(dataset_key)
        filter_names = [field.name for field in definition.input_model.filters]
        assert filter_names == ["ts_code"]


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
    assert get_dataset_definition("index_mins").storage.layer_plan == "raw-only"
    assert get_dataset_definition("index_mins").storage.serving_table is None


def test_dataset_definition_projection_only_owns_freshness_projection() -> None:
    projection = dataset_definition_projection.build_dataset_freshness_projection(get_dataset_definition("daily"))

    assert projection.dataset_key == "daily"
    assert projection.raw_table == "raw_tushare.daily"
    assert projection.target_table == "core_serving.equity_daily_bar"
    assert projection.primary_action_key == "daily.maintain"
    assert dataset_definition_projection.delivery_mode_label("single_source_serving") == "单源服务"
    assert dataset_definition_projection.delivery_mode_tone("single_source_serving") == "success"


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
