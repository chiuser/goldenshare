from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .contracts import (
    CandidateDecision,
    CandidateStatus,
    ClassificationStatus,
    EventCluster,
    EventTypeStatus,
    FrozenNewsItem,
    LabelCandidates,
)
from .policy import (
    DEEP_ANALYSIS_LIMIT,
    build_label_candidates,
    event_type_hypothesis,
    parent_topic_for_subtopic,
    topic_hypothesis,
)
from .replay import clean_candidate, cluster_candidates, mark_exact_duplicates


class EmbeddingProvider(Protocol):
    def embed(
        self, texts: tuple[tuple[str, str], ...], *, timeout_seconds: float
    ) -> dict[str, tuple[float, ...]]: ...


class NliProvider(Protocol):
    def nli(
        self,
        requests: tuple[tuple[str, str, tuple[str, ...]], ...],
        *,
        timeout_seconds: float,
    ) -> dict[str, tuple[float, ...]]: ...


@dataclass(frozen=True, slots=True)
class LightweightEventAnalysis:
    event_id: str
    representative_sample_id: str
    candidates: LabelCandidates
    classification_status: ClassificationStatus
    primary_topic: str | None
    primary_subtopic: str | None
    topic_scores: tuple[tuple[str, float], ...]
    event_type_status: EventTypeStatus
    primary_event_type: str | None
    event_type_scores: tuple[tuple[str, float], ...]


@dataclass(frozen=True, slots=True)
class CalibrationPipelineResult:
    candidates: tuple[CandidateDecision, ...]
    events: tuple[EventCluster, ...]
    analyses: tuple[LightweightEventAnalysis, ...]
    deep_analysis_event_ids: tuple[str, ...]


def run_lightweight_pipeline(
    items: tuple[FrozenNewsItem, ...],
    *,
    embedding_provider: EmbeddingProvider,
    nli_provider: NliProvider,
    embedding_timeout_seconds: float,
    nli_timeout_seconds: float,
    classification_threshold: float = 0.5,
    clustering_threshold: float = 0.88,
) -> CalibrationPipelineResult:
    candidates = mark_exact_duplicates(
        items, tuple(clean_candidate(item) for item in items)
    )
    eligible = tuple(
        candidate
        for candidate in candidates
        if candidate.status is CandidateStatus.ELIGIBLE
    )
    embeddings = embedding_provider.embed(
        tuple(
            (candidate.sample_id, candidate.representative_text)
            for candidate in eligible
        ),
        timeout_seconds=embedding_timeout_seconds,
    )
    if set(embeddings) != {candidate.sample_id for candidate in eligible}:
        raise RuntimeError(
            "embedding stage did not return exactly one result per eligible candidate"
        )
    events = cluster_candidates(
        items, candidates, embeddings, similarity_threshold=clustering_threshold
    )
    item_by_id = {item.sample_id: item for item in items}
    candidates_by_event: dict[str, LabelCandidates] = {}
    nli_requests: list[tuple[str, str, tuple[str, ...]]] = []
    for event in events:
        representative = item_by_id[event.representative_sample_id]
        label_candidates = build_label_candidates(
            representative.title, representative.content
        )
        candidates_by_event[event.event_id] = label_candidates
        premise = f"{representative.title}\n{representative.content}"
        if label_candidates.primary_topics:
            nli_requests.append(
                (
                    f"{event.event_id}:topic",
                    premise,
                    tuple(
                        topic_hypothesis(code)
                        for code in label_candidates.primary_topics
                    ),
                )
            )
        if label_candidates.event_types:
            nli_requests.append(
                (
                    f"{event.event_id}:event",
                    premise,
                    tuple(
                        event_type_hypothesis(code)
                        for code in label_candidates.event_types
                    ),
                )
            )
    nli_scores = nli_provider.nli(
        tuple(nli_requests), timeout_seconds=nli_timeout_seconds
    )

    analyses: list[LightweightEventAnalysis] = []
    for event in events:
        label_candidates = candidates_by_event[event.event_id]
        topic_scores = _zip_scores(
            label_candidates.primary_topics,
            nli_scores.get(f"{event.event_id}:topic")
            if label_candidates.primary_topics
            else (),
            stage="topic",
        )
        event_scores = _zip_scores(
            label_candidates.event_types,
            nli_scores.get(f"{event.event_id}:event")
            if label_candidates.event_types
            else (),
            stage="event_type",
        )
        primary_topic = _best_above(topic_scores, classification_threshold)
        primary_event_type = _best_above(event_scores, classification_threshold)
        primary_subtopic = next(
            (
                code
                for code in label_candidates.matched_rules
                if primary_topic is not None
                and parent_topic_for_subtopic(code) == primary_topic
            ),
            None,
        )
        analyses.append(
            LightweightEventAnalysis(
                event_id=event.event_id,
                representative_sample_id=event.representative_sample_id,
                candidates=label_candidates,
                classification_status=(
                    ClassificationStatus.CLASSIFIED
                    if primary_topic
                    else ClassificationStatus.UNRESOLVED
                ),
                primary_topic=primary_topic,
                primary_subtopic=primary_subtopic,
                topic_scores=topic_scores,
                event_type_status=(
                    EventTypeStatus.CLASSIFIED
                    if primary_event_type
                    else EventTypeStatus.UNRESOLVED
                    if label_candidates.event_types
                    else EventTypeStatus.NOT_APPLICABLE
                ),
                primary_event_type=primary_event_type,
                event_type_scores=event_scores,
            )
        )
    deep_analysis = select_deep_analysis(
        events, tuple(analyses), candidates, limit=DEEP_ANALYSIS_LIMIT
    )
    return CalibrationPipelineResult(
        candidates=candidates,
        events=events,
        analyses=tuple(analyses),
        deep_analysis_event_ids=deep_analysis,
    )


def select_deep_analysis(
    events: tuple[EventCluster, ...],
    analyses: tuple[LightweightEventAnalysis, ...],
    candidates: tuple[CandidateDecision, ...],
    *,
    limit: int,
) -> tuple[str, ...]:
    if not 0 <= limit <= DEEP_ANALYSIS_LIMIT:
        raise ValueError(f"deep analysis limit must be in 0..{DEEP_ANALYSIS_LIMIT}")
    candidate_by_id = {candidate.sample_id: candidate for candidate in candidates}
    analysis_by_event = {analysis.event_id: analysis for analysis in analyses}
    priority_subtopics = {
        "ECONOMY.MACRO_ECONOMY",
        "ECONOMY.MONETARY_POLICY",
        "ECONOMY.CAPITAL_MARKET_REGULATION",
        "TECH.ARTIFICIAL_INTELLIGENCE",
        "TECH.SEMICONDUCTOR",
        "CONFLICT.SANCTIONS_COUNTERMEASURES",
    }
    ordered = sorted(
        events,
        key=lambda event: (
            -(analysis_by_event[event.event_id].primary_subtopic in priority_subtopics),
            -candidate_by_id[event.representative_sample_id].summary_eligible,
            -max(
                (score for _, score in analysis_by_event[event.event_id].topic_scores),
                default=0.0,
            ),
            event.event_id,
        ),
    )
    return tuple(event.event_id for event in ordered[:limit])


def _zip_scores(
    labels: tuple[str, ...], scores: tuple[float, ...] | None, *, stage: str
) -> tuple[tuple[str, float], ...]:
    if scores is None or len(labels) != len(scores):
        raise RuntimeError(f"NLI {stage} stage did not return one score per hypothesis")
    return tuple(
        sorted(zip(labels, scores, strict=True), key=lambda item: (-item[1], item[0]))
    )


def _best_above(scores: tuple[tuple[str, float], ...], threshold: float) -> str | None:
    if not scores or scores[0][1] < threshold:
        return None
    return scores[0][0]
