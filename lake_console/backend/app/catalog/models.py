from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LakeViewGroup:
    group_key: str
    group_label: str
    group_order: int


@dataclass(frozen=True)
class LakeLayerDefinition:
    layer: str
    layer_name: str
    purpose: str
    layout: str
    path: str
    recommended_usage: str


@dataclass(frozen=True)
class LakeDatasetDefinition:
    dataset_key: str
    display_name: str
    source: str
    api_name: str | None
    source_doc_id: str | None
    description: str | None
    dataset_role: str
    storage_root: str
    group_key: str
    primary_layout: str
    available_layouts: tuple[str, ...]
    write_policy: str
    update_mode: str
    supported_freqs: tuple[int, ...] = ()
    raw_freqs: tuple[int, ...] = ()
    derived_freqs: tuple[int, ...] = ()
    layers: tuple[LakeLayerDefinition, ...] = ()
