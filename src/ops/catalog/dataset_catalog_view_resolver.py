from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from src.foundation.datasets.models import DatasetDefinition
from src.foundation.datasets.registry import list_dataset_definitions
from src.ops.catalog.dataset_catalog_views import (
    OPS_DATASET_DEFAULT_VIEW,
    DatasetCatalogGroup,
    DatasetCatalogItem,
    DatasetCatalogView,
)


class DatasetCatalogConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedDatasetCatalogItem:
    dataset_key: str
    group_key: str
    group_label: str
    group_order: int
    item_order: int
    visible: bool


def get_default_dataset_catalog_view() -> DatasetCatalogView:
    return OPS_DATASET_DEFAULT_VIEW


def resolve_default_dataset_catalog_item(dataset_key: str) -> ResolvedDatasetCatalogItem:
    return DatasetCatalogViewResolver().resolve_item(dataset_key)


def validate_default_dataset_catalog(definitions: Iterable[DatasetDefinition] | None = None) -> list[str]:
    return DatasetCatalogViewResolver().validate(definitions)


class DatasetCatalogViewResolver:
    def __init__(self, view: DatasetCatalogView = OPS_DATASET_DEFAULT_VIEW) -> None:
        self._view = view
        self._groups = self._build_group_index(view.groups)
        self._items = self._build_item_index(view.items)

    def resolve_item(self, dataset_key: str) -> ResolvedDatasetCatalogItem:
        item = self._items.get(dataset_key)
        if item is None:
            raise DatasetCatalogConfigurationError(f"数据集未配置 Ops 展示目录：{dataset_key}")
        group = self._groups.get(item.group_key)
        if group is None:
            raise DatasetCatalogConfigurationError(f"数据集展示目录引用了不存在的分组：{dataset_key} -> {item.group_key}")
        return ResolvedDatasetCatalogItem(
            dataset_key=dataset_key,
            group_key=group.group_key,
            group_label=group.group_label,
            group_order=group.group_order,
            item_order=item.item_order,
            visible=item.visible,
        )

    def validate(self, definitions: Iterable[DatasetDefinition] | None = None) -> list[str]:
        errors: list[str] = []
        registry_keys = {definition.dataset_key for definition in (definitions or list_dataset_definitions())}
        group_labels: dict[str, tuple[str, int]] = {}
        for group in self._view.groups:
            previous = group_labels.get(group.group_key)
            current = (group.group_label, group.group_order)
            if previous is not None and previous != current:
                errors.append(f"group_key 重复但 label/order 不一致：{group.group_key}")
            group_labels[group.group_key] = current

        seen_items: set[str] = set()
        for item in self._view.items:
            if item.dataset_key in seen_items:
                errors.append(f"dataset_key 重复配置：{item.dataset_key}")
            seen_items.add(item.dataset_key)
            if item.group_key not in group_labels:
                errors.append(f"dataset_key 引用了不存在的 group_key：{item.dataset_key} -> {item.group_key}")
            if item.dataset_key not in registry_keys:
                errors.append(f"展示目录引用了不存在的 dataset_key：{item.dataset_key}")

        missing = sorted(registry_keys - seen_items)
        if missing:
            errors.append(f"数据集缺少 Ops 展示目录配置：{', '.join(missing)}")

        return errors

    @staticmethod
    def _build_group_index(groups: Iterable[DatasetCatalogGroup]) -> dict[str, DatasetCatalogGroup]:
        result: dict[str, DatasetCatalogGroup] = {}
        for group in groups:
            previous = result.get(group.group_key)
            if previous is not None and (previous.group_label, previous.group_order) != (group.group_label, group.group_order):
                raise DatasetCatalogConfigurationError(f"group_key 重复但 label/order 不一致：{group.group_key}")
            result[group.group_key] = group
        return result

    @staticmethod
    def _build_item_index(items: Iterable[DatasetCatalogItem]) -> dict[str, DatasetCatalogItem]:
        result: dict[str, DatasetCatalogItem] = {}
        for item in items:
            if item.dataset_key in result:
                raise DatasetCatalogConfigurationError(f"dataset_key 重复配置：{item.dataset_key}")
            result[item.dataset_key] = item
        return result
