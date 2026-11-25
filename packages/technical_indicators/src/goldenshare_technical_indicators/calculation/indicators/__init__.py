"""Assemble the fixed built-ins; execution and discovery share this registry."""

from dataclasses import replace


def create_builtin_registry(*, enable_index_minute_nine_turn: bool = False):
    from ..registry import CalculationRegistry
    from . import bollinger_bands, kdj, macd, moving_average, nine_turn, price, trend_channel

    nine_turn_definition = nine_turn.DEFINITION
    if enable_index_minute_nine_turn:
        nine_turn_definition = replace(
            nine_turn_definition,
            additional_sources=(*nine_turn_definition.additional_sources, *nine_turn.INDEX_MINUTE_SOURCES),
        )

    registry = CalculationRegistry()
    for definition, factory in (
        (price.DEFINITION, price.PriceCalculation),
        (moving_average.WINDOW_MEAN_DEFINITION, moving_average.WindowMeanCalculation),
        (moving_average.DEFINITION, moving_average.MovingAverageCalculation),
        (bollinger_bands.DEFINITION, bollinger_bands.BollingerBandsCalculation),
        (macd.DEFINITION, macd.MACDCalculation),
        (kdj.WINDOW_RANGE_DEFINITION, kdj.WindowRangeCalculation),
        (kdj.DEFINITION, kdj.KDJCalculation),
        (nine_turn_definition, nine_turn.NineTurnCalculation),
        (trend_channel.DEFINITION, trend_channel.TrendChannelCalculation),
    ):
        registry.register(definition, factory)
    registry.freeze()
    return registry
