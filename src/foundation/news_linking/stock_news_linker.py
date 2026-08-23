"""Deterministic, dictionary-backed news-to-stock linking.

The linker deliberately has no database, API, model, or task-runtime
dependency. Callers build the stock lexicon from the current security master
and historical namechange intervals, construct one linker per lexicon snapshot,
and then pass news text through it.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
import re
import unicodedata
from typing import Iterable


class MatchMethod(StrEnum):
    """The strongest deterministic rule that produced a link."""

    CODE_EXACT = "CODE_EXACT"
    FULL_NAME_EXACT = "FULL_NAME_EXACT"
    SHORT_NAME_EXACT = "SHORT_NAME_EXACT"


class SourceField(StrEnum):
    """News fields scanned by the linker."""

    TITLE = "title"
    CONTENT = "content"
    TITLE_AND_CONTENT = "title_and_content"


@dataclass(frozen=True, slots=True)
class StockLexiconEntry:
    """The minimum stock-master fields needed to build a lexicon."""

    ts_code: str
    symbol: str | None
    name: str | None
    fullname: str | None
    security_type: str = "EQUITY"


@dataclass(frozen=True, slots=True)
class HistoricalNameEntry:
    """One historical short-name interval from ``namechange``."""

    ts_code: str
    name: str
    start_date: date
    end_date: date | None = None


@dataclass(frozen=True, slots=True)
class NewsRecord:
    """News text supplied to the linker."""

    news_id: str
    title: str | None = None
    content: str | None = None
    news_date: date | None = None


@dataclass(frozen=True, slots=True)
class StockNewsLink:
    """One deduplicated news-to-stock association."""

    news_id: str
    ts_code: str
    match_method: MatchMethod
    source_field: SourceField
    rule_version: str


@dataclass(frozen=True, slots=True)
class _TermMatch:
    term: str
    ts_code: str
    match_method: MatchMethod
    start_date: date | None = None
    end_date: date | None = None


@dataclass(slots=True)
class _AutomatonNode:
    transitions: dict[str, int]
    failure: int
    outputs: list[_TermMatch]


_CODE_PATTERN = re.compile(
    r"(?<![0-9A-Z])(?P<symbol>[0-9]{6})(?:\.(?P<exchange>SH|SZ|BJ))?(?![0-9A-Z])",
)
_METHOD_PRIORITY: dict[MatchMethod, int] = {
    MatchMethod.CODE_EXACT: 0,
    MatchMethod.FULL_NAME_EXACT: 1,
    MatchMethod.SHORT_NAME_EXACT: 2,
}


def normalize_match_text(value: str) -> str:
    """Normalize text without changing Chinese semantic characters."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if not character.isspace())


class StockNewsLinker:
    """Link news to stocks with exact code/name/short-name rules.

    Code rules use a bounded six-digit code expression.  Name rules use a
    single Aho-Corasick automaton containing current and historical names, so
    one news text is scanned once rather than once per stock.
    """

    def __init__(
        self,
        entries: Iterable[StockLexiconEntry],
        *,
        historical_names: Iterable[HistoricalNameEntry] = (),
        rule_version: str = "news-stock-rule-v1",
    ) -> None:
        if not rule_version.strip():
            raise ValueError("rule_version must be non-empty")

        self.rule_version = rule_version
        eligible_entries = self._eligible_entries(entries)
        self._entries_by_explicit_code = {
            entry.ts_code.upper(): entry.ts_code.upper() for entry in eligible_entries
        }
        self._entries_by_symbol = self._build_unique_symbol_map(eligible_entries)
        term_matches = self._build_term_map(eligible_entries, historical_names)
        self._automaton = _AhoCorasickAutomaton(term_matches)

    def link(self, news: NewsRecord) -> tuple[StockNewsLink, ...]:
        """Return deterministic, deduplicated links for one news row."""

        if not news.news_id.strip():
            raise ValueError("news_id must be non-empty")

        matches: dict[str, tuple[set[MatchMethod], set[SourceField]]] = {}
        for source_field, value in (
            (SourceField.TITLE, news.title),
            (SourceField.CONTENT, news.content),
        ):
            if not value or not value.strip():
                continue
            normalized = normalize_match_text(value)
            self._collect_code_matches(normalized.upper(), source_field, matches)
            self._collect_name_matches(normalized, source_field, news.news_date, matches)

        links: list[StockNewsLink] = []
        for ts_code in sorted(matches):
            methods, source_fields = matches[ts_code]
            links.append(
                StockNewsLink(
                    news_id=news.news_id,
                    ts_code=ts_code,
                    match_method=min(methods, key=_METHOD_PRIORITY.__getitem__),
                    source_field=self._source_field(source_fields),
                    rule_version=self.rule_version,
                )
            )
        return tuple(links)

    @staticmethod
    def _eligible_entries(entries: Iterable[StockLexiconEntry]) -> tuple[StockLexiconEntry, ...]:
        eligible: dict[str, StockLexiconEntry] = {}
        for entry in entries:
            ts_code = entry.ts_code.strip().upper()
            if not ts_code or entry.security_type.strip().upper() != "EQUITY":
                continue
            normalized = StockLexiconEntry(
                ts_code=ts_code,
                symbol=entry.symbol.strip() if entry.symbol else None,
                name=entry.name.strip() if entry.name else None,
                fullname=entry.fullname.strip() if entry.fullname else None,
                security_type="EQUITY",
            )
            existing = eligible.get(ts_code)
            if existing is not None and existing != normalized:
                raise ValueError(f"duplicate stock lexicon entry with conflicting values: {ts_code}")
            eligible[ts_code] = normalized
        return tuple(eligible.values())

    @staticmethod
    def _build_unique_symbol_map(entries: Iterable[StockLexiconEntry]) -> dict[str, str]:
        candidates: dict[str, set[str]] = {}
        for entry in entries:
            symbol = normalize_match_text(entry.symbol or entry.ts_code.split(".", 1)[0]).upper()
            if not symbol:
                continue
            candidates.setdefault(symbol, set()).add(entry.ts_code.upper())
        return {symbol: next(iter(ts_codes)) for symbol, ts_codes in candidates.items() if len(ts_codes) == 1}

    @staticmethod
    def _build_term_map(
        entries: Iterable[StockLexiconEntry],
        historical_names: Iterable[HistoricalNameEntry],
    ) -> dict[str, tuple[_TermMatch, ...]]:
        fullname_candidates: dict[str, set[str]] = {}
        short_name_first: dict[str, str] = {}
        for entry in entries:
            if entry.fullname and entry.fullname.strip():
                term = normalize_match_text(entry.fullname)
                if term:
                    fullname_candidates.setdefault(term, set()).add(entry.ts_code.upper())
            if entry.name and entry.name.strip():
                term = normalize_match_text(entry.name)
                if term:
                    # The caller defines "first" by lexicon iteration order.
                    short_name_first.setdefault(term, entry.ts_code.upper())

        term_map: dict[str, list[_TermMatch]] = {}
        for term, ts_codes in fullname_candidates.items():
            if len(ts_codes) != 1:
                continue
            ts_code = next(iter(ts_codes))
            term_map.setdefault(term, []).append(_TermMatch(term, ts_code, MatchMethod.FULL_NAME_EXACT))
        for term, ts_code in short_name_first.items():
            term_map.setdefault(term, []).append(_TermMatch(term, ts_code, MatchMethod.SHORT_NAME_EXACT))

        eligible_ts_codes = {entry.ts_code.upper() for entry in entries}
        for historical in historical_names:
            ts_code = historical.ts_code.strip().upper()
            name = historical.name.strip()
            if ts_code not in eligible_ts_codes or not name:
                continue
            if historical.end_date is not None and historical.end_date < historical.start_date:
                raise ValueError(f"historical name interval is invalid: {ts_code}/{name}")
            term = normalize_match_text(name)
            if not term:
                continue
            term_map.setdefault(term, []).append(
                _TermMatch(
                    term,
                    ts_code,
                    MatchMethod.SHORT_NAME_EXACT,
                    historical.start_date,
                    historical.end_date,
                )
            )
        return {term: tuple(matches) for term, matches in term_map.items()}

    def _collect_code_matches(
        self,
        normalized_text: str,
        source_field: SourceField,
        matches: dict[str, tuple[set[MatchMethod], set[SourceField]]],
    ) -> None:
        for code_match in _CODE_PATTERN.finditer(normalized_text):
            symbol = code_match.group("symbol")
            exchange = code_match.group("exchange")
            ts_code: str | None
            if exchange:
                ts_code = self._entries_by_explicit_code.get(f"{symbol}.{exchange}")
            else:
                ts_code = self._entries_by_symbol.get(symbol)
            if ts_code is not None:
                self._add_match(matches, ts_code, MatchMethod.CODE_EXACT, source_field)

    def _collect_name_matches(
        self,
        normalized_text: str,
        source_field: SourceField,
        news_date: date | None,
        matches: dict[str, tuple[set[MatchMethod], set[SourceField]]],
    ) -> None:
        selected_terms: set[str] = set()
        for term_match in self._automaton.find(normalized_text):
            if term_match.term in selected_terms:
                continue
            if not self._is_active_term(term_match, news_date):
                continue
            self._add_match(matches, term_match.ts_code, term_match.match_method, source_field)
            selected_terms.add(term_match.term)

    @staticmethod
    def _is_active_term(term_match: _TermMatch, news_date: date | None) -> bool:
        if term_match.start_date is None:
            return True
        if news_date is None or news_date < term_match.start_date:
            return False
        return term_match.end_date is None or news_date <= term_match.end_date

    @staticmethod
    def _add_match(
        matches: dict[str, tuple[set[MatchMethod], set[SourceField]]],
        ts_code: str,
        method: MatchMethod,
        source_field: SourceField,
    ) -> None:
        methods, fields = matches.setdefault(ts_code, (set(), set()))
        methods.add(method)
        fields.add(source_field)

    @staticmethod
    def _source_field(fields: set[SourceField]) -> SourceField:
        if SourceField.TITLE in fields and SourceField.CONTENT in fields:
            return SourceField.TITLE_AND_CONTENT
        if SourceField.TITLE in fields:
            return SourceField.TITLE
        return SourceField.CONTENT


class _AhoCorasickAutomaton:
    def __init__(self, term_map: dict[str, tuple[_TermMatch, ...]]) -> None:
        self._nodes = [_AutomatonNode(transitions={}, failure=0, outputs=[])]
        for term, matches in term_map.items():
            self._add_term(term, matches)
        self._build_failure_links()

    def find(self, text: str) -> tuple[_TermMatch, ...]:
        found: list[_TermMatch] = []
        state = 0
        for character in text:
            while state and character not in self._nodes[state].transitions:
                state = self._nodes[state].failure
            state = self._nodes[state].transitions.get(character, 0)
            found.extend(self._nodes[state].outputs)
        return tuple(found)

    def _add_term(self, term: str, matches: tuple[_TermMatch, ...]) -> None:
        state = 0
        for character in term:
            next_state = self._nodes[state].transitions.get(character)
            if next_state is None:
                next_state = len(self._nodes)
                self._nodes[state].transitions[character] = next_state
                self._nodes.append(_AutomatonNode(transitions={}, failure=0, outputs=[]))
            state = next_state
        self._nodes[state].outputs.extend(matches)

    def _build_failure_links(self) -> None:
        queue: deque[int] = deque()
        for child in self._nodes[0].transitions.values():
            queue.append(child)
            self._nodes[child].failure = 0

        while queue:
            state = queue.popleft()
            for character, child in self._nodes[state].transitions.items():
                queue.append(child)
                failure = self._nodes[state].failure
                while failure and character not in self._nodes[failure].transitions:
                    failure = self._nodes[failure].failure
                self._nodes[child].failure = self._nodes[failure].transitions.get(character, 0)
                self._nodes[child].outputs.extend(self._nodes[self._nodes[child].failure].outputs)


__all__ = [
    "HistoricalNameEntry",
    "MatchMethod",
    "NewsRecord",
    "SourceField",
    "StockLexiconEntry",
    "StockNewsLink",
    "StockNewsLinker",
    "normalize_match_text",
]
