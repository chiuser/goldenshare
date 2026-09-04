from __future__ import annotations

from decimal import Decimal

from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    BuiltMethodFacts,
    FORMULA_BUNDLE_VERSION,
    DailyInsightItemRow,
    DailyInsightSummaryRow,
    PreviousPublishedEvidence,
    SectorAnalysisSourceBundle,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.template_renderer import (
    SectorDailyInsightTemplateRenderer,
)


class SectorDailyInsightBuilder:
    CHANGE_THRESHOLD_PP = Decimal("10")
    HOT_ENTRY_PERCENTILE = Decimal("80")
    COLD_ENTRY_PERCENTILE = Decimal("20")
    def __init__(self, *, renderer: SectorDailyInsightTemplateRenderer | None = None) -> None:
        self._renderer = renderer or SectorDailyInsightTemplateRenderer()

    def build(
        self,
        *,
        bundle: SectorAnalysisSourceBundle,
        facts: BuiltMethodFacts,
        previous: PreviousPublishedEvidence | None,
    ) -> tuple[tuple[DailyInsightSummaryRow, ...], tuple[DailyInsightItemRow, ...]]:
        momentum = {
            (row.identity.sector_code, row.period): row
            for row in facts.momentum
            if row.identity.comparison_scope == f"LEVEL_{row.identity.industry_level}"
        }
        dual = {
            row.identity.sector_code: row
            for row in facts.dual_momentum
            if row.identity.comparison_scope == f"LEVEL_{row.identity.industry_level}" and row.period == 20
        }
        rotation = {
            row.identity.sector_code: row
            for row in facts.relative_rotation
            if row.identity.comparison_scope == f"LEVEL_{row.identity.industry_level}" and row.period == 20
        }
        breadth = {
            row.identity.sector_code: row
            for row in facts.member_breadth
            if row.identity.comparison_scope == f"LEVEL_{row.identity.industry_level}"
        }
        ma20 = {
            row.identity.sector_code: row
            for row in facts.member_ma_breadth
            if row.identity.comparison_scope == f"LEVEL_{row.identity.industry_level}" and row.ma_period == 20
        }
        price_volume = {
            row.identity.sector_code: row
            for row in facts.price_volume
            if row.identity.comparison_scope == f"LEVEL_{row.identity.industry_level}" and row.period == 20
        }

        summaries: list[DailyInsightSummaryRow] = []
        items: list[DailyInsightItemRow] = []
        previous_compatible = (
            previous is not None
            and previous.trade_date == bundle.previous_trade_date
            and previous.hierarchy_version == bundle.hierarchy.baseline_version
            and previous.formula_bundle_version == FORMULA_BUNDLE_VERSION
        )
        for level in (1, 2, 3):
            nodes = tuple(node for node in bundle.hierarchy.nodes if node.industry_level == level)
            one_day = tuple(momentum[(node.sector_code, 1)] for node in nodes)
            valid_one_day = tuple(row for row in one_day if row.return_pct is not None)
            missing_counts = self._missing_counts(one_day, dual, breadth, ma20, price_volume)
            summaries.append(
                DailyInsightSummaryRow(
                    trade_date=bundle.trade_date,
                    industry_level=level,
                    values={
                        "sector_count": len(nodes),
                        "calculable_count": len(valid_one_day),
                        "missing_count": len(nodes) - len(valid_one_day),
                        "up_count": sum(row.return_pct > 0 for row in valid_one_day),
                        "down_count": sum(row.return_pct < 0 for row in valid_one_day),
                        "flat_count": sum(row.return_pct == 0 for row in valid_one_day),
                        "median_change_pct_1d": self._median(tuple(row.return_pct for row in valid_one_day if row.return_pct is not None)),
                        "dual_momentum_count_20d_80": sum(dual[node.sector_code].qualification_status_80 == "QUALIFIED" for node in nodes),
                        "leading_improving_count_20d_5d": sum(rotation[node.sector_code].rotation_status == "LEADING_IMPROVING" for node in nodes),
                        "price_volume_joint_count_20d": sum(price_volume[node.sector_code].values["distribution_state"] == "JOINT" for node in nodes),
                        "breadth_up_share_above_50_count": sum(
                            breadth[node.sector_code].values["member_qualification"] == "ELIGIBLE"
                            and isinstance(breadth[node.sector_code].values["member_up_pct"], Decimal)
                            and breadth[node.sector_code].values["member_up_pct"].is_finite()
                            and breadth[node.sector_code].values["member_up_pct"] > Decimal("50")
                            for node in nodes
                        ),
                        **missing_counts,
                        "missing_previous_batch_count": 0 if previous_compatible else len(nodes),
                    },
                )
            )
            items.extend(
                self._level_items(
                    level=level,
                    nodes=nodes,
                    momentum=momentum,
                    dual=dual,
                    rotation=rotation,
                    breadth=breadth,
                    ma20=ma20,
                    price_volume=price_volume,
                    previous=previous if previous_compatible else None,
                )
            )
        return tuple(summaries), tuple(items)

    def _level_items(self, *, level, nodes, momentum, dual, rotation, breadth, ma20, price_volume, previous):  # type: ignore[no-untyped-def]
        rows: list[DailyInsightItemRow] = []
        node_by_code = {node.sector_code: node for node in nodes}
        one_day = [momentum[(node.sector_code, 1)] for node in nodes]
        categories = {
            "HEAD_GAINER": sorted((row for row in one_day if row.return_pct is not None and row.return_pct > 0), key=lambda row: (-row.return_pct, row.identity.sector_code)),
            "HEAD_LOSER": sorted((row for row in one_day if row.return_pct is not None and row.return_pct < 0), key=lambda row: (row.return_pct, row.identity.sector_code)),
        }
        if previous is not None:
            strengthening = []
            weakening = []
            for node in nodes:
                current = momentum[(node.sector_code, 20)]
                old = previous.by_sector.get(node.sector_code)
                if current.percentile is None or old is None or old.percentile_20d is None:
                    continue
                delta = current.percentile - old.percentile_20d
                if delta >= self.CHANGE_THRESHOLD_PP or (old.percentile_20d < self.HOT_ENTRY_PERCENTILE <= current.percentile):
                    strengthening.append(current)
                if delta <= -self.CHANGE_THRESHOLD_PP or (old.percentile_20d > self.COLD_ENTRY_PERCENTILE >= current.percentile):
                    weakening.append(current)
            categories["STRENGTHENING"] = sorted(strengthening, key=lambda row: (-(row.percentile - previous.by_sector[row.identity.sector_code].percentile_20d), row.identity.sector_code))
            categories["WEAKENING"] = sorted(weakening, key=lambda row: (-abs(row.percentile - previous.by_sector[row.identity.sector_code].percentile_20d), row.identity.sector_code))
        else:
            categories["STRENGTHENING"] = []
            categories["WEAKENING"] = []

        for category in ("HEAD_GAINER", "HEAD_LOSER", "STRENGTHENING", "WEAKENING"):
            for order, row in enumerate(categories[category], start=1):
                code = row.identity.sector_code
                node = node_by_code[code]
                old = previous.by_sector.get(code) if previous else None
                current20 = momentum[(code, 20)]
                values = {
                    "stable_order": order,
                    "event_type": self._event_type(category, momentum[(code, 1)].return_pct),
                    "sector_name": node.sector_name,
                    "hierarchy_path": node.hierarchy_path,
                    "return_pct_1d": momentum[(code, 1)].return_pct,
                    "return_pct_5d": momentum[(code, 5)].return_pct,
                    "return_pct_20d": current20.return_pct,
                    "current_rank_20d": current20.strength_rank,
                    "current_rankable_count_20d": current20.rankable_count,
                    "current_percentile_20d": current20.percentile,
                    "previous_rank_20d": old.rank_20d if old else None,
                    "previous_rankable_count_20d": old.rankable_count_20d if old else None,
                    "previous_percentile_20d": old.percentile_20d if old else None,
                    "rank_change": (old.rank_20d - current20.strength_rank) if old and old.rank_20d is not None and current20.strength_rank is not None else None,
                    "percentile_change_pp": (current20.percentile - old.percentile_20d) if old and old.percentile_20d is not None and current20.percentile is not None else None,
                    "price_volume_state_current": price_volume[code].values["distribution_state"],
                    "price_volume_state_previous": old.price_volume_state if old else None,
                    "dual_qualification_20d_80_current": dual[code].qualification_status_80,
                    "dual_qualification_20d_80_previous": old.dual_qualification_20d_80 if old else None,
                    "rotation_status_20d_current": rotation[code].rotation_status,
                    "rotation_status_20d_previous": old.rotation_status_20d if old else None,
                    "member_up_pct_current": breadth[code].values["member_up_pct"],
                    "member_up_pct_previous": old.member_up_pct if old else None,
                    "turnover_up_pct_current": breadth[code].values["turnover_up_pct"],
                    "turnover_up_pct_previous": old.turnover_up_pct if old else None,
                    "ma20_above_pct_current": ma20[code].values["above_pct"],
                    "ma20_above_pct_previous": old.ma20_above_pct if old else None,
                }
                evidence = self._renderer.select_evidence(
                    values=values,
                    qualifications={
                        "MEMBER_BREADTH": breadth[code].values["member_qualification"],
                        "TURNOVER_BREADTH": breadth[code].values["turnover_qualification"],
                        "MA20_BREADTH": ma20[code].values["qualification"],
                    },
                )
                previous_evidence = self._renderer.select_evidence(
                    values=values,
                    qualifications={
                        "MEMBER_BREADTH": old.member_qualification if old else None,
                        "TURNOVER_BREADTH": old.turnover_qualification if old else None,
                        "MA20_BREADTH": old.ma20_qualification if old else None,
                    },
                    suffix="previous",
                )
                evidence = evidence[:2]
                template_key, template_version, rendered = self._renderer.render(
                    category=category,
                    sector_name=node.sector_name,
                    industry_level=level,
                    values=values,
                    evidence_types=evidence,
                    previous_evidence_types=previous_evidence,
                )
                values.update(
                    {
                        "primary_evidence_type": evidence[0] if evidence else None,
                        "secondary_evidence_type_1": evidence[1] if len(evidence) > 1 else None,
                        "secondary_evidence_type_2": None,
                        "template_key": template_key,
                        "template_version": template_version,
                        "rendered_text": rendered,
                    }
                )
                rows.append(DailyInsightItemRow(row.identity.trade_date, level, category, code, values))
        return rows

    @staticmethod
    def _event_type(category: str, return_pct: Decimal | None) -> str:
        if category == "STRENGTHENING" and return_pct is not None and return_pct < 0:
            return "COUNTER_TREND_STRENGTHENING"
        if category == "WEAKENING" and return_pct is not None and return_pct > 0:
            return "RISING_BUT_WEAKENING"
        return category

    @staticmethod
    def _median(values: tuple[Decimal, ...]) -> Decimal | None:
        if not values:
            return None
        rows = sorted(values)
        middle = len(rows) // 2
        return rows[middle] if len(rows) % 2 else (rows[middle - 1] + rows[middle]) / Decimal(2)

    @staticmethod
    def _missing_counts(one_day, dual, breadth, ma20, price_volume) -> dict[str, int]:  # type: ignore[no-untyped-def]
        codes = tuple(row.identity.sector_code for row in one_day)
        reasons = [row.missing_reason for row in one_day if row.missing_reason != "NONE"]
        return {
            "missing_history_count": sum(reason == "HISTORY_INSUFFICIENT" for reason in reasons),
            "missing_date_count": sum(reason == "DATE_MISSING" for reason in reasons),
            "missing_price_count": sum(reason in {"CLOSE_MISSING", "CLOSE_NON_POSITIVE", "PCT_CHANGE_MISSING"} for reason in reasons),
            "missing_member_count": sum("SOURCE_MEMBER_EMPTY" in breadth[code].values["member_reason_codes"] for code in codes),
            "missing_amount_count": sum(bool(set(breadth[code].values["turnover_reason_codes"]) & {"AMOUNT_MISSING", "AMOUNT_NON_POSITIVE"}) for code in codes),
            "missing_adj_factor_count": sum(bool(set(ma20[code].values["reason_codes"]) & {"ADJ_FACTOR_MISSING", "ADJ_FACTOR_NON_POSITIVE"}) for code in codes),
            "missing_group_size_count": sum(
                dual[code].relative_status_80 == "SAMPLE_INSUFFICIENT" for code in codes
            ),
            "missing_coverage_count": sum(not (breadth[code].values["member_qualification"] == "ELIGIBLE") for code in codes),
            "missing_other_count": sum(price_volume[code].calculation_status == "UNAVAILABLE" for code in codes),
        }
