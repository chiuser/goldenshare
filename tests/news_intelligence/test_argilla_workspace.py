from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

import pytest

from src.app.runtime.news_intelligence.argilla_workspace import (
    ARGILLA_DATASET_NAMES,
    ArgillaContractError,
    ArgillaHttpClient,
    export_submitted_annotations,
    import_annotation_tasks,
)
from src.biz.services.wealth.news_intelligence.policy import TAXONOMY_VERSION


class FakeArgillaClient:
    def __init__(self) -> None:
        self.datasets: dict[str, dict[str, object]] = {}
        self.records: dict[str, list[dict[str, object]]] = {}
        self.questions: list[Mapping[str, object]] = []

    def request(self, method, path, *, body=None, query=None):
        if method == "GET" and path == "me/workspaces":
            return {"items": [{"id": "workspace-1", "name": "news-intelligence-m1"}]}
        if method == "GET" and path == "me/datasets":
            name = query["name"]
            return {
                "items": [
                    dataset
                    for dataset in self.datasets.values()
                    if dataset["name"] == name
                ]
            }
        if method == "POST" and path == "datasets":
            dataset_id = f"dataset-{len(self.datasets) + 1}"
            dataset = {"id": dataset_id, "status": "draft", **dict(body)}
            self.datasets[dataset_id] = dataset
            self.records[dataset_id] = []
            return dataset
        if method == "POST" and path.endswith("/fields"):
            return {"id": "field"}
        if method == "POST" and path.endswith("/questions"):
            self.questions.append(body)
            return {"id": "question"}
        if method == "PUT" and path.endswith("/publish"):
            dataset_id = path.split("/")[1]
            self.datasets[dataset_id]["status"] = "ready"
            return self.datasets[dataset_id]
        if method == "GET" and path.endswith("/records"):
            dataset_id = path.split("/")[1]
            offset = int(query["offset"])
            limit = int(query["limit"])
            return {"items": self.records[dataset_id][offset : offset + limit]}
        if method == "POST" and path.endswith("/records/bulk"):
            dataset_id = path.split("/")[1]
            created = []
            for item in body["items"]:
                record = {
                    "id": (
                        "record-"
                        f"{sum(len(rows) for rows in self.records.values()) + 1}"
                    ),
                    "responses": [],
                    **dict(item),
                }
                self.records[dataset_id].append(record)
                created.append(record)
            return {"items": created}
        raise AssertionError((method, path, body, query))


def _write_import(path: Path) -> None:
    records = []
    for index, sample_group in enumerate(("TUTORIAL", "BLIND_PILOT"), start=1):
        sample_id = f"m1:news:{index}"
        records.append(
            {
                "external_id": sample_id,
                "fields": {
                    "title": f"title {index}",
                    "content": f"content {index}",
                    "source_type": "news",
                    "source_name": "test",
                    "business_time": None,
                    "content_date": "2026-09-20",
                },
                "metadata": {
                    "sample_id": sample_id,
                    "input_hash": str(index) * 64,
                    "taxonomy_version": TAXONOMY_VERSION,
                    "sample_group": sample_group,
                    "stratum": "news:SHORT",
                    "selection_probability": 0.5,
                    "enrichment_reason": None,
                },
            }
        )
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def test_argilla_import_is_split_blind_and_idempotent(tmp_path: Path) -> None:
    input_path = tmp_path / "annotation_import.jsonl"
    _write_import(input_path)
    client = FakeArgillaClient()

    first = import_annotation_tasks(
        client=client,
        input_path=input_path,
        workspace_name="news-intelligence-m1",
    )
    second = import_annotation_tasks(
        client=client,
        input_path=input_path,
        workspace_name="news-intelligence-m1",
    )

    assert set(first.dataset_ids) == set(ARGILLA_DATASET_NAMES)
    assert first.imported == {"TUTORIAL": 1, "BLIND_PILOT": 1}
    assert second.imported == {"TUTORIAL": 0, "BLIND_PILOT": 0}
    assert second.already_present == {"TUTORIAL": 1, "BLIND_PILOT": 1}
    assert len(client.datasets) == 2
    assert all(
        "suggestions" not in record
        for rows in client.records.values()
        for record in rows
    )
    primary_topic = next(
        question for question in client.questions if question["name"] == "primary_topic"
    )
    first_option = primary_topic["settings"]["options"][0]
    assert first_option["text"] != first_option["value"]


def test_argilla_import_rejects_changed_frozen_input(tmp_path: Path) -> None:
    input_path = tmp_path / "annotation_import.jsonl"
    _write_import(input_path)
    client = FakeArgillaClient()
    result = import_annotation_tasks(
        client=client,
        input_path=input_path,
        workspace_name="news-intelligence-m1",
    )
    tutorial_id = result.dataset_ids["TUTORIAL"]
    client.records[tutorial_id][0]["metadata"]["input_hash"] = "f" * 64

    with pytest.raises(ArgillaContractError, match="different input_hash"):
        import_annotation_tasks(
            client=client,
            input_path=input_path,
            workspace_name="news-intelligence-m1",
        )


def test_argilla_export_writes_only_submitted_responses(tmp_path: Path) -> None:
    input_path = tmp_path / "annotation_import.jsonl"
    _write_import(input_path)
    client = FakeArgillaClient()
    imported = import_annotation_tasks(
        client=client,
        input_path=input_path,
        workspace_name="news-intelligence-m1",
    )
    blind_id = imported.dataset_ids["BLIND_PILOT"]
    record = client.records[blind_id][0]
    record["responses"] = [
        {
            "status": "submitted",
            "user_id": "reviewer-1",
            "updated_at": "2026-09-29T12:00:00+00:00",
            "values": {
                "classification_status": {"value": "CLASSIFIED"},
                "primary_topic": {"value": "ECONOMY_BUSINESS_FINANCE"},
            },
        }
    ]
    output_path = tmp_path / "annotation_export.jsonl"

    result = export_submitted_annotations(
        client=client,
        dataset_id=blind_id,
        output_path=output_path,
        annotation_round=1,
    )

    exported = json.loads(output_path.read_text(encoding="utf-8"))
    assert result.submitted_records == 1
    assert exported["sample_id"] == "m1:news:2"
    assert exported["input_hash"] == "2" * 64
    assert exported["reviewer_id"] == "reviewer-1"
    assert exported["submitted_at"] == "2026-09-29T12:00:00+00:00"


def test_argilla_client_rejects_non_loopback_url() -> None:
    with pytest.raises(ValueError, match="loopback"):
        ArgillaHttpClient(api_url="https://example.com/api/v1", api_key="secret")
