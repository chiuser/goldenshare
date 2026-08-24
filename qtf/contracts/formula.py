from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from qtf.contracts.errors import QtfRequestInvalid


class TimeFrontierRule(StrEnum):
    AS_OF_T_CLOSE = "AS_OF_T_CLOSE"


@dataclass(frozen=True, slots=True)
class FormulaDefinition:
    formula_key: str
    formula_version: str
    input_fields: tuple[str, ...]
    output_fields: tuple[str, ...]
    lookback_requirement: str
    time_frontier: TimeFrontierRule
    implementation_version: str
    parameter_schema_key: str
    parameter_schema_version: str
    active: bool = True

    @property
    def identity(self) -> tuple[str, str]:
        return self.formula_key, self.formula_version


@dataclass(frozen=True, slots=True)
class ResearchTemplate:
    template_key: str
    title: str
    capability_key: str
    universe_key: str
    formula_key: str
    formula_version: str
    parameter_schema_key: str
    parameter_schema_version: str
    input_contract_key: str
    validation_contract_key: str
    validation_contract_version: int
    active: bool = True


@dataclass(frozen=True, slots=True)
class RegisteredFormula:
    definition: FormulaDefinition
    implementation: Callable[..., object]


class FormulaRegistry:
    def __init__(self, formulas: Iterable[RegisteredFormula]) -> None:
        by_identity: dict[tuple[str, str], RegisteredFormula] = {}
        for formula in formulas:
            identity = formula.definition.identity
            if identity in by_identity:
                raise ValueError(f"duplicate formula registration: {identity[0]}@{identity[1]}")
            if not callable(formula.implementation):
                raise TypeError(f"formula implementation is not callable: {identity[0]}@{identity[1]}")
            by_identity[identity] = formula
        self._by_identity = MappingProxyType(by_identity)

    def get(self, formula_key: str, formula_version: str) -> RegisteredFormula:
        identity = (formula_key, formula_version)
        formula = self._by_identity.get(identity)
        if formula is None or not formula.definition.active:
            raise QtfRequestInvalid(f"formula is not registered: {formula_key}@{formula_version}")
        return formula

    def definitions(self) -> tuple[FormulaDefinition, ...]:
        return tuple(
            registered.definition
            for _, registered in sorted(self._by_identity.items(), key=lambda item: item[0])
        )


class ResearchTemplateRegistry:
    def __init__(self, templates: Iterable[ResearchTemplate]) -> None:
        by_key: dict[str, ResearchTemplate] = {}
        for template in templates:
            if template.template_key in by_key:
                raise ValueError(f"duplicate research template registration: {template.template_key}")
            by_key[template.template_key] = template
        self._by_key = MappingProxyType(by_key)

    def get(self, template_key: str) -> ResearchTemplate:
        template = self._by_key.get(template_key)
        if template is None or not template.active:
            raise QtfRequestInvalid(f"research template is not registered: {template_key}")
        return template

    def templates(self) -> tuple[ResearchTemplate, ...]:
        return tuple(template for _, template in sorted(self._by_key.items()))
