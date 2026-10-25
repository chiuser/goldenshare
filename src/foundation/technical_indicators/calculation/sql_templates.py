"""Load only code-declared package SQL and replace internal table roles."""

from __future__ import annotations

from collections.abc import Mapping
from importlib.resources import files
import re
from types import MappingProxyType

from ..errors import CalculationExecutionError


_PACKAGES = frozenset({
    "src.foundation.technical_indicators.calculation",
    "src.foundation.technical_indicators.output",
})
_PACKAGE_FILES = MappingProxyType({
    "src.foundation.technical_indicators.calculation": frozenset({
        "smoothing_parameters.sql", "rolling_mean.sql", "bollinger_bands.sql",
        "macd_first.sql", "macd_segment.sql", "kdj_window.sql", "kdj_segment.sql",
    }),
    "src.foundation.technical_indicators.output": frozenset({
        "merge_batch.sql", "retain_tail.sql", "select_result.sql",
    }),
})
_FILENAME = re.compile(r"[a-z][a-z0-9_]*\.sql\Z")
_NAME = re.compile(r"ti_[a-z][a-z0-9_]*\Z")
_ROLE = re.compile(r"[a-z][a-z0-9_]*\Z")
_TOKEN = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")


def load_sql_templates(
    owner_type: type, *, request_texts: dict[tuple[str, str], str], control,
) -> Mapping[str, str]:
    """Reuse unrendered text only within the current owning request.

    Validate this class's entire declaration before inspecting even a cached
    entry. Engine and collector separately restrict their own package.
    """
    package = getattr(owner_type, "SQL_PACKAGE", None)
    names = getattr(owner_type, "SQL_FILES", None)
    if not isinstance(package, str) or package not in _PACKAGES or not isinstance(names, tuple):
        raise CalculationExecutionError("SQL resources require a fixed package and immutable file list")
    if any(not isinstance(name, str) or not _FILENAME.fullmatch(name) for name in names) or len(set(names)) != len(names):
        raise CalculationExecutionError("SQL resource names must be unique declared package file names")
    if any(name not in _PACKAGE_FILES[package] for name in names):
        raise CalculationExecutionError("SQL resource is not an implemented file in the fixed package")
    loaded = {}
    for name in names:
        control.check_active()
        key = (package, name)
        if key in request_texts:
            text = request_texts[key]
            if not isinstance(text, str):
                raise CalculationExecutionError("Request SQL resources must contain complete text")
            control.check_active()
        else:
            try:
                text = files(package).joinpath("sql", name).read_text(encoding="utf-8")
            except (OSError, ModuleNotFoundError, UnicodeError) as exc:
                control.check_active()
                raise CalculationExecutionError(f"Declared SQL resource is unavailable: {name}") from exc
            control.check_active()
            request_texts[key] = text
        loaded[name] = text
    return MappingProxyType(loaded)


def render_sql(
    text: str, *, tables: Mapping[str, str], integers: Mapping[str, int] | None = None,
) -> str:
    """Only internal names and validated integer window sizes enter SQL text.

    Indicator values and request limits use DB-API bindings, never this method.
    Callers are built-in code holding the fixed template, not business inputs.
    """
    values = {}
    for role, name in tables.items():
        if not isinstance(role, str) or not _ROLE.fullmatch(role) or not isinstance(name, str) or not _NAME.fullmatch(name):
            raise CalculationExecutionError("SQL table roles require internal technical indicator names")
        values[role] = f'"{name}"'
    for role, value in (integers or {}).items():
        if role in values or not isinstance(role, str) or not _ROLE.fullmatch(role) or type(value) is not int or value < 0:
            raise CalculationExecutionError("SQL window tokens require nonnegative integer values")
        values[role] = str(value)
    try:
        rendered = _TOKEN.sub(lambda match: values[match.group(1)], text)
    except KeyError as exc:
        raise CalculationExecutionError("A fixed SQL template has an unresolved role") from exc
    if "{{" in rendered or "}}" in rendered:
        raise CalculationExecutionError("A fixed SQL template contains an unsupported token")
    return rendered
