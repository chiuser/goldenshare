from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.core_serving.wealth_sector_hierarchy import WealthSectorHierarchy


class SectorHierarchyUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SectorHierarchyNode:
    sector_code: str
    sector_name: str
    industry_level: int
    parent_sector_code: str | None
    root_sector_code: str
    hierarchy_path: str
    display_order: int
    baseline_version: str


@dataclass(frozen=True, slots=True)
class SectorHierarchySnapshot:
    baseline_version: str
    nodes: tuple[SectorHierarchyNode, ...]
    nodes_by_code: dict[str, SectorHierarchyNode]
    children_by_parent: dict[str | None, tuple[SectorHierarchyNode, ...]]


class SectorHierarchyQuery:
    """Load and validate the currently published industry hierarchy."""

    def load(self, session: Session) -> SectorHierarchySnapshot:
        rows = session.execute(
            select(
                WealthSectorHierarchy.sector_code,
                WealthSectorHierarchy.sector_name,
                WealthSectorHierarchy.industry_level,
                WealthSectorHierarchy.parent_sector_code,
                WealthSectorHierarchy.root_sector_code,
                WealthSectorHierarchy.hierarchy_path,
                WealthSectorHierarchy.display_order,
                WealthSectorHierarchy.baseline_version,
            ).order_by(
                WealthSectorHierarchy.industry_level,
                WealthSectorHierarchy.display_order,
                WealthSectorHierarchy.sector_code,
            )
        ).all()
        if not rows:
            raise SectorHierarchyUnavailableError("industry hierarchy serving is empty")

        versions = {str(row.baseline_version) for row in rows}
        if len(versions) != 1:
            raise SectorHierarchyUnavailableError("industry hierarchy contains multiple baseline versions")

        nodes = tuple(
            SectorHierarchyNode(
                sector_code=row.sector_code,
                sector_name=row.sector_name,
                industry_level=int(row.industry_level),
                parent_sector_code=row.parent_sector_code,
                root_sector_code=row.root_sector_code,
                hierarchy_path=row.hierarchy_path,
                display_order=int(row.display_order),
                baseline_version=row.baseline_version,
            )
            for row in rows
        )
        nodes_by_code = {node.sector_code: node for node in nodes}
        if len(nodes_by_code) != len(nodes):
            raise SectorHierarchyUnavailableError("industry hierarchy contains duplicate sector codes")

        children: dict[str | None, list[SectorHierarchyNode]] = {}
        for node in nodes:
            children.setdefault(node.parent_sector_code, []).append(node)
            self._validate_node(node, nodes_by_code=nodes_by_code)
        roots = children.get(None, [])
        if not roots or any(node.industry_level != 1 for node in roots):
            raise SectorHierarchyUnavailableError("industry hierarchy has no valid level-1 roots")

        return SectorHierarchySnapshot(
            baseline_version=versions.pop(),
            nodes=nodes,
            nodes_by_code=nodes_by_code,
            children_by_parent={key: tuple(value) for key, value in children.items()},
        )

    @staticmethod
    def _validate_node(
        node: SectorHierarchyNode,
        *,
        nodes_by_code: dict[str, SectorHierarchyNode],
    ) -> None:
        if node.industry_level == 1:
            if node.parent_sector_code is not None or node.root_sector_code != node.sector_code:
                raise SectorHierarchyUnavailableError(f"invalid root node: {node.sector_code}")
            return
        parent = nodes_by_code.get(node.parent_sector_code or "")
        root = nodes_by_code.get(node.root_sector_code)
        if parent is None or parent.industry_level != node.industry_level - 1:
            raise SectorHierarchyUnavailableError(f"invalid parent closure: {node.sector_code}")
        if root is None or root.industry_level != 1 or parent.root_sector_code != node.root_sector_code:
            raise SectorHierarchyUnavailableError(f"invalid root closure: {node.sector_code}")
