from __future__ import annotations

from dataclasses import dataclass

from .summary_card_builder import SummaryTemplateVariables
from .summary_definition_registry import MarketSummaryDefinition, MarketSummaryTemplate


@dataclass(frozen=True, slots=True)
class SummaryTextRenderResult:
    title: str
    content: str
    template_key: str
    used_fallback: bool = False
    failure_reason: str | None = None


class SummaryTextRenderer:
    """Render summary text card from fixed templates and computed variables."""

    def render(
        self,
        *,
        definition: MarketSummaryDefinition,
        session_status: str,
        variables: SummaryTemplateVariables,
    ) -> SummaryTextRenderResult:
        selected = self._select_template(definition=definition, session_status=session_status)
        if selected is None:
            return self._fallback(definition=definition, failure_reason="template_not_found")

        replacements = {
            "majorIndexTone": variables.major_index_tone,
            "upDownTone": variables.up_down_tone,
            "turnoverTone": variables.turnover_tone,
            "limitUpDownTone": variables.limit_up_down_tone,
            "fundFlowTone": variables.fund_flow_tone,
            "flowPatternTone": variables.flow_pattern_tone,
        }
        try:
            title = selected.title_template.format(**replacements)
            content = selected.content_template.format(**replacements)
        except KeyError as exc:
            return self._fallback(definition=definition, failure_reason=f"missing_variable:{exc}")

        policy = definition.policy
        if any(word and (word in title or word in content) for word in policy.forbidden_words):
            return self._fallback(definition=definition, failure_reason="forbidden_word")

        if len(title) > policy.max_title_chars:
            title = title[: policy.max_title_chars]
        if len(content) > policy.max_content_chars:
            content = content[: policy.max_content_chars]

        return SummaryTextRenderResult(
            title=title,
            content=content,
            template_key=selected.template_key,
            used_fallback=False,
        )

    def _select_template(self, *, definition: MarketSummaryDefinition, session_status: str) -> MarketSummaryTemplate | None:
        preferred_key = definition.close_template_key if session_status == "CLOSED" else definition.intraday_template_key
        preferred = definition.templates_by_key.get(preferred_key)
        if preferred is not None:
            return preferred
        for template in definition.templates_by_key.values():
            if session_status in template.session_statuses:
                return template
        return None

    @staticmethod
    def _fallback(*, definition: MarketSummaryDefinition, failure_reason: str) -> SummaryTextRenderResult:
        return SummaryTextRenderResult(
            title=definition.policy.fallback_title,
            content=definition.policy.fallback_content,
            template_key="fallback",
            used_fallback=True,
            failure_reason=failure_reason,
        )

