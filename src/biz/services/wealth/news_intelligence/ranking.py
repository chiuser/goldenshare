from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Mapping, Sequence

from .contracts import ImportanceDimension
from .policy import DEBUG_TOP_N, DELIVERY_TOP_N


DIMENSION_LIMITS = {
    "potential_impact": 30,
    "impact_scope": 15,
    "urgency": 15,
    "user_relevance": 15,
    "novelty": 10,
    "source_corroboration": 10,
    "source_credibility": 5,
}


@dataclass(frozen=True, slots=True)
class RankedEvent:
    event_id: str
    total_score: int
    primary_topic: str
    primary_entity: str | None
    dimensions: Mapping[str, ImportanceDimension]
    raw_rank: int
    final_rank: int


def validate_dimensions(dimensions: Mapping[str, ImportanceDimension]) -> int:
    if set(dimensions) != set(DIMENSION_LIMITS):
        raise ValueError(
            "importance dimensions must contain exactly the seven frozen dimensions"
        )
    total = 0
    for name, limit in DIMENSION_LIMITS.items():
        value = dimensions[name]
        if value.score < 0 or value.score > limit:
            raise ValueError(f"importance dimension {name} exceeds 0..{limit}")
        if not value.reason.strip():
            raise ValueError(f"importance dimension {name} requires a reason")
        total += value.score
    return total


def rank_events(
    events: Sequence[tuple[str, str, str | None, Mapping[str, ImportanceDimension]]],
    *,
    max_same_topic: int = 5,
    max_same_entity: int = 3,
) -> tuple[RankedEvent, ...]:
    scored = [
        (event_id, topic, entity, dimensions, validate_dimensions(dimensions))
        for event_id, topic, entity, dimensions in events
    ]
    scored.sort(key=lambda item: (-item[4], item[0]))
    raw_rank = {item[0]: index for index, item in enumerate(scored, start=1)}
    topic_counts: Counter[str] = Counter()
    entity_counts: Counter[str] = Counter()
    accepted: list[
        tuple[str, str, str | None, Mapping[str, ImportanceDimension], int]
    ] = []
    deferred: list[
        tuple[str, str, str | None, Mapping[str, ImportanceDimension], int]
    ] = []
    for item in scored:
        _, topic, entity, _, _ = item
        if topic_counts[topic] >= max_same_topic or (
            entity and entity_counts[entity] >= max_same_entity
        ):
            deferred.append(item)
            continue
        accepted.append(item)
        topic_counts[topic] += 1
        if entity:
            entity_counts[entity] += 1
    final = (accepted + deferred)[:DEBUG_TOP_N]
    return tuple(
        RankedEvent(
            event_id=event_id,
            total_score=score,
            primary_topic=topic,
            primary_entity=entity,
            dimensions=dimensions,
            raw_rank=raw_rank[event_id],
            final_rank=index,
        )
        for index, (event_id, topic, entity, dimensions, score) in enumerate(
            final, start=1
        )
    )


def delivery_candidates(ranked: Sequence[RankedEvent]) -> tuple[RankedEvent, ...]:
    return tuple(ranked[:DELIVERY_TOP_N])
