from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

from src.biz.services.wealth.news_intelligence.contracts import as_jsonable
from src.biz.services.wealth.news_intelligence.policy import (
    EVENT_TYPES,
    FOCUSED_SUBTOPICS,
    PRIMARY_TOPICS,
    TAXONOMY_VERSION,
)
from src.biz.services.wealth.news_intelligence.sampling import SampleSelection


def build_argilla_import_record(selection: SampleSelection) -> dict[str, object]:
    item = selection.item
    return {
        "external_id": item.sample_id,
        "fields": {
            "title": item.title,
            "content": item.content,
            "source_type": item.source_type.value,
            "source_name": item.source_name,
            "business_time": item.published_at.isoformat()
            if item.published_at
            else None,
            "content_date": item.content_date.isoformat()
            if item.content_date
            else None,
        },
        "metadata": {
            "sample_id": item.sample_id,
            "input_hash": item.input_hash,
            "taxonomy_version": TAXONOMY_VERSION,
            "sample_group": selection.sample_group,
            "stratum": selection.stratum,
            "selection_probability": selection.selection_probability,
            "enrichment_reason": selection.enrichment_reason,
        },
    }


def annotation_schema() -> dict[str, object]:
    return {
        "schema_version": "news-intelligence-argilla-v1",
        "taxonomy_version": TAXONOMY_VERSION,
        "primary_topics": list(PRIMARY_TOPICS),
        "focused_subtopics": list(FOCUSED_SUBTOPICS),
        "event_types": list(EVENT_TYPES),
        "classification_statuses": [
            "CLASSIFIED",
            "UNRESOLVED",
            "AMBIGUOUS",
            "NOT_NEWS",
            "MIXED_CONTENT",
            "INVALID_CONTENT",
        ],
        "event_type_statuses": ["CLASSIFIED", "NOT_APPLICABLE", "UNRESOLVED"],
        "confidence_values": ["CERTAIN", "MOSTLY_CERTAIN", "UNCERTAIN", "TAXONOMY_GAP"],
        "impact_scopes": [
            "SYSTEMIC_NATIONAL",
            "CROSS_MARKET",
            "WHOLE_MARKET",
            "MULTI_INDUSTRY",
            "SINGLE_INDUSTRY",
            "SINGLE_COMPANY",
            "LOCAL",
            "UNKNOWN",
        ],
    }


def normalize_argilla_export(
    record: Mapping[str, object],
    *,
    reviewer_id: str,
    annotation_round: int,
    submitted_at: str | None = None,
) -> dict[str, object]:
    metadata = record.get("metadata")
    response = record.get("response")
    if not isinstance(metadata, Mapping) or not isinstance(response, Mapping):
        raise ValueError("Argilla export requires metadata and response objects")
    sample_id = metadata.get("sample_id")
    input_hash = metadata.get("input_hash")
    if not isinstance(sample_id, str) or not sample_id.startswith("m1:"):
        raise ValueError("Argilla export is missing a valid stable sample_id")
    if not isinstance(input_hash, str) or len(input_hash) != 64:
        raise ValueError("Argilla export is missing a valid input_hash")
    normalized = {
        "sample_id": sample_id,
        "input_hash": input_hash,
        "taxonomy_version": metadata.get("taxonomy_version"),
        "reviewer_id": reviewer_id,
        "annotation_round": annotation_round,
        "submitted_at": submitted_at or datetime.now(timezone.utc).isoformat(),
        **dict(response),
    }
    return as_jsonable(normalized)  # type: ignore[return-value]
