from __future__ import annotations

from dataclasses import dataclass

from src.biz.queries.wealth.market.sector_overview.sector_hierarchy_query import SectorHierarchyNode


@dataclass(frozen=True, slots=True)
class IndustrySelectionResult:
    level1_code: str | None
    level2_code: str | None
    level3_code: str | None
    detail_sector_code: str | None
    corrected: bool


@dataclass(frozen=True, slots=True)
class FlatSelectionResult:
    selected_code: str | None
    corrected: bool


class SectorSelectionResolver:
    """Resolve stable server-owned selection paths without database access."""

    @staticmethod
    def resolve_industry(
        *,
        nodes_by_code: dict[str, SectorHierarchyNode],
        ranked_by_parent: dict[str | None, list[SectorHierarchyNode]],
        requested_code: str | None,
    ) -> IndustrySelectionResult:
        requested = nodes_by_code.get(requested_code or "")
        corrected = requested_code is not None and requested is None

        roots = ranked_by_parent.get(None, [])
        requested_root = requested.root_sector_code if requested is not None else None
        level1 = SectorSelectionResolver._preserve_or_first(roots, requested_root)
        if requested_root is not None and (level1 is None or level1.sector_code != requested_root):
            corrected = True

        level2_rows = ranked_by_parent.get(level1.sector_code, []) if level1 is not None else []
        requested_level2 = SectorSelectionResolver._requested_level2(requested, nodes_by_code=nodes_by_code)
        level2 = SectorSelectionResolver._preserve_or_first(level2_rows, requested_level2)
        if requested_level2 is not None and (level2 is None or level2.sector_code != requested_level2):
            corrected = True

        level3_rows = ranked_by_parent.get(level2.sector_code, []) if level2 is not None else []
        requested_level3 = requested.sector_code if requested is not None and requested.industry_level == 3 else None
        level3 = SectorSelectionResolver._preserve_or_first(level3_rows, requested_level3)
        if requested_level3 is not None and (level3 is None or level3.sector_code != requested_level3):
            corrected = True

        detail = level3 or level2 or level1
        return IndustrySelectionResult(
            level1_code=level1.sector_code if level1 is not None else None,
            level2_code=level2.sector_code if level2 is not None else None,
            level3_code=level3.sector_code if level3 is not None else None,
            detail_sector_code=detail.sector_code if detail is not None else None,
            corrected=corrected,
        )

    @staticmethod
    def resolve_flat(*, candidate_codes: list[str], requested_code: str | None) -> FlatSelectionResult:
        if requested_code is not None and requested_code in candidate_codes:
            return FlatSelectionResult(selected_code=requested_code, corrected=False)
        return FlatSelectionResult(
            selected_code=candidate_codes[0] if candidate_codes else None,
            corrected=requested_code is not None,
        )

    @staticmethod
    def _preserve_or_first(
        rows: list[SectorHierarchyNode],
        requested_code: str | None,
    ) -> SectorHierarchyNode | None:
        if requested_code is not None:
            for row in rows:
                if row.sector_code == requested_code:
                    return row
        return rows[0] if rows else None

    @staticmethod
    def _requested_level2(
        requested: SectorHierarchyNode | None,
        *,
        nodes_by_code: dict[str, SectorHierarchyNode],
    ) -> str | None:
        if requested is None or requested.industry_level == 1:
            return None
        if requested.industry_level == 2:
            return requested.sector_code
        parent = nodes_by_code.get(requested.parent_sector_code or "")
        return parent.sector_code if parent is not None and parent.industry_level == 2 else None
