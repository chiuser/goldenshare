from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from .strategy_config_models import (
    StrategyConfigEnvelope,
    StrategyConfigNotFoundError,
    StrategyConfigValidationError,
)
from .strategy_config_registry import (
    StrategyConfigRegistration,
    build_strategy_config_registration_index,
    get_default_definitions_dir,
    get_default_strategy_config_registrations,
)


@dataclass(frozen=True, slots=True)
class StrategyConfigRecord:
    module_key: str
    market: str
    version: str
    updated_at_iso: str
    updated_by: str
    payload: BaseModel
    source_path: str


class StrategyConfigService:
    """Centralized strategy config reader for wealth modules."""

    def __init__(
        self,
        *,
        definitions_dir: Path | None = None,
        registrations: tuple[StrategyConfigRegistration, ...] | list[StrategyConfigRegistration] | None = None,
    ) -> None:
        self._definitions_dir = definitions_dir or get_default_definitions_dir()
        raw_registrations = registrations or get_default_strategy_config_registrations()
        self._registration_index = build_strategy_config_registration_index(raw_registrations)
        self._cache: dict[tuple[str, str], StrategyConfigRecord] = {}

    def get_config(self, *, module_key: str, market: str) -> StrategyConfigRecord:
        cache_key = (module_key.strip(), market.strip())
        if cache_key in self._cache:
            return self._cache[cache_key]

        registration = self._registration_index.get(cache_key)
        if registration is None:
            raise StrategyConfigNotFoundError(f"strategy config not registered: {cache_key[0]}/{cache_key[1]}")

        source_path = self._definitions_dir / registration.definition_file
        if not source_path.exists():
            raise StrategyConfigNotFoundError(f"strategy config file not found: {source_path}")

        raw_config = self._load_json(source_path)
        envelope = self._validate_envelope(raw_config=raw_config, source_path=source_path)

        if envelope.module_key != registration.module_key or envelope.market != registration.market:
            raise StrategyConfigValidationError(
                "strategy config envelope does not match registration: "
                f"file={source_path}, expected={registration.module_key}/{registration.market}, "
                f"actual={envelope.module_key}/{envelope.market}"
            )

        payload = self._validate_payload(
            payload_model=registration.payload_model,
            payload=envelope.payload,
            source_path=source_path,
        )

        record = StrategyConfigRecord(
            module_key=envelope.module_key,
            market=envelope.market,
            version=envelope.version,
            updated_at_iso=envelope.updated_at.isoformat(),
            updated_by=envelope.updated_by,
            payload=payload,
            source_path=str(source_path),
        )
        self._cache[cache_key] = record
        return record

    def get_payload(self, *, module_key: str, market: str) -> BaseModel:
        return self.get_config(module_key=module_key, market=market).payload

    def get_version(self, *, module_key: str, market: str) -> str:
        return self.get_config(module_key=module_key, market=market).version

    @staticmethod
    def _load_json(source_path: Path) -> dict[str, Any]:
        try:
            return json.loads(source_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StrategyConfigValidationError(f"invalid JSON in strategy config: {source_path}; error={exc}") from exc
        except OSError as exc:
            raise StrategyConfigValidationError(f"failed to read strategy config: {source_path}; error={exc}") from exc

    @staticmethod
    def _validate_envelope(*, raw_config: dict[str, Any], source_path: Path) -> StrategyConfigEnvelope:
        try:
            return StrategyConfigEnvelope.model_validate(raw_config)
        except ValidationError as exc:
            raise StrategyConfigValidationError(
                f"invalid strategy config envelope: {source_path}; details={exc.errors()}"
            ) from exc

    @staticmethod
    def _validate_payload(
        *,
        payload_model: type[BaseModel],
        payload: dict[str, Any],
        source_path: Path,
    ) -> BaseModel:
        try:
            return payload_model.model_validate(payload)
        except ValidationError as exc:
            raise StrategyConfigValidationError(
                f"invalid strategy config payload: {source_path}; details={exc.errors()}"
            ) from exc

