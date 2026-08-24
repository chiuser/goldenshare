from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from qtf.contracts.errors import QtfRequestInvalid


class ValidationGateKey(StrEnum):
    INPUT = "INPUT"
    TIME_FRONTIER = "TIME_FRONTIER"
    FUTURE_LEAKAGE = "FUTURE_LEAKAGE"
    WARMUP = "WARMUP"
    COVERAGE = "COVERAGE"
    OUT_OF_SAMPLE_SENSITIVITY = "OUT_OF_SAMPLE_SENSITIVITY"


class ValidationGateResultStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT = "INSUFFICIENT"


class ParameterEffectStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    REJECTED = "REJECTED"
    INSUFFICIENT = "INSUFFICIENT"


class SignalEntryType(StrEnum):
    ENTRY = "ENTRY"
    RETENTION = "RETENTION"


class HorizonEvaluationStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    UNEVALUABLE = "UNEVALUABLE"


class RunConclusionKind(StrEnum):
    ENDED = "ENDED"
    OBSERVED = "OBSERVED"


@dataclass(frozen=True, slots=True)
class FutureHorizonRule:
    horizon_trade_days: int
    required_on_list_days: int

    def as_dict(self) -> dict[str, int]:
        return {
            "horizon_trade_days": self.horizon_trade_days,
            "required_on_list_days": self.required_on_list_days,
        }


@dataclass(frozen=True, slots=True)
class ValidationContractDefinition:
    contract_key: str
    contract_version: int
    primary_objective: str
    event_types: tuple[SignalEntryType, ...]
    future_horizon_rules: tuple[FutureHorizonRule, ...]
    label_tail_trade_days: int
    split_rule: str
    hard_gates: tuple[ValidationGateKey, ...]
    ranking_source: str
    missing_future_policy: HorizonEvaluationStatus
    active: bool = True

    @property
    def identity(self) -> tuple[str, int]:
        return self.contract_key, self.contract_version

    def success_definition(self) -> dict[str, object]:
        return {
            "selected_keys": [self.primary_objective],
            "validation_contract_key": self.contract_key,
            "validation_contract_version": self.contract_version,
            "event_types": [item.value for item in self.event_types],
            "future_horizons": [item.horizon_trade_days for item in self.future_horizon_rules],
            "future_horizon_rules": [item.as_dict() for item in self.future_horizon_rules],
            "ranking_source": self.ranking_source,
            "missing_future_policy": self.missing_future_policy.value,
        }


class ValidationContractRegistry:
    def __init__(self, contracts: Iterable[ValidationContractDefinition]) -> None:
        by_identity: dict[tuple[str, int], ValidationContractDefinition] = {}
        for contract in contracts:
            identity = contract.identity
            if identity in by_identity:
                raise ValueError(f"duplicate validation contract registration: {identity[0]}@{identity[1]}")
            _validate_definition(contract)
            by_identity[identity] = contract
        self._by_identity = MappingProxyType(by_identity)

    def get(self, contract_key: str, contract_version: int) -> ValidationContractDefinition:
        identity = (contract_key, contract_version)
        contract = self._by_identity.get(identity)
        if contract is None or not contract.active:
            raise QtfRequestInvalid(
                f"validation contract is not registered: {contract_key}@{contract_version}"
            )
        return contract

    def definitions(self) -> tuple[ValidationContractDefinition, ...]:
        return tuple(contract for _, contract in sorted(self._by_identity.items()))


def _validate_definition(contract: ValidationContractDefinition) -> None:
    if not contract.contract_key.strip() or contract.contract_version < 1:
        raise ValueError("validation contract identity is invalid")
    if not contract.event_types or len(set(contract.event_types)) != len(contract.event_types):
        raise ValueError("validation contract event types must be unique and non-empty")
    horizons = tuple(item.horizon_trade_days for item in contract.future_horizon_rules)
    if not horizons or horizons != tuple(sorted(set(horizons))):
        raise ValueError("validation contract horizons must be sorted, unique and non-empty")
    if any(
        item.required_on_list_days < 1 or item.required_on_list_days > item.horizon_trade_days
        for item in contract.future_horizon_rules
    ):
        raise ValueError("validation contract future success rule is invalid")
    if contract.label_tail_trade_days != max(horizons):
        raise ValueError("validation contract label tail must match the largest horizon")
    if tuple(contract.hard_gates) != tuple(ValidationGateKey):
        raise ValueError("validation contract must register the six gates in canonical order")
