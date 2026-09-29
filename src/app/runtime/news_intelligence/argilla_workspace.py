from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from src.app.runtime.news_intelligence.argilla_exchange import (
    annotation_schema,
    normalize_argilla_export,
)
from src.biz.services.wealth.news_intelligence.policy import (
    EVENT_TYPE_NAMES,
    EVENT_TYPES,
    FOCUSED_SUBTOPIC_NAMES,
    FOCUSED_SUBTOPICS,
    PRIMARY_TOPIC_NAMES,
    PRIMARY_TOPICS,
    TAXONOMY_VERSION,
)


ARGILLA_SCHEMA_VERSION = "news-intelligence-argilla-v1"
ARGILLA_MAX_RECORDS = 1_000
ARGILLA_BATCH_SIZE = 500
ARGILLA_DATASET_NAMES = {
    "TUTORIAL": "m1-taxonomy-v2-candidate-1-tutorial",
    "BLIND_PILOT": "m1-taxonomy-v2-candidate-1-blind",
}


class ArgillaContractError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ArgillaImportResult:
    workspace_id: str
    dataset_ids: Mapping[str, str]
    imported: Mapping[str, int]
    already_present: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class ArgillaExportResult:
    dataset_id: str
    submitted_records: int
    output_path: Path


class ArgillaHttpClient:
    def __init__(self, *, api_url: str, api_key: str, timeout_seconds: float = 30.0):
        parsed = urlparse(api_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise ValueError("M1 Argilla API must use a loopback URL")
        if not api_key:
            raise ValueError("Argilla API key is required")
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, object] | None = None,
        query: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        url = f"{self._api_url}/{path.lstrip('/')}"
        if query:
            encoded = urlencode(
                [(key, value) for key, value in query.items() if value is not None],
                doseq=True,
            )
            if encoded:
                url = f"{url}?{encoded}"
        payload = None
        headers = {
            "Accept": "application/json",
            "X-Argilla-Api-Key": self._api_key,
        }
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=payload, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                content = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:2_000]
            raise ArgillaContractError(
                f"Argilla {method} {path} failed with HTTP {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise ArgillaContractError(
                f"Argilla {method} {path} failed: {exc.reason}"
            ) from exc
        if not content:
            return {}
        decoded = json.loads(content)
        if not isinstance(decoded, Mapping):
            raise ArgillaContractError(
                f"Argilla {method} {path} returned a non-object response"
            )
        return decoded


def import_annotation_tasks(
    *,
    client: ArgillaHttpClient,
    input_path: Path,
    workspace_name: str,
) -> ArgillaImportResult:
    records = _read_import_records(input_path)
    workspace_id = _workspace_id(client, workspace_name)
    grouped = {
        group: tuple(record for record in records if _sample_group(record) == group)
        for group in ARGILLA_DATASET_NAMES
    }
    dataset_ids: dict[str, str] = {}
    imported: dict[str, int] = {}
    already_present: dict[str, int] = {}
    for sample_group, dataset_name in ARGILLA_DATASET_NAMES.items():
        group_records = grouped[sample_group]
        if not group_records:
            raise ArgillaContractError(f"no records found for {sample_group}")
        dataset_id = _get_or_create_dataset(
            client,
            workspace_id=workspace_id,
            dataset_name=dataset_name,
            sample_group=sample_group,
        )
        existing = {
            str(record["external_id"]): record
            for record in _list_records(client, dataset_id=dataset_id)
        }
        missing: list[Mapping[str, object]] = []
        for record in group_records:
            external_id = str(record["external_id"])
            current = existing.get(external_id)
            if current is None:
                missing.append(_record_for_argilla(record))
                continue
            _assert_same_frozen_input(current, record)
        for batch in _batched(missing, ARGILLA_BATCH_SIZE):
            client.request(
                "POST",
                f"datasets/{dataset_id}/records/bulk",
                body={"items": list(batch)},
            )
        final_records = _list_records(client, dataset_id=dataset_id)
        final_external_ids = {str(record["external_id"]) for record in final_records}
        expected_ids = {str(record["external_id"]) for record in group_records}
        if not expected_ids.issubset(final_external_ids):
            missing_ids = sorted(expected_ids - final_external_ids)
            raise ArgillaContractError(
                "Argilla import verification failed for "
                f"{dataset_name}: {missing_ids[:5]}"
            )
        dataset_ids[sample_group] = dataset_id
        imported[sample_group] = len(missing)
        already_present[sample_group] = len(group_records) - len(missing)
    return ArgillaImportResult(
        workspace_id=workspace_id,
        dataset_ids=dataset_ids,
        imported=imported,
        already_present=already_present,
    )


def export_submitted_annotations(
    *,
    client: ArgillaHttpClient,
    dataset_id: str,
    output_path: Path,
    annotation_round: int,
) -> ArgillaExportResult:
    if annotation_round < 1:
        raise ValueError("annotation_round must be positive")
    normalized: list[Mapping[str, object]] = []
    for record in _list_records(client, dataset_id=dataset_id, include_responses=True):
        responses = record.get("responses")
        if not isinstance(responses, Sequence):
            continue
        submitted = [
            response
            for response in responses
            if isinstance(response, Mapping) and response.get("status") == "submitted"
        ]
        if not submitted:
            continue
        latest = max(submitted, key=lambda item: str(item.get("updated_at") or ""))
        values = latest.get("values")
        if not isinstance(values, Mapping):
            raise ArgillaContractError("submitted Argilla response has no values")
        flattened = {
            name: value["value"]
            for name, value in values.items()
            if isinstance(name, str)
            and isinstance(value, Mapping)
            and "value" in value
        }
        reviewer_id = latest.get("user_id")
        if not isinstance(reviewer_id, str) or not reviewer_id:
            raise ArgillaContractError("submitted Argilla response has no user_id")
        normalized.append(
            normalize_argilla_export(
                {
                    "metadata": record.get("metadata"),
                    "response": {
                        **flattened,
                        "argilla_dataset_id": dataset_id,
                        "argilla_record_id": record.get("id"),
                    },
                },
                reviewer_id=reviewer_id,
                annotation_round=annotation_round,
                submitted_at=str(latest.get("updated_at") or ""),
            )
        )
    normalized.sort(key=lambda item: str(item["sample_id"]))
    _atomic_write_jsonl(output_path, normalized)
    return ArgillaExportResult(
        dataset_id=dataset_id,
        submitted_records=len(normalized),
        output_path=output_path,
    )


def _read_import_records(path: Path) -> tuple[Mapping[str, object], ...]:
    records: list[Mapping[str, object]] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, Mapping):
                raise ArgillaContractError(f"line {line_number} is not an object")
            external_id = record.get("external_id")
            metadata = record.get("metadata")
            fields = record.get("fields")
            if (
                not isinstance(external_id, str)
                or not external_id.startswith("m1:")
                or external_id in seen
            ):
                raise ArgillaContractError(
                    f"line {line_number} has an invalid or duplicate external_id"
                )
            if not isinstance(metadata, Mapping) or not isinstance(fields, Mapping):
                raise ArgillaContractError(
                    f"line {line_number} must contain fields and metadata objects"
                )
            if metadata.get("sample_id") != external_id:
                raise ArgillaContractError(
                    f"line {line_number} sample_id does not match external_id"
                )
            input_hash = metadata.get("input_hash")
            if (
                not isinstance(input_hash, str)
                or len(input_hash) != 64
                or any(character not in "0123456789abcdef" for character in input_hash)
            ):
                raise ArgillaContractError(
                    f"line {line_number} has an invalid input_hash"
                )
            if metadata.get("taxonomy_version") != TAXONOMY_VERSION:
                raise ArgillaContractError(
                    f"line {line_number} taxonomy_version does not match "
                    f"{TAXONOMY_VERSION}"
                )
            _sample_group(record)
            seen.add(external_id)
            records.append(record)
            if len(records) > ARGILLA_MAX_RECORDS:
                raise ArgillaContractError(
                    f"Argilla input exceeds the {ARGILLA_MAX_RECORDS}-record M1 limit"
                )
    if not records:
        raise ArgillaContractError("Argilla input is empty")
    return tuple(records)


def _sample_group(record: Mapping[str, object]) -> str:
    metadata = record.get("metadata")
    sample_group = (
        metadata.get("sample_group") if isinstance(metadata, Mapping) else None
    )
    if sample_group not in ARGILLA_DATASET_NAMES:
        raise ArgillaContractError(f"unsupported sample_group: {sample_group!r}")
    return str(sample_group)


def _workspace_id(client: ArgillaHttpClient, workspace_name: str) -> str:
    response = client.request("GET", "me/workspaces")
    items = response.get("items")
    if not isinstance(items, Sequence):
        raise ArgillaContractError("Argilla workspace list is malformed")
    matches = [
        item
        for item in items
        if isinstance(item, Mapping) and item.get("name") == workspace_name
    ]
    if len(matches) != 1 or not isinstance(matches[0].get("id"), str):
        raise ArgillaContractError(
            f"expected exactly one Argilla workspace named {workspace_name!r}"
        )
    return str(matches[0]["id"])


def _get_or_create_dataset(
    client: ArgillaHttpClient,
    *,
    workspace_id: str,
    dataset_name: str,
    sample_group: str,
) -> str:
    schema = _dataset_schema(sample_group)
    schema_sha256 = _canonical_sha256(schema)
    response = client.request(
        "GET",
        "me/datasets",
        query={"workspace_id": workspace_id, "name": dataset_name},
    )
    items = response.get("items")
    if not isinstance(items, Sequence):
        raise ArgillaContractError("Argilla dataset list is malformed")
    matches = [item for item in items if isinstance(item, Mapping)]
    if len(matches) > 1:
        raise ArgillaContractError(f"duplicate Argilla dataset name: {dataset_name}")
    if matches:
        dataset = matches[0]
        metadata = dataset.get("metadata")
        if not isinstance(metadata, Mapping) or metadata.get(
            "schema_sha256"
        ) != schema_sha256:
            raise ArgillaContractError(
                f"existing Argilla dataset {dataset_name} has a different schema"
            )
        if dataset.get("status") != "ready" or not isinstance(dataset.get("id"), str):
            raise ArgillaContractError(
                f"existing Argilla dataset {dataset_name} is not ready"
            )
        return str(dataset["id"])

    dataset = client.request(
        "POST",
        "datasets",
        body={
            "name": dataset_name,
            "workspace_id": workspace_id,
            "guidelines": _guidelines(sample_group),
            "allow_extra_metadata": True,
            "metadata": {
                "schema_version": ARGILLA_SCHEMA_VERSION,
                "taxonomy_version": TAXONOMY_VERSION,
                "sample_group": sample_group,
                "schema_sha256": schema_sha256,
            },
        },
    )
    dataset_id = dataset.get("id")
    if not isinstance(dataset_id, str):
        raise ArgillaContractError("Argilla dataset creation returned no id")
    for field in schema["fields"]:
        client.request("POST", f"datasets/{dataset_id}/fields", body=field)
    for question in schema["questions"]:
        client.request("POST", f"datasets/{dataset_id}/questions", body=question)
    published = client.request("PUT", f"datasets/{dataset_id}/publish")
    if published.get("status") != "ready":
        raise ArgillaContractError(f"Argilla dataset {dataset_name} was not published")
    return dataset_id


def _dataset_schema(sample_group: str) -> Mapping[str, object]:
    primary_topic_options = _options(PRIMARY_TOPICS, PRIMARY_TOPIC_NAMES)
    subtopic_options = _options(FOCUSED_SUBTOPICS, FOCUSED_SUBTOPIC_NAMES)
    secondary_options = primary_topic_options + subtopic_options
    event_options = _options(EVENT_TYPES, EVENT_TYPE_NAMES)
    return {
        "schema_version": ARGILLA_SCHEMA_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "sample_group": sample_group,
        "annotation_contract": annotation_schema(),
        "fields": [
            _text_field("title", "新闻标题", required=True),
            _text_field("content", "新闻正文", required=True),
            _text_field("source_type", "来源类型"),
            _text_field("source_name", "来源名称"),
            _text_field("business_time", "业务时间"),
            _text_field("content_date", "内容日期"),
        ],
        "questions": [
            _label_question(
                "classification_status",
                "内容与分类状态",
                [
                    ("CLASSIFIED", "正常且可分类"),
                    ("UNRESOLVED", "信息不足，无法可靠分类"),
                    ("AMBIGUOUS", "多个叙事中心，边界不清"),
                    ("NOT_NEWS", "非新闻内容"),
                    ("MIXED_CONTENT", "拼接了多条互不相关新闻"),
                    ("INVALID_CONTENT", "正文异常或不可用"),
                ],
                required=True,
            ),
            _label_question(
                "primary_topic", "主一级主题", primary_topic_options
            ),
            _label_question(
                "primary_subtopic", "主二级主题（适用时）", subtopic_options
            ),
            _multi_label_question(
                "secondary_topics",
                "副主题（最多两个）",
                secondary_options,
            ),
            _label_question(
                "event_type_status",
                "事件类型状态",
                [
                    ("CLASSIFIED", "适用且可以分类"),
                    ("NOT_APPLICABLE", "本期事件类型不适用"),
                    ("UNRESOLVED", "应有事件类型但证据不足"),
                ],
                required=True,
            ),
            _label_question("primary_event_type", "主事件类型", event_options),
            _multi_label_question(
                "related_event_types",
                "关联事件类型（最多两个）",
                event_options,
            ),
            _text_question("actors", "事件主体（用中文逗号分隔）"),
            _text_question(
                "affected_entities", "直接受影响对象（用中文逗号分隔）"
            ),
            _text_question(
                "industries", "行业与产业链（用中文逗号分隔）"
            ),
            _text_question(
                "instruments", "资产与金融工具（用中文逗号分隔）"
            ),
            _text_question("regions", "国家与地区（用中文逗号分隔）"),
            _text_question("markets", "交易市场（用中文逗号分隔）"),
            _label_question(
                "impact_scope",
                "影响范围",
                [
                    ("SYSTEMIC_NATIONAL", "全国或系统性"),
                    ("CROSS_MARKET", "跨市场"),
                    ("WHOLE_MARKET", "全市场"),
                    ("MULTI_INDUSTRY", "多行业"),
                    ("SINGLE_INDUSTRY", "单行业"),
                    ("SINGLE_COMPANY", "单公司"),
                    ("LOCAL", "局部"),
                    ("UNKNOWN", "不明"),
                ],
                required=True,
            ),
            _label_question(
                "confidence",
                "标注确定度",
                [
                    ("CERTAIN", "确定"),
                    ("MOSTLY_CERTAIN", "基本确定"),
                    ("UNCERTAIN", "不确定"),
                    ("TAXONOMY_GAP", "分类体系缺项"),
                ],
                required=True,
            ),
            _label_question(
                "importance_level",
                "重要度档位",
                [
                    ("CRITICAL", "重大"),
                    ("HIGH", "高"),
                    ("MEDIUM", "中"),
                    ("LOW", "低"),
                ],
                required=True,
            ),
            _text_question("importance_evidence", "重要度判断证据"),
            _label_question(
                "should_top_15",
                "本窗口是否应进入 Top 15",
                [("YES", "是"), ("NO", "否"), ("UNSURE", "无法判断")],
                required=True,
            ),
            _label_question(
                "same_event",
                "与候选新闻是否同一事件",
                [
                    ("NOT_APPLICABLE", "当前没有候选新闻"),
                    ("SAME_EVENT", "同一事件"),
                    ("DIFFERENT_EVENT", "不同事件"),
                    ("UNSURE", "无法判断"),
                ],
                required=True,
            ),
            _label_question(
                "summary_fact_check",
                "摘要事实核验",
                [
                    ("NOT_APPLICABLE", "当前没有摘要"),
                    ("NO_ERROR", "未发现错误"),
                    ("NUMBER_OR_ENTITY_ERROR", "数字或实体错误"),
                    ("UNSUPPORTED_FACT", "存在原文不支持的事实"),
                    ("OTHER_ERROR", "其他错误"),
                ],
                required=True,
            ),
            _text_question("note", "边界、缺项或混淆备注"),
        ],
    }


def _text_field(
    name: str, title: str, *, required: bool = False
) -> Mapping[str, object]:
    return {
        "name": name,
        "title": title,
        "required": required,
        "settings": {"type": "text", "use_markdown": False},
    }


def _label_question(
    name: str,
    title: str,
    options: Sequence[tuple[str, str]],
    *,
    required: bool = False,
) -> Mapping[str, object]:
    return {
        "name": name,
        "title": title,
        "required": required,
        "settings": {
            "type": "label_selection",
            "options": [
                {"value": value, "text": text} for value, text in options
            ],
        },
    }


def _multi_label_question(
    name: str, title: str, options: Sequence[tuple[str, str]]
) -> Mapping[str, object]:
    return {
        "name": name,
        "title": title,
        "required": False,
        "settings": {
            "type": "multi_label_selection",
            "options": [
                {"value": value, "text": text} for value, text in options
            ],
        },
    }


def _text_question(name: str, title: str) -> Mapping[str, object]:
    return {
        "name": name,
        "title": title,
        "required": False,
        "settings": {"type": "text", "use_markdown": False},
    }


def _options(
    values: Sequence[str], names: Mapping[str, str]
) -> list[tuple[str, str]]:
    return [(value, names[value]) for value in values]


def _guidelines(sample_group: str) -> str:
    prefix = (
        "这是教学/讨论样本，不计入一致性指标。"
        if sample_group == "TUTORIAL"
        else "这是盲标样本；不要参考模型输出或重要度建议。"
    )
    return (
        f"{prefix}\n\n"
        "按顺序判断内容状态、主/副主题、事件类型、主体与影响对象、"
        "影响范围、确定度和重要度。主主题只选一个，副主题和关联"
        "事件类型最多各选两个。无候选新闻或摘要时，相应问题选择"
        "“不适用”。分类体系没有合适答案时，选择 UNRESOLVED 或"
        "taxonomy 缺项并在备注写明边界，不要自行创建新标签。"
    )


def _record_for_argilla(record: Mapping[str, object]) -> Mapping[str, object]:
    fields = record["fields"]
    metadata = record["metadata"]
    assert isinstance(fields, Mapping)
    assert isinstance(metadata, Mapping)
    return {
        "external_id": record["external_id"],
        "fields": {
            key: "" if value is None else str(value) for key, value in fields.items()
        },
        "metadata": dict(metadata),
    }


def _assert_same_frozen_input(
    current: Mapping[str, object], expected: Mapping[str, object]
) -> None:
    current_metadata = current.get("metadata")
    expected_metadata = expected.get("metadata")
    if not isinstance(current_metadata, Mapping) or not isinstance(
        expected_metadata, Mapping
    ):
        raise ArgillaContractError("existing Argilla record has malformed metadata")
    if current_metadata.get("input_hash") != expected_metadata.get("input_hash"):
        raise ArgillaContractError(
            f"Argilla record {expected.get('external_id')} has a different input_hash"
        )


def _list_records(
    client: ArgillaHttpClient,
    *,
    dataset_id: str,
    include_responses: bool = False,
) -> tuple[Mapping[str, object], ...]:
    records: list[Mapping[str, object]] = []
    offset = 0
    while True:
        query: dict[str, object] = {"offset": offset, "limit": ARGILLA_BATCH_SIZE}
        if include_responses:
            query["include"] = "responses"
        response = client.request(
            "GET", f"datasets/{dataset_id}/records", query=query
        )
        items = response.get("items")
        if not isinstance(items, Sequence):
            raise ArgillaContractError("Argilla record list is malformed")
        page = tuple(item for item in items if isinstance(item, Mapping))
        records.extend(page)
        if len(page) < ARGILLA_BATCH_SIZE:
            break
        offset += len(page)
        if offset >= ARGILLA_MAX_RECORDS:
            break
    if len(records) > ARGILLA_MAX_RECORDS:
        raise ArgillaContractError(
            f"Argilla dataset exceeds the {ARGILLA_MAX_RECORDS}-record M1 limit"
        )
    return tuple(records)


def _batched(
    values: Sequence[Mapping[str, object]], batch_size: int
) -> Iterable[Sequence[Mapping[str, object]]]:
    for start in range(0, len(values), batch_size):
        yield values[start : start + batch_size]


def _canonical_sha256(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_write_jsonl(
    output_path: Path, records: Sequence[Mapping[str, object]]
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        delete=False,
    ) as handle:
        temporary_path = Path(handle.name)
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
    temporary_path.replace(output_path)
