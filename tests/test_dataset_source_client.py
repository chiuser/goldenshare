from __future__ import annotations

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.clients.tushare_client import TushareRateLimitError
from src.foundation.ingestion import source_client as source_client_module
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot
from src.foundation.ingestion.source_client import DatasetSourceClient


class RecordingConnector:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.rows = rows or []

    def call(self, api_name: str, params=None, fields=None):  # type: ignore[no-untyped-def]
        self.calls.append({"api_name": api_name, "params": dict(params or {}), "fields": tuple(fields or ())})
        return [dict(row) for row in self.rows]


class PaginatedConnector:
    def __init__(self, pages: dict[int, list[dict[str, object]]]) -> None:
        self.calls: list[dict[str, object]] = []
        self.pages = pages

    def call(self, api_name: str, params=None, fields=None):  # type: ignore[no-untyped-def]
        params_dict = dict(params or {})
        self.calls.append({"api_name": api_name, "params": params_dict, "fields": tuple(fields or ())})
        offset = int(params_dict.get("offset") or 0)
        return [dict(row) for row in self.pages.get(offset, [])]


class RateLimitedOnceConnector:
    def __init__(self) -> None:
        self.calls = 0

    def call(self, api_name: str, params=None, fields=None):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == 1:
            raise TushareRateLimitError(
                api_name=api_name,
                message="抱歉，您访问接口(index_daily)频率超限(500次/分钟)",
            )
        return [{"ts_code": "000001.SH", "trade_date": "20260424"}]


def test_major_news_source_client_passes_definition_source_fields(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    connector = RecordingConnector()
    monkeypatch.setattr(source_client_module, "create_source_connector", lambda source_key: connector)

    result = DatasetSourceClient().fetch(
        definition=get_dataset_definition("major_news"),
        unit=PlanUnitSnapshot(
            unit_id="major-news-u1",
            dataset_key="major_news",
            source_key="tushare",
            trade_date=None,
            request_params={
                "src": "新华网",
                "start_date": "2026-04-24 00:00:00",
                "end_date": "2026-04-24 23:59:59",
            },
            progress_context={},
            pagination_policy="offset_limit",
            page_limit=400,
        ),
    )

    assert result.request_count == 1
    assert connector.calls == [
        {
            "api_name": "major_news",
            "params": {
                "src": "新华网",
                "start_date": "2026-04-24 00:00:00",
                "end_date": "2026-04-24 23:59:59",
                "offset": 0,
                "limit": 400,
            },
            "fields": ("title", "content", "pub_time", "src", "url"),
        }
    ]


def test_news_source_client_passes_fields_and_annotates_src(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    connector = RecordingConnector(rows=[{"datetime": "2026-04-24 10:11:12", "title": "快讯标题", "content": ""}])
    monkeypatch.setattr(source_client_module, "create_source_connector", lambda source_key: connector)

    result = DatasetSourceClient().fetch(
        definition=get_dataset_definition("news"),
        unit=PlanUnitSnapshot(
            unit_id="news-u1",
            dataset_key="news",
            source_key="tushare",
            trade_date=None,
            request_params={
                "src": "sina",
                "start_date": "2026-04-24 00:00:00",
                "end_date": "2026-04-24 23:59:59",
            },
            progress_context={},
            pagination_policy="offset_limit",
            page_limit=1500,
        ),
    )

    assert result.request_count == 1
    assert result.rows_raw == [{"datetime": "2026-04-24 10:11:12", "title": "快讯标题", "content": "", "src": "sina"}]
    assert connector.calls == [
        {
            "api_name": "news",
            "params": {
                "src": "sina",
                "start_date": "2026-04-24 00:00:00",
                "end_date": "2026-04-24 23:59:59",
                "offset": 0,
                "limit": 1500,
            },
            "fields": ("datetime", "content", "title", "channels", "score"),
        }
    ]


def test_anns_d_source_client_passes_definition_fields(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    connector = RecordingConnector()
    monkeypatch.setattr(source_client_module, "create_source_connector", lambda source_key: connector)

    result = DatasetSourceClient().fetch(
        definition=get_dataset_definition("anns_d"),
        unit=PlanUnitSnapshot(
            unit_id="anns-d-u1",
            dataset_key="anns_d",
            source_key="tushare",
            trade_date=None,
            request_params={"start_date": "20260514", "end_date": "20260514", "ts_code": "600000.SH"},
            progress_context={},
            pagination_policy="offset_limit",
            page_limit=2000,
        ),
    )

    assert result.request_count == 1
    assert connector.calls == [
        {
            "api_name": "anns_d",
            "params": {
                "start_date": "20260514",
                "end_date": "20260514",
                "ts_code": "600000.SH",
                "offset": 0,
                "limit": 2000,
            },
            "fields": ("ann_date", "ts_code", "name", "title", "url", "rec_time"),
        }
    ]


def test_irm_qa_source_client_passes_definition_fields(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    connector = RecordingConnector()
    monkeypatch.setattr(source_client_module, "create_source_connector", lambda source_key: connector)

    result = DatasetSourceClient().fetch(
        definition=get_dataset_definition("irm_qa_sz"),
        unit=PlanUnitSnapshot(
            unit_id="irm-qa-sz-u1",
            dataset_key="irm_qa_sz",
            source_key="tushare",
            trade_date=None,
            request_params={"trade_date": "20260514"},
            progress_context={},
            pagination_policy="offset_limit",
            page_limit=3000,
        ),
    )

    assert result.request_count == 1
    assert connector.calls == [
        {
            "api_name": "irm_qa_sz",
            "params": {
                "trade_date": "20260514",
                "offset": 0,
                "limit": 3000,
            },
            "fields": ("ts_code", "name", "trade_date", "q", "a", "pub_time", "industry"),
        }
    ]


def test_research_report_source_client_passes_definition_fields(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    connector = RecordingConnector()
    monkeypatch.setattr(source_client_module, "create_source_connector", lambda source_key: connector)

    result = DatasetSourceClient().fetch(
        definition=get_dataset_definition("research_report"),
        unit=PlanUnitSnapshot(
            unit_id="research-report-u1",
            dataset_key="research_report",
            source_key="tushare",
            trade_date=None,
            request_params={"trade_date": "20260121", "report_type": "个股研报"},
            progress_context={},
            pagination_policy="offset_limit",
            page_limit=1000,
        ),
    )

    assert result.request_count == 1
    assert connector.calls == [
        {
            "api_name": "research_report",
            "params": {
                "trade_date": "20260121",
                "report_type": "个股研报",
                "offset": 0,
                "limit": 1000,
            },
            "fields": (
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
            ),
        }
    ]


def test_cyq_chips_source_client_uses_offset_limit_pagination(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    connector = PaginatedConnector(
        {
            0: [
                {"ts_code": "600000.SH", "trade_date": "20260424", "price": "10.01", "percent": "1.01"},
                {"ts_code": "600000.SH", "trade_date": "20260424", "price": "10.02", "percent": "1.02"},
            ],
            2: [
                {"ts_code": "600000.SH", "trade_date": "20260424", "price": "10.03", "percent": "1.03"},
            ],
        }
    )
    monkeypatch.setattr(source_client_module, "create_source_connector", lambda source_key: connector)

    result = DatasetSourceClient().fetch(
        definition=get_dataset_definition("cyq_chips"),
        unit=PlanUnitSnapshot(
            unit_id="cyq-chips-u1",
            dataset_key="cyq_chips",
            source_key="tushare",
            trade_date=None,
            request_params={"ts_code": "600000.SH", "start_date": "20260420", "end_date": "20260424"},
            progress_context={},
            pagination_policy="offset_limit",
            page_limit=2,
        ),
    )

    assert result.request_count == 2
    assert len(result.rows_raw) == 3
    assert connector.calls == [
        {
            "api_name": "cyq_chips",
            "params": {
                "ts_code": "600000.SH",
                "start_date": "20260420",
                "end_date": "20260424",
                "offset": 0,
                "limit": 2,
            },
            "fields": ("ts_code", "trade_date", "price", "percent"),
        },
        {
            "api_name": "cyq_chips",
            "params": {
                "ts_code": "600000.SH",
                "start_date": "20260420",
                "end_date": "20260424",
                "offset": 2,
                "limit": 2,
            },
            "fields": ("ts_code", "trade_date", "price", "percent"),
        },
    ]


def test_idx_factor_pro_source_client_pages_full_trade_date_result(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    first_page = [{"ts_code": f"000{index:04d}.SH", "trade_date": "20260424"} for index in range(8000)]
    connector = PaginatedConnector(
        {
            0: first_page,
            8000: [{"ts_code": "399300.SZ", "trade_date": "20260424"}],
        }
    )
    monkeypatch.setattr(source_client_module, "create_source_connector", lambda source_key: connector)
    definition = get_dataset_definition("idx_factor_pro")

    result = DatasetSourceClient().fetch(
        definition=definition,
        unit=PlanUnitSnapshot(
            unit_id="idx-factor-pro-u1",
            dataset_key="idx_factor_pro",
            source_key="tushare",
            trade_date=None,
            request_params={"trade_date": "20260424"},
            progress_context={},
            pagination_policy="offset_limit",
            page_limit=8000,
        ),
    )

    assert result.request_count == 2
    assert len(result.rows_raw) == 8001
    assert [call["params"] for call in connector.calls] == [
        {"trade_date": "20260424", "offset": 0, "limit": 8000},
        {"trade_date": "20260424", "offset": 8000, "limit": 8000},
    ]
    assert all(call["api_name"] == "idx_factor_pro" for call in connector.calls)
    assert all(call["fields"] == definition.source.source_fields for call in connector.calls)


def test_index_mins_source_client_passes_fields_and_fills_missing_freq(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    connector = RecordingConnector(rows=[{"ts_code": "000001.SH", "trade_time": "2026-04-30 15:00:00"}])
    monkeypatch.setattr(source_client_module, "create_source_connector", lambda source_key: connector)

    result = DatasetSourceClient().fetch(
        definition=get_dataset_definition("index_mins"),
        unit=PlanUnitSnapshot(
            unit_id="index-mins-u1",
            dataset_key="index_mins",
            source_key="tushare",
            trade_date=None,
            request_params={
                "ts_code": "000001.SH",
                "freq": "30min",
                "start_date": "2026-04-30 09:00:00",
                "end_date": "2026-04-30 19:00:00",
            },
            progress_context={},
            pagination_policy="offset_limit",
            page_limit=8000,
        ),
    )

    assert result.request_count == 1
    assert result.rows_raw == [{"ts_code": "000001.SH", "trade_time": "2026-04-30 15:00:00", "freq": "30min"}]
    assert connector.calls == [
        {
            "api_name": "idx_mins",
            "params": {
                "ts_code": "000001.SH",
                "freq": "30min",
                "start_date": "2026-04-30 09:00:00",
                "end_date": "2026-04-30 19:00:00",
                "offset": 0,
                "limit": 8000,
            },
            "fields": (
                "ts_code",
                "trade_time",
                "close",
                "open",
                "high",
                "low",
                "vol",
                "amount",
                "freq",
                "exchange",
                "vwap",
            ),
        }
    ]


def test_source_client_waits_full_window_before_retrying_tushare_rate_limit(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    connector = RateLimitedOnceConnector()
    sleeps: list[float] = []
    monkeypatch.setattr(source_client_module, "create_source_connector", lambda source_key: connector)
    monkeypatch.setattr(source_client_module.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = DatasetSourceClient().fetch(
        definition=get_dataset_definition("index_daily"),
        unit=PlanUnitSnapshot(
            unit_id="index-daily-u1",
            dataset_key="index_daily",
            source_key="tushare",
            trade_date=None,
            request_params={"ts_code": "000001.SH", "trade_date": "20260424"},
            progress_context={},
            pagination_policy="none",
            page_limit=None,
        ),
    )

    assert connector.calls == 2
    assert result.request_count == 1
    assert result.retry_count == 1
    assert result.rows_raw == [{"ts_code": "000001.SH", "trade_date": "20260424"}]
    assert sleeps == [65.0]
