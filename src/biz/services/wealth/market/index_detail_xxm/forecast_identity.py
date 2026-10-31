"""One result identity from native next-bar facts, independent of display/DTOs."""
from __future__ import annotations

import hashlib
import json
import math


ROOT_FACT_FIELDS = (
    'tsCode', 'period', 'forecastVersion', 'forecastSpecHash', 'detectorSpecHash',
    'computedThrough', 'requestedAsOf', 'mode', 'dataStatus', 'ordinaryState',
    'direction', 'targetEndpoint', 'barsAhead', 'status', 'reasonCode',
)
DETAIL_FACT_FIELDS = (
    'sourceInputId', 'calendarInputId', 'precisionPolicy', 'references',
    'selectedReference', 'nearestDecision', 'farEvaluated', 'conditions',
    'precisionRanges', 'structureFollowConditions',
)
_FLOAT_FIELDS = frozenset((
    'price', 'dif', 'lower', 'upper', 'e12', 'e26', 'dea', 'pCoefficient',
    'cCoefficient', 'constant', 'factor', 'guard',
))


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _numeric_facts(value, field=None):
    if field in _FLOAT_FIELDS and value is not None:
        if type(value) not in (int, float):
            raise ValueError('Identity numeric facts must be original numbers')
        try:
            number = float(value)
        except OverflowError as exc:
            raise ValueError('Identity numeric facts must be finite') from exc
        if not math.isfinite(number):
            raise ValueError('Identity numeric facts must be finite')
        return 0.0 if number == 0 else number
    if isinstance(value, dict):
        return {key: _numeric_facts(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [_numeric_facts(item) for item in value]
    return value


def forecast_result_id(payload: dict) -> str:
    facts = {name: payload[name] for name in (*ROOT_FACT_FIELDS, *DETAIL_FACT_FIELDS)}
    facts = _numeric_facts(facts)
    for condition in (*facts['conditions'], *facts['structureFollowConditions']):
        condition.pop('id', None)
        for price_range in condition['priceRanges']:
            price_range.pop('displayLower', None)
            price_range.pop('displayUpper', None)
    return digest(facts)


def forecast_condition_id(forecast_id: str, outcome: str, related_structure_id: str | None = None) -> str:
    facts = {'forecastId': forecast_id, 'outcome': outcome}
    if related_structure_id is not None:
        facts['relatedStructureId'] = related_structure_id
    return digest(facts)
