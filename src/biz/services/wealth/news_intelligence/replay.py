from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
import hashlib
import html
import json
import math
import re
from zoneinfo import ZoneInfo

from .contracts import (
    CandidateDecision,
    CandidateStatus,
    EventCluster,
    FrozenNewsItem,
    NewsSourceType,
    ReplayWindow,
)
from .policy import (
    EMBEDDING_REPRESENTATIVE_TOKENS,
    SCHEDULE_HOURS,
    SUMMARY_MIN_CHARS,
    TAXONOMY_VERSION,
    TIMEZONE,
)


_HTML_TAG = re.compile(r"(?is)<[^>]+>")
_WHITESPACE = re.compile(r"\s+")
_NORMALIZE_PUNCTUATION = re.compile(r"[^0-9a-z\u3400-\u9fff]+", re.IGNORECASE)
_SENTENCE_END = re.compile(r"[。！？!?]+")
_NUMBER = re.compile(r"\d+(?:\.\d+)?%?")


def build_replay_windows(day: date) -> tuple[ReplayWindow, ...]:
    zone = ZoneInfo(TIMEZONE)
    windows: list[ReplayWindow] = []
    for hour in SCHEDULE_HOURS:
        end_at = datetime.combine(day, time(hour), tzinfo=zone)
        if hour == 8:
            start_at = datetime.combine(day - timedelta(days=1), time(22), tzinfo=zone)
        else:
            prior_hour = SCHEDULE_HOURS[SCHEDULE_HOURS.index(hour) - 1]
            start_at = datetime.combine(day, time(prior_hour), tzinfo=zone)
        windows.append(
            ReplayWindow(scheduled_at=end_at, start_at=start_at, end_at=end_at)
        )
    return tuple(windows)


def freeze_news_item(
    *,
    source_type: NewsSourceType,
    source_key: str,
    title: str | None,
    content: str | None,
    source_name: str,
    published_at: datetime | None,
    content_date: date | None,
    fetched_at: datetime,
    replay_assignment: str,
) -> FrozenNewsItem:
    clean_title = (title or "").strip()
    clean_content = (content or "").strip()
    sample_id = f"m1:{source_type.value}:{source_key}"
    payload = {
        "source_type": source_type.value,
        "source_key": source_key,
        "title": clean_title,
        "content": clean_content,
        "source_name": source_name,
        "published_at": published_at.isoformat() if published_at else None,
        "content_date": content_date.isoformat() if content_date else None,
        "fetched_at": fetched_at.isoformat(),
    }
    input_hash = hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    return FrozenNewsItem(
        sample_id=sample_id,
        source_type=source_type,
        source_key=source_key,
        title=clean_title,
        content=clean_content,
        source_name=source_name,
        published_at=published_at,
        content_date=content_date,
        fetched_at=fetched_at,
        input_hash=input_hash,
        replay_assignment=replay_assignment,
    )


def clean_candidate(item: FrozenNewsItem) -> CandidateDecision:
    title = normalize_display_text(item.title)
    content = normalize_display_text(item.content)
    sentence_count = len(
        tuple(part for part in _SENTENCE_END.split(content) if part.strip())
    )
    if not title and not content:
        return CandidateDecision(
            sample_id=item.sample_id,
            status=CandidateStatus.EXCLUDED,
            exclusion_code="INVALID_CONTENT_EMPTY",
            normalized_title="",
            normalized_content="",
            representative_text="",
            content_length=0,
            sentence_count=0,
            summary_eligible=False,
        )
    representative = build_representative_text(title, content)
    return CandidateDecision(
        sample_id=item.sample_id,
        status=CandidateStatus.ELIGIBLE,
        exclusion_code=None,
        normalized_title=normalize_match_text(title),
        normalized_content=normalize_match_text(content),
        representative_text=representative,
        content_length=len(content),
        sentence_count=sentence_count,
        summary_eligible=len(content) >= SUMMARY_MIN_CHARS and sentence_count > 1,
    )


def mark_exact_duplicates(
    items: tuple[FrozenNewsItem, ...], decisions: tuple[CandidateDecision, ...]
) -> tuple[CandidateDecision, ...]:
    source_by_sample_id = {item.sample_id: item.source_type for item in items}
    if set(source_by_sample_id) != {decision.sample_id for decision in decisions}:
        raise ValueError("items and decisions must contain the same sample identities")
    first_by_fingerprint: dict[str, str] = {}
    output: list[CandidateDecision] = []
    for decision in decisions:
        if decision.status is CandidateStatus.EXCLUDED:
            output.append(decision)
            continue
        fingerprint = hashlib.sha256(
            (
                f"{source_by_sample_id[decision.sample_id].value}\n"
                f"{decision.normalized_title}\n{decision.normalized_content}"
            ).encode("utf-8")
        ).hexdigest()
        duplicate_of = first_by_fingerprint.get(fingerprint)
        if duplicate_of is None:
            first_by_fingerprint[fingerprint] = decision.sample_id
            output.append(decision)
            continue
        output.append(
            CandidateDecision(
                sample_id=decision.sample_id,
                status=CandidateStatus.EXCLUDED,
                exclusion_code="EXACT_DUPLICATE",
                normalized_title=decision.normalized_title,
                normalized_content=decision.normalized_content,
                representative_text=decision.representative_text,
                content_length=decision.content_length,
                sentence_count=decision.sentence_count,
                summary_eligible=False,
                exact_duplicate_of=duplicate_of,
            )
        )
    return tuple(output)


def cluster_candidates(
    items: tuple[FrozenNewsItem, ...],
    decisions: tuple[CandidateDecision, ...],
    embeddings: dict[str, tuple[float, ...]],
    *,
    similarity_threshold: float = 0.88,
    policy_version: str = TAXONOMY_VERSION,
) -> tuple[EventCluster, ...]:
    item_by_id = {item.sample_id: item for item in items}
    eligible = [
        decision
        for decision in decisions
        if decision.status is CandidateStatus.ELIGIBLE
    ]
    parents = list(range(len(eligible)))
    evidence: dict[int, list[dict[str, object]]] = defaultdict(list)

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for left_index, left in enumerate(eligible):
        for right_index in range(left_index + 1, len(eligible)):
            right = eligible[right_index]
            left_item = item_by_id[left.sample_id]
            right_item = item_by_id[right.sample_id]
            if not _within_cluster_time(left_item, right_item):
                continue
            if _numeric_conflict(left.representative_text, right.representative_text):
                continue
            similarity = cosine_similarity(
                embeddings.get(left.sample_id), embeddings.get(right.sample_id)
            )
            if similarity < similarity_threshold:
                continue
            left_root = find(left_index)
            right_root = find(right_index)
            if left_root == right_root:
                continue
            parents[right_root] = left_root
            evidence[left_root].append(
                {
                    "left": left.sample_id,
                    "right": right.sample_id,
                    "cosine": round(similarity, 6),
                }
            )

    grouped: dict[int, list[CandidateDecision]] = defaultdict(list)
    for index, decision in enumerate(eligible):
        grouped[find(index)].append(decision)

    clusters: list[EventCluster] = []
    for root, members in grouped.items():
        member_ids = tuple(sorted(member.sample_id for member in members))
        representative = max(
            members, key=lambda member: (member.content_length, member.sample_id)
        )
        event_id = hashlib.sha256(
            f"{policy_version}|{'|'.join(member_ids)}".encode("utf-8")
        ).hexdigest()
        clusters.append(
            EventCluster(
                event_id=event_id,
                member_sample_ids=member_ids,
                representative_sample_id=representative.sample_id,
                merge_evidence=tuple(evidence.get(root, ())),
            )
        )
    return tuple(sorted(clusters, key=lambda cluster: cluster.event_id))


def normalize_display_text(value: str) -> str:
    return _WHITESPACE.sub(" ", html.unescape(_HTML_TAG.sub(" ", value))).strip()


def normalize_match_text(value: str) -> str:
    return _NORMALIZE_PUNCTUATION.sub("", value).casefold()


def build_representative_text(
    title: str, content: str, *, max_tokens: int = EMBEDDING_REPRESENTATIVE_TOKENS
) -> str:
    # This is a tokenizer-independent pre-limit. The model adapter still enforces max_tokens.
    max_chars = max_tokens * 2
    combined = f"{title}\n{content}".strip()
    return combined[:max_chars]


def cosine_similarity(
    left: tuple[float, ...] | None, right: tuple[float, ...] | None
) -> float:
    if left is None or right is None or len(left) != len(right) or not left:
        return -1.0
    numerator = sum(x * y for x, y in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(x * x for x in left))
    right_norm = math.sqrt(sum(y * y for y in right))
    if left_norm == 0 or right_norm == 0:
        return -1.0
    return numerator / (left_norm * right_norm)


def _within_cluster_time(left: FrozenNewsItem, right: FrozenNewsItem) -> bool:
    if left.published_at is not None and right.published_at is not None:
        return abs(left.published_at - right.published_at) <= timedelta(hours=72)
    left_date = left.content_date or (
        left.published_at.date() if left.published_at else None
    )
    right_date = right.content_date or (
        right.published_at.date() if right.published_at else None
    )
    return (
        left_date is not None
        and right_date is not None
        and abs(left_date - right_date) <= timedelta(days=3)
    )


def _numeric_conflict(left: str, right: str) -> bool:
    left_numbers = set(_NUMBER.findall(left))
    right_numbers = set(_NUMBER.findall(right))
    return bool(
        left_numbers and right_numbers and left_numbers.isdisjoint(right_numbers)
    )
