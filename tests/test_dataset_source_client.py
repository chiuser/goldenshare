from __future__ import annotations

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion import source_client as source_client_module
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot
from src.foundation.ingestion.source_client import DatasetSourceClient


class RecordingConnector:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def call(self, api_name: str, params=None, fields=None):  # type: ignore[no-untyped-def]
        self.calls.append({"api_name": api_name, "params": dict(params or {}), "fields": tuple(fields or ())})
        return []


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
