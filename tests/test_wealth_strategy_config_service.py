from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from src.biz.services.wealth.config import (
    MajorIndicesStrategyPayload,
    MarketNewsStrategyPayload,
    SectorOverviewHeatStrategyPayload,
    StrategyConfigNotFoundError,
    StrategyConfigRegistration,
    StrategyConfigRegistrationError,
    StrategyConfigService,
    StrategyConfigValidationError,
    get_default_strategy_config_registrations,
)
from src.biz.services.wealth.config.strategy_config_registry import build_strategy_config_registration_index


def _write_config(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _assert_semver(value: str) -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", value)


def test_default_strategy_configs_can_be_loaded() -> None:
    service = StrategyConfigService()

    major = service.get_config(module_key="majorIndices", market="CN_A")
    leaderboard = service.get_config(module_key="leaderboards", market="CN_A")
    summary = service.get_config(module_key="marketSummary", market="CN_A")
    news = service.get_config(module_key="marketNews", market="CN_A")
    sector_overview = service.get_config(module_key="sectorOverview", market="CN_A")

    _assert_semver(major.version)
    _assert_semver(leaderboard.version)
    _assert_semver(summary.version)
    _assert_semver(news.version)
    _assert_semver(sector_overview.version)

    assert isinstance(major.payload, MajorIndicesStrategyPayload)
    assert len(major.payload.index_codes) == 10
    assert len(set(major.payload.index_codes)) == 10
    assert isinstance(news.payload, MarketNewsStrategyPayload)
    assert news.payload.visible_item_count == 10
    assert news.payload.query_limit >= 300
    assert isinstance(sector_overview.payload, SectorOverviewHeatStrategyPayload)
    assert sector_overview.payload.score_version == "concept-heat-eod-v2"


def test_sector_heat_config_rejects_incoherent_windows() -> None:
    record = StrategyConfigService().get_config(module_key="sectorOverview", market="CN_A")
    payload = copy.deepcopy(record.payload.model_dump(mode="python", by_alias=True))
    payload["baselineTradingDays"] = 4
    payload["flowTradingDays"] = 5

    with pytest.raises(ValueError, match="baselineTradingDays"):
        SectorOverviewHeatStrategyPayload.model_validate(payload)


def test_get_version_reads_from_strategy_config() -> None:
    service = StrategyConfigService()
    version = service.get_version(module_key="majorIndices", market="CN_A")
    _assert_semver(version)


def test_unregistered_module_raises_not_found() -> None:
    service = StrategyConfigService()
    with pytest.raises(StrategyConfigNotFoundError):
        service.get_config(module_key="unknownModule", market="CN_A")


def test_missing_config_file_raises_not_found(tmp_path: Path) -> None:
    registrations = [
        StrategyConfigRegistration(
            module_key="majorIndices",
            market="CN_A",
            definition_file="missing.json",
            payload_model=MajorIndicesStrategyPayload,
        )
    ]
    service = StrategyConfigService(definitions_dir=tmp_path, registrations=registrations)
    with pytest.raises(StrategyConfigNotFoundError):
        service.get_config(module_key="majorIndices", market="CN_A")


def test_invalid_envelope_fails_strict_validation(tmp_path: Path) -> None:
    config_path = tmp_path / "major_indices.cn_a.v1.json"
    _write_config(
        config_path,
        {
            "moduleKey": "majorIndices",
            "market": "CN_A",
            "version": "1.0.0",
            "updatedAt": "2026-05-08T21:00:00+08:00",
            "payload": {"indexCodes": ["000001.SH"]},
        },
    )
    registrations = [
        StrategyConfigRegistration(
            module_key="majorIndices",
            market="CN_A",
            definition_file=config_path.name,
            payload_model=MajorIndicesStrategyPayload,
        )
    ]
    service = StrategyConfigService(definitions_dir=tmp_path, registrations=registrations)
    with pytest.raises(StrategyConfigValidationError, match="invalid strategy config envelope"):
        service.get_config(module_key="majorIndices", market="CN_A")


def test_invalid_payload_fails_strict_validation(tmp_path: Path) -> None:
    config_path = tmp_path / "major_indices.cn_a.v1.json"
    _write_config(
        config_path,
        {
            "moduleKey": "majorIndices",
            "market": "CN_A",
            "version": "1.0.0",
            "updatedAt": "2026-05-08T21:00:00+08:00",
            "updatedBy": "wealth-team",
            "payload": {"indexCodes": ["000001.SH"]},
        },
    )
    registrations = [
        StrategyConfigRegistration(
            module_key="majorIndices",
            market="CN_A",
            definition_file=config_path.name,
            payload_model=MajorIndicesStrategyPayload,
        )
    ]
    service = StrategyConfigService(definitions_dir=tmp_path, registrations=registrations)
    with pytest.raises(StrategyConfigValidationError, match="invalid strategy config payload"):
        service.get_config(module_key="majorIndices", market="CN_A")


def test_duplicate_registration_rejected() -> None:
    duplicate = [
        StrategyConfigRegistration(
            module_key="majorIndices",
            market="CN_A",
            definition_file="a.json",
            payload_model=MajorIndicesStrategyPayload,
        ),
        StrategyConfigRegistration(
            module_key="majorIndices",
            market="CN_A",
            definition_file="b.json",
            payload_model=MajorIndicesStrategyPayload,
        ),
    ]

    with pytest.raises(StrategyConfigRegistrationError, match="duplicate strategy config registration"):
        build_strategy_config_registration_index(duplicate)


def test_default_registration_index_has_no_duplicates() -> None:
    registrations = get_default_strategy_config_registrations()
    index = build_strategy_config_registration_index(registrations)
    assert len(index) == len(registrations)
