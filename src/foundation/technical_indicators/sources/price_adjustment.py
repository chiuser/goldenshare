"""The shared price conversion formula, expressed only in DuckDB SQL."""

from pathlib import Path

from ..calculation.calculation import SqlStep
from ..errors import SourceUnsupportedError

PRICE_FIELDS = frozenset(("open", "high", "low", "close"))
VALUE_FIELDS = PRICE_FIELDS | {"volume", "amount"}
FORMULA_VERSION = "1.0.0"


class PriceAdjustmentCalculation:
    algorithm_version = FORMULA_VERSION

    def describe(self, input_adjustment, target, basis):
        if input_adjustment != target and not (input_adjustment == "none" and target in ("qfq", "hfq")):
            raise SourceUnsupportedError("This input/target adjustment is not supported")
        return {"formula_version": self.algorithm_version, "converted": input_adjustment != target,
                "basis_rule": basis}

    def build_sql(self, input_table, factors, basis, *, output_table, fields, time_fields, processed_rows):
        # All identifiers come from Session constants and the definition whitelist.
        if not set(fields) <= VALUE_FIELDS:
            raise ValueError("Unknown standard price field")
        columns = ["b.seq"] + [f'b."{name}"' for name in time_fields]
        for name in fields:
            expression = f'b."{name}"'
            if name in PRICE_FIELDS:
                expression = f"CAST({expression} * f.adj_factor / a.basis_value AS DOUBLE)"
            columns.append(f'{expression} AS "{name}"')
        template = (Path(__file__).parent / "sql/adjust_price.sql").read_text()
        return SqlStep("adjust_price", template.format(output_table=output_table,
            projection=", ".join(columns), input_table=input_table, factors=factors, basis=basis),
            (), (input_table, factors, basis), (output_table,), processed_rows)
