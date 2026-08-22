from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from qtf.contracts.research import RevisionContent
from qtf.engine.canonical_hash import canonical_json_hash, revision_content_hash


def test_canonical_hash_is_stable_across_mapping_order_and_timezone_offsets() -> None:
    first = {
        "decimal": Decimal("1.2300"),
        "at": datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
        "nested": {"b": 2, "a": 1},
    }
    second = {
        "nested": {"a": 1, "b": 2},
        "at": datetime(2026, 8, 22, 20, 0, tzinfo=timezone(timedelta(hours=8))),
        "decimal": Decimal("1.2300"),
    }

    assert canonical_json_hash(first) == canonical_json_hash(second)


def test_canonical_hash_rejects_naive_datetimes_and_non_string_keys() -> None:
    with pytest.raises(ValueError, match="timezone"):
        canonical_json_hash({"at": datetime(2026, 8, 22, 12, 0)})
    with pytest.raises(TypeError, match="keys must be strings"):
        canonical_json_hash({1: "not allowed"})


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("problem_statement", "changed question"),
        ("success_definition", {"horizons": [1]}),
        ("non_goals", ["changed non-goal"]),
        ("source_contract", {"source": "lake"}),
        ("universe_spec", {"level": 3}),
        ("comparison_spec", {"scope": "same_level"}),
        ("formula_key", "changed_formula"),
        ("formula_version", "2"),
        ("parameter_schema_key", "changed_schema"),
        ("parameter_schema_version", "2"),
        ("effective_params", {"trend_days": [20]}),
        ("validation_spec", {"split": "changed"}),
        ("budget", {"max_parameter_sets": 9}),
    ],
)
def test_revision_hash_covers_every_frozen_content_section(field: str, replacement: object) -> None:
    content = _content()
    baseline = revision_content_hash(content)
    changed = replace(content, **{field: replacement})

    assert len(baseline) == 64
    assert baseline != revision_content_hash(changed)


def _content() -> RevisionContent:
    return RevisionContent(
        problem_statement="find warming sectors",
        success_definition={"horizons": [1, 3, 5]},
        non_goals=["per-sector tuning"],
        source_contract={"source": "prod"},
        universe_spec={"level": 2},
        comparison_spec={"scope": "siblings"},
        formula_key="sector_heat",
        formula_version="1",
        parameter_schema_key="sector_l2",
        parameter_schema_version="1",
        effective_params={"trend_days": [5, 10]},
        validation_spec={"split": "ordered"},
        budget={"max_parameter_sets": 8},
    )
