"""Immutable input requirements and versioned finite-warmup rules."""

from dataclasses import dataclass

# Algorithm-version constants, bound into fixed SQL rather than recomputed in Python.
MIN_RECURSIVE_WARMUP_ROWS = 500
INITIALIZATION_ERROR_BUDGET = 2.5e-9
# This is the established precision-proof domain, not a per-request price check.
PRICE_ABSOLUTE_BOUND = 1_000_000.0


@dataclass(frozen=True, slots=True)
class HistoryRequirement:
    fields: frozenset[str]
    preceding_rows: int
    warmup_rows: int | None
    requires_source_origin: bool
    state_fields: tuple[str, ...]
    initial_null_rule: str
    output_alignment: str = "current_bar"

    def __post_init__(self) -> None:
        if type(self.preceding_rows) is not int or self.preceding_rows < 0:
            raise ValueError("preceding_rows must be a nonnegative integer")
        if type(self.requires_source_origin) is not bool:
            raise ValueError("requires_source_origin must be a boolean")
        if self.requires_source_origin:
            if self.warmup_rows is not None:
                raise ValueError("Origin history requires warmup_rows=None")
        elif type(self.warmup_rows) is not int or self.warmup_rows < self.preceding_rows:
            raise ValueError("Finite warmup must cover the preceding window")
        object.__setattr__(self, "fields", frozenset(self.fields))
        object.__setattr__(self, "state_fields", tuple(self.state_fields))
        if self.output_alignment != "current_bar":
            raise ValueError("Only current_bar output alignment is defined")


def combine_history_and_fields(requirements) -> HistoryRequirement:
    requirements = tuple(requirements)
    if not all(isinstance(item, HistoryRequirement) for item in requirements):
        raise ValueError("History combination requires resolved HistoryRequirement objects")
    origin = any(item.requires_source_origin for item in requirements)
    return HistoryRequirement(
        fields=frozenset(field for item in requirements for field in item.fields),
        preceding_rows=max((item.preceding_rows for item in requirements), default=0),
        warmup_rows=None if origin else max((item.warmup_rows for item in requirements), default=0),
        requires_source_origin=origin,
        state_fields=tuple(dict.fromkeys(field for item in requirements for field in item.state_fields)),
        initial_null_rule="Each calculation retains its declared initialization and NULL rule",
    )
