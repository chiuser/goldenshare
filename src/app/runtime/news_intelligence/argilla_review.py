"""Argilla v3 review transport. Frozen v2 datasets are never mutated."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from src.biz.services.wealth.news_intelligence.policy import EVENT_TYPE_NAMES
from src.biz.services.wealth.news_intelligence.review_policy import (
    ASSISTED_ROLES, BLIND_ROLES, INDUSTRIES, INDUSTRY_VERSION, INTERESTS,
    INTEREST_VERSION, REVIEW_SCHEMA_VERSION, REVIEW_TAXONOMY_VERSION,
    REVIEW_FIELDS, resolve_review, topic_options, validate_prediction,
)
from .argilla_workspace import (
    ArgillaContractError, ArgillaHttpClient, _atomic_write_jsonl, _canonical_sha256,
    _label_question, _list_records, _multi_label_question, _text_field,
    _text_question, _workspace_id,
)

VERSIONS = {"taxonomy_version": REVIEW_TAXONOMY_VERSION,
            "industry_version": INDUSTRY_VERSION, "interest_version": INTEREST_VERSION,
            "schema_version": REVIEW_SCHEMA_VERSION}


def review_schema(role: str) -> dict[str, object]:
    if role not in ASSISTED_ROLES | BLIND_ROLES:
        raise ValueError("invalid evaluation role")
    blind = role in BLIND_ROLES
    actions = [("LABEL", "独立填写答案"), ("UNRESOLVED", "无法判断或选项有问题")] if blind else [
        ("ACCEPT", "全部正确，接受建议"), ("EDIT", "有错误，只修改错项"),
        ("UNRESOLVED", "无法判断或建议无效")]
    fields = [_text_field("title", "新闻标题", required=True),
              _text_field("content", "新闻原文", required=True)]
    if not blind:
        fields.append(_text_field("machine_proposal", "机器建议与原文证据", required=True))
    return {"versions": VERSIONS, "evaluation_role": role, "fields": fields,
            "questions": [
                _label_question("review_action", "审核动作", actions, required=True),
                _label_question("classification_status", "内容与分类状态", [
                    ("CLASSIFIED", "正常且可分类"), ("UNRESOLVED", "信息不足"),
                    ("AMBIGUOUS", "主题边界不清"), ("NOT_NEWS", "非新闻"),
                    ("MIXED_CONTENT", "多条内容拼接"), ("INVALID_CONTENT", "内容异常")]),
                _label_question("topic_path", "主主题（完整路径）", list(topic_options().items())),
                _multi_label_question("secondary_topics", "副主题（最多两个）", list(topic_options().items())),
                _label_question("industry_status", "行业适用状态", [
                    ("SPECIFIC", "具体行业"), ("CROSS_INDUSTRY", "跨行业"),
                    ("NONE", "无具体行业"), ("UNKNOWN", "无法判断")]),
                _multi_label_question("industries", "行业领域", list(INDUSTRIES.items())),
                _multi_label_question("interest_tags", "重点关注方向", list(INTERESTS.items())),
                _label_question("event_type_status", "事件类型适用状态", [
                    ("CLASSIFIED", "适用且可分类"), ("NOT_APPLICABLE", "不适用"),
                    ("UNRESOLVED", "证据不足")]),
                _label_question("primary_event_type", "主事件类型", list(EVENT_TYPE_NAMES.items())),
                _label_question("importance_tier", "重要度档位", [
                    ("HIGH", "高"), ("MEDIUM", "中"), ("LOW", "低"), ("UNKNOWN", "无法判断")]),
                _multi_label_question("clear_fields", "清空原建议（仅修改时使用）", [
                    ("secondary_topics", "清空副主题"), ("industries", "清空行业"),
                    ("interest_tags", "清空关注标签")]),
                _label_question("issue_reason", "无法判断原因", [
                    ("SOURCE_INSUFFICIENT", "原文信息不足"), ("LABEL_GAP", "选项缺失"),
                    ("DEFINITION_CONFLICT", "定义冲突"), ("MODEL_INVALID", "机器建议无效")]),
                _text_question("note", "纠偏备注（选填）"),
            ]}


def prepare_review_record(record: Mapping[str, object]) -> dict[str, object]:
    metadata, fields = record.get("metadata"), record.get("fields")
    if not isinstance(metadata, Mapping) or not isinstance(fields, Mapping):
        raise ValueError("review record requires fields and metadata")
    sample_id, input_hash = metadata.get("sample_id"), metadata.get("input_hash")
    if record.get("external_id") != sample_id or not isinstance(sample_id, str) or not sample_id.startswith("m1:"):
        raise ValueError("invalid sample_id")
    if not isinstance(input_hash, str) or len(input_hash) != 64 or any(c not in "0123456789abcdef" for c in input_hash):
        raise ValueError("invalid input_hash")
    if any(metadata.get(key) != value for key, value in VERSIONS.items()):
        raise ValueError("review policy version mismatch")
    role = metadata.get("evaluation_role")
    if role not in ASSISTED_ROLES | BLIND_ROLES:
        raise ValueError("invalid evaluation role")
    title, content = fields.get("title"), fields.get("content")
    if not isinstance(title, str) or not isinstance(content, str) or not (title.strip() or content.strip()):
        raise ValueError("review requires nonempty original text")
    prediction = record.get("machine_prediction")
    output_fields = {"title": title, "content": content}
    output_metadata = dict(metadata)
    if role in BLIND_ROLES:
        if prediction is not None or set(fields) - {"title", "content"} or metadata.get("prediction_exposed") is not False:
            raise ValueError("blind input must not carry a prediction or extra display fields")
        if set(metadata) - {*VERSIONS, "sample_id", "input_hash", "evaluation_role", "prediction_exposed"}:
            raise ValueError("blind metadata must not carry hidden model hints")
    else:
        if not isinstance(prediction, Mapping):
            raise ValueError("assisted input requires a machine prediction")
        prediction = validate_prediction(prediction, title + "\n" + content)
        output_metadata["prediction_exposed"] = True
        output_metadata["machine_prediction"] = prediction
        output_fields["machine_proposal"] = _display_prediction(prediction)
    result = {"external_id": sample_id, "fields": output_fields, "metadata": output_metadata}
    output_metadata["review_input_sha256"] = _canonical_sha256(result)
    return result


def _display_prediction(prediction):
    values, evidence = prediction["values"], prediction["evidence"]
    labels = {"topic_path": topic_options(), "secondary_topics": topic_options(),
              "industries": INDUSTRIES, "interest_tags": INTERESTS,
              "primary_event_type": EVENT_TYPE_NAMES}
    rows = [f"模型revision：{prediction['model_revision']}；提示词：{prediction['prompt_version']}",
            "全部正确只选‘接受建议’；修改时只填写错项。移除全部标签使用‘清空原建议’；清空事件需选择不适用。"]
    rows.extend(str(warning) for warning in prediction.get("warnings", []))
    names = {"classification_status": "内容状态", "topic_path": "主主题", "secondary_topics": "副主题", "industry_status": "行业状态",
             "industries": "行业", "interest_tags": "关注方向", "event_type_status": "事件状态",
             "primary_event_type": "事件类型", "importance_tier": "重要度"}
    for field, value in values.items():
        mapping = labels.get(field, {})
        display = "、".join(mapping.get(v, v) for v in value) if isinstance(value, list) else mapping.get(value, value)
        rows.append(f"{names[field]}：{display or '无'}\n依据[{evidence[field]['source']}]：{evidence[field]['quote']}")
        if evidence[field].get("matched_quotes"):
            rows.append("字面匹配证据：" + json.dumps(evidence[field]["matched_quotes"], ensure_ascii=False))
    return "\n\n".join(rows)


def import_review_tasks(*, client: ArgillaHttpClient, input_path: Path, workspace_name: str) -> dict[str, object]:
    records = []
    with input_path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(prepare_review_record(json.loads(line)))
            if len(records) > 1_000:
                raise ValueError("review input exceeds 1000 records")
    if not records or len({r["external_id"] for r in records}) != len(records):
        raise ValueError("empty or duplicate review input")
    roles = {r["metadata"]["evaluation_role"] for r in records}
    if len(roles) != 1:
        raise ValueError("each review import must have exactly one evaluation role")
    role = roles.pop()
    schema = review_schema(role)
    schema_hash = _canonical_sha256(schema)
    workspace_id = _workspace_id(client, workspace_name)
    name = f"m1-taxonomy-v3-candidate-1-{role.lower().replace('_', '-')}"
    datasets = client.request("GET", "me/datasets", query={"workspace_id": workspace_id, "name": name}).get("items", [])
    if len(datasets) > 1:
        raise ArgillaContractError("duplicate v3 review dataset")
    if datasets:
        dataset = datasets[0]
        if dataset.get("status") != "ready" or dataset.get("metadata", {}).get("schema_sha256") != schema_hash:
            raise ArgillaContractError("v3 dataset schema conflict or not ready")
    else:
        dataset = client.request("POST", "datasets", body={
            "name": name, "workspace_id": workspace_id, "allow_extra_metadata": True,
            "metadata": {**VERSIONS, "schema_sha256": schema_hash, "evaluation_role": role},
            "guidelines": "独立任务不显示机器建议。辅助审核：全部正确只选接受；有错只改错项；无法判断选择原因。缺少比较材料不判断排名、重复或摘要。"})
        dataset_id = dataset["id"]
        for kind in ("fields", "questions"):
            for definition in schema[kind]:
                client.request("POST", f"datasets/{dataset_id}/{kind}", body=definition)
        dataset = client.request("PUT", f"datasets/{dataset_id}/publish")
        if dataset.get("status") != "ready":
            raise ArgillaContractError("review dataset publish failed")
    dataset_id = dataset["id"]
    current = {r["external_id"]: r for r in _list_records(client, dataset_id=dataset_id)}
    if len(set(current) | {r["external_id"] for r in records}) > 1_000:
        raise ValueError("review dataset exceeds 1000 records")
    missing = []
    for record in records:
        old = current.get(record["external_id"])
        if old is None:
            missing.append(record)
        elif old.get("metadata", {}).get("review_input_sha256") != record["metadata"]["review_input_sha256"]:
            raise ArgillaContractError("frozen content/prediction conflict; refusing overwrite")
    for start in range(0, len(missing), 100):
        client.request("POST", f"datasets/{dataset_id}/records/bulk", body={"items": missing[start:start + 100]})
    final = {r["external_id"]: r for r in _list_records(client, dataset_id=dataset_id)}
    if any(final.get(r["external_id"], {}).get("metadata", {}).get("review_input_sha256") != r["metadata"]["review_input_sha256"] for r in records):
        raise ArgillaContractError("review import readback failed")
    suggestions = populate_review_suggestions(client=client, dataset_id=dataset_id)
    return {"dataset_id": dataset_id, "dataset_name": name, "imported": len(missing),
            "already_present": len(records) - len(missing), **suggestions}


def populate_review_suggestions(*, client: ArgillaHttpClient, dataset_id: str) -> dict[str, int]:
    """Project frozen predictions into native controls, never into human responses."""
    questions = client.request("GET", f"datasets/{dataset_id}/questions")["items"]
    question_ids = {question["name"]: question["id"] for question in questions}
    plans = []
    skipped = 0
    for record in _list_records(client, dataset_id=dataset_id, include_responses=True):
        metadata = record.get("metadata", {})
        if any(metadata.get(key) != value for key, value in VERSIONS.items()):
            raise ValueError("native suggestions require a v3 review dataset")
        role = metadata.get("evaluation_role")
        existing = client.request("GET", f"records/{record['id']}/suggestions")["items"]
        if role in BLIND_ROLES:
            if existing or metadata.get("machine_prediction") is not None:
                raise ValueError("blind review must have no suggestions")
            continue
        if role not in ASSISTED_ROLES:
            raise ValueError("invalid evaluation role")
        # Even a draft belongs to the human. Never change their working context.
        if record.get("responses"):
            skipped += 1
            continue
        fields = record["fields"]
        prediction = validate_prediction(metadata["machine_prediction"], fields["title"] + "\n" + fields["content"])
        current = {suggestion["question_id"]: suggestion for suggestion in existing}
        expected = []
        for field in REVIEW_FIELDS:
            value = prediction["values"][field]
            if value is None or value == []:
                # Argilla 2.8 rejects empty multi-label suggestions. Empty/unknown
                # choices stay blank; never invent a label to make the API accept it.
                continue
            if field not in question_ids:
                raise ValueError(f"review schema is missing {field}")
            producer = prediction["evidence"][field]["source"].lower()
            suggestion = {"question_id": question_ids[field], "value": value,
                          "type": "model", "agent": f"news-intelligence-v3-{producer}"}
            old = current.get(suggestion["question_id"])
            if old is not None and any(old.get(key) != val for key, val in suggestion.items()):
                raise ValueError("existing native suggestion conflicts with frozen prediction")
            expected.append(suggestion)
        plans.append((record["id"], expected, current))
    added = 0
    # All contracts/conflicts are checked before writing the first record.
    for record_id, expected, current in plans:
        for suggestion in expected:
            if suggestion["question_id"] not in current:
                client.request("PUT", f"records/{record_id}/suggestions", body=suggestion)
                added += 1
        actual = {s["question_id"]: s for s in client.request("GET", f"records/{record_id}/suggestions")["items"]}
        if any(any(actual.get(s["question_id"], {}).get(k) != v for k, v in s.items()) for s in expected):
            raise ArgillaContractError("native suggestions readback failed")
    return {"suggestions_added": added, "reviewed_records_skipped": skipped}


def export_reviews(*, client: ArgillaHttpClient, dataset_id: str, output_path: Path, annotation_round: int) -> dict[str, object]:
    if annotation_round < 1 or output_path.exists():
        raise ValueError("positive annotation_round and a new output path are required")
    output = []
    for record in _list_records(client, dataset_id=dataset_id, include_responses=True):
        metadata = record.get("metadata", {})
        if any(metadata.get(k) != v for k, v in VERSIONS.items()):
            raise ValueError("not a v3 review record")
        submitted = [r for r in record.get("responses", []) if r.get("status") == "submitted"]
        if not submitted:
            continue
        latest = max(submitted, key=lambda r: r.get("updated_at") or "")
        if not latest.get("user_id") or not latest.get("updated_at"):
            raise ValueError("submitted review lacks reviewer or timestamp")
        response = {k: v["value"] for k, v in latest["values"].items() if "value" in v}
        original_response = dict(response)
        clear_fields = response.pop("clear_fields", [])
        if not isinstance(clear_fields, list) or any(k not in {"secondary_topics", "industries", "interest_tags"} for k in clear_fields):
            raise ValueError("invalid fields to clear")
        if clear_fields and response.get("review_action") != "EDIT":
            raise ValueError("only EDIT can clear original predictions")
        for key in clear_fields:
            if response.get(key):
                raise ValueError("cannot both fill and clear the same field")
            response[key] = []
        # Clearing the event is represented by changing its applicability status.
        if response.get("event_type_status") in {"NOT_APPLICABLE", "UNRESOLVED"}:
            response["primary_event_type"] = None
        if response.get("industry_status") in {"NONE", "UNKNOWN"}:
            response.setdefault("industries", [])
        if response.get("review_action") == "LABEL":
            for key in ("secondary_topics", "industries", "interest_tags"):
                response.setdefault(key, [])
            if response.get("classification_status") != "CLASSIFIED":
                response.setdefault("topic_path", None)
        fields = record["fields"]
        resolved = resolve_review(response=response, prediction=metadata.get("machine_prediction"),
                                  role=metadata["evaluation_role"], source_text=fields["title"] + "\n" + fields["content"])
        resolved["human_response"] = original_response
        output.append({**metadata, **resolved, "argilla_dataset_id": dataset_id,
                       "reviewer_id": latest["user_id"], "submitted_at": latest["updated_at"],
                       "annotation_round": annotation_round})
    _atomic_write_jsonl(output_path, sorted(output, key=lambda r: r["sample_id"]))
    return {"dataset_id": dataset_id, "submitted_records": len(output), "output_path": str(output_path)}
