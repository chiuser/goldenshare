from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import random

from .contracts import CandidateDecision, FrozenNewsItem, NewsSourceType
from .policy import build_label_candidates


@dataclass(frozen=True, slots=True)
class SampleSelection:
    item: FrozenNewsItem
    decision: CandidateDecision
    sample_group: str
    stratum: str
    selection_probability: float
    enrichment_reason: str | None


def select_taxonomy_pilot(
    items: tuple[FrozenNewsItem, ...],
    decisions: tuple[CandidateDecision, ...],
    *,
    blind_per_source: int = 40,
    tutorial_size: int = 20,
    seed: str = "news-taxonomy-v2-pilot-1",
) -> tuple[SampleSelection, ...]:
    decision_by_id = {decision.sample_id: decision for decision in decisions}
    eligible_by_source: dict[NewsSourceType, list[FrozenNewsItem]] = defaultdict(list)
    for item in items:
        decision = decision_by_id[item.sample_id]
        if decision.exclusion_code is None:
            eligible_by_source[item.source_type].append(item)

    rng = random.Random(_seed_value(seed))
    blind: list[SampleSelection] = []
    remaining: list[tuple[FrozenNewsItem, CandidateDecision]] = []
    for source_type in NewsSourceType:
        source_items = eligible_by_source[source_type]
        selected = _balanced_length_sample(
            source_items, decision_by_id, blind_per_source, rng
        )
        selected_ids = {item.sample_id for item in selected}
        for item in selected:
            decision = decision_by_id[item.sample_id]
            blind.append(
                SampleSelection(
                    item=item,
                    decision=decision,
                    sample_group="BLIND_PILOT",
                    stratum=f"{source_type.value}:{_length_bucket(decision.content_length)}",
                    selection_probability=min(
                        1.0, blind_per_source / max(1, len(source_items))
                    ),
                    enrichment_reason=_priority_reason(item),
                )
            )
        remaining.extend(
            (item, decision_by_id[item.sample_id])
            for item in source_items
            if item.sample_id not in selected_ids
        )

    rng.shuffle(remaining)
    tutorial = [
        SampleSelection(
            item=item,
            decision=decision,
            sample_group="TUTORIAL",
            stratum=f"{item.source_type.value}:{_length_bucket(decision.content_length)}",
            selection_probability=min(1.0, tutorial_size / max(1, len(remaining))),
            enrichment_reason=_priority_reason(item),
        )
        for item, decision in remaining[:tutorial_size]
    ]
    return tuple(tutorial + blind)


def select_formal_calibration_set(
    items: tuple[FrozenNewsItem, ...],
    decisions: tuple[CandidateDecision, ...],
    *,
    excluded_sample_ids: frozenset[str] = frozenset(),
    quotas: dict[NewsSourceType, int] | None = None,
    seed: str = "news-taxonomy-v2-formal-1",
) -> tuple[SampleSelection, ...]:
    quotas = quotas or {
        NewsSourceType.NEWS: 320,
        NewsSourceType.MAJOR_NEWS: 320,
        NewsSourceType.CCTV_NEWS: 160,
    }
    decision_by_id = {decision.sample_id: decision for decision in decisions}
    rng = random.Random(_seed_value(seed))
    output: list[SampleSelection] = []

    for source_type, quota in quotas.items():
        population = [
            item
            for item in items
            if item.source_type is source_type
            and item.sample_id not in excluded_sample_ids
            and decision_by_id[item.sample_id].exclusion_code is None
        ]
        representative_quota = round(quota * 0.70)
        enriched_quota = quota - representative_quota
        representative = _balanced_length_sample(
            population, decision_by_id, representative_quota, rng
        )
        selected_ids = {item.sample_id for item in representative}
        priority_pool = [
            item
            for item in population
            if item.sample_id not in selected_ids and _priority_reason(item)
        ]
        rng.shuffle(priority_pool)
        enriched = priority_pool[:enriched_quota]
        if len(enriched) < enriched_quota:
            fallback = [
                item
                for item in population
                if item.sample_id not in selected_ids and item not in enriched
            ]
            rng.shuffle(fallback)
            enriched.extend(fallback[: enriched_quota - len(enriched)])

        for item in representative:
            decision = decision_by_id[item.sample_id]
            output.append(
                SampleSelection(
                    item=item,
                    decision=decision,
                    sample_group="FORMAL_REPRESENTATIVE",
                    stratum=f"{source_type.value}:{_length_bucket(decision.content_length)}",
                    selection_probability=min(
                        1.0, representative_quota / max(1, len(population))
                    ),
                    enrichment_reason=None,
                )
            )
        for item in enriched:
            decision = decision_by_id[item.sample_id]
            output.append(
                SampleSelection(
                    item=item,
                    decision=decision,
                    sample_group="FORMAL_PRIORITY_ENRICHED",
                    stratum=f"{source_type.value}:{_length_bucket(decision.content_length)}",
                    selection_probability=min(
                        1.0, enriched_quota / max(1, len(priority_pool))
                    ),
                    enrichment_reason=_priority_reason(item),
                )
            )

    return tuple(sorted(output, key=lambda selection: selection.item.sample_id))


def _balanced_length_sample(
    items: list[FrozenNewsItem],
    decisions: dict[str, CandidateDecision],
    size: int,
    rng: random.Random,
) -> list[FrozenNewsItem]:
    buckets: dict[str, list[FrozenNewsItem]] = defaultdict(list)
    for item in items:
        buckets[_length_bucket(decisions[item.sample_id].content_length)].append(item)
    for bucket in buckets.values():
        rng.shuffle(bucket)
    selected: list[FrozenNewsItem] = []
    bucket_names = ("SHORT", "BOUNDARY", "LONG")
    while len(selected) < min(size, len(items)):
        changed = False
        for name in bucket_names:
            if buckets[name] and len(selected) < size:
                selected.append(buckets[name].pop())
                changed = True
        if not changed:
            break
    return selected


def _priority_reason(item: FrozenNewsItem) -> str | None:
    candidates = build_label_candidates(item.title, item.content)
    priority = [
        code
        for code in candidates.matched_rules
        if code
        in {
            "ECONOMY.MACRO_ECONOMY",
            "ECONOMY.MONETARY_POLICY",
            "ECONOMY.CAPITAL_MARKET_REGULATION",
            "ECONOMY.FINANCIAL_MARKETS",
            "TECH.ARTIFICIAL_INTELLIGENCE",
            "TECH.SEMICONDUCTOR",
            "CONFLICT.SANCTIONS_COUNTERMEASURES",
        }
    ]
    return priority[0] if priority else None


def _length_bucket(length: int) -> str:
    if length < 800:
        return "SHORT"
    if length <= 1_200:
        return "BOUNDARY"
    return "LONG"


def _seed_value(seed: str) -> int:
    return int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16], 16)
