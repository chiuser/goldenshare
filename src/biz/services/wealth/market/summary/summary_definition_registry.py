from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.biz.services.wealth.config import (
    MarketSummaryStrategyPayload,
    StrategyConfigNotFoundError,
    StrategyConfigService,
    StrategyConfigValidationError,
)


class MarketSummaryDefinitionError(ValueError):
    """Raised when summary definition/config is invalid."""


@dataclass(frozen=True, slots=True)
class MarketSummaryTemplate:
    template_key: str
    session_statuses: tuple[str, ...]
    title_template: str
    content_template: str


@dataclass(frozen=True, slots=True)
class MarketSummaryTemplatePolicy:
    forbidden_words: tuple[str, ...]
    max_title_chars: int
    max_content_chars: int
    fallback_title: str
    fallback_content: str


@dataclass(frozen=True, slots=True)
class MarketSummaryDefinition:
    definition_key: str
    version: str
    card_count: int
    enabled_card_keys: tuple[str, ...]
    intraday_template_key: str
    close_template_key: str
    templates_by_key: dict[str, MarketSummaryTemplate]
    policy: MarketSummaryTemplatePolicy

    @property
    def layout_variant(self) -> Literal["FIVE_SINGLE_ROW", "SIX_TWO_ROWS"]:
        return "FIVE_SINGLE_ROW" if self.card_count == 5 else "SIX_TWO_ROWS"


class SummaryDefinitionRegistry:
    """Load market summary module definition from strategy config center."""

    def __init__(self, *, config_service: StrategyConfigService | None = None) -> None:
        self._config_service = config_service or StrategyConfigService()
        self._cache_by_market: dict[str, MarketSummaryDefinition] = {}

    def get_definition(self, *, market: str) -> MarketSummaryDefinition:
        cache_key = market.strip().upper()
        if cache_key in self._cache_by_market:
            return self._cache_by_market[cache_key]

        try:
            record = self._config_service.get_config(module_key="marketSummary", market=cache_key)
        except StrategyConfigNotFoundError as exc:
            raise MarketSummaryDefinitionError("MS_CONFIG_MISSING: summary strategy config not found") from exc
        except StrategyConfigValidationError as exc:
            raise MarketSummaryDefinitionError("MS_CONFIG_MISSING: summary strategy config invalid") from exc

        payload = record.payload
        if not isinstance(payload, MarketSummaryStrategyPayload):
            raise MarketSummaryDefinitionError("MS_CONFIG_MISSING: summary payload model mismatch")

        templates_by_key, policy = self._load_template_bundle()
        if payload.card_count not in (5, 6):
            raise MarketSummaryDefinitionError("MS_CARD_COUNT_INVALID: cardCount must be 5 or 6")

        definition = MarketSummaryDefinition(
            definition_key="CN_A_SUMMARY_V1",
            version=record.version,
            card_count=payload.card_count,
            enabled_card_keys=tuple(payload.enabled_card_keys),
            intraday_template_key=payload.intraday_template_key,
            close_template_key=payload.close_template_key,
            templates_by_key=templates_by_key,
            policy=policy,
        )
        self._cache_by_market[cache_key] = definition
        return definition

    @staticmethod
    def _load_template_bundle() -> tuple[dict[str, MarketSummaryTemplate], MarketSummaryTemplatePolicy]:
        template_path = Path(__file__).resolve().parent / "config" / "market_summary_text_templates.json"
        try:
            payload = json.loads(template_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MarketSummaryDefinitionError("MS_CONFIG_MISSING: summary text template file invalid") from exc

        templates_by_key: dict[str, MarketSummaryTemplate] = {}
        for template in payload.get("templates", []):
            item = MarketSummaryTemplate(
                template_key=str(template["templateKey"]).strip(),
                session_statuses=tuple(str(v).strip() for v in template["sessionStatuses"]),
                title_template=str(template["titleTemplate"]).strip(),
                content_template=str(template["contentTemplate"]).strip(),
            )
            templates_by_key[item.template_key] = item

        fallback = payload.get("fallback", {})
        policy = payload.get("policy", {})
        template_policy = MarketSummaryTemplatePolicy(
            forbidden_words=tuple(str(v) for v in policy.get("forbiddenWords", [])),
            max_title_chars=int(policy.get("maxTitleChars", 36)),
            max_content_chars=int(policy.get("maxContentChars", 220)),
            fallback_title=str(fallback.get("title", "今日市场客观总结")),
            fallback_content=str(fallback.get("content", "当前可用数据不足，暂仅展示已确认的客观事实。")),
        )
        return templates_by_key, template_policy
