from __future__ import annotations

from src.foundation.datasets.registry import get_dataset_definition
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
