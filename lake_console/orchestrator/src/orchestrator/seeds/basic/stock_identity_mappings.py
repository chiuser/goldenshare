"""Version-controlled non-self stock identity mappings."""

import csv
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path


STOCK_IDENTITY_MAPPINGS_SEED_PATH = (
    Path(__file__).with_name("stock_identity_mappings.cn_a.csv")
)
STOCK_IDENTITY_MAPPINGS_SEED_VERSION = "stock_identity_mappings.cn_a.v1"
STOCK_IDENTITY_MAPPINGS_SEED_COLUMNS = (
    "latest_ts_code",
    "source_ts_code",
    "valid_from",
    "valid_to",
    "identity_source",
    "confidence",
    "reason",
)
STOCK_IDENTITY_ALLOWED_SEED_SOURCES = frozenset({"bse_mapping", "namechange"})
STOCK_IDENTITY_ALLOWED_CONFIDENCE = frozenset({"confirmed", "inferred"})


@dataclass(frozen=True)
class StockIdentityMappingSeedRow:
    latest_ts_code: str
    source_ts_code: str
    valid_from: date
    valid_to: date | None
    identity_source: str
    confidence: str
    reason: str


def load_stock_identity_mapping_seed(
    path: Path = STOCK_IDENTITY_MAPPINGS_SEED_PATH,
) -> tuple[StockIdentityMappingSeedRow, ...]:
    """Load and validate the version-controlled non-self identity mapping seed."""

    if not path.exists():
        raise FileNotFoundError(f"Missing stock identity mapping seed: {path}")

    with path.open(newline="") as file:
        reader = csv.DictReader(file)
        if tuple(reader.fieldnames or ()) != STOCK_IDENTITY_MAPPINGS_SEED_COLUMNS:
            raise ValueError(
                "Stock identity mapping seed columns must be exactly "
                f"{STOCK_IDENTITY_MAPPINGS_SEED_COLUMNS}."
            )
        rows = tuple(_coerce_seed_row(raw_row, row_number=index + 2) for index, raw_row in enumerate(reader))

    if not rows:
        raise ValueError("Stock identity mapping seed must not be empty.")

    duplicate_source_codes = _duplicates(row.source_ts_code for row in rows)
    if duplicate_source_codes:
        raise ValueError(
            "Stock identity mapping seed source_ts_code must be unique: "
            f"{duplicate_source_codes[:10]}"
        )

    self_mapping_codes = [
        row.source_ts_code for row in rows if row.source_ts_code == row.latest_ts_code
    ]
    if self_mapping_codes:
        raise ValueError(
            "Stock identity mapping seed must contain only non-self mappings: "
            f"{self_mapping_codes[:10]}"
        )

    return rows


def _coerce_seed_row(
    raw_row: dict[str, str],
    *,
    row_number: int,
) -> StockIdentityMappingSeedRow:
    values = {
        column: (raw_row.get(column) or "").strip()
        for column in STOCK_IDENTITY_MAPPINGS_SEED_COLUMNS
    }
    required_columns = (
        "latest_ts_code",
        "source_ts_code",
        "valid_from",
        "identity_source",
        "confidence",
        "reason",
    )
    missing_columns = [column for column in required_columns if not values[column]]
    if missing_columns:
        raise ValueError(
            f"Stock identity mapping seed row {row_number} has blank required fields: "
            f"{missing_columns}"
        )
    if values["identity_source"] not in STOCK_IDENTITY_ALLOWED_SEED_SOURCES:
        raise ValueError(
            f"Stock identity mapping seed row {row_number} has unsupported "
            f"identity_source: {values['identity_source']}"
        )
    if values["confidence"] not in STOCK_IDENTITY_ALLOWED_CONFIDENCE:
        raise ValueError(
            f"Stock identity mapping seed row {row_number} has unsupported "
            f"confidence: {values['confidence']}"
        )

    valid_from = _parse_seed_date(values["valid_from"], row_number=row_number, field_name="valid_from")
    valid_to = (
        _parse_seed_date(values["valid_to"], row_number=row_number, field_name="valid_to")
        if values["valid_to"]
        else None
    )
    if valid_to is not None and valid_to < valid_from:
        raise ValueError(
            f"Stock identity mapping seed row {row_number} has valid_to before valid_from."
        )

    return StockIdentityMappingSeedRow(
        latest_ts_code=values["latest_ts_code"],
        source_ts_code=values["source_ts_code"],
        valid_from=valid_from,
        valid_to=valid_to,
        identity_source=values["identity_source"],
        confidence=values["confidence"],
        reason=values["reason"],
    )


def _parse_seed_date(value: str, *, row_number: int, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Stock identity mapping seed row {row_number} has invalid {field_name}: {value}"
        ) from exc


def _duplicates(values) -> list[str]:
    counts = Counter(values)
    return sorted(value for value, count in counts.items() if count > 1)

