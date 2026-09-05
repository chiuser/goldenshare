from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re
import unicodedata

from .news_display_title import build_news_display_title


NEWS_EVENT_WINDOW = timedelta(minutes=10)
NEWS_EVENT_NGRAM_SIZE = 3
NEWS_EVENT_CONTAINMENT_THRESHOLD = 0.80
NEWS_EVENT_MIN_EXACT_TITLE_LENGTH = 12
NEWS_EVENT_MIN_EXACT_CONTENT_LENGTH = 24
NEWS_EVENT_MIN_APPROXIMATE_LENGTH = 16
NEWS_EVENT_TRUNCATED_PREFIX_LENGTH = 16
NEWS_EVENT_CANDIDATE_BATCH_SIZE = 500
NEWS_EVENT_MAX_CANDIDATE_SCAN = 10000

_NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?%?")
_TRUNCATED_SUFFIX_PATTERN = re.compile(r"(?:\.{3,}|…+)\s*$")
_SENTENCE_END_PATTERN = re.compile(r"[。！？\r\n]")


@dataclass(frozen=True, slots=True)
class NewsEventCandidate:
    news_id: str
    publish_time: datetime
    title: str | None
    content: str | None
    source: str
    match_method: str


@dataclass(frozen=True, slots=True)
class NewsEvent:
    representative: NewsEventCandidate
    display_title: str


@dataclass(frozen=True, slots=True)
class _PreparedCandidate:
    candidate: NewsEventCandidate
    display_title: str
    normalized_title: str
    normalized_content: str
    normalized_fact_sentence: str
    title_numbers: tuple[str, ...]
    fact_numbers: tuple[str, ...]
    title_is_truncated: bool
    content_is_truncated: bool


def deduplicate_news_events(candidates: list[NewsEventCandidate]) -> list[NewsEvent]:
    prepared = sorted(
        (_prepare_candidate(candidate) for candidate in candidates),
        key=lambda item: (-item.candidate.publish_time.timestamp(), item.candidate.news_id),
    )
    parents = list(range(len(prepared)))
    latest_times = [item.candidate.publish_time for item in prepared]
    earliest_times = [item.candidate.publish_time for item in prepared]

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        combined_latest = max(latest_times[left_root], latest_times[right_root])
        combined_earliest = min(earliest_times[left_root], earliest_times[right_root])
        if combined_latest - combined_earliest > NEWS_EVENT_WINDOW:
            return
        parents[right_root] = left_root
        latest_times[left_root] = combined_latest
        earliest_times[left_root] = combined_earliest

    for left_index, left in enumerate(prepared):
        for right_index in range(left_index + 1, len(prepared)):
            right = prepared[right_index]
            if left.candidate.publish_time - right.candidate.publish_time > NEWS_EVENT_WINDOW:
                break
            if _is_same_event(left, right):
                union(left_index, right_index)

    grouped: dict[int, list[_PreparedCandidate]] = {}
    for index, item in enumerate(prepared):
        grouped.setdefault(find(index), []).append(item)

    events = []
    for members in grouped.values():
        representative = min(members, key=_representative_sort_key)
        events.append(
            NewsEvent(
                representative=representative.candidate,
                display_title=representative.display_title,
            )
        )
    return sorted(
        events,
        key=lambda event: (
            -event.representative.publish_time.timestamp(),
            event.representative.news_id,
        ),
    )


def _prepare_candidate(candidate: NewsEventCandidate) -> _PreparedCandidate:
    fallback_title = (candidate.content or "").strip()[:80]
    display_title = build_news_display_title(candidate.title, candidate.content, fallback_title)
    normalized_content = _normalize_text(candidate.content)
    normalized_fact_sentence = _normalize_text(_extract_fact_sentence(candidate.content))
    return _PreparedCandidate(
        candidate=candidate,
        display_title=display_title,
        normalized_title=_normalize_text(display_title),
        normalized_content=normalized_content,
        normalized_fact_sentence=normalized_fact_sentence,
        title_numbers=_extract_numbers(display_title),
        fact_numbers=_extract_numbers(_extract_fact_sentence(candidate.content)),
        title_is_truncated=_is_truncated(candidate.title or display_title),
        content_is_truncated=_is_truncated(candidate.content or ""),
    )


def _is_same_event(left: _PreparedCandidate, right: _PreparedCandidate) -> bool:
    if abs(left.candidate.publish_time - right.candidate.publish_time) > NEWS_EVENT_WINDOW:
        return False
    if _has_numeric_conflict(left.title_numbers, right.title_numbers):
        return False
    if (
        not left.content_is_truncated
        and not right.content_is_truncated
        and _has_numeric_conflict(left.fact_numbers, right.fact_numbers)
    ):
        return False
    if _same_sufficient_text(
        left.normalized_title,
        right.normalized_title,
        minimum_length=NEWS_EVENT_MIN_EXACT_TITLE_LENGTH,
    ):
        return True
    if _same_sufficient_text(
        left.normalized_fact_sentence,
        right.normalized_fact_sentence,
        minimum_length=NEWS_EVENT_MIN_EXACT_CONTENT_LENGTH,
    ):
        return True
    if _has_safe_truncated_prefix(left, right) or _has_safe_truncated_prefix(right, left):
        return True
    if min(len(left.normalized_title), len(right.normalized_title)) < NEWS_EVENT_MIN_APPROXIMATE_LENGTH:
        return False

    left_content = left.normalized_fact_sentence or left.normalized_content
    right_content = right.normalized_fact_sentence or right.normalized_content
    if min(len(left_content), len(right_content)) < NEWS_EVENT_MIN_APPROXIMATE_LENGTH:
        return False

    title_containment = _ngram_containment(left.normalized_title, right.normalized_title)
    fact_containment = _ngram_containment(left.normalized_fact_sentence, right.normalized_fact_sentence)
    content_containment = _ngram_containment(left.normalized_content, right.normalized_content)
    return (
        title_containment >= NEWS_EVENT_CONTAINMENT_THRESHOLD
        and max(fact_containment, content_containment) >= NEWS_EVENT_CONTAINMENT_THRESHOLD
    )


def _same_sufficient_text(left: str, right: str, *, minimum_length: int) -> bool:
    return len(left) >= minimum_length and left == right


def _has_safe_truncated_prefix(truncated: _PreparedCandidate, complete: _PreparedCandidate) -> bool:
    prefix = truncated.normalized_title
    return (
        truncated.title_is_truncated
        and len(prefix) >= NEWS_EVENT_TRUNCATED_PREFIX_LENGTH
        and complete.normalized_title.startswith(prefix)
    )


def _has_numeric_conflict(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    return bool(left) and len(left) == len(right) and left != right


def _ngram_containment(left: str, right: str) -> float:
    left_ngrams = _ngrams(left)
    right_ngrams = _ngrams(right)
    if not left_ngrams or not right_ngrams:
        return 0.0
    return len(left_ngrams & right_ngrams) / min(len(left_ngrams), len(right_ngrams))


def _ngrams(value: str) -> frozenset[str]:
    if len(value) < NEWS_EVENT_NGRAM_SIZE:
        return frozenset()
    return frozenset(
        value[index : index + NEWS_EVENT_NGRAM_SIZE]
        for index in range(len(value) - NEWS_EVENT_NGRAM_SIZE + 1)
    )


def _representative_sort_key(item: _PreparedCandidate) -> tuple[int, int, int, float, str]:
    raw_title = (item.candidate.title or "").strip()
    has_complete_source_title = bool(raw_title) and not item.title_is_truncated
    return (
        0 if has_complete_source_title else 1,
        -len(item.normalized_content),
        -len(item.normalized_title),
        -item.candidate.publish_time.timestamp(),
        item.candidate.news_id,
    )


def _extract_fact_sentence(content: str | None) -> str:
    normalized = (content or "").strip()
    if normalized.startswith("【"):
        closing_position = normalized.find("】", 1)
        if closing_position >= 0:
            normalized = normalized[closing_position + 1 :].strip()
    sentence = _SENTENCE_END_PATTERN.split(normalized, maxsplit=1)[0]
    return sentence.strip()


def _extract_numbers(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", value)
    return tuple(_NUMBER_PATTERN.findall(normalized))


def _is_truncated(value: str) -> bool:
    return bool(_TRUNCATED_SUFFIX_PATTERN.search(value.strip()))


def _normalize_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(character for character in normalized if character.isalnum())
