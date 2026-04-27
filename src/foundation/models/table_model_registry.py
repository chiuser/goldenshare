from __future__ import annotations

from functools import lru_cache
from importlib import import_module
from pkgutil import walk_packages

from sqlalchemy import Table

from src.foundation import models as foundation_models
from src.foundation.models.base import Base


FOUNDATION_MODEL_SCHEMAS = {
    "core",
    "core_multi",
    "core_serving",
    "core_serving_light",
    "dm",
    "meta",
    "raw_biying",
    "raw_tushare",
}


def _import_foundation_model_modules() -> None:
    for module_info in walk_packages(foundation_models.__path__, f"{foundation_models.__name__}."):
        if module_info.name.endswith(".all_models"):
            continue
        import_module(module_info.name)


def _table_key(table: Table) -> str | None:
    if not table.schema or table.schema not in FOUNDATION_MODEL_SCHEMAS:
        return None
    return f"{table.schema}.{table.name}"


@lru_cache(maxsize=1)
def table_model_registry() -> dict[str, type]:
    _import_foundation_model_modules()
    registry: dict[str, type] = {}
    mappers = sorted(
        Base.registry.mappers,
        key=lambda mapper: f"{mapper.class_.__module__}.{mapper.class_.__name__}",
    )
    for mapper in mappers:
        table_key = _table_key(mapper.local_table)
        if table_key is None:
            continue
        registry[table_key] = mapper.class_
    return registry


def get_model_by_table_name(table_name: str) -> type | None:
    return table_model_registry().get(table_name)
