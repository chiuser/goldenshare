"""Prod serving write contract for the Wealth sector hierarchy snapshot."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone

from orchestrator.seeds.board.eastmoney_dc_industry_hierarchy import (
    EASTMONEY_DC_INDUSTRY_HIERARCHY_LEVEL_COUNTS,
    EASTMONEY_DC_INDUSTRY_HIERARCHY_SEED_VERSION,
    EASTMONEY_DC_INDUSTRY_HIERARCHY_SOURCE_RECEIVED_DATE,
)

PROD_CORE_WEALTH_SECTOR_HIERARCHY_TABLE = (
    "core_serving.wealth_sector_hierarchy"
)
PROD_CORE_WEALTH_SECTOR_HIERARCHY_CONTENT_COLUMNS = (
    "sector_code",
    "sector_name",
    "industry_level",
    "industry_level_name",
    "parent_sector_code",
    "parent_sector_name",
    "root_sector_code",
    "root_sector_name",
    "hierarchy_path",
    "is_leaf",
    "display_order",
    "baseline_version",
    "source_received_date",
    "code_reference_trade_date",
)
PROD_CORE_WEALTH_SECTOR_HIERARCHY_COLUMNS = (
    *PROD_CORE_WEALTH_SECTOR_HIERARCHY_CONTENT_COLUMNS,
    "published_at",
)

_INDUSTRY_LEVEL_NAMES = {
    1: "东财一级行业",
    2: "东财二级行业",
    3: "东财三级行业",
}
_BOARD_CODE_RE = re.compile(r"^BK[0-9]{4}\.DC$")
_INSERT_COLUMNS_SQL = "\n".join(
    f"  {column}{',' if index < len(PROD_CORE_WEALTH_SECTOR_HIERARCHY_COLUMNS) - 1 else ''}"
    for index, column in enumerate(PROD_CORE_WEALTH_SECTOR_HIERARCHY_COLUMNS)
)
_INSERT_PLACEHOLDERS_SQL = ", ".join(
    "%s" for _ in PROD_CORE_WEALTH_SECTOR_HIERARCHY_COLUMNS
)

PROD_CORE_WEALTH_SECTOR_HIERARCHY_DELETE_SQL = (
    f"DELETE FROM {PROD_CORE_WEALTH_SECTOR_HIERARCHY_TABLE}"
)
PROD_CORE_WEALTH_SECTOR_HIERARCHY_INSERT_SQL = f"""
INSERT INTO {PROD_CORE_WEALTH_SECTOR_HIERARCHY_TABLE} (
{_INSERT_COLUMNS_SQL}
) VALUES ({_INSERT_PLACEHOLDERS_SQL})
"""
PROD_CORE_WEALTH_SECTOR_HIERARCHY_SELECT_SQL = f"""
SELECT
{_INSERT_COLUMNS_SQL}
FROM {PROD_CORE_WEALTH_SECTOR_HIERARCHY_TABLE}
ORDER BY display_order, sector_code
"""


@dataclass(frozen=True, slots=True)
class WealthSectorHierarchyContentAudit:
    rows: tuple[dict[str, object], ...]
    row_count: int
    level_counts: tuple[tuple[int, int], ...]
    baseline_version: str
    source_received_date: date
    code_reference_trade_date: date
    content_hash: str


@dataclass(frozen=True, slots=True)
class ProdCoreWealthSectorHierarchySyncAudit:
    row_count: int
    observed_columns: tuple[str, ...]
    deleted_row_count: int | None
    inserted_row_count: int | None
    read_back_row_count: int
    level_counts: tuple[tuple[int, int], ...]
    baseline_version: str
    content_hash: str
    read_back_content_hash: str
    published_at: datetime


def audit_wealth_sector_hierarchy_rows(
    rows: Sequence[Mapping[str, object]],
) -> WealthSectorHierarchyContentAudit:
    """Normalize and validate the fixed 496-row hierarchy business contract."""

    expected_row_count = sum(EASTMONEY_DC_INDUSTRY_HIERARCHY_LEVEL_COUNTS.values())
    if len(rows) != expected_row_count:
        raise ValueError(
            "wealth sector hierarchy requires exactly "
            f"{expected_row_count} rows; observed {len(rows)}."
        )

    normalized_rows = tuple(_normalize_content_row(row) for row in rows)
    normalized_rows = tuple(
        sorted(
            normalized_rows,
            key=lambda row: (int(row["display_order"]), str(row["sector_code"])),
        )
    )
    _validate_hierarchy_contract(normalized_rows)

    level_counts = tuple(
        sorted(Counter(int(row["industry_level"]) for row in normalized_rows).items())
    )
    baseline_version = str(normalized_rows[0]["baseline_version"])
    source_received_date = normalized_rows[0]["source_received_date"]
    code_reference_trade_date = normalized_rows[0]["code_reference_trade_date"]
    assert isinstance(source_received_date, date)
    assert isinstance(code_reference_trade_date, date)
    return WealthSectorHierarchyContentAudit(
        rows=normalized_rows,
        row_count=len(normalized_rows),
        level_counts=level_counts,
        baseline_version=baseline_version,
        source_received_date=source_received_date,
        code_reference_trade_date=code_reference_trade_date,
        content_hash=_content_hash(normalized_rows),
    )


def replace_prod_core_wealth_sector_hierarchy(
    *,
    connection,
    rows: Sequence[Mapping[str, object]],
    published_at: datetime | None = None,
) -> ProdCoreWealthSectorHierarchySyncAudit:
    """Replace the full hierarchy and prove the committed candidate by read-back."""

    source_audit = audit_wealth_sector_hierarchy_rows(rows)
    normalized_published_at = _normalize_published_at(
        published_at or datetime.now(timezone.utc)
    )
    insert_rows = tuple(
        {**row, "published_at": normalized_published_at}
        for row in source_audit.rows
    )

    cursor = connection.cursor()
    try:
        cursor.execute(PROD_CORE_WEALTH_SECTOR_HIERARCHY_DELETE_SQL)
        deleted_row_count = _rowcount_or_none(cursor)
        cursor.executemany(
            PROD_CORE_WEALTH_SECTOR_HIERARCHY_INSERT_SQL,
            [_insert_params(row) for row in insert_rows],
        )
        inserted_row_count = _rowcount_or_none(cursor)
        cursor.execute(PROD_CORE_WEALTH_SECTOR_HIERARCHY_SELECT_SQL)
        read_back_rows = _normalize_read_back_rows(cursor.fetchall())
        try:
            read_back_audit = audit_wealth_sector_hierarchy_rows(read_back_rows)
        except (TypeError, ValueError) as error:
            raise RuntimeError(
                "Prod wealth sector hierarchy read-back audit failed: "
                "selected rows violate the hierarchy contract."
            ) from error

        read_back_published_at = {
            _normalize_published_at(row["published_at"])
            for row in read_back_rows
        }
        if read_back_published_at != {normalized_published_at}:
            raise RuntimeError(
                "Prod wealth sector hierarchy read-back audit failed: "
                "published_at does not match the current publication."
            )
        if (
            source_audit.rows != read_back_audit.rows
            or source_audit.content_hash != read_back_audit.content_hash
        ):
            raise RuntimeError(
                "Prod wealth sector hierarchy read-back audit failed: "
                "inserted rows do not match selected rows."
            )

        return ProdCoreWealthSectorHierarchySyncAudit(
            row_count=source_audit.row_count,
            observed_columns=PROD_CORE_WEALTH_SECTOR_HIERARCHY_COLUMNS,
            deleted_row_count=deleted_row_count,
            inserted_row_count=inserted_row_count,
            read_back_row_count=read_back_audit.row_count,
            level_counts=read_back_audit.level_counts,
            baseline_version=read_back_audit.baseline_version,
            content_hash=source_audit.content_hash,
            read_back_content_hash=read_back_audit.content_hash,
            published_at=normalized_published_at,
        )
    except Exception:
        rollback = getattr(connection, "rollback", None)
        if callable(rollback):
            rollback()
        raise
    finally:
        close = getattr(cursor, "close", None)
        if callable(close):
            close()


def validate_prod_core_wealth_sector_hierarchy_sql_contract() -> None:
    """Fail closed if the publisher escapes its explicit table/DML boundary."""

    combined_sql = (
        f"{PROD_CORE_WEALTH_SECTOR_HIERARCHY_DELETE_SQL}\n"
        f"{PROD_CORE_WEALTH_SECTOR_HIERARCHY_INSERT_SQL}\n"
        f"{PROD_CORE_WEALTH_SECTOR_HIERARCHY_SELECT_SQL}"
    )
    normalized_sql = " ".join(combined_sql.lower().split())
    for forbidden_fragment in (
        "select *",
        "truncate",
        " update ",
        " create ",
        " alter ",
        " drop ",
    ):
        if forbidden_fragment in f" {normalized_sql} ":
            raise RuntimeError(
                "Prod wealth sector hierarchy SQL contains forbidden fragment: "
                f"{forbidden_fragment.strip()}."
            )

    referenced_tables = set(re.findall(r"core_serving\.[a-z0-9_]+", normalized_sql))
    if referenced_tables != {PROD_CORE_WEALTH_SECTOR_HIERARCHY_TABLE}:
        raise RuntimeError(
            "Prod wealth sector hierarchy SQL must reference only its target table: "
            f"{sorted(referenced_tables)}."
        )
    for required_column in PROD_CORE_WEALTH_SECTOR_HIERARCHY_COLUMNS:
        if not re.search(rf"\b{re.escape(required_column)}\b", normalized_sql):
            raise RuntimeError(
                "Prod wealth sector hierarchy SQL is missing required column "
                f"{required_column}."
            )
    for required_clause in (
        f"delete from {PROD_CORE_WEALTH_SECTOR_HIERARCHY_TABLE}",
        f"insert into {PROD_CORE_WEALTH_SECTOR_HIERARCHY_TABLE}",
        f"from {PROD_CORE_WEALTH_SECTOR_HIERARCHY_TABLE}",
        "order by display_order, sector_code",
    ):
        if required_clause not in normalized_sql:
            raise RuntimeError(
                "Prod wealth sector hierarchy SQL is missing required clause: "
                f"{required_clause}."
            )


def _normalize_content_row(row: Mapping[str, object]) -> dict[str, object]:
    missing_columns = [
        column
        for column in PROD_CORE_WEALTH_SECTOR_HIERARCHY_CONTENT_COLUMNS
        if column not in row
    ]
    if missing_columns:
        raise ValueError(
            "wealth sector hierarchy row is missing columns: "
            f"{missing_columns}."
        )

    sector_code = _required_text(row["sector_code"], field_name="sector_code")
    if not _BOARD_CODE_RE.fullmatch(sector_code):
        raise ValueError(f"invalid wealth sector hierarchy sector_code: {sector_code}.")
    industry_level = _required_int(
        row["industry_level"],
        field_name="industry_level",
    )
    industry_level_name = _required_text(
        row["industry_level_name"],
        field_name="industry_level_name",
    )
    if _INDUSTRY_LEVEL_NAMES.get(industry_level) != industry_level_name:
        raise ValueError(
            "wealth sector hierarchy industry level name mismatch: "
            f"level={industry_level}, name={industry_level_name}."
        )

    return {
        "sector_code": sector_code,
        "sector_name": _required_text(row["sector_name"], field_name="sector_name"),
        "industry_level": industry_level,
        "industry_level_name": industry_level_name,
        "parent_sector_code": _optional_text(row["parent_sector_code"]),
        "parent_sector_name": _optional_text(row["parent_sector_name"]),
        "root_sector_code": _required_text(
            row["root_sector_code"], field_name="root_sector_code"
        ),
        "root_sector_name": _required_text(
            row["root_sector_name"], field_name="root_sector_name"
        ),
        "hierarchy_path": _required_text(
            row["hierarchy_path"], field_name="hierarchy_path"
        ),
        "is_leaf": _required_bool(row["is_leaf"], field_name="is_leaf"),
        "display_order": _required_int(
            row["display_order"], field_name="display_order"
        ),
        "baseline_version": _required_text(
            row["baseline_version"], field_name="baseline_version"
        ),
        "source_received_date": _required_date(
            row["source_received_date"], field_name="source_received_date"
        ),
        "code_reference_trade_date": _required_date(
            row["code_reference_trade_date"],
            field_name="code_reference_trade_date",
        ),
    }


def _validate_hierarchy_contract(rows: tuple[dict[str, object], ...]) -> None:
    expected_level_counts = tuple(
        sorted(EASTMONEY_DC_INDUSTRY_HIERARCHY_LEVEL_COUNTS.items())
    )
    observed_level_counts = tuple(
        sorted(Counter(int(row["industry_level"]) for row in rows).items())
    )
    if observed_level_counts != expected_level_counts:
        raise ValueError(
            "wealth sector hierarchy level counts mismatch: "
            f"expected={expected_level_counts}, observed={observed_level_counts}."
        )

    sector_codes = [str(row["sector_code"]) for row in rows]
    if len(set(sector_codes)) != len(rows):
        raise ValueError("wealth sector hierarchy contains duplicate sector_code values.")
    hierarchy_paths = [str(row["hierarchy_path"]) for row in rows]
    if len(set(hierarchy_paths)) != len(rows):
        raise ValueError("wealth sector hierarchy contains duplicate hierarchy_path values.")
    display_orders = [int(row["display_order"]) for row in rows]
    if display_orders != list(range(1, len(rows) + 1)):
        raise ValueError(
            "wealth sector hierarchy display_order must be continuous from 1 to 496."
        )

    baseline_versions = {str(row["baseline_version"]) for row in rows}
    if baseline_versions != {EASTMONEY_DC_INDUSTRY_HIERARCHY_SEED_VERSION}:
        raise ValueError(
            "wealth sector hierarchy baseline_version mismatch: "
            f"{sorted(baseline_versions)}."
        )
    source_received_dates = {row["source_received_date"] for row in rows}
    if source_received_dates != {
        EASTMONEY_DC_INDUSTRY_HIERARCHY_SOURCE_RECEIVED_DATE
    }:
        raise ValueError(
            "wealth sector hierarchy source_received_date mismatch: "
            f"{sorted(source_received_dates)}."
        )
    code_reference_dates = {row["code_reference_trade_date"] for row in rows}
    if len(code_reference_dates) != 1:
        raise ValueError(
            "wealth sector hierarchy must use one code_reference_trade_date."
        )

    rows_by_code = {str(row["sector_code"]): row for row in rows}
    parent_codes = {
        str(row["parent_sector_code"])
        for row in rows
        if row["parent_sector_code"] is not None
    }
    for row in rows:
        level = int(row["industry_level"])
        code = str(row["sector_code"])
        name = str(row["sector_name"])
        root_code = str(row["root_sector_code"])
        hierarchy_segments = str(row["hierarchy_path"]).split(" > ")
        if len(hierarchy_segments) != level or hierarchy_segments[-1] != name:
            raise ValueError(
                f"wealth sector hierarchy path level/name mismatch for {code}."
            )
        if bool(row["is_leaf"]) != (code not in parent_codes):
            raise ValueError(
                f"wealth sector hierarchy is_leaf mismatch for {code}."
            )
        root = rows_by_code.get(root_code)
        if root is None or int(root["industry_level"]) != 1:
            raise ValueError(
                f"wealth sector hierarchy root closure failed for {code}."
            )
        if str(root["sector_name"]) != str(row["root_sector_name"]):
            raise ValueError(
                f"wealth sector hierarchy root name mismatch for {code}."
            )
        if hierarchy_segments[0] != str(root["sector_name"]):
            raise ValueError(
                f"wealth sector hierarchy path root mismatch for {code}."
            )
        if level == 1:
            if (
                row["parent_sector_code"] is not None
                or row["parent_sector_name"] is not None
                or root_code != code
                or str(row["root_sector_name"]) != name
            ):
                raise ValueError(
                    f"wealth sector hierarchy level-one closure failed for {code}."
                )
            continue

        parent_code = row["parent_sector_code"]
        parent_name = row["parent_sector_name"]
        if parent_code is None or parent_name is None:
            raise ValueError(
                f"wealth sector hierarchy parent is missing for {code}."
            )
        parent = rows_by_code.get(str(parent_code))
        if parent is None or int(parent["industry_level"]) != level - 1:
            raise ValueError(
                f"wealth sector hierarchy parent closure failed for {code}."
            )
        if str(parent["sector_name"]) != str(parent_name):
            raise ValueError(
                f"wealth sector hierarchy parent name mismatch for {code}."
            )
        if hierarchy_segments[:-1] != str(parent["hierarchy_path"]).split(" > "):
            raise ValueError(
                f"wealth sector hierarchy path parent mismatch for {code}."
            )


def _normalize_read_back_rows(
    rows: Sequence[Sequence[object]],
) -> tuple[dict[str, object], ...]:
    normalized: list[dict[str, object]] = []
    for row in rows:
        if len(row) != len(PROD_CORE_WEALTH_SECTOR_HIERARCHY_COLUMNS):
            raise RuntimeError(
                "Prod wealth sector hierarchy read-back returned an invalid column count."
            )
        normalized.append(
            dict(
                zip(
                    PROD_CORE_WEALTH_SECTOR_HIERARCHY_COLUMNS,
                    row,
                    strict=True,
                )
            )
        )
    return tuple(normalized)


def _insert_params(row: Mapping[str, object]) -> tuple[object, ...]:
    return tuple(row[column] for column in PROD_CORE_WEALTH_SECTOR_HIERARCHY_COLUMNS)


def _content_hash(rows: Sequence[Mapping[str, object]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        payload = {
            column: _canonical_value(row[column])
            for column in PROD_CORE_WEALTH_SECTOR_HIERARCHY_CONTENT_COLUMNS
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest.update(encoded)
        digest.update(b"\n")
    return digest.hexdigest()


def _canonical_value(value: object) -> object:
    if isinstance(value, datetime):
        return _normalize_published_at(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _required_text(value: object, *, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError(f"wealth sector hierarchy {field_name} must not be blank.")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"wealth sector hierarchy {field_name} must be an integer.")
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"wealth sector hierarchy {field_name} must be an integer."
        ) from error


def _required_bool(value: object, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"wealth sector hierarchy {field_name} must be a boolean.")
    return value


def _required_date(value: object, *, field_name: str) -> date:
    if isinstance(value, datetime):
        raise TypeError(f"wealth sector hierarchy {field_name} must be a date.")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"wealth sector hierarchy {field_name} must be an ISO date."
        ) from error


def _normalize_published_at(value: object) -> datetime:
    if isinstance(value, datetime):
        normalized = value
    else:
        try:
            normalized = datetime.fromisoformat(str(value))
        except (TypeError, ValueError) as error:
            raise ValueError(
                "wealth sector hierarchy published_at must be an ISO timestamp."
            ) from error
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc)


def _rowcount_or_none(cursor) -> int | None:
    rowcount = getattr(cursor, "rowcount", None)
    if rowcount is None or rowcount < 0:
        return None
    return int(rowcount)


validate_prod_core_wealth_sector_hierarchy_sql_contract()


__all__ = [
    "PROD_CORE_WEALTH_SECTOR_HIERARCHY_COLUMNS",
    "PROD_CORE_WEALTH_SECTOR_HIERARCHY_CONTENT_COLUMNS",
    "PROD_CORE_WEALTH_SECTOR_HIERARCHY_DELETE_SQL",
    "PROD_CORE_WEALTH_SECTOR_HIERARCHY_INSERT_SQL",
    "PROD_CORE_WEALTH_SECTOR_HIERARCHY_SELECT_SQL",
    "PROD_CORE_WEALTH_SECTOR_HIERARCHY_TABLE",
    "ProdCoreWealthSectorHierarchySyncAudit",
    "WealthSectorHierarchyContentAudit",
    "audit_wealth_sector_hierarchy_rows",
    "replace_prod_core_wealth_sector_hierarchy",
    "validate_prod_core_wealth_sector_hierarchy_sql_contract",
]
