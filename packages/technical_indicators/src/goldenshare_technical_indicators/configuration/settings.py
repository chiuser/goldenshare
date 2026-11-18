"""不可变的计算配置，不读取环境或数据文件。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import Literal

from ..contracts import Adjustment, Period, SecurityType, PERIODS, _MAX_OUTPUT_ROWS
from ..errors import SourceUnsupportedError
from ..sources.contracts import DatasetReadTarget


DataLocation = Literal["dg", "prod_pg"]
_BACKENDS = ("dg", "prod_pg")
_ADJUSTMENTS = ("none", "qfq", "hfq")
_CONFIG_FIELDS = {"goldenshare_lake_root", "data_location", "dataset_locations", "market_datasets"}
_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*")
_TOKEN = re.compile(r"[A-Za-z0-9_-]+")
_PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
_DATE_PARTITIONS = {"trade_date", "week_end", "month"}


def _freeze_conditions(values: Mapping[str, object]) -> Mapping[str, int | str]:
    if not isinstance(values, Mapping):
        raise ValueError("Fixed conditions must be a mapping")
    for key, value in values.items():
        if not isinstance(key, str) or not _IDENTIFIER.fullmatch(key):
            raise ValueError("Invalid fixed condition name")
        if type(value) is not int and (not isinstance(value, str) or not _TOKEN.fullmatch(value)):
            raise ValueError("Fixed conditions require integer or plain string values")
    return MappingProxyType(dict(values))


def _freeze_location(backend: str, location: Mapping[str, object] | None):
    if location is None:
        return None
    required, conditions = (
        ({"relative_path"}, "partitions") if backend == "dg" else ({"schema", "relation"}, "filters")
    )
    if (not isinstance(location, Mapping) or not required <= location.keys()
            or location.keys() - required - {conditions, "enabled_adjustments"}):
        raise ValueError(f"Invalid {backend} dataset location")

    allowed = location.get("enabled_adjustments", ())
    if (not isinstance(allowed, (list, tuple, set, frozenset))
            or any(value not in _ADJUSTMENTS for value in allowed)):
        raise ValueError("Invalid enabled adjustments")
    fixed = _freeze_conditions(location.get(conditions, {}))
    if backend == "dg":
        path = location["relative_path"]
        if (not isinstance(path, str) or "\\" in path or ":" in path
                or any(part in {"", ".", ".."} for part in path.split("/"))):
            raise ValueError("DG location requires a relative path inside the lake")
        placeholders = set(_PLACEHOLDER.findall(path))
        remaining = _PLACEHOLDER.sub("", path)
        if ("{" in remaining or "}" in remaining or not fixed.keys() <= placeholders
                or placeholders - fixed.keys() - _DATE_PARTITIONS):
            raise ValueError("Invalid DG partition template")
    elif any(
        not isinstance(location[key], str) or not _IDENTIFIER.fullmatch(location[key])
        for key in required
    ):
        raise ValueError("PG requires a schema and relation name")
    return MappingProxyType({
        **{key: location[key] for key in required},
        conditions: fixed,
        "enabled_adjustments": frozenset(allowed),
    })


@dataclass(frozen=True, slots=True, kw_only=True)
class KernelConfig:
    """一次运行实例的配置。"""

    goldenshare_lake_root: str
    max_concurrent_requests: int
    max_waiting_requests: int
    max_wait_ms: int
    sql_threads: int
    batch_rows: int
    query_memory_bytes: int
    request_memory_bytes: int
    deployment_reserve_bytes: int
    total_target_ms: int
    cleanup_reserve_ms: int
    max_input_rows: int
    max_source_files: int
    max_output_rows: int
    max_indicator_instances: int
    max_projected_row_group_bytes: int
    control_poll_ms: int
    monitor_join_target_ms: int
    data_location: DataLocation
    dataset_locations: Mapping[str, Mapping[str, Mapping[str, object] | None]]
    market_datasets: Mapping[tuple[SecurityType, Period], str]

    def __post_init__(self) -> None:
        for field in fields(self):
            if field.name in _CONFIG_FIELDS:
                continue
            value = getattr(self, field.name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field.name} must be an integer, not bool")
            minimum = 0 if field.name == "max_waiting_requests" else 1
            if value < minimum:
                raise ValueError(f"{field.name} must be >= {minimum}")
        if self.cleanup_reserve_ms >= self.total_target_ms:
            raise ValueError("cleanup_reserve_ms must be smaller than total_target_ms")
        if self.control_poll_ms >= self.cleanup_reserve_ms:
            raise ValueError("control_poll_ms must be smaller than cleanup_reserve_ms")
        if self.max_output_rows > _MAX_OUTPUT_ROWS:
            raise ValueError(f"max_output_rows must be <= {_MAX_OUTPUT_ROWS}")
        if self.data_location not in _BACKENDS:
            raise ValueError("data_location must be dg or prod_pg")
        if self.data_location == "dg" and (
            not isinstance(self.goldenshare_lake_root, str)
            or not PurePosixPath(self.goldenshare_lake_root).is_absolute()
        ):
            raise ValueError("DG requires an absolute lake root")
        if not isinstance(self.dataset_locations, Mapping) or not isinstance(self.market_datasets, Mapping):
            raise ValueError("Data locations and market datasets must be mappings")
        locations = {}
        for dataset_id, backends in self.dataset_locations.items():
            if (not isinstance(dataset_id, str) or not _IDENTIFIER.fullmatch(dataset_id)
                    or not isinstance(backends, Mapping) or backends.keys() != set(_BACKENDS)):
                raise ValueError("A dataset must declare both dg and prod_pg locations")
            locations[dataset_id] = MappingProxyType({
                backend: _freeze_location(backend, backends[backend]) for backend in _BACKENDS
            })
        markets = dict(self.market_datasets)
        for key, dataset_id in markets.items():
            if (not isinstance(key, tuple) or len(key) != 2 or key[0] not in ("stock", "index")
                    or key[1] not in PERIODS or not isinstance(dataset_id, str) or dataset_id not in locations):
                raise ValueError("Invalid market dataset mapping")
            security_type, period = key
            adjustable = security_type == "stock" and period not in ("week", "month", "90m", "120m")
            supported = set(_ADJUSTMENTS) if adjustable else {"none"}
            if any(location is not None and location["enabled_adjustments"] - supported
                   for location in locations[dataset_id].values()):
                raise ValueError("Adjustment is unsupported for this market dataset")
        object.__setattr__(self, "dataset_locations", MappingProxyType(locations))
        object.__setattr__(self, "market_datasets", MappingProxyType(markets))

    def market_dataset_id(self, security_type: SecurityType, period: Period) -> str:
        dataset_id = self.market_datasets.get((security_type, period))
        if dataset_id is None:
            raise SourceUnsupportedError("Market dataset is not registered")
        return dataset_id

    def _location(self, dataset_id: str) -> Mapping[str, object] | None:
        backends = self.dataset_locations.get(dataset_id)
        return None if backends is None else backends[self.data_location]

    def enabled_adjustments(self, dataset_id: str) -> frozenset[Adjustment]:
        location = self._location(dataset_id)
        return frozenset() if location is None else location["enabled_adjustments"]

    def resolve_dataset_location(self, dataset_id: str) -> DatasetReadTarget:
        location = self._location(dataset_id)
        if location is None:
            raise SourceUnsupportedError("Dataset has no location in this environment")
        if self.data_location == "dg":
            template = location["relative_path"]
            for key, value in location["partitions"].items():
                template = template.replace("{" + key + "}", str(value))
            selected = {"path_template": str(PurePosixPath(self.goldenshare_lake_root) / template)}
        else:
            selected = {key: location[key] for key in ("schema", "relation", "filters")}
        return DatasetReadTarget(dataset_id, self.data_location, MappingProxyType(selected))
