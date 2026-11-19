"""Immutable public-field descriptions copied by the library service."""

from dataclasses import dataclass
from typing import Literal

from ..contracts import Parameters, _freeze_parameters


@dataclass(frozen=True, slots=True)
class OutputFieldDescription:
    name: str
    sql_type: Literal["DOUBLE"]
    nullable: bool
    initialization_rule: str


@dataclass(frozen=True, slots=True)
class OutputInstanceDescription:
    calculation_index: int
    calculation_id: str
    algorithm_version: str
    parameters: Parameters
    fields: tuple[OutputFieldDescription, ...]

    def __post_init__(self) -> None:
        if type(self.calculation_index) is not int or self.calculation_index < 0:
            raise ValueError("The calculation index must be a nonnegative integer")
        object.__setattr__(self, "parameters", _freeze_parameters(self.parameters))
        copied = tuple(self.fields)
        if not all(isinstance(item, OutputFieldDescription) for item in copied):
            raise TypeError("Output fields require immutable field descriptions")
        object.__setattr__(self, "fields", copied)
