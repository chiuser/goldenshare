"""Version-controlled Eastmoney industry hierarchy baseline."""

import csv
import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path


EASTMONEY_DC_INDUSTRY_HIERARCHY_SEED_VERSION = "eastmoney_dc_industry_hierarchy.cn_a.v1"
EASTMONEY_DC_INDUSTRY_HIERARCHY_SOURCE_RECEIVED_DATE = date(2026, 8, 2)
EASTMONEY_DC_INDUSTRY_HIERARCHY_SEED_PATH = Path(__file__).with_name(
    "eastmoney_dc_industry_hierarchy.cn_a.v1.csv"
)
EASTMONEY_DC_INDUSTRY_HIERARCHY_SOURCE_IMAGE_PATH = Path(__file__).with_name(
    "eastmoney_dc_industry_hierarchy.cn_a.v1.source.png"
)
EASTMONEY_DC_INDUSTRY_HIERARCHY_SEED_SHA256 = (
    "36f603dc6a9e50e1194a24fb53b6e47c0cdf99ef0df241c4d5cf38446480210c"
)
EASTMONEY_DC_INDUSTRY_HIERARCHY_SOURCE_IMAGE_SHA256 = (
    "7b499617be0ddfa129bade02dc54922d4bb158a931423b6b85855382d7946299"
)
EASTMONEY_DC_INDUSTRY_HIERARCHY_SEED_COLUMNS = (
    "node_path",
    "parent_path",
    "industry_level",
    "name",
    "display_order",
)
EASTMONEY_DC_INDUSTRY_HIERARCHY_LEVEL_COUNTS = {1: 31, 2: 128, 3: 337}


@dataclass(frozen=True)
class EastmoneyDcIndustryHierarchySeedRow:
    node_path: str
    parent_path: str | None
    industry_level: int
    name: str
    display_order: int


@dataclass(frozen=True)
class EastmoneyDcIndustryHierarchySeed:
    version: str
    source_received_date: date
    seed_sha256: str
    source_image_sha256: str
    rows: tuple[EastmoneyDcIndustryHierarchySeedRow, ...]


@cache
def load_eastmoney_dc_industry_hierarchy_seed(
    path: Path = EASTMONEY_DC_INDUSTRY_HIERARCHY_SEED_PATH,
) -> EastmoneyDcIndustryHierarchySeed:
    """Load and validate the immutable Eastmoney industry hierarchy baseline."""

    if not path.is_file():
        raise FileNotFoundError(f"Missing Eastmoney industry hierarchy seed: {path}")

    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if tuple(reader.fieldnames or ()) != EASTMONEY_DC_INDUSTRY_HIERARCHY_SEED_COLUMNS:
            raise ValueError(
                "Eastmoney industry hierarchy seed columns must be exactly "
                f"{EASTMONEY_DC_INDUSTRY_HIERARCHY_SEED_COLUMNS}."
            )
        rows = tuple(
            _coerce_seed_row(raw_row, row_number=index + 2)
            for index, raw_row in enumerate(reader)
        )

    _validate_seed_rows(rows)
    seed_sha256 = _sha256(path)
    source_image_sha256 = EASTMONEY_DC_INDUSTRY_HIERARCHY_SOURCE_IMAGE_SHA256
    if path == EASTMONEY_DC_INDUSTRY_HIERARCHY_SEED_PATH:
        _validate_default_seed_evidence(seed_sha256)

    return EastmoneyDcIndustryHierarchySeed(
        version=EASTMONEY_DC_INDUSTRY_HIERARCHY_SEED_VERSION,
        source_received_date=EASTMONEY_DC_INDUSTRY_HIERARCHY_SOURCE_RECEIVED_DATE,
        seed_sha256=seed_sha256,
        source_image_sha256=source_image_sha256,
        rows=rows,
    )


def _coerce_seed_row(
    raw_row: dict[str, str],
    *,
    row_number: int,
) -> EastmoneyDcIndustryHierarchySeedRow:
    values = {
        column: (raw_row.get(column) or "").strip()
        for column in EASTMONEY_DC_INDUSTRY_HIERARCHY_SEED_COLUMNS
    }
    required_columns = ("node_path", "industry_level", "name", "display_order")
    missing_columns = [column for column in required_columns if not values[column]]
    if missing_columns:
        raise ValueError(
            "Eastmoney industry hierarchy seed row "
            f"{row_number} has blank required fields: {missing_columns}."
        )
    if "/" in values["name"]:
        raise ValueError(
            f"Eastmoney industry hierarchy seed row {row_number} name must not contain '/'."
        )
    try:
        industry_level = int(values["industry_level"])
    except ValueError as exc:
        raise ValueError(
            "Eastmoney industry hierarchy seed row "
            f"{row_number} has non-integer industry_level: {values['industry_level']}."
        ) from exc
    try:
        display_order = int(values["display_order"])
    except ValueError as exc:
        raise ValueError(
            "Eastmoney industry hierarchy seed row "
            f"{row_number} has non-integer display_order: {values['display_order']}."
        ) from exc
    return EastmoneyDcIndustryHierarchySeedRow(
        node_path=values["node_path"],
        parent_path=values["parent_path"] or None,
        industry_level=industry_level,
        name=values["name"],
        display_order=display_order,
    )


def _validate_seed_rows(rows: tuple[EastmoneyDcIndustryHierarchySeedRow, ...]) -> None:
    expected_total = sum(EASTMONEY_DC_INDUSTRY_HIERARCHY_LEVEL_COUNTS.values())
    if len(rows) != expected_total:
        raise ValueError(
            "Eastmoney industry hierarchy seed must contain exactly "
            f"{expected_total} rows."
        )

    level_counts = Counter(row.industry_level for row in rows)
    if dict(level_counts) != EASTMONEY_DC_INDUSTRY_HIERARCHY_LEVEL_COUNTS:
        raise ValueError(
            "Eastmoney industry hierarchy seed level counts must be "
            f"{EASTMONEY_DC_INDUSTRY_HIERARCHY_LEVEL_COUNTS}: {dict(level_counts)}."
        )

    display_orders = [row.display_order for row in rows]
    expected_orders = list(range(1, expected_total + 1))
    if display_orders != expected_orders:
        raise ValueError(
            "Eastmoney industry hierarchy seed display_order must be continuous and ordered "
            f"from 1 to {expected_total}."
        )

    paths = [row.node_path for row in rows]
    duplicate_paths = _duplicates(paths)
    if duplicate_paths:
        raise ValueError(
            f"Eastmoney industry hierarchy seed has duplicate node_path values: {duplicate_paths[:10]}."
        )
    duplicate_level_names = _duplicates((row.industry_level, row.name) for row in rows)
    if duplicate_level_names:
        raise ValueError(
            "Eastmoney industry hierarchy seed has duplicate (industry_level, name) values: "
            f"{duplicate_level_names[:10]}."
        )

    rows_by_path = {row.node_path: row for row in rows}
    for row in rows:
        segments = row.node_path.split("/")
        if len(segments) != row.industry_level:
            raise ValueError(
                "Eastmoney industry hierarchy seed node_path level mismatch: "
                f"{row.node_path}."
            )
        if segments[-1] != row.name:
            raise ValueError(
                "Eastmoney industry hierarchy seed node_path final segment must equal name: "
                f"{row.node_path}."
            )
        expected_parent_path = "/".join(segments[:-1]) or None
        if row.parent_path != expected_parent_path:
            raise ValueError(
                "Eastmoney industry hierarchy seed parent_path does not match node_path: "
                f"{row.node_path}."
            )
        if row.industry_level == 1:
            continue
        parent = rows_by_path.get(row.parent_path or "")
        if parent is None:
            raise ValueError(
                "Eastmoney industry hierarchy seed parent does not exist: "
                f"{row.node_path} -> {row.parent_path}."
            )
        if parent.industry_level != row.industry_level - 1:
            raise ValueError(
                "Eastmoney industry hierarchy seed parent level is invalid: "
                f"{row.node_path} -> {row.parent_path}."
            )


def _validate_default_seed_evidence(seed_sha256: str) -> None:
    if seed_sha256 != EASTMONEY_DC_INDUSTRY_HIERARCHY_SEED_SHA256:
        raise ValueError(
            "Eastmoney industry hierarchy seed SHA-256 does not match the approved v1 baseline."
        )
    if not EASTMONEY_DC_INDUSTRY_HIERARCHY_SOURCE_IMAGE_PATH.is_file():
        raise FileNotFoundError(
            "Missing Eastmoney industry hierarchy source image: "
            f"{EASTMONEY_DC_INDUSTRY_HIERARCHY_SOURCE_IMAGE_PATH}"
        )
    if _sha256(EASTMONEY_DC_INDUSTRY_HIERARCHY_SOURCE_IMAGE_PATH) != (
        EASTMONEY_DC_INDUSTRY_HIERARCHY_SOURCE_IMAGE_SHA256
    ):
        raise ValueError(
            "Eastmoney industry hierarchy source image SHA-256 does not match the approved v1 baseline."
        )


def _duplicates(values) -> list:
    counts = Counter(values)
    return sorted(value for value, count in counts.items() if count > 1)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
