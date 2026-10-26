"""Existing output-range and partial-period rules, shared without price arithmetic."""

from datetime import datetime
import re

from .errors import SourceContractError, SourceUnsupportedError


def range_filter(request, *, include_start=True):
    minute = request.period.endswith("m")
    time_key = "trade_time" if minute else "period_start"
    terms, bindings = [], []
    for value, column, operator in (
        (request.start if include_start else None,
         "period_end" if request.period in ("week", "month") else time_key, ">="),
        (request.end, time_key, "<="),
        (request.before, time_key, "<"),
    ):
        if value is not None:
            if minute and isinstance(value, datetime):
                value = value.replace(tzinfo=None)
            terms.append(f'"{column}" {operator} ?')
            bindings.append(value)
    return " AND ".join(terms) or "TRUE", tuple(bindings)


def check_period_cutoff(executor, table_name, request):
    if not re.fullmatch(r"ti_[a-z0-9_]+", table_name):
        raise SourceContractError("Period checks require a controlled table")
    end = request.end
    if request.period in ("week", "month") and end is not None:
        later = executor.scalar(
            f"SELECT EXISTS(SELECT 1 FROM {table_name} WHERE period_start <= ? "
            "AND ? < period_end AND source_as_of > ?)", (end, end, end))
        if later:
            raise SourceUnsupportedError("Source has only a later version of the unfinished period")
