from __future__ import annotations

from qtf.contracts.formula import (
    FormulaDefinition,
    FormulaRegistry,
    RegisteredFormula,
    ResearchTemplate,
    ResearchTemplateRegistry,
    TimeFrontierRule,
)
from qtf.modules.sector.factor_kernel import compute_sector_heat
from qtf.modules.sector.parameter_schema import (
    SECTOR_L2_PARAMETER_SCHEMA_KEY,
    SECTOR_L2_PARAMETER_SCHEMA_VERSION,
    SECTOR_PARAMETER_SCHEMA_REGISTRY,
)


SECTOR_L2_TEMPLATE_KEY = "sector_l2_turn_hot_v1"
SECTOR_L2_FORMULA_KEY = "sector_heat_research_v1"
SECTOR_L2_FORMULA_VERSION = "1"

SECTOR_L2_FORMULA = FormulaDefinition(
    formula_key=SECTOR_L2_FORMULA_KEY,
    formula_version=SECTOR_L2_FORMULA_VERSION,
    input_fields=(
        "trade_date",
        "sector_code",
        "parent_sector_code",
        "pct_change",
        "amount",
    ),
    output_fields=(
        "relative_return_1d",
        "amount_ratio",
        "log_amount_ratio",
        "daily_horizontal_score",
        "daily_rank_pct",
        "on_list",
        "relative_return_z",
        "log_amount_ratio_z",
        "state_input",
        "heat_state",
        "trend_slope",
        "upward_change_share",
        "signal",
        "issue_codes",
    ),
    lookback_requirement="amount_lookback_days + baseline_days + trend_days - 1",
    time_frontier=TimeFrontierRule.AS_OF_T_CLOSE,
    implementation_version="sector_heat_research_v1",
    parameter_schema_key=SECTOR_L2_PARAMETER_SCHEMA_KEY,
    parameter_schema_version=SECTOR_L2_PARAMETER_SCHEMA_VERSION,
)

SECTOR_L2_TEMPLATE = ResearchTemplate(
    template_key=SECTOR_L2_TEMPLATE_KEY,
    title="二级行业逐渐转热",
    capability_key="sector_heat_research",
    universe_key="EASTMONEY_INDUSTRY_L2",
    formula_key=SECTOR_L2_FORMULA_KEY,
    formula_version=SECTOR_L2_FORMULA_VERSION,
    parameter_schema_key=SECTOR_L2_PARAMETER_SCHEMA_KEY,
    parameter_schema_version=SECTOR_L2_PARAMETER_SCHEMA_VERSION,
    input_contract_key="sector_l2_prod_input_v1",
    validation_contract_key="sector_l2_continuation_validation_v1",
)

SECTOR_FORMULA_REGISTRY = FormulaRegistry(
    (RegisteredFormula(definition=SECTOR_L2_FORMULA, implementation=compute_sector_heat),)
)
SECTOR_TEMPLATE_REGISTRY = ResearchTemplateRegistry((SECTOR_L2_TEMPLATE,))


def validate_sector_registry_integrity() -> None:
    template = SECTOR_TEMPLATE_REGISTRY.get(SECTOR_L2_TEMPLATE_KEY)
    formula = SECTOR_FORMULA_REGISTRY.get(template.formula_key, template.formula_version)
    schema = SECTOR_PARAMETER_SCHEMA_REGISTRY.get(
        template.parameter_schema_key,
        template.parameter_schema_version,
    )
    if formula.definition.parameter_schema_key != schema.schema_key:
        raise ValueError("sector formula and parameter schema registration do not match")
    if formula.definition.parameter_schema_version != schema.schema_version:
        raise ValueError("sector formula and parameter schema versions do not match")


validate_sector_registry_integrity()
