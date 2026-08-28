from __future__ import annotations

from typing import Any

from sqlalchemy import Integer, case, func, literal
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.functions import FunctionElement

NEWS_TITLE_OPENING_BRACKET = "【"
NEWS_TITLE_CLOSING_BRACKET = "】"


class _SubstringPosition(FunctionElement[int]):
    type = Integer()
    inherit_cache = True


@compiles(_SubstringPosition)
def _compile_substring_position(
    element: _SubstringPosition,
    compiler: Any,
    **kwargs: Any,
) -> str:
    value, substring = list(element.clauses)
    return f"instr({compiler.process(value, **kwargs)}, {compiler.process(substring, **kwargs)})"


@compiles(_SubstringPosition, "postgresql")
def _compile_postgresql_substring_position(
    element: _SubstringPosition,
    compiler: Any,
    **kwargs: Any,
) -> str:
    value, substring = list(element.clauses)
    return f"strpos({compiler.process(value, **kwargs)}, {compiler.process(substring, **kwargs)})"


def extract_leading_bracket_title(title: str | None) -> str | None:
    normalized = (title or "").strip()
    if not normalized.startswith(NEWS_TITLE_OPENING_BRACKET):
        return None

    closing_position = normalized.find(NEWS_TITLE_CLOSING_BRACKET, 1)
    if closing_position < 0:
        return None

    extracted = normalized[1:closing_position].strip()
    return extracted or None


def build_news_display_title(
    title: str | None,
    content: str | None,
    fallback_title: str,
) -> str:
    normalized_title = (title or "").strip()
    candidate = normalized_title or (content or "").strip()
    return extract_leading_bracket_title(candidate) or normalized_title or fallback_title


def build_news_display_title_expr(
    title_column: ColumnElement[str],
    content_column: ColumnElement[str],
) -> ColumnElement[str]:
    normalized_title = func.trim(title_column)
    candidate = func.coalesce(func.nullif(normalized_title, ""), func.trim(content_column))
    closing_position = _SubstringPosition(
        candidate,
        literal(NEWS_TITLE_CLOSING_BRACKET),
    )
    extracted_title = func.trim(func.substr(candidate, 2, closing_position - 2))
    legacy_display_title = func.substr(candidate, 1, 80)
    return case(
        (
            (func.substr(candidate, 1, 1) == literal(NEWS_TITLE_OPENING_BRACKET))
            & (closing_position > 2)
            & (func.length(extracted_title) > 0),
            extracted_title,
        ),
        else_=legacy_display_title,
    )
