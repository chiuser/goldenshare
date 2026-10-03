from copy import deepcopy
import json

import pytest

from src.app.runtime.news_intelligence.argilla_review import (
    VERSIONS, export_reviews, import_review_tasks, populate_review_suggestions,
    prepare_review_record, review_schema,
)
from src.app.runtime.news_intelligence.argilla_workspace import ArgillaContractError
from src.biz.services.wealth.news_intelligence.review_policy import (
    INDUSTRIES, INTERESTS, REVIEW_FIELDS, SUBTOPICS, resolve_review, topic_options,
    topic_parent, validate_prediction, validate_values,
)
from .test_argilla_workspace import FakeArgillaClient as BaseFakeClient


class FakeArgillaClient(BaseFakeClient):
    def request(self, method, path, *, body=None, query=None):
        if method == "POST" and path.endswith("/questions"):
            question = {**body, "id": f"q-{len(self.questions)}", "dataset_id": path.split("/")[1]}
            self.questions.append(question)
            return question
        if method == "GET" and path.endswith("/questions"):
            return {"items": [q for q in self.questions if q["dataset_id"] == path.split("/")[1]]}
        if path.startswith("records/") and path.endswith("/suggestions"):
            record_id = path.split("/")[1]
            record = next(r for rs in self.records.values() for r in rs if r["id"] == record_id)
            suggestions = record.setdefault("suggestions", [])
            if method == "GET":
                return {"items": deepcopy(suggestions)}
            if method == "PUT":
                assert body["value"] != []  # Real Argilla 2.8 returns HTTP 422.
                assert body["question_id"] not in {s["question_id"] for s in suggestions}
                suggestions.append(dict(body))
                return body
        return super().request(method, path, body=body, query=query)


TEXT = "芯片公司发布财报，营业收入增长20%。"


def values():
    return {"classification_status": "CLASSIFIED", "topic_path": "ECONOMY.BUSINESS_OPERATIONS", "secondary_topics": [],
            "industry_status": "SPECIFIC", "industries": ["ELECTRONICS_SEMICONDUCTORS"],
            "interest_tags": ["SEMICONDUCTORS"], "event_type_status": "CLASSIFIED",
            "primary_event_type": "EARNINGS_GUIDANCE", "importance_tier": "MEDIUM"}


def prediction():
    return {"status": "COMPLETE", "prompt_version": "test-only", "model_revision": "fake-only",
            "values": values(), "evidence": {field: {"quote": TEXT, "source": "MODEL"} for field in REVIEW_FIELDS}}


def record(role="TUTORIAL"):
    result = {"external_id": "m1:news:1", "fields": {"title": "芯片公司财报", "content": TEXT},
              "metadata": {**VERSIONS, "sample_id": "m1:news:1", "input_hash": "a" * 64,
                           "evaluation_role": role, "prediction_exposed": role == "TUTORIAL"}}
    if role == "TUTORIAL":
        result["machine_prediction"] = prediction()
    return result


def test_separate_axes_and_unique_parent():
    assert len(topic_options()) == 25
    assert len(SUBTOPICS) == 8 and len(INDUSTRIES) == 17 and len(INTERESTS) == 15
    assert topic_parent("ECONOMY.BUSINESS_OPERATIONS") == "ECONOMY_BUSINESS_FINANCE"
    assert topic_parent("ENVIRONMENT") == "ENVIRONMENT"
    assert "TECH.ARTIFICIAL_INTELLIGENCE" not in topic_options()
    with pytest.raises(ValueError):
        topic_parent("ECONOMY.REAL_ESTATE")


@pytest.mark.parametrize("change", [
    {"secondary_topics": ["ECONOMY_BUSINESS_FINANCE"]},
    {"secondary_topics": ["ECONOMY.BUSINESS_OPERATIONS"]},
    {"secondary_topics": ["ENVIRONMENT", "ENVIRONMENT"]},
    {"industry_status": "NONE"}, {"industry_status": "SPECIFIC", "industries": []},
    {"industries": ["made-up"]}, {"interest_tags": ["made-up"]},
    {"event_type_status": "NOT_APPLICABLE"}, {"importance_tier": "made-up"},
])
def test_invalid_axis_values_rejected(change):
    with pytest.raises(ValueError):
        validate_values({**values(), **change})


def test_accept_one_click_and_edit_only_wrong_fields():
    pred = prediction()
    accepted = resolve_review(response={"review_action": "ACCEPT"}, prediction=pred,
                              role="TUTORIAL", source_text=TEXT)
    assert accepted["final_values"]["primary_topic"] == "ECONOMY_BUSINESS_FINANCE"
    assert accepted["changed_fields"] == []
    prefilled = resolve_review(response={"review_action": "ACCEPT", **values()}, prediction=pred,
                              role="TUTORIAL", source_text=TEXT)
    assert prefilled["changed_fields"] == []
    edited = resolve_review(response={"review_action": "EDIT", "importance_tier": "HIGH"},
                            prediction=pred, role="TUTORIAL", source_text=TEXT)
    assert edited["changed_fields"] == ["importance_tier"]
    filled_edit = resolve_review(response={"review_action": "EDIT", **values(), "importance_tier": "HIGH"},
                                prediction=pred, role="TUTORIAL", source_text=TEXT)
    assert filled_edit["changed_fields"] == ["importance_tier"]
    assert pred == prediction()  # Do not mutate frozen model output.
    with pytest.raises(ValueError):
        resolve_review(response={"review_action": "EDIT"}, prediction=pred, role="TUTORIAL", source_text=TEXT)
    with pytest.raises(ValueError):
        resolve_review(response={"review_action": "ACCEPT", "importance_tier": "HIGH"},
                       prediction=pred, role="TUTORIAL", source_text=TEXT)


@pytest.mark.parametrize("change", [{"status": "FAILED"}, {"model_revision": ""}, {"evidence": {}}])
def test_invalid_prediction_cannot_be_accepted(change):
    with pytest.raises(ValueError):
        validate_prediction({**prediction(), **change}, TEXT)


def test_evidence_must_be_in_original_and_unresolved_has_no_fake_gold():
    pred = prediction()
    pred["evidence"]["topic_path"]["quote"] = "原文没有这句话"
    with pytest.raises(ValueError):
        validate_prediction(pred, TEXT)
    unresolved = resolve_review(response={"review_action": "UNRESOLVED", "issue_reason": "MODEL_INVALID"},
                                prediction=pred, role="TUTORIAL", source_text=TEXT)
    assert unresolved["final_values"] is None
    with pytest.raises(ValueError):
        resolve_review(response={"review_action": "UNRESOLVED"}, prediction=pred, role="TUTORIAL", source_text=TEXT)


def test_blind_task_never_exposes_or_accepts_prediction():
    blind = record("BLIND_VALIDATION")
    prepared = prepare_review_record(blind)
    assert set(prepared["fields"]) == {"title", "content"}
    schema = review_schema("BLIND_VALIDATION")
    assert "machine_proposal" not in {field["name"] for field in schema["fields"]}
    action = schema["questions"][0]
    assert "ACCEPT" not in {option["value"] for option in action["settings"]["options"]}
    labeled = resolve_review(response={"review_action": "LABEL", **values()}, prediction=None,
                             role="BLIND_VALIDATION", source_text=TEXT)
    assert labeled["machine_prediction"] is None
    contaminated = deepcopy(blind)
    contaminated["machine_prediction"] = prediction()
    with pytest.raises(ValueError):
        prepare_review_record(contaminated)
    blind["metadata"]["hidden_hint"] = "芯片"
    with pytest.raises(ValueError):
        prepare_review_record(blind)
    with pytest.raises(ValueError):
        resolve_review(response={"review_action": "ACCEPT"}, prediction=None, role="BLIND_VALIDATION", source_text=TEXT)


def test_form_has_one_required_action_and_no_unanswerable_questions():
    schema = review_schema("TUTORIAL")
    assert [q["name"] for q in schema["questions"] if q["required"]] == ["review_action"]
    assert not {"should_top_15", "same_event", "summary_fact_check", "primary_subtopic"} & {q["name"] for q in schema["questions"]}


def test_non_news_status_does_not_force_a_topic():
    result = resolve_review(response={"review_action": "LABEL", **values(),
                                     "classification_status": "NOT_NEWS", "topic_path": None},
                            prediction=None, role="BLIND_VALIDATION", source_text=TEXT)
    assert result["final_values"]["primary_topic"] is None


def test_import_idempotent_preserves_v2_and_refuses_prediction_conflict(tmp_path):
    client = FakeArgillaClient()
    client.datasets["v2"] = {"id": "v2", "name": "m1-taxonomy-v2-candidate-1-tutorial"}
    client.records["v2"] = [{"id": "old", "responses": [{"status": "submitted"}]}]
    old = deepcopy(client.records["v2"])
    path = tmp_path / "input.jsonl"
    row = record()
    path.write_text(json.dumps(row) + "\n")
    first = import_review_tasks(client=client, input_path=path, workspace_name="news-intelligence-m1")
    second = import_review_tasks(client=client, input_path=path, workspace_name="news-intelligence-m1")
    assert first["imported"] == 1 and second["imported"] == 0
    assert client.records["v2"] == old
    suggestions = client.records[first["dataset_id"]][0]["suggestions"]
    assert len(suggestions) == len([value for value in values().values() if value is not None and value != []])
    action_ids = {q["id"] for q in client.questions if q["name"] == "review_action"}
    assert not action_ids & {s["question_id"] for s in suggestions}
    assert second["suggestions_added"] == 0
    row["machine_prediction"]["values"]["importance_tier"] = "HIGH"
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(ArgillaContractError, match="conflict"):
        import_review_tasks(client=client, input_path=path, workspace_name="news-intelligence-m1")


def test_export_original_response_clear_tags_and_versions(tmp_path):
    client = FakeArgillaClient()
    row = prepare_review_record(record())
    response = {"review_action": "EDIT", "clear_fields": ["interest_tags"]}
    row["responses"] = [{"status": "submitted", "user_id": "reviewer", "updated_at": "2026-10-03T12:00:00Z",
                         "values": {k: {"value": v} for k, v in response.items()}}]
    client.records["v3"] = [row]
    path = tmp_path / "output.jsonl"
    export_reviews(client=client, dataset_id="v3", output_path=path, annotation_round=1)
    exported = json.loads(path.read_text())
    assert exported["human_response"] == response
    assert exported["machine_prediction"] == prediction()
    assert exported["final_values"]["interest_tags"] == []
    assert exported["changed_fields"] == ["interest_tags"]
    assert exported["input_hash"] == "a" * 64
    assert all(exported[k] == v for k, v in VERSIONS.items())
    with pytest.raises(ValueError):
        export_reviews(client=client, dataset_id="v3", output_path=path, annotation_round=1)


def test_invalid_submitted_response_never_writes_output(tmp_path):
    client = FakeArgillaClient()
    row = prepare_review_record(record())
    row["responses"] = [{"status": "submitted", "user_id": "reviewer", "updated_at": "2026-10-03",
                         "values": {"review_action": {"value": "EDIT"}}}]
    client.records["v3"] = [row]
    path = tmp_path / "output.jsonl"
    with pytest.raises(ValueError):
        export_reviews(client=client, dataset_id="v3", output_path=path, annotation_round=1)
    assert not path.exists()


def test_suggestions_never_create_responses_and_skip_human_drafts(tmp_path):
    client = FakeArgillaClient()
    path = tmp_path / "input.jsonl"
    path.write_text(json.dumps(record()) + "\n")
    result = import_review_tasks(client=client, input_path=path, workspace_name="news-intelligence-m1")
    row = client.records[result["dataset_id"]][0]
    assert row["responses"] == []
    row["responses"] = [{"status": "draft", "values": {"review_action": {"value": "EDIT"}}}]
    original = deepcopy(row)
    result = populate_review_suggestions(client=client, dataset_id=result["dataset_id"])
    assert result == {"suggestions_added": 0, "reviewed_records_skipped": 1}
    assert row == original


def test_native_suggestion_conflict_is_not_overwritten(tmp_path):
    client = FakeArgillaClient()
    path = tmp_path / "input.jsonl"
    path.write_text(json.dumps(record()) + "\n")
    result = import_review_tasks(client=client, input_path=path, workspace_name="news-intelligence-m1")
    row = client.records[result["dataset_id"]][0]
    row["suggestions"][0]["value"] = "invalid"
    original = deepcopy(row)
    with pytest.raises(ValueError, match="conflicts"):
        populate_review_suggestions(client=client, dataset_id=result["dataset_id"])
    assert row == original


def test_blind_import_has_no_native_suggestions(tmp_path):
    client = FakeArgillaClient()
    path = tmp_path / "blind.jsonl"
    path.write_text(json.dumps(record("BLIND_VALIDATION")) + "\n")
    result = import_review_tasks(client=client, input_path=path, workspace_name="news-intelligence-m1")
    row = client.records[result["dataset_id"]][0]
    assert row["suggestions"] == [] and row["responses"] == []
