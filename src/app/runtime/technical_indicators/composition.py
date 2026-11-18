"""Isolated D4 assembly; importing this module does not create a runtime."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

import anyio

from src.foundation.clients.local_lake.technical_indicator_price_source import LakeTechnicalIndicatorPriceSource
from src.foundation.clients.technical_indicator_postgres import PostgresTechnicalIndicatorPriceSource
from src.foundation.config.settings import Settings, technical_indicator_config_from_settings
from goldenshare_technical_indicators.calculation.indicators import create_builtin_registry
from goldenshare_technical_indicators.calculation.registry import CalculationRegistry
from goldenshare_technical_indicators.configuration import KernelConfig
from goldenshare_technical_indicators.configuration.datasets import DATASET_LOCATIONS
from goldenshare_technical_indicators.sources.contracts import PriceSource

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


def create_runtime(settings: Settings, *, session_factory=None) -> TechnicalIndicatorRuntime:
    environment = settings.app_env.strip().lower()
    if "app_env" not in settings.model_fields_set or environment not in {"dev", "local", "prod", "production"}:
        raise ValueError("Technical indicators require an explicit local or production APP_ENV")
    backend = "dg" if environment in {"dev", "local"} else "prod_pg"
    locations = deepcopy(DATASET_LOCATIONS)
    for dataset_id, adjustments in (
        ("stock_daily", ("none", "qfq")), ("index_daily", ("none",)), ("index_mins_5m", ("none",)),
    ):
        locations[dataset_id][backend]["enabled_adjustments"] = adjustments
    config = technical_indicator_config_from_settings(settings, data_location=backend, dataset_locations=locations)
    registry = create_builtin_registry()
    if backend == "dg":
        source = LakeTechnicalIndicatorPriceSource(config)
    else:
        if session_factory is None:
            from src.db import get_session_factory

            session_factory = get_session_factory()
        source = PostgresTechnicalIndicatorPriceSource(config, session_factory)
    admission = AdmissionController(config)
    return TechnicalIndicatorRuntime(config, registry, source, admission)
