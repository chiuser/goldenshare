from __future__ import annotations

from datetime import date
from datetime import datetime

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.normalizer import DatasetNormalizer
from src.foundation.ingestion.source_client import SourceFetchResult


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
