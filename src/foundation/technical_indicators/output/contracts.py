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
    instance_id: str
    calculation_id: str
    algorithm_version: str
    parameters: Parameters
    fields: tuple[OutputFieldDescription, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", _freeze_parameters(self.parameters))
        copied = tuple(self.fields)
        if not all(isinstance(item, OutputFieldDescription) for item in copied):
            raise TypeError("Output fields require immutable field descriptions")
        object.__setattr__(self, "fields", copied)
