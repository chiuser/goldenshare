from __future__ import annotations

from collections.abc import Mapping, Sequence

from qtf.contracts.errors import QtfRequestInvalid
from qtf.engine.canonical_hash import canonical_json_hash


def gate_result_hash(payload: Mapping[str, object]) -> str:
    return _record_hash("RUN_GATE_RESULT", payload)


def parameter_result_hash(payload: Mapping[str, object]) -> str:
    return _record_hash("RUN_PARAMETER_RESULT", payload)


def signal_event_hash(payload: Mapping[str, object]) -> str:
    return _record_hash("SECTOR_SIGNAL_EVENT", payload)


def run_validation_result_hash(
    *,
    runtime_fingerprint: Mapping[str, object],
    gate_results: Sequence[Mapping[str, object]],
    parameter_results: Sequence[Mapping[str, object]],
    signal_events: Sequence[Mapping[str, object]],
) -> str:
    ordered_gates = _ordered_unique(gate_results, keys=("gate_key",), label="gate result")
    ordered_parameters = _ordered_unique(
        parameter_results,
        keys=("parameter_set_key",),
        label="parameter result",
    )
    ordered_events = _ordered_unique(
        signal_events,
        keys=("parameter_set_key", "signal_trade_date", "sector_code", "entry_type"),
        label="signal event",
    )
    return canonical_json_hash(
        {
            "runtime_fingerprint": dict(runtime_fingerprint),
            "gate_results": ordered_gates,
            "parameter_results": ordered_parameters,
            "signal_events": ordered_events,
        }
    )


def _record_hash(record_type: str, payload: Mapping[str, object]) -> str:
    return canonical_json_hash({"record_type": record_type, "payload": dict(payload)})


def _ordered_unique(
    values: Sequence[Mapping[str, object]],
    *,
    keys: tuple[str, ...],
    label: str,
) -> list[dict[str, object]]:
    normalized: list[tuple[tuple[str, ...], dict[str, object]]] = []
    seen: set[tuple[str, ...]] = set()
    for value in values:
        missing = [key for key in keys if key not in value]
        if missing:
            raise QtfRequestInvalid(f"{label} is missing stable keys: {missing}")
        identity = tuple(str(value[key]) for key in keys)
        if identity in seen:
            raise QtfRequestInvalid(f"duplicate {label} identity: {identity}")
        seen.add(identity)
        normalized.append((identity, dict(value)))
    return [payload for _, payload in sorted(normalized, key=lambda item: item[0])]
