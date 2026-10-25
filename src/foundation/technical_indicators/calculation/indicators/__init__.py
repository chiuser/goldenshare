"""Assemble the fixed built-ins; execution and discovery share this registry."""


def create_builtin_registry():
    from ..registry import CalculationRegistry
    from . import bollinger_bands, kdj, macd, moving_average, price

    registry = CalculationRegistry()
    for definition, factory in (
        (price.DEFINITION, price.PriceCalculation),
        (moving_average.WINDOW_MEAN_DEFINITION, moving_average.WindowMeanCalculation),
        (moving_average.DEFINITION, moving_average.MovingAverageCalculation),
        (bollinger_bands.DEFINITION, bollinger_bands.BollingerBandsCalculation),
        (macd.DEFINITION, macd.MACDCalculation),
        (kdj.WINDOW_RANGE_DEFINITION, kdj.WindowRangeCalculation),
        (kdj.DEFINITION, kdj.KDJCalculation),
    ):
        registry.register(definition, factory)
    registry.freeze()
    return registry
