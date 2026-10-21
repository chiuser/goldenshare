"""Named local contracts and canonical full-content comparison, never cross-project IO."""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields, is_dataclass
from decimal import Decimal
from enum import IntEnum
from types import MappingProxyType
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .download_errors import require
from .download_models import DownloadMode
from .source_contract import (
    _FORMATS,
    SourceDatasetContract,
    SourceKind,
    scalar_matches,
)


def canonical_value(value):
    if value is None:
        return [0]
    if isinstance(value, IntEnum):
        return [2, str(int(value))]
    if type(value) is bool:
        return [4, value]
    if type(value) is str:
        return [1, value]
    if type(value) is int:
        return [2, str(value)]
    if type(value) is Decimal:
        require(value.is_finite())
        parts = value.as_tuple()
        return [3, parts.sign, list(parts.digits), parts.exponent]
    if is_dataclass(value):
        return {
            f.name: canonical_value(getattr(value, f.name))
            for f in fields(value)
            if f.name != "local_evidence_paths"
        }
    if isinstance(value, dict):
        return {key: canonical_value(value[key]) for key in sorted(value)}
    if type(value) in (tuple, list):
        return [canonical_value(x) for x in value]
    raise TypeError("unsupported canonical definition")


def canonical_content(value) -> bytes:
    return json.dumps(
        canonical_value(value),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def content_digest(value) -> str:
    return hashlib.sha256(canonical_content(value)).hexdigest()


def _unique(values) -> bool:
    keys = [canonical_content(x) for x in values]
    return len(keys) == len(set(keys))


def validate_contract(contract: SourceDatasetContract) -> None:
    require(isinstance(contract, SourceDatasetContract))
    require(
        all(
            type(x) is str and x
            for x in (
                contract.contract_name,
                contract.dataset_id,
                contract.version,
                contract.source_api_name,
            )
        )
    )
    require(contract.contract_name.endswith("@" + contract.version))
    require(type(contract.fields) is tuple and bool(contract.fields))
    require(len(set(contract.field_names)) == len(contract.fields))
    for f in contract.fields:
        require(
            type(f.name) is str
            and bool(f.name)
            and isinstance(f.source_kind, SourceKind)
        )
        require(type(f.nullable) is bool)
    require(
        type(contract.parameters) is tuple
        and type(contract.modes) is tuple
        and bool(contract.modes)
    )
    params = {p.name: p for p in contract.parameters}
    require(len(params) == len(contract.parameters))
    forbidden = {"token", "fields", "api_name", "url", "base_url", "database", "path"}
    require(not forbidden.intersection(params))
    for p in params.values():
        require(
            type(p.name) is str
            and bool(p.name)
            and isinstance(p.source_kind, SourceKind)
        )
        require(all(type(x) is bool for x in (p.required, p.has_default, p.nullable)))
        if p.has_default:
            require(scalar_matches(p.default, p.source_kind, p.nullable))
        if p.choices is not None:
            require(type(p.choices) is tuple and _unique(p.choices))
            require(
                all(scalar_matches(v, p.source_kind, p.nullable) for v in p.choices)
            )
    require(len({m.mode for m in contract.modes}) == len(contract.modes))
    for m in contract.modes:
        require(isinstance(m.mode, DownloadMode))
        require(
            type(m.allowed_filters) is tuple
            and type(m.enum_dimensions) is tuple
            and type(m.unit_enum_dimensions) is tuple
        )
        require(
            all(
                type(x) is bool
                for x in (
                    m.allow_empty_objects,
                    m.allow_empty_points,
                    m.allow_empty_object_ranges,
                )
            )
        )
        roles = tuple(
            x
            for x in (
                m.object_param,
                m.point_param,
                m.range_start_param,
                m.range_end_param,
            )
            if x is not None
        )
        enums = tuple(e.parameter_name for e in m.enum_dimensions)
        require(
            len(set(roles + m.allowed_filters + enums))
            == len(roles + m.allowed_filters + enums)
        )
        require(set(roles + m.allowed_filters + enums) <= params.keys())
        require(
            bool(m.object_param)
            == (
                m.mode
                in (
                    DownloadMode.BY_OBJECT,
                    DownloadMode.BY_OBJECT_POINT,
                    DownloadMode.BY_OBJECT_RANGE,
                )
            )
        )
        require(
            bool(m.point_param)
            == (m.mode in (DownloadMode.BY_POINT, DownloadMode.BY_OBJECT_POINT))
        )
        needs_range = m.mode in (DownloadMode.BY_RANGE, DownloadMode.BY_OBJECT_RANGE)
        require(
            bool(m.range_start_param) == needs_range
            and bool(m.range_end_param) == needs_range
        )
        require(
            len(set(m.unit_enum_dimensions)) == len(m.unit_enum_dimensions)
            and set(m.unit_enum_dimensions) <= set(enums)
        )
        for e in m.enum_dimensions:
            require(
                type(e.ordered_values) is tuple
                and bool(e.ordered_values)
                and _unique(e.ordered_values)
            )
            require(
                all(
                    scalar_matches(
                        v,
                        params[e.parameter_name].source_kind,
                        params[e.parameter_name].nullable,
                    )
                    for v in e.ordered_values
                )
            )
            require(type(e.has_default) is bool and type(e.default_values) is tuple)
            require(_unique(e.default_values))
            require(not e.has_default or bool(e.default_values))
            require(
                all(
                    canonical_content(v)
                    in {canonical_content(x) for x in e.ordered_values}
                    for v in e.default_values
                )
            )
    all_roles = {
        x
        for m in contract.modes
        for x in (m.object_param, m.point_param, m.range_start_param, m.range_end_param)
        if x is not None
    }
    for m in contract.modes:
        roles = {
            x
            for x in (
                m.object_param,
                m.point_param,
                m.range_start_param,
                m.range_end_param,
            )
            if x is not None
        }
        require(not (all_roles & set(m.allowed_filters)))
        require(not (all_roles & {e.parameter_name for e in m.enum_dimensions}))
        require(
            all(
                not p.required or p.name not in all_roles or p.name in roles
                for p in contract.parameters
            )
        )
    p = contract.pagination
    require(type(p.strategy) is int and p.strategy in (1, 2, 3))
    if p.strategy == 1:
        require(
            all(
                x is None
                for x in (
                    p.effective_limit,
                    p.offset_start,
                    p.offset_step,
                    p.limit_param,
                    p.offset_param,
                    p.split_time_rule_key,
                )
            )
        )
    else:
        require(type(p.effective_limit) is int and p.effective_limit > 0)
        require(
            type(p.offset_start) is int
            and p.offset_start >= 0
            and type(p.offset_step) is int
            and p.offset_step > 0
        )
        require(
            type(p.limit_param) is str
            and bool(p.limit_param)
            and type(p.offset_param) is str
            and bool(p.offset_param)
        )
        require(
            p.limit_param != p.offset_param
            and not ({p.limit_param, p.offset_param} & (params.keys() | forbidden))
        )
        require(
            p.short_page_ends or p.empty_page_ends or p.reliable_total_path is not None
        )
    require(type(p.short_page_ends) is bool and type(p.empty_page_ends) is bool)
    require(
        p.truncation_limit is None
        or (type(p.truncation_limit) is int and p.truncation_limit > 0)
    )
    for path in (p.reliable_total_path, p.reliable_next_offset_path):
        require(
            path is None
            or (
                type(path) is tuple
                and bool(path)
                and all(type(x) is str and bool(x) for x in path)
            )
        )
    require(
        type(contract.time_rules) is tuple
        and len({x.rule_key for x in contract.time_rules}) == len(contract.time_rules)
    )
    for t in contract.time_rules:
        require(t.rule_key in ("day", "month", "timestamp") and t.rule_version == "1")
        require(
            t.input_format in _FORMATS
            and t.source_format in _FORMATS
            and t.range_bounds == "closed"
        )
        require(type(t.minimum_step) is int and t.minimum_step == 1)
        require(t.rule_key != "timestamp" or t.timezone is not None)
        formats = {
            "day": {"YYYY-MM-DD", "YYYYMMDD"},
            "month": {"YYYY-MM", "YYYYMM"},
            "timestamp": {"YYYY-MM-DD HH:MM:SS", "YYYYMMDD HH:MM:SS"},
        }[t.rule_key]
        require(t.input_format in formats and t.source_format in formats)
        if t.timezone is not None:
            valid_zone = True
            try:
                ZoneInfo(t.timezone)
            except (ZoneInfoNotFoundError, ValueError, TypeError):
                valid_zone = False
            require(valid_zone)
    if any(m.point_param or m.range_start_param for m in contract.modes):
        contract.time_rule()
    if p.strategy == 3:
        require(p.split_time_rule_key is not None)
        contract.time_rule(p.split_time_rule_key)
        require(all(m.range_start_param is not None for m in contract.modes))
    o = contract.ordering
    require((o.time_field is None) == (o.time_rule_key is None))
    if o.time_field is not None:
        require(o.time_field in contract.field_names)
        contract.time_rule(o.time_rule_key)


class ContractRegistry:
    def __init__(self, contracts: tuple[SourceDatasetContract, ...] = ()):
        for contract in contracts:
            validate_contract(contract)
        require(len({c.contract_name for c in contracts}) == len(contracts))
        self._contracts = MappingProxyType({c.contract_name: c for c in contracts})

    def resolve(self, name: str) -> SourceDatasetContract:
        contract = self._contracts.get(name)
        require(contract is not None)
        return contract

    @staticmethod
    def same_content(left: SourceDatasetContract, right: SourceDatasetContract) -> bool:
        return canonical_content(left) == canonical_content(right)
