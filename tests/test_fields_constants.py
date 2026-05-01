from src.foundation.datasets.registry import get_dataset_definition


def _source_fields(dataset_key: str) -> tuple[str, ...]:
    return tuple(get_dataset_definition(dataset_key).source.source_fields)


def test_dataset_definition_source_fields_cover_reference_resources() -> None:
    assert _source_fields("stock_basic")[0] == "ts_code"
    assert _source_fields("trade_cal") == ("exchange", "cal_date", "is_open", "pretrade_date")
    assert _source_fields("hk_basic") == (
        "ts_code",
        "name",
        "fullname",
        "enname",
        "cn_spell",
        "market",
        "list_status",
        "list_date",
        "delist_date",
        "trade_unit",
        "isin",
        "curr_type",
    )
    assert _source_fields("us_basic") == (
        "ts_code",
        "name",
        "enname",
        "classify",
        "list_date",
        "delist_date",
    )
    assert _source_fields("etf_basic") == (
        "ts_code",
        "csname",
        "extname",
        "cname",
        "index_code",
        "index_name",
        "setup_date",
        "list_date",
        "list_status",
        "exchange",
        "mgr_name",
        "custod_name",
        "mgt_fee",
        "etf_type",
    )


def test_dataset_definition_source_fields_cover_market_and_board_resources() -> None:
    assert "adj_factor" in _source_fields("adj_factor")
    assert "close" in _source_fields("daily_basic")
    assert "winner_rate" in _source_fields("cyq_perf")
    assert "net_mf_amount" in _source_fields("moneyflow")
    assert tuple(_source_fields("margin")) == (
        "trade_date",
        "exchange_id",
        "rzye",
        "rzmre",
        "rzche",
        "rqye",
        "rqmcl",
        "rzrqye",
        "rqyl",
    )
    assert tuple(_source_fields("ths_index")) == ("ts_code", "name", "count", "exchange", "list_date", "type")
    assert tuple(_source_fields("dc_member")) == ("trade_date", "ts_code", "con_code", "name")
    assert "idx_type" in _source_fields("dc_index")
    assert "swing" in _source_fields("dc_daily")


def test_dataset_definition_source_fields_cover_extended_resources() -> None:
    stk_mins = get_dataset_definition("stk_mins")
    assert "trade_time" in _source_fields("stk_mins")
    assert any(field.name == "freq" for field in stk_mins.input_model.filters)
    assert stk_mins.date_model.observed_field == "trade_time"
    assert stk_mins.observability.observed_field == "trade_time"
    assert stk_mins.normalization.required_fields == ("ts_code", "freq", "trade_time")
    assert stk_mins.quality.required_fields == ("ts_code", "freq", "trade_time")
    assert "trade_date" not in stk_mins.normalization.required_fields
    assert "session_tag" not in stk_mins.normalization.required_fields
    assert "open_qfq" in _source_fields("stk_period_bar_adj_week")
    assert "publisher" in _source_fields("index_basic")
    index_basic = get_dataset_definition("index_basic")
    assert index_basic.date_model.window_mode == "none"
    assert index_basic.input_model.time_fields == ()
    assert {field.name for field in index_basic.input_model.filters} == {
        "ts_code",
        "symbol",
        "name",
        "market",
        "publisher",
        "category",
    }
    assert index_basic.capabilities.get_action("maintain").supported_time_modes == ("none",)
    assert tuple(_source_fields("index_weight")) == ("index_code", "con_code", "trade_date", "weight")
    assert tuple(_source_fields("broker_recommend")) == (
        "month",
        "currency",
        "name",
        "ts_code",
        "trade_date",
        "close",
        "pct_change",
        "target_price",
        "industry",
        "broker",
        "broker_mkt",
        "author",
        "recom_type",
        "reason",
    )
    assert tuple(_source_fields("stk_factor_pro"))[:2] == ("ts_code", "trade_date")
    assert "seller" in _source_fields("block_trade")
    assert {"div_listdate", "base_date", "base_share"}.issubset(set(_source_fields("dividend")))
    assert "holder_num" in _source_fields("stk_holdernumber")
    assert "limit_times" in _source_fields("limit_list_d")
    assert tuple(_source_fields("stk_limit")) == ("trade_date", "ts_code", "pre_close", "up_limit", "down_limit")
    assert tuple(_source_fields("stock_st")) == ("ts_code", "name", "trade_date", "type", "type_name")
    assert tuple(_source_fields("suspend_d")) == ("ts_code", "trade_date", "suspend_timing", "suspend_type")
    assert tuple(_source_fields("stk_nineturn")) == (
        "ts_code",
        "trade_date",
        "freq",
        "open",
        "high",
        "low",
        "close",
        "vol",
        "amount",
        "up_count",
        "down_count",
        "nine_up_turn",
        "nine_down_turn",
    )
    assert "macd_qfq" in _source_fields("stk_factor_pro")
    assert "xsii_td4_qfq" in _source_fields("stk_factor_pro")
