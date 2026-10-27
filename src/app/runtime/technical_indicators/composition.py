"""Isolated D4 assembly; importing this module does not create a runtime."""

from __future__ import annotations

from dataclasses import dataclass

import anyio

from src.foundation.clients.local_lake.technical_indicator_price_source import LakeTechnicalIndicatorPriceSource
from src.foundation.config.settings import Settings
from src.foundation.technical_indicators.calculation.indicators import create_builtin_registry
from src.foundation.technical_indicators.calculation.registry import CalculationRegistry
from src.foundation.technical_indicators.configuration import KernelConfig
from src.foundation.technical_indicators.sources.contracts import PriceSource

from .admission import AdmissionController


@dataclass(frozen=True, slots=True)
class TechnicalIndicatorRuntime:
    config: KernelConfig
    registry: CalculationRegistry
    source: PriceSource
    admission: AdmissionController

    async def aclose(self) -> None:
        with anyio.CancelScope(shield=True):
            await self.admission.shutdown()


def create_runtime(settings: Settings) -> TechnicalIndicatorRuntime:
    config = KernelConfig.from_settings(settings)
    registry = create_builtin_registry()
    source = LakeTechnicalIndicatorPriceSource(config)
    admission = AdmissionController(config)
    return TechnicalIndicatorRuntime(config, registry, source, admission)
