import csv
import tempfile
import unittest
from pathlib import Path

from orchestrator.seeds.board import eastmoney_dc_industry_hierarchy as seed_module


def _current_seed_rows() -> list[dict[str, str]]:
    catalog = seed_module.load_eastmoney_dc_industry_hierarchy_seed()
    return [
        {
            "node_path": row.node_path,
            "parent_path": row.parent_path or "",
            "industry_level": str(row.industry_level),
            "name": row.name,
            "display_order": str(row.display_order),
        }
        for row in catalog.rows
    ]


def _write_seed_file(
    path: Path,
    rows: list[dict[str, str]],
    *,
    fieldnames: tuple[str, ...] | None = None,
) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames or seed_module.EASTMONEY_DC_INDUSTRY_HIERARCHY_SEED_COLUMNS,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


class EastmoneyDcIndustryHierarchySeedTests(unittest.TestCase):
    def tearDown(self) -> None:
        seed_module.load_eastmoney_dc_industry_hierarchy_seed.cache_clear()

    def test_default_seed_is_the_approved_v1_baseline(self) -> None:
        catalog = seed_module.load_eastmoney_dc_industry_hierarchy_seed()

        self.assertEqual(
            catalog.version,
            seed_module.EASTMONEY_DC_INDUSTRY_HIERARCHY_SEED_VERSION,
        )
        self.assertEqual(catalog.seed_sha256, seed_module.EASTMONEY_DC_INDUSTRY_HIERARCHY_SEED_SHA256)
        self.assertEqual(
            catalog.source_image_sha256,
            seed_module.EASTMONEY_DC_INDUSTRY_HIERARCHY_SOURCE_IMAGE_SHA256,
        )
        self.assertEqual(len(catalog.rows), 496)
        self.assertEqual(
            {level: sum(row.industry_level == level for row in catalog.rows) for level in (1, 2, 3)},
            {1: 31, 2: 128, 3: 337},
        )
        self.assertEqual(
            [row.display_order for row in catalog.rows],
            list(range(1, 497)),
        )

    def test_known_paths_and_user_exclusions_are_frozen(self) -> None:
        catalog = seed_module.load_eastmoney_dc_industry_hierarchy_seed()
        paths = {row.node_path for row in catalog.rows}
        names = {row.name for row in catalog.rows}

        self.assertIn("农林牧渔/种植业/种子", paths)
        self.assertIn("电力设备/其他电源设备Ⅱ/其他电源设备Ⅲ", paths)
        self.assertIn("非银金融/证券Ⅱ/证券Ⅲ", paths)
        self.assertNotIn("储能", names)
        self.assertNotIn("其他多元金融", names)

    def test_loader_rejects_bad_header(self) -> None:
        self._assert_seed_rejected(
            _current_seed_rows(),
            fieldnames=("node_path", "parent_path", "industry_level"),
            expected_message="columns must be exactly",
        )

    def test_loader_rejects_duplicate_path(self) -> None:
        rows = _current_seed_rows()
        rows[1]["node_path"] = rows[0]["node_path"]
        self._assert_seed_rejected(rows, expected_message="duplicate node_path")

    def test_loader_rejects_display_order_drift(self) -> None:
        rows = _current_seed_rows()
        rows[1]["display_order"] = "3"
        self._assert_seed_rejected(rows, expected_message="display_order must be continuous")

    def test_loader_rejects_invalid_parent_path(self) -> None:
        rows = _current_seed_rows()
        rows[1]["parent_path"] = "不存在的行业"
        self._assert_seed_rejected(rows, expected_message="parent_path does not match")

    def test_loader_rejects_path_level_mismatch(self) -> None:
        rows = _current_seed_rows()
        rows[1]["node_path"] = "农林牧渔/种植业/not_a_real_leaf"
        self._assert_seed_rejected(rows, expected_message="node_path level mismatch")

    def test_loader_rejects_orphan_node(self) -> None:
        rows = _current_seed_rows()
        rows[1]["node_path"] = "不存在的一级行业/种植业"
        rows[1]["parent_path"] = "不存在的一级行业"
        self._assert_seed_rejected(rows, expected_message="parent does not exist")

    def test_loader_rejects_name_with_path_delimiter(self) -> None:
        rows = _current_seed_rows()
        rows[1]["name"] = "种/植业"
        self._assert_seed_rejected(rows, expected_message="name must not contain")

    def test_loader_rejects_wrong_node_count(self) -> None:
        rows = _current_seed_rows()
        rows.pop()
        self._assert_seed_rejected(rows, expected_message="must contain exactly 496 rows")

    def _assert_seed_rejected(
        self,
        rows: list[dict[str, str]],
        *,
        expected_message: str,
        fieldnames: tuple[str, ...] | None = None,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "eastmoney_dc_industry_hierarchy.cn_a.v1.csv"
            _write_seed_file(path, rows, fieldnames=fieldnames)
            with self.assertRaisesRegex(ValueError, expected_message):
                seed_module.load_eastmoney_dc_industry_hierarchy_seed(path)


if __name__ == "__main__":
    unittest.main()
