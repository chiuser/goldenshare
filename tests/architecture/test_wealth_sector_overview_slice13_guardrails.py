from __future__ import annotations

from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]
SECTOR_ROOT = REPO_ROOT / "wealth/src/features/market-overview/sectors"
SECTOR_API = SECTOR_ROOT / "api/marketSectorOverviewApi.ts"
SECTOR_CSS = REPO_ROOT / "wealth/src/pages/market-overview/market-overview-page.css"
LLD = REPO_ROOT / "wealth/docs/pages/market-overview/sector-overview-low-level-design-v2.md"


def _sector_source() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(SECTOR_ROOT.rglob("*.ts*")))


def test_s13_a01_n01_generic_rank_item_contract_cannot_return() -> None:
    api_source = SECTOR_API.read_text(encoding="utf-8")

    assert not re.search(r"export interface SectorRankItem\b", api_source)
    assert "export interface IndustryRankItem" in api_source
    assert "export interface ConceptRankItem" in api_source
    assert "export interface RegionRankItem" in api_source


def test_s13_a10_p02_fixed_seven_row_scroll_contract_remains_explicit() -> None:
    css_source = SECTOR_CSS.read_text(encoding="utf-8")

    assert ".sector-overview-v2" in css_source
    assert "height: 680px;" in css_source
    viewport_rule = re.search(r"\.sector-flat-rank-viewport\s*\{(?P<body>.*?)\}", css_source, re.DOTALL)
    assert viewport_rule is not None
    assert "overflow-y: auto;" in viewport_rule.group("body")


def test_s13_a16_n01_sector_detail_routes_and_entry_copy_cannot_return() -> None:
    sector_source = _sector_source()

    for forbidden in (
        "进入板块行情",
        "进入概念行情",
        "进入地域行情",
        "buildSectorDetailPath",
        "navigateSectorDetail",
    ):
        assert forbidden not in sector_source


def test_s13_a17_n01_real_sector_feature_cannot_import_or_fallback_to_mock() -> None:
    sector_source = _sector_source()

    assert "marketOverviewMockAdapter" not in sector_source
    assert "mockSector" not in sector_source
    assert '=== "mock"' not in sector_source


def test_s13_a18_a19_n01_automation_cannot_claim_pixel_or_release_acceptance() -> None:
    lld_source = LLD.read_text(encoding="utf-8")

    assert "### Slice 14：Heat 盘后自动化" in lld_source
    assert "### Slice 15：Figma 与首页像素验收" in lld_source
    assert "### Slice 16：候选版本部署、性能与观测验收" in lld_source
    assert "A18" in lld_source
    assert "OPEN" in lld_source
    assert "Slice 14 结论为 PASS" in lld_source
    assert "Slice 14 已闭环" in lld_source
    assert "Slice 15 正式像素尚未验收" in lld_source
    assert "不得进入 Slice 15" in lld_source
