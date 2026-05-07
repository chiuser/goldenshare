from __future__ import annotations

from datetime import date
from datetime import datetime

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.normalizer import DatasetNormalizer
from src.foundation.ingestion.source_client import SourceFetchResult
from src.foundation.services.transform.top_list_payload import build_top_list_payload_hash


def test_dc_daily_normalizer_keeps_required_fields() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("dc_daily"),
        fetch_result=SourceFetchResult(
            unit_id="u-dc-daily",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[{"trade_date": "20260401", "ts_code": "BK001", "close": "1"}],
        ),
    )

    assert batch.rows_rejected == 0
    assert batch.rows_normalized[0]["trade_date"] == date(2026, 4, 1)
    assert batch.rows_normalized[0]["ts_code"] == "BK001"


def test_top_list_normalizer_hashes_punctuation_variants_to_same_reason_hash() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("top_list"),
        fetch_result=SourceFetchResult(
            unit_id="u-top-list",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "trade_date": "20190719",
                    "ts_code": "603256.SH",
                    "reason": "当日无价格涨跌幅限制的A股，出现异常波动停牌的",
                },
                {
                    "trade_date": "20190719",
                    "ts_code": "603256.SH",
                    "reason": "当日无价格涨跌幅限制的A股,出现异常波动停牌的",
                },
            ],
        ),
    )

    assert batch.rows_rejected == 0
    assert batch.rows_normalized[0]["reason"] != batch.rows_normalized[1]["reason"]
    assert batch.rows_normalized[0]["reason_hash"] == batch.rows_normalized[1]["reason_hash"]
    assert batch.rows_normalized[0]["payload_hash"] != batch.rows_normalized[1]["payload_hash"]


def test_top_list_normalizer_treats_nan_float_values_as_null() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("top_list"),
        fetch_result=SourceFetchResult(
            unit_id="u-top-list-nan-float-values",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "trade_date": "20170329",
                    "ts_code": "603517.SH",
                    "reason": "非ST、*ST和S证券连续三个交易日内收盘价格涨幅偏离值累计达到20%的证券",
                    "float_values": float("nan"),
                }
            ],
        ),
    )

    assert batch.rows_rejected == 0
    assert batch.rows_normalized[0]["float_values"] is None
    assert isinstance(batch.rows_normalized[0]["payload_hash"], str)
    assert len(batch.rows_normalized[0]["payload_hash"]) == 64


def test_top_list_normalizer_normalizes_equivalent_null_float_values_to_same_payload_hash() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("top_list"),
        fetch_result=SourceFetchResult(
            unit_id="u-top-list-equivalent-null-payload",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "trade_date": "20170329",
                    "ts_code": "603517.SH",
                    "reason": "非ST、*ST和S证券连续三个交易日内收盘价格涨幅偏离值累计达到20%的证券",
                    "float_values": float("nan"),
                },
                {
                    "trade_date": "20170329",
                    "ts_code": "603517.SH",
                    "reason": "非ST、*ST和S证券连续三个交易日内收盘价格涨幅偏离值累计达到20%的证券",
                    "float_values": None,
                },
            ],
        ),
    )

    assert batch.rows_rejected == 0
    assert batch.rows_normalized[0]["payload_hash"] == batch.rows_normalized[1]["payload_hash"]


def test_top_list_payload_hash_matches_between_raw_and_serving_row_shapes() -> None:
    raw_row = {
        "ts_code": "603517.SH",
        "trade_date": date(2017, 3, 29),
        "reason": "非ST、*ST和S证券连续三个交易日内收盘价格涨幅偏离值累计达到20%的证券",
        "name": "绝味食品",
        "close": "51.69",
        "pct_change": "10.0100",
        "turnover_rate": "8.8200",
        "amount": "2041.500000",
        "l_sell": "61.501425",
        "l_buy": "2041.495965",
        "l_amount": "2102.997390",
        "net_amount": "1979.994540",
        "net_rate": "96.9900",
        "amount_rate": "103.0100",
        "float_values": "2482500000.0",
    }
    serving_row = {
        "ts_code": "603517.SH",
        "trade_date": date(2017, 3, 29),
        "reason": "非ST、*ST和S证券连续三个交易日内收盘价格涨幅偏离值累计达到20%的证券",
        "name": "绝味食品",
        "close": "51.69",
        "pct_chg": "10.0100",
        "turnover_rate": "8.8200",
        "amount": "2041.500000",
        "l_sell": "61.501425",
        "l_buy": "2041.495965",
        "l_amount": "2102.997390",
        "net_amount": "1979.994540",
        "net_rate": "96.9900",
        "amount_rate": "103.0100",
        "float_values": "2482500000.0",
    }

    assert build_top_list_payload_hash(raw_row) == build_top_list_payload_hash(serving_row)


def test_cctv_news_normalizer_keeps_source_date_and_builds_row_hash() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("cctv_news"),
        fetch_result=SourceFetchResult(
            unit_id="u-cctv-news",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "date": "20260424",
                    "title": "  央视快讯  ",
                    "content": "  新闻联播内容  ",
                }
            ],
        ),
    )

    assert batch.rows_rejected == 0
    normalized = batch.rows_normalized[0]
    assert normalized["date"] == date(2026, 4, 24)
    assert normalized["title"] == "央视快讯"
    assert normalized["content"] == "新闻联播内容"
    assert isinstance(normalized["row_key_hash"], str)
    assert len(normalized["row_key_hash"]) == 64


def test_trade_cal_normalizer_treats_nan_pretrade_date_as_null() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("trade_cal"),
        fetch_result=SourceFetchResult(
            unit_id="u-trade-cal",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "exchange": "SSE",
                    "cal_date": "20260424",
                    "is_open": "1",
                    "pretrade_date": "nan",
                }
            ],
        ),
    )

    assert batch.rows_rejected == 0
    normalized = batch.rows_normalized[0]
    assert normalized["cal_date"] == date(2026, 4, 24)
    assert normalized["trade_date"] == date(2026, 4, 24)
    assert normalized["pretrade_date"] is None
    assert normalized["is_open"] is True


def test_bak_basic_normalizer_trims_text_and_parses_dates() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("bak_basic"),
        fetch_result=SourceFetchResult(
            unit_id="u-bak-basic",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "trade_date": "20260424",
                    "ts_code": "000001.sz",
                    "name": " 平安银行 ",
                    "industry": " 银行 ",
                    "area": " 深圳 ",
                    "pe": "5.25",
                    "list_date": "19910403",
                    "holder_num": 321456,
                }
            ],
        ),
    )

    assert batch.rows_rejected == 0
    normalized = batch.rows_normalized[0]
    assert normalized["trade_date"] == date(2026, 4, 24)
    assert normalized["ts_code"] == "000001.SZ"
    assert normalized["name"] == "平安银行"
    assert normalized["industry"] == "银行"
    assert normalized["area"] == "深圳"
    assert normalized["list_date"] == date(1991, 4, 3)
    assert str(normalized["pe"]) == "5.25"
    assert normalized["holder_num"] == 321456


def test_bak_basic_normalizer_treats_zero_list_date_as_null() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("bak_basic"),
        fetch_result=SourceFetchResult(
            unit_id="u-bak-basic",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "trade_date": "20260424",
                    "ts_code": "000001.SZ",
                    "name": "平安银行",
                    "list_date": 0,
                }
            ],
        ),
    )

    assert batch.rows_rejected == 0
    assert batch.rows_normalized[0]["list_date"] is None


def test_bak_basic_normalizer_rejects_zero_required_trade_date() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("bak_basic"),
        fetch_result=SourceFetchResult(
            unit_id="u-bak-basic",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "trade_date": 0,
                    "ts_code": "000001.SZ",
                    "name": "平安银行",
                    "list_date": 0,
                }
            ],
        ),
    )

    assert batch.rows_rejected == 1
    assert batch.rejected_reasons == {"normalize.required_field_missing:trade_date": 1}


def test_namechange_normalizer_builds_row_hash_and_trims_fields() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("namechange"),
        fetch_result=SourceFetchResult(
            unit_id="u-namechange",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "ts_code": "000001.sz",
                    "name": " 平安银行 ",
                    "start_date": "20200101",
                    "end_date": "",
                    "ann_date": "20200424",
                    "change_reason": " 证券简称变更 ",
                }
            ],
        ),
    )

    assert batch.rows_rejected == 0
    normalized = batch.rows_normalized[0]
    assert normalized["ts_code"] == "000001.SZ"
    assert normalized["name"] == "平安银行"
    assert normalized["start_date"] == date(2020, 1, 1)
    assert normalized["end_date"] is None
    assert normalized["ann_date"] == date(2020, 4, 24)
    assert normalized["change_reason"] == "证券简称变更"
    assert isinstance(normalized["row_key_hash"], str)
    assert len(normalized["row_key_hash"]) == 64


def test_st_normalizer_preserves_source_field_name_and_builds_row_hash() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("st"),
        fetch_result=SourceFetchResult(
            unit_id="u-st",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "ts_code": "000001.sz",
                    "name": " 平安银行 ",
                    "pub_date": "20260424",
                    "imp_date": "20260425",
                    "st_tpye": " 风险警示 ",
                    "st_reason": " 触发条件 ",
                    "st_explain": " 说明内容 ",
                }
            ],
        ),
    )

    assert batch.rows_rejected == 0
    normalized = batch.rows_normalized[0]
    assert normalized["ts_code"] == "000001.SZ"
    assert normalized["name"] == "平安银行"
    assert normalized["pub_date"] == date(2026, 4, 24)
    assert normalized["imp_date"] == date(2026, 4, 25)
    assert normalized["st_tpye"] == "风险警示"
    assert normalized["st_reason"] == "触发条件"
    assert normalized["st_explain"] == "说明内容"
    assert isinstance(normalized["row_key_hash"], str)
    assert len(normalized["row_key_hash"]) == 64


def test_major_news_normalizer_parses_pub_time_and_builds_row_hash() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("major_news"),
        fetch_result=SourceFetchResult(
            unit_id="u-major-news",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "src": " 新浪财经 ",
                    "pub_time": "2026-04-24 10:11:12",
                    "title": "  长篇通讯标题  ",
                    "content": "  长篇通讯正文  ",
                    "url": "  https://example.com/news/1  ",
                }
            ],
        ),
    )

    assert batch.rows_rejected == 0
    normalized = batch.rows_normalized[0]
    assert normalized["src"] == "新浪财经"
    assert normalized["pub_time"].isoformat() == "2026-04-24T10:11:12+08:00"
    assert normalized["title"] == "长篇通讯标题"
    assert normalized["content"] == "长篇通讯正文"
    assert normalized["url"] == "https://example.com/news/1"
    assert isinstance(normalized["row_key_hash"], str)
    assert len(normalized["row_key_hash"]) == 64


def test_major_news_normalizer_records_structured_rejection_reason() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("major_news"),
        fetch_result=SourceFetchResult(
            unit_id="u-major-news",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "src": "新浪财经",
                    "pub_time": "2026-04-24 10:11:12",
                    "title": "长篇通讯标题",
                }
            ],
        ),
    )

    assert batch.rows_normalized == []
    assert batch.rows_rejected == 1
    assert batch.rejected_reasons == {"normalize.required_field_missing:content": 1}


def test_major_news_normalizer_uses_url_in_row_hash() -> None:
    base_row = {
        "src": "新浪财经",
        "pub_time": "2026-04-24 10:11:12",
        "title": "长篇通讯标题",
        "content": "长篇通讯正文",
    }
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("major_news"),
        fetch_result=SourceFetchResult(
            unit_id="u-major-news",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {**base_row, "url": "https://example.com/a"},
                {**base_row, "url": "https://example.com/b"},
            ],
        ),
    )

    assert batch.rows_rejected == 0
    assert batch.rows_normalized[0]["row_key_hash"] != batch.rows_normalized[1]["row_key_hash"]


def test_bak_basic_invalid_date_rejection_keeps_field_sample() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("bak_basic"),
        fetch_result=SourceFetchResult(
            unit_id="u-bak-basic",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "trade_date": "20260424",
                    "ts_code": "000001.SZ",
                    "name": "平安银行",
                    "list_date": "20260231",
                }
            ],
        ),
    )

    reason_key = "normalize.invalid_date:list_date"
    assert batch.rows_rejected == 1
    assert batch.rejected_reasons == {reason_key: 1}
    assert batch.rejected_samples[reason_key][0]["field"] == "list_date"
    assert batch.rejected_samples[reason_key][0]["value"] == "20260231"
    assert batch.rejected_samples[reason_key][0]["row"]["ts_code"] == "000001.SZ"


def test_index_basic_normalizer_keeps_source_date_strings_for_raw_layer() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("index_basic"),
        fetch_result=SourceFetchResult(
            unit_id="u-index-basic",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "ts_code": "000300.SH",
                    "name": "沪深300",
                    "base_date": "20041231",
                    "base_point": "1000",
                    "list_date": "20050408",
                    "exp_date": "",
                }
            ],
        ),
    )

    assert batch.rows_rejected == 0
    normalized = batch.rows_normalized[0]
    assert normalized["base_date"] == "20041231"
    assert normalized["list_date"] == "20050408"
    assert normalized["exp_date"] == ""
    assert str(normalized["base_point"]) == "1000"


def test_major_news_normalizer_allows_title_or_content_only() -> None:
    base_row = {
        "src": "新浪财经",
        "pub_time": "2026-04-24 10:11:12",
        "url": "https://example.com/news/1",
    }
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("major_news"),
        fetch_result=SourceFetchResult(
            unit_id="u-major-news",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {**base_row, "title": "", "content": "只有正文"},
                {**base_row, "title": "只有标题", "content": ""},
            ],
        ),
    )

    assert batch.rows_rejected == 0
    assert batch.rows_normalized[0]["title"] is None
    assert batch.rows_normalized[0]["content"] == "只有正文"
    assert batch.rows_normalized[1]["title"] == "只有标题"
    assert batch.rows_normalized[1]["content"] is None


def test_major_news_normalizer_rejects_missing_title_and_content() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("major_news"),
        fetch_result=SourceFetchResult(
            unit_id="u-major-news",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "src": "新浪财经",
                    "pub_time": "2026-04-24 10:11:12",
                    "title": "",
                    "content": "",
                    "url": "https://example.com/news/1",
                }
            ],
        ),
    )

    assert batch.rows_normalized == []
    assert batch.rows_rejected == 1
    assert batch.rejected_reasons == {"normalize.empty_not_allowed:title_content": 1}


def test_news_normalizer_parses_news_time_and_builds_row_hash() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("news"),
        fetch_result=SourceFetchResult(
            unit_id="u-news",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "src": " sina ",
                    "datetime": "2026-04-24 10:11:12",
                    "title": "  快讯标题  ",
                    "content": "  快讯正文  ",
                    "channels": "  财经  ",
                    "score": "  1  ",
                }
            ],
        ),
    )

    assert batch.rows_rejected == 0
    normalized = batch.rows_normalized[0]
    assert normalized["src"] == "sina"
    assert normalized["news_time"].isoformat() == "2026-04-24T10:11:12+08:00"
    assert normalized["title"] == "快讯标题"
    assert normalized["content"] == "快讯正文"
    assert normalized["channels"] == "财经"
    assert normalized["score"] == "1"
    assert isinstance(normalized["row_key_hash"], str)
    assert len(normalized["row_key_hash"]) == 64


def test_news_normalizer_allows_title_or_content_only() -> None:
    base_row = {
        "src": "sina",
        "datetime": "2026-04-24 10:11:12",
    }
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("news"),
        fetch_result=SourceFetchResult(
            unit_id="u-news",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {**base_row, "title": "", "content": "只有正文"},
                {**base_row, "title": "只有标题", "content": ""},
            ],
        ),
    )

    assert batch.rows_rejected == 0
    assert batch.rows_normalized[0]["title"] is None
    assert batch.rows_normalized[0]["content"] == "只有正文"
    assert batch.rows_normalized[1]["title"] == "只有标题"
    assert batch.rows_normalized[1]["content"] is None


def test_news_normalizer_rejects_missing_title_and_content() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("news"),
        fetch_result=SourceFetchResult(
            unit_id="u-news",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "src": "sina",
                    "datetime": "2026-04-24 10:11:12",
                    "title": "",
                    "content": "",
                }
            ],
        ),
    )

    assert batch.rows_normalized == []
    assert batch.rows_rejected == 1
    assert batch.rejected_reasons == {"normalize.empty_not_allowed:title_content": 1}


def test_stk_mins_normalizer_writes_slim_storage_fields_only() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("stk_mins"),
        fetch_result=SourceFetchResult(
            unit_id="u-stk-mins",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "ts_code": "600000.sh",
                    "freq": "5min",
                    "trade_time": "2026-04-24 09:35:00",
                    "open": "10.234",
                    "close": "10.236",
                    "high": "10.246",
                    "low": "10.221",
                    "vol": "3000000000",
                    "amount": "5678.9",
                    "trade_date": "20260424",
                    "session_tag": "morning",
                    "api_name": "stk_mins",
                    "fetched_at": "2026-04-24T09:36:00+08:00",
                    "raw_payload": "{}",
                }
            ],
        ),
    )

    assert batch.rows_rejected == 0
    normalized = batch.rows_normalized[0]
    assert normalized == {
        "ts_code": "600000.SH",
        "freq": 5,
        "trade_time": datetime(2026, 4, 24, 9, 35),
        "open": 10.23,
        "close": 10.24,
        "high": 10.25,
        "low": 10.22,
        "vol": 3000000000,
        "amount": 5678.9,
    }


def test_stk_mins_normalizer_rejects_outside_trading_session() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("stk_mins"),
        fetch_result=SourceFetchResult(
            unit_id="u-stk-mins",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "ts_code": "600000.SH",
                    "freq": "1min",
                    "trade_time": "2026-04-24 12:00:00",
                    "open": "10.23",
                    "close": "10.23",
                    "high": "10.23",
                    "low": "10.23",
                    "vol": "1",
                    "amount": "1",
                }
            ],
        ),
    )

    assert batch.rows_normalized == []
    assert batch.rows_rejected == 1
    assert batch.rejected_reasons == {"normalize.row_transform_failed": 1}


def test_index_mins_normalizer_keeps_source_freq_string_and_vwap() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("index_mins"),
        fetch_result=SourceFetchResult(
            unit_id="u-index-mins",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "ts_code": "000001.sh",
                    "trade_time": "2026-04-30 15:00:00",
                    "close": "3279.0352",
                    "open": "3278.7501",
                    "high": "3280.1203",
                    "low": "3277.9912",
                    "vol": "7214808600.0",
                    "amount": "83307859.3000",
                    "freq": "30min",
                    "exchange": "sse",
                    "vwap": "3278.8888",
                    "api_name": "idx_mins",
                    "raw_payload": "{}",
                }
            ],
        ),
    )

    assert batch.rows_rejected == 0
    assert batch.rows_normalized == [
        {
            "ts_code": "000001.SH",
            "trade_time": datetime(2026, 4, 30, 15, 0),
            "close": 3279.0352,
            "open": 3278.7501,
            "high": 3280.1203,
            "low": 3277.9912,
            "vol": 7214808600.0,
            "amount": 83307859.3,
            "freq": "30min",
            "exchange": "SSE",
            "vwap": 3278.8888,
        }
    ]


def test_index_mins_normalizer_rejects_unknown_freq() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("index_mins"),
        fetch_result=SourceFetchResult(
            unit_id="u-index-mins",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "ts_code": "000001.SH",
                    "trade_time": "2026-04-30 15:00:00",
                    "freq": "90min",
                }
            ],
        ),
    )

    assert batch.rows_normalized == []
    assert batch.rows_rejected == 1
    assert batch.rejected_reasons == {"normalize.row_transform_failed": 1}


def test_reference_security_normalizers_resolve_hk_and_us_row_transforms() -> None:
    hk_batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("hk_basic"),
        fetch_result=SourceFetchResult(
            unit_id="u-hk-basic",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "ts_code": "00700.HK",
                    "name": "腾讯控股",
                    "list_date": "2004-06-16",
                }
            ],
        ),
    )
    us_batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("us_basic"),
        fetch_result=SourceFetchResult(
            unit_id="u-us-basic",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "ts_code": "AAPL.O",
                    "name": "Apple Inc.",
                    "list_date": "1980-12-12",
                }
            ],
        ),
    )

    assert hk_batch.rows_rejected == 0
    assert hk_batch.rows_normalized[0]["source"] == "tushare"
    assert us_batch.rows_rejected == 0
    assert us_batch.rows_normalized[0]["source"] == "tushare"


def test_kpl_concept_cons_normalizer_resolves_board_name_alias() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("kpl_concept_cons"),
        fetch_result=SourceFetchResult(
            unit_id="u-kpl-concept-cons",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "trade_date": "2026-04-24",
                    "ts_code": "BK1234",
                    "ts_name": "AI算力",
                    "con_code": "000001.SZ",
                    "con_name": "",
                }
            ],
        ),
    )

    assert batch.rows_rejected == 0
    assert batch.rows_normalized[0]["con_name"] == "AI算力"
