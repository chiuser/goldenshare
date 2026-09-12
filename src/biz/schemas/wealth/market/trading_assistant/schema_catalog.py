"""Generate JSON Schema from the actual models, not a second handwritten spec."""

from pydantic import TypeAdapter
from pydantic.json_schema import GenerateJsonSchema

from . import (accounts, calculation_status, common, errors, positions, previews, receipts,
               records, recovered_inputs, recovery, returns, robot, rules, scopes)

MODULES = (accounts, calculation_status, common, errors, positions, previews, receipts,
           records, recovered_inputs, recovery, returns, robot, rules, scopes)


def contract_models() -> tuple[type[common.Contract], ...]:
    return tuple(sorted((
        model for module in MODULES for model in vars(module).values()
        if isinstance(model, type) and issubclass(model, common.Contract)
        and model is not common.Contract and model.__module__ == module.__name__
        and not model.__pydantic_generic_metadata__["parameters"]
    ), key=lambda model: (model.__module__, model.__name__)))


def json_schema_bundle() -> dict:
    """Serializable schema metadata only; no model instances, IO or route setup."""
    # Generate named unions together with models so colliding class names use
    # the same reference map (not independently generated/merged definitions).
    roots, definitions = GenerateJsonSchema(by_alias=True).generate_definitions([
        *((model, "validation", model.__pydantic_core_schema__) for model in contract_models()),
        ("RecoveryInputResponse", "validation", TypeAdapter(recovered_inputs.RecoveryInputResponse).core_schema),
    ])
    definitions["RecoveryInputResponse"] = roots[("RecoveryInputResponse", "validation")]
    return {"title": "TradingAssistant contracts", "$defs": definitions}
