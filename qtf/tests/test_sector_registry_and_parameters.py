from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields

import pytest

from qtf.contracts.errors import QtfRequestInvalid
from qtf.contracts.formula import (
    FormulaDefinition,
    FormulaRegistry,
    RegisteredFormula,
    ResearchTemplateRegistry,
    TimeFrontierRule,
)
from qtf.contracts.parameters import ParameterSchemaRegistry, ParameterValueSource
from qtf.modules.sector.factor_kernel import compute_sector_heat
from qtf.modules.sector.parameter_schema import (
    SECTOR_L2_PARAMETER_SCHEMA,
    SECTOR_PARAMETER_SCHEMA_REGISTRY,
    ComparisonScope,
    EventClusterRule,
    RankingRuleKind,
    resolve_sector_heat_parameters,
)
from qtf.modules.sector.templates import (
    SECTOR_FORMULA_REGISTRY,
    SECTOR_L2_FORMULA_KEY,
    SECTOR_L2_FORMULA_VERSION,
    SECTOR_L2_TEMPLATE_KEY,
    SECTOR_TEMPLATE_REGISTRY,
    validate_sector_registry_integrity,
)


def test_sector_registries_expose_only_the_implemented_v1_contract() -> None:
    template = SECTOR_TEMPLATE_REGISTRY.get(SECTOR_L2_TEMPLATE_KEY)
    formula = SECTOR_FORMULA_REGISTRY.get(SECTOR_L2_FORMULA_KEY, SECTOR_L2_FORMULA_VERSION)
    schema = SECTOR_PARAMETER_SCHEMA_REGISTRY.get(
        template.parameter_schema_key,
        template.parameter_schema_version,
    )

    assert template.universe_key == "EASTMONEY_INDUSTRY_L2"
    assert template.formula_key == formula.definition.formula_key
    assert formula.definition.time_frontier is TimeFrontierRule.AS_OF_T_CLOSE
    assert schema is SECTOR_L2_PARAMETER_SCHEMA
    assert formula.implementation is compute_sector_heat
    assert {field.name for field in fields(FormulaDefinition)}.isdisjoint(
        {"python_source", "expression", "module_path"}
    )
    assert not any(name.startswith("success_") or name == "lift" for name in formula.definition.output_fields)
    validate_sector_registry_integrity()


def test_registries_reject_unknown_or_duplicate_entries() -> None:
    with pytest.raises(QtfRequestInvalid, match="formula is not registered"):
        SECTOR_FORMULA_REGISTRY.get(SECTOR_L2_FORMULA_KEY, "uploaded-source")
    with pytest.raises(QtfRequestInvalid, match="research template is not registered"):
        SECTOR_TEMPLATE_REGISTRY.get("sector_l2_turn_hot_v2")
    with pytest.raises(QtfRequestInvalid, match="parameter schema is not registered"):
        SECTOR_PARAMETER_SCHEMA_REGISTRY.get("sector_l2_heat_params_v1", "2")

    definition = FormulaDefinition(
        formula_key="duplicate",
        formula_version="1",
        input_fields=("value",),
        output_fields=("result",),
        lookback_requirement="0",
        time_frontier=TimeFrontierRule.AS_OF_T_CLOSE,
        implementation_version="duplicate_v1",
        parameter_schema_key="schema",
        parameter_schema_version="1",
    )
    registered = RegisteredFormula(definition, lambda: None)
    with pytest.raises(ValueError, match="duplicate formula"):
        FormulaRegistry((registered, registered))
    template = SECTOR_TEMPLATE_REGISTRY.get(SECTOR_L2_TEMPLATE_KEY)
    with pytest.raises(ValueError, match="duplicate research template"):
        ResearchTemplateRegistry((template, template))
    with pytest.raises(ValueError, match="duplicate parameter schema"):
        ParameterSchemaRegistry((SECTOR_L2_PARAMETER_SCHEMA, SECTOR_L2_PARAMETER_SCHEMA))


def test_effective_parameters_are_complete_explicit_and_hash_stable() -> None:
    values = _valid_values()
    sources = _valid_sources()
    first = resolve_sector_heat_parameters(values, sources)
    second = resolve_sector_heat_parameters(
        dict(reversed(tuple(values.items()))),
        dict(reversed(tuple(sources.items()))),
    )
    float_threshold = dict(values)
    float_threshold["ranking_rule"] = {"threshold": 80.0, "kind": "PERCENTILE_GTE"}
    third = resolve_sector_heat_parameters(float_threshold, sources)

    assert first.effective.parameter_hash == second.effective.parameter_hash
    assert first.effective.parameter_hash == third.effective.parameter_hash
    assert first.parameters.baseline_days == 60
    assert first.parameters.trend_days == 10
    assert first.parameters.future_horizons == (1, 3, 5)
    assert first.parameters.comparison_scope is ComparisonScope.SIBLINGS
    assert first.parameters.ranking_rule.kind is RankingRuleKind.PERCENTILE_GTE
    assert first.parameters.event_cluster_rule is EventClusterRule.RESET_ONLY
    assert first.parameters.required_source_history_days == 89
    assert all(not field.has_default for field in SECTOR_L2_PARAMETER_SCHEMA.fields)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"baseline_days": 250}, "not allowed"),
        ({"trend_days": 15}, "not allowed"),
        ({"amount_lookback_days": 10}, "not allowed"),
        ({"ewma_lambda": 0}, "minimum"),
        ({"ewma_lambda": 1.01}, "maximum"),
        ({"ewma_lambda": float("inf")}, "finite"),
        ({"price_weight": -0.1}, "minimum"),
        ({"z_clip": float("nan")}, "finite"),
        ({"price_weight": 0.7}, "must sum to 1"),
        ({"signal_threshold": 101.0}, "maximum"),
        ({"reset_threshold": -1.0}, "minimum"),
        ({"reset_threshold": 70.0}, "lower than"),
        ({"up_move_share_min": 1.01}, "maximum"),
        ({"future_horizons": [1, 5, 3]}, "exactly"),
        ({"future_horizons": [1, 3, 3, 5]}, "exactly"),
        ({"comparison_scope": "GLOBAL_L2"}, "not allowed"),
        ({"minimum_group_size": 1}, "minimum"),
        ({"ranking_rule": {"kind": "TOP_N", "threshold": 80}}, "not supported"),
        ({"ranking_rule": {"kind": "PERCENTILE_GTE"}}, "exactly"),
        ({"ranking_rule": {"kind": "PERCENTILE_GTE", "threshold": 101}}, "within"),
        ({"event_cluster_rule": "FUTURE_5D"}, "not allowed"),
        ({"trend_days": "10"}, "integer"),
    ],
)
def test_effective_parameters_reject_invalid_values(
    mutation: Mapping[str, object],
    message: str,
) -> None:
    values = _valid_values()
    values.update(mutation)
    with pytest.raises(QtfRequestInvalid, match=message):
        resolve_sector_heat_parameters(values, _valid_sources())


def test_effective_parameters_reject_missing_unknown_and_unapproved_candidate_source() -> None:
    missing = _valid_values()
    missing.pop("z_clip")
    with pytest.raises(QtfRequestInvalid, match=r"missing=\['z_clip'\]"):
        resolve_sector_heat_parameters(missing, _valid_sources())

    unknown = _valid_values()
    unknown["python_source"] = "print('not allowed')"
    with pytest.raises(QtfRequestInvalid, match="python_source"):
        resolve_sector_heat_parameters(unknown, _valid_sources())

    sources = _valid_sources()
    sources["ewma_lambda"] = ParameterValueSource.CANDIDATE
    with pytest.raises(QtfRequestInvalid, match="not an approved candidate dimension"):
        resolve_sector_heat_parameters(_valid_values(), sources)

    missing_source = _valid_sources()
    missing_source.pop("signal_threshold")
    with pytest.raises(QtfRequestInvalid, match="parameter sources do not match schema"):
        resolve_sector_heat_parameters(_valid_values(), missing_source)


def _valid_values() -> dict[str, object]:
    return {
        "baseline_days": 60,
        "trend_days": 10,
        "amount_lookback_days": 20,
        "ewma_lambda": 0.30,
        "price_weight": 0.50,
        "amount_weight": 0.50,
        "z_clip": 3.0,
        "signal_threshold": 70.0,
        "reset_threshold": 60.0,
        "up_move_share_min": 0.60,
        "future_horizons": [1, 3, 5],
        "comparison_scope": "SIBLINGS",
        "minimum_group_size": 3,
        "ranking_rule": {"kind": "PERCENTILE_GTE", "threshold": 80},
        "event_cluster_rule": "RESET_ONLY",
    }


def _valid_sources() -> dict[str, ParameterValueSource]:
    return {
        key: (
            ParameterValueSource.CANDIDATE
            if key in {"baseline_days", "trend_days"}
            else ParameterValueSource.FIXED
        )
        for key in _valid_values()
    }
