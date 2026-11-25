"""The shared price conversion formula, expressed only in DuckDB SQL."""

from math import isfinite

from ..calculation.calculation import SqlStep
from ..errors import SourceContractError, SourceUnsupportedError

PRICE_FIELDS = frozenset(("open", "high", "low", "close"))
VALUE_FIELDS = PRICE_FIELDS | {"volume", "amount"}
FORMULA_VERSION = "1.0.0"


def validate_adjustment_basis(description) -> None:
    if (description.basis_date is None or description.basis_value is None
            or not isfinite(description.basis_value) or description.basis_value <= 0):
        raise SourceContractError("Converted daily prices require a finite positive adjustment factor basis")


def validate_adjustment_factors(executor, prices: str, factors: str) -> None:
    """Validate factors already loaded for this request, using caller-owned tables."""
    invalid_date = executor.scalar(f"""
        SELECT prices.trade_date
        FROM (SELECT DISTINCT trade_date FROM {prices}) AS prices
        LEFT JOIN {factors} AS factor USING (trade_date)
        GROUP BY prices.trade_date
        HAVING count(*) <> 1 OR count(factor.adj_factor) <> 1
            OR NOT bool_and(isfinite(factor.adj_factor) AND factor.adj_factor > 0)
        ORDER BY prices.trade_date LIMIT 1
    """)
    if invalid_date is not None:
        raise SourceContractError(f"Missing, duplicate or invalid adjustment factor for {invalid_date}")


class PriceAdjustmentCalculation:
    algorithm_version = FORMULA_VERSION

    def describe(self, input_adjustment, target, basis):
        if input_adjustment != target and not (input_adjustment == "none" and target in ("qfq", "hfq")):
            raise SourceUnsupportedError("This input/target adjustment is not supported")
        return {"formula_version": self.algorithm_version, "converted": input_adjustment != target,
                "basis_rule": basis}

    def build_sql(self, input_table, factors, basis, *, output_table, fields, time_fields,
                  processed_rows, template: str):
        # All identifiers come from Session constants and the definition whitelist.
        if not set(fields) <= VALUE_FIELDS:
            raise ValueError("Unknown standard price field")
        columns = ["b.seq"] + [f'b."{name}"' for name in time_fields]
        for name in fields:
            expression = f'b."{name}"'
            if name in PRICE_FIELDS:
                expression = f"CAST({expression} * f.adj_factor / a.basis_value AS DOUBLE)"
            columns.append(f'{expression} AS "{name}"')
        return SqlStep("adjust_price", template.format(output_table=output_table,
            projection=", ".join(columns), input_table=input_table, factors=factors, basis=basis),
            (), (input_table, factors, basis), (output_table,), processed_rows)
