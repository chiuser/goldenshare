"""Explicit request bindings, independently maintained from source field contracts."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from .download_errors import require


@dataclass(frozen=True, slots=True)
class TransportBinding:
    dataset_id: str
    source_api_name: str
    kind: int = 1
    adapter_key: str = "http_pro"
    version: str = "1"
    allowed_sdk_versions: tuple[str, ...] = ()
    http_path_rule: str | None = "base"


class DatasetTransportMapping:
    def __init__(self, bindings: tuple[TransportBinding, ...] = ()):
        require(len({b.dataset_id for b in bindings}) == len(bindings))
        for b in bindings:
            require(type(b.kind) is int and b.kind in (1, 2))
            require(b.version == "1" and bool(b.dataset_id) and bool(b.source_api_name))
            require(
                (
                    b.kind == 1
                    and b.adapter_key == "http_pro"
                    and b.http_path_rule in ("base", "api_name")
                )
                or (
                    b.kind == 2
                    and b.http_path_rule is None
                    and bool(b.allowed_sdk_versions)
                )
            )
        self._bindings = MappingProxyType({b.dataset_id: b for b in bindings})

    def resolve(self, contract) -> TransportBinding:
        result = self._bindings.get(contract.dataset_id)
        require(
            result is not None and result.source_api_name == contract.source_api_name
        )
        return result


# Dataset onboarding owns source evidence; this binding never selects an SDK fallback.
BINDINGS = (
    TransportBinding(
        dataset_id="stk_factor_pro",
        source_api_name="stk_factor_pro",
        http_path_rule="base",
    ),
)
