"""Design §4.5.1: largest remainder allocation over a complete sell day."""

from dataclasses import dataclass

from .precision import CalculationInvariantError, require_integer, round_ratio_half_up


@dataclass(frozen=True, slots=True)
class SellQuantity:
    source_id: str
    quantity: int

    def __post_init__(self) -> None:
        if type(self.source_id) is not str or not self.source_id:
            raise CalculationInvariantError("Missing stable source ID")
        require_integer(self.quantity, minimum=1)


@dataclass(frozen=True, slots=True)
class AllocatedCost:
    source_id: str
    cost_cents: int
    adjustment_cents: int


@dataclass(frozen=True, slots=True)
class CostAllocation:
    items: tuple[AllocatedCost, ...]
    allocated_cents: int
    remaining_cost_cents: int
    remaining_quantity: int


def allocate_sell_costs(pool_cents: int, opening_quantity: int,
                        sells: tuple[SellQuantity, ...]) -> CostAllocation:
    require_integer(pool_cents, minimum=0)
    require_integer(opening_quantity, minimum=0)
    if len({item.source_id for item in sells}) != len(sells):
        raise CalculationInvariantError("Duplicate sell identity")
    total_quantity = sum(item.quantity for item in sells)
    if total_quantity > opening_quantity:
        raise CalculationInvariantError("Sell exceeds opening quantity")
    if not sells:
        return CostAllocation((), 0, pool_cents, opening_quantity)
    target = round_ratio_half_up(pool_cents * total_quantity, opening_quantity)
    bases = {item.source_id: pool_cents * item.quantity // opening_quantity for item in sells}
    remainder_order = sorted(sells, key=lambda item: (
        -(pool_cents * item.quantity % opening_quantity), item.source_id))
    extra = target - sum(bases.values())
    if not 0 <= extra <= len(sells):
        raise CalculationInvariantError("Allocation remainder out of bounds")
    for item in remainder_order[:extra]:
        bases[item.source_id] += 1
    items = tuple(AllocatedCost(item.source_id, bases[item.source_id], bases[item.source_id] -
                               round_ratio_half_up(pool_cents * item.quantity, opening_quantity))
                  for item in sorted(sells, key=lambda item: item.source_id))
    return CostAllocation(items, target, pool_cents - target, opening_quantity - total_quantity)
