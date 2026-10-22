"""History requirements describe input, without calculating indicator values."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HistoryRequirement:
    fields: frozenset[str]
    preceding_rows: int
    recursive_from_source_start: bool
    state_fields: tuple[str, ...]
    initial_null_rule: str
    output_alignment: str = "current_bar"

    def __post_init__(self) -> None:
        if type(self.preceding_rows) is not int or self.preceding_rows < 0:
            raise ValueError("preceding_rows must be a nonnegative integer")
        object.__setattr__(self, "fields", frozenset(self.fields))
        object.__setattr__(self, "state_fields", tuple(self.state_fields))
        if self.output_alignment != "current_bar":
            raise ValueError("Only current_bar output alignment is defined")


def combine_history_and_fields(plan) -> HistoryRequirement:
    requirements = tuple(node.calculation.input_requirement() for node in plan.nodes)
    return HistoryRequirement(
        fields=frozenset(field for item in requirements for field in item.fields),
        preceding_rows=max((item.preceding_rows for item in requirements), default=0),
        recursive_from_source_start=any(item.recursive_from_source_start for item in requirements),
        state_fields=tuple(dict.fromkeys(field for item in requirements for field in item.state_fields)),
        initial_null_rule="Each calculation retains its declared initialization and NULL rule",
    )
