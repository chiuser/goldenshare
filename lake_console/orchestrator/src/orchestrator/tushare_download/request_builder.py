"""Build full-field source requests exclusively from the resolved contract."""

from __future__ import annotations

from itertools import product

from .contract_registry import canonical_content
from .download_errors import DownloadErrorCode, require
from .download_models import PageRequest
from .source_contract import scalar_matches


class RequestBuilder:
    def __init__(self, contract):
        self.contract = contract

    def validate_parameters(self, params, mode):
        definitions = {p.name: p for p in self.contract.parameters}
        require(set(params) <= definitions.keys())
        active_roles = {
            x
            for x in (
                mode.object_param,
                mode.point_param,
                mode.range_start_param,
                mode.range_end_param,
            )
            if x is not None
        }
        all_roles = {
            x
            for m in self.contract.modes
            for x in (
                m.object_param,
                m.point_param,
                m.range_start_param,
                m.range_end_param,
            )
            if x is not None
        }
        for p in definitions.values():
            if p.name in all_roles - active_roles:
                require(p.name not in params)
                continue
            if p.name not in params and p.has_default:
                params[p.name] = p.default
            require(not p.required or p.name in params, DownloadErrorCode.INPUT)
            if p.name in params:
                value = params[p.name]
                require(
                    scalar_matches(value, p.source_kind, p.nullable),
                    DownloadErrorCode.INPUT,
                )
                require(
                    p.choices is None
                    or canonical_content(value)
                    in {canonical_content(x) for x in p.choices},
                    DownloadErrorCode.INPUT,
                )
        return tuple(
            (p.name, params[p.name])
            for p in self.contract.parameters
            if p.name in params
        )

    def iter_inputs(self, unit):
        m = self.contract.mode_rule(unit.mode)
        base = dict(unit.filters)

        def add(name, value):
            if name is not None:
                require(name not in base)
                base[name] = value

        add(m.object_param, unit.object_code)
        if m.point_param:
            add(m.point_param, self.contract.time_rule().to_source(unit.point))
        if m.range_start_param:
            rule = self.contract.time_rule()
            add(m.range_start_param, rule.to_source(unit.time_range.start))
            add(m.range_end_param, rule.to_source(unit.time_range.end))
        for values in product(*(v for _, v in unit.enum_values)):
            params = dict(base)
            for (name, _), value in zip(unit.enum_values, values, strict=True):
                require(name not in params)
                params[name] = value
            yield self.validate_parameters(params, m)

    def build_page(self, unit, request_input, position) -> PageRequest:
        params = dict(request_input)
        m, p = self.contract.mode_rule(unit.mode), self.contract.pagination
        if position.time_range is not None:
            require(m.range_start_param is not None and m.range_end_param is not None)
            rule = self.contract.time_rule(p.split_time_rule_key)
            params[m.range_start_param] = rule.to_source(position.time_range.start)
            params[m.range_end_param] = rule.to_source(position.time_range.end)
        ordered = list(self.validate_parameters(params, m))
        if p.strategy != 1:
            require(
                position.offset is not None
                and type(position.offset) is int
                and position.offset >= 0
            )
            ordered.extend(
                ((p.limit_param, p.effective_limit), (p.offset_param, position.offset))
            )
        return PageRequest(
            self.contract.source_api_name,
            self.contract.field_names,
            tuple(ordered),
            position,
            p.effective_limit,
        )
