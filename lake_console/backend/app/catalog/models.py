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
    layer_order: int
    description: str


LAKE_LAYER_DEFINITIONS: tuple[LakeLayerDefinition, ...] = (
    LakeLayerDefinition(layer="raw_tushare", layer_name="原始层", layer_order=10, description="源站或生产库导出的原始事实层。"),
    LakeLayerDefinition(layer="manifest", layer_name="辅助清单层", layer_order=20, description="本地同步、对象池和治理辅助清单。"),
    LakeLayerDefinition(layer="derived", layer_name="派生层", layer_order=30, description="由本地数据计算生成的派生资产。"),
    LakeLayerDefinition(layer="research", layer_name="研究层", layer_order=40, description="面向研究查询优化的重排或清洗资产。"),
)

_LAYER_BY_KEY = {item.layer: item for item in LAKE_LAYER_DEFINITIONS}


def get_layer_definition(layer: str) -> LakeLayerDefinition:
    try:
        return _LAYER_BY_KEY[layer]
    except KeyError as exc:
        raise ValueError(f"Unknown Lake layer: {layer}") from exc


@dataclass(frozen=True)
class LakeNodeDefinition:
    layer: str
    node_name: str
    description: str
    scan_profile: str
    path: str
    recommended_usage: str
    node_key: str | None = None
    asset_role: str | None = None
    source_node_keys: tuple[str, ...] = ()
    partition_dimensions: tuple[str, ...] = ()
    sort_order: int = 0

    def __post_init__(self) -> None:
        scan_profile = _normalize_scan_profile(self.scan_profile, path=self.path)
        object.__setattr__(self, "scan_profile", scan_profile)
        if self.node_key is None:
            object.__setattr__(self, "node_key", _default_node_key(layer=self.layer, scan_profile=scan_profile, path=self.path))
        if self.asset_role is None:
            object.__setattr__(self, "asset_role", _default_asset_role(layer=self.layer, path=self.path))
        if not self.partition_dimensions:
            object.__setattr__(self, "partition_dimensions", _default_partition_dimensions(scan_profile))
        get_layer_definition(self.layer)


@dataclass(frozen=True)
class LakeCommandExample:
    example_key: str
    title: str
    scenario: str
    description: str
    argv: tuple[str, ...]
    prerequisites: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def command(self) -> str:
        return " ".join(self.argv)


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
    nodes: tuple[LakeNodeDefinition, ...] = ()
    command_examples: tuple[LakeCommandExample, ...] = ()

    def require_node(self, *, layer: str | None = None, node_key: str | None = None) -> LakeNodeDefinition:
        for node in self.nodes:
            if layer is not None and node.layer != layer:
                continue
            if node_key is not None and node.node_key != node_key:
                continue
            return node
        details = []
        if layer is not None:
            details.append(f"layer={layer}")
        if node_key is not None:
            details.append(f"node_key={node_key}")
        raise RuntimeError(f"LakeDatasetDefinition 缺少内容节点：dataset_key={self.dataset_key} {' '.join(details)}")


@dataclass(frozen=True)
class LakeCommandSetDefinition:
    command_set_key: str
    display_name: str
    group_key: str
    description: str
    command_examples: tuple[LakeCommandExample, ...]


def _normalize_scan_profile(scan_profile: str, *, path: str) -> str:
    if scan_profile == "by_symbol_month":
        return "freq_trade_month_bucket"
    if scan_profile == "by_date":
        return "freq_trade_date" if path.endswith("_mins_by_date") else "trade_date"
    return scan_profile


def _default_node_key(*, layer: str, scan_profile: str, path: str) -> str:
    name = path.rstrip("/").split("/")[-1]
    if scan_profile == "current_file":
        return "raw_current" if layer == "raw_tushare" else f"{layer}_current"
    if scan_profile == "manifest_file":
        return "manifest_file"
    if name == "stk_mins_by_date_clean_next":
        return "clean_next_by_date"
    if name == "stk_mins_by_symbol_month":
        return "by_symbol_month"
    if name == "stk_mins_indicators_by_date":
        return "indicators_by_date"
    if name == "stk_mins_indicators_by_symbol_month":
        return "indicators_by_symbol_month"
    if scan_profile == "freq_trade_date":
        return f"{layer}_by_date"
    if scan_profile == "freq_trade_month_bucket":
        return f"{layer}_by_symbol_month"
    if scan_profile == "trade_date":
        return f"{layer}_by_date"
    if scan_profile == "event_date":
        return f"{layer}_by_event_date"
    return f"{layer}_{scan_profile}"


def _default_asset_role(*, layer: str, path: str) -> str:
    if "clean_next" in path:
        return "clean_baseline"
    if "indicators" in path:
        return "local_derived" if layer == "derived" else "query_projection"
    if layer == "raw_tushare":
        return "source_raw"
    if layer == "manifest":
        return "governance_manifest"
    if layer == "derived":
        return "local_derived"
    if layer == "research":
        return "query_projection"
    return "lake_asset"


def _default_partition_dimensions(scan_profile: str) -> tuple[str, ...]:
    mapping = {
        "current_file": (),
        "manifest_file": (),
        "event_date": ("event_date",),
        "trade_date": ("trade_date",),
        "freq_trade_date": ("freq", "trade_date"),
        "freq_trade_month_bucket": ("freq", "trade_month", "bucket"),
        "indicator_params_freq_trade_date": ("indicator", "params_key", "freq", "trade_date"),
        "indicator_params_freq_trade_month_bucket": ("indicator", "params_key", "freq", "trade_month", "bucket"),
    }
    return mapping.get(scan_profile, ())
