"""Bounded physical contract for the approved, immutable suspension facts.

No CSV, event history, connections, or write operations belong in this module.
"""

import re
import stat
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from orchestrator.defs.run_contracts.asset_column_schemas import (
    SILVER_STOCK_SUSPEND_CONFIRMED_SCHEMA,
)

STOCK_SUSPEND_CONFIRMED_ASSET_KEY = "silver_stock_suspend_confirmed"
STOCK_SUSPEND_CONFIRMED_VERSION = "confirmed_stock_full_day_suspend_v1"
STOCK_SUSPEND_CONFIRMED_APPROVED_LOGICAL_SHA256 = (
    "c88a7406ecda31c7dfe92b20b1d9cc719ffd2d049ece93113676ef4e60db4307"
)
STOCK_SUSPEND_CONFIRMED_CHECKS = (
    "silver_stock_suspend_confirmed_schema_check",
    "silver_stock_suspend_confirmed_approved_content_check",
)
STOCK_SUSPEND_CONFIRMED_COUNTS = (4022, 4022, 29, 1857, 4020, 2)
STOCK_SUSPEND_CONFIRMED_OVERRIDE_KEYS = (
    ("688005.SH", "2026-01-16"), ("688766.SH", "2025-11-26"),
)
CONFIRMED_COLUMNS = tuple(column.name for column in SILVER_STOCK_SUSPEND_CONFIRMED_SCHEMA)
CONFIRMED_SAMPLE_LIMIT = 20


class ConfirmedFactsError(ValueError):
    def __init__(self, message: str, reason_code: str = "validation_failed", exit_code: int = 3):
        super().__init__(message)
        self.reason_code = reason_code
        self.exit_code = exit_code


@dataclass(frozen=True)
class FileIdentity:
    path: str
    device: int
    inode: int
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class LoadedConfirmedFacts:
    relation_name: str
    path: Path
    file_identity: FileIdentity


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    reason_code: str
    checked_rows: int
    failed_rows: int
    samples: tuple[dict, ...] = ()
    logical_sha256: str | None = None


@dataclass(frozen=True)
class ConfirmedFileInspection:
    path: Path
    file_identity: FileIdentity
    columns: tuple[tuple[str, str], ...]
    row_count: int
    schema_validation: ValidationResult


@dataclass(frozen=True)
class ConfirmedFactsSummary:
    version: str
    logical_sha256: str
    row_count: int
    code_count: int
    date_count: int
    add_missing_count: int
    replace_confirmed_count: int
    min_trade_date: str
    max_trade_date: str


def suspend_relation_identifier(name: str) -> str:
    """Only internal simple identifiers, never arbitrary SQL."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", name):
        raise ConfirmedFactsError("非法停牌关系名", "invalid_relation", 2)
    return f'"{name}"'


def assert_suspend_path(path: Path, *, root: Path) -> Path:
    """Check lexical containment and every component before resolving symlinks."""
    if not path.is_absolute() or not root.is_absolute() or ".." in path.parts:
        raise ConfirmedFactsError(f"非法绝对路径: {path}", "invalid_path", 2)
    if not path.is_relative_to(root):
        raise ConfirmedFactsError(f"路径越界: {path}", "invalid_path", 2)
    for component in (*reversed(path.parents), path):
        if component.is_symlink():
            raise ConfirmedFactsError(f"拒绝符号链接: {component}", "invalid_path", 2)
    if not root.is_dir():
        raise ConfirmedFactsError(f"根目录不存在: {root}", "root_unavailable", 6)
    if path.exists() and not (path.is_file() or path.is_dir()):
        raise ConfirmedFactsError(f"非普通文件/目录: {path}", "invalid_path", 2)
    return path


def suspend_file_identity(path: Path) -> FileIdentity:
    assert_suspend_path(path, root=path.anchor and Path(path.anchor))
    observed = path.stat()
    if not stat.S_ISREG(observed.st_mode):
        raise ConfirmedFactsError(f"不是普通文件: {path}", "invalid_path", 2)
    return FileIdentity(str(path), observed.st_dev, observed.st_ino, observed.st_size, observed.st_mtime_ns)


def suspend_file_sha256(path: Path) -> str:
    before = suspend_file_identity(path)
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if suspend_file_identity(path) != before:
        raise ConfirmedFactsError(f"文件读取中发生变化: {path}", "input_drift", 4)
    return digest.hexdigest()


def _validate_confirmed_columns(columns, row_count: int) -> ValidationResult:
    expected = tuple((column.name, column.type) for column in SILVER_STOCK_SUSPEND_CONFIRMED_SCHEMA)
    passed = tuple((row[0], row[1]) for row in columns) == expected
    return ValidationResult(passed, "ok" if passed else "schema_mismatch", row_count, 0 if passed else row_count)


def inspect_confirmed_file(connection, path: Path) -> ConfirmedFileInspection:
    """Read physical structure/count only, without materializing rows or casting."""
    before = suspend_file_identity(path)
    # Prevent unbounded decoding of an unexpected file before any SQL allocation.
    if before.size > 100 * 1024 * 1024:
        raise ConfirmedFactsError("固定事实文件超过100MiB准备预算", "size_exceeded")
    columns = connection.execute(
        "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=false)", [str(path)],
    ).fetchall()
    row_count = connection.execute(
        "SELECT count(*) FROM read_parquet(?, hive_partitioning=false)", [str(path)],
    ).fetchone()[0]
    if before != suspend_file_identity(path):
        raise ConfirmedFactsError("固定事实检查期间发生变化", "input_drift", 4)
    return ConfirmedFileInspection(path, before, tuple((row[0], row[1]) for row in columns),
                                   row_count, _validate_confirmed_columns(columns, row_count))


def load_confirmed_relation(connection, inspection: ConfirmedFileInspection, *, relation_name: str) -> LoadedConfirmedFacts:
    """Load one bounded, unchanged inspected file; callers retain this relation."""
    relation = suspend_relation_identifier(relation_name)
    path, before = inspection.path, inspection.file_identity
    if before != suspend_file_identity(path):
        raise ConfirmedFactsError("固定事实inspection已失效", "input_drift", 4)
    if not inspection.schema_validation.passed:
        raise ConfirmedFactsError("固定事实五列物理schema不符，禁止cast修饰", "schema_mismatch")
    if inspection.row_count > STOCK_SUSPEND_CONFIRMED_COUNTS[0]:
        raise ConfirmedFactsError("固定事实行数超过批准上界", "row_count_mismatch")
    projection = ", ".join(CONFIRMED_COLUMNS)
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE {relation} AS SELECT {projection} "
        "FROM read_parquet(?, hive_partitioning=false)", [str(path)],
    )
    if before != suspend_file_identity(path):
        raise ConfirmedFactsError("固定事实加载期间发生变化", "input_drift", 4)
    return LoadedConfirmedFacts(relation_name, path, before)


def validate_confirmed_schema(connection, relation_name: str) -> ValidationResult:
    relation = suspend_relation_identifier(relation_name)
    columns = connection.execute(f"DESCRIBE {relation}").fetchall()
    count = connection.execute(f"SELECT count(*) FROM {relation}").fetchone()[0]
    return _validate_confirmed_columns(columns, count)


def _confirmed_invalid_predicate() -> str:
    return """ts_code IS NULL OR NOT regexp_full_match(ts_code, '[0-9]{6}\\.(SH|SZ|BJ)')
        OR trade_date IS NULL OR NOT isfinite(trade_date)
        OR suspend_timing IS NOT NULL OR suspend_type IS DISTINCT FROM 'S'
        OR merge_mode IS NULL OR merge_mode NOT IN ('add_missing','replace_confirmed')"""


def confirmed_logical_sha256(connection, relation_name: str) -> str:
    relation = suspend_relation_identifier(relation_name)
    schema = validate_confirmed_schema(connection, relation_name)
    if not schema.passed or schema.checked_rows > STOCK_SUSPEND_CONFIRMED_COUNTS[0]:
        raise ConfirmedFactsError("无法编码非法schema或超范围固定事实", "encoding_invalid")
    invalid, duplicate = connection.execute(f"""
        SELECT count(*) FILTER (WHERE {_confirmed_invalid_predicate()}),
               count(*) - count(DISTINCT (ts_code, trade_date)) FROM {relation}
    """).fetchone()
    if invalid or duplicate:
        raise ConfirmedFactsError("无法编码非法值域或重复键", "encoding_invalid")
    encoded = connection.execute(f"""
        SELECT 'stock_suspend_confirmed|v1' || chr(10) || coalesce(string_agg(
          ts_code || chr(9) || strftime(trade_date, '%Y-%m-%d') || chr(9) ||
          chr(92) || 'N' || chr(9) || suspend_type || chr(9) || merge_mode || chr(10),
          '' ORDER BY ts_code, trade_date), '') FROM {relation}
    """).fetchone()[0]
    return sha256(encoded.encode("utf-8")).hexdigest()


def validate_confirmed_content(connection, relation_name: str) -> ValidationResult:
    relation = suspend_relation_identifier(relation_name)
    schema = validate_confirmed_schema(connection, relation_name)
    if not schema.passed:
        return schema
    if schema.checked_rows != STOCK_SUSPEND_CONFIRMED_COUNTS[0]:
        return ValidationResult(False, "row_count_mismatch", schema.checked_rows, schema.checked_rows)
    counts = connection.execute(f"""
        SELECT count(*), count(DISTINCT (ts_code, trade_date)), count(DISTINCT ts_code),
          count(DISTINCT trade_date), count(*) FILTER (WHERE merge_mode='add_missing'),
          count(*) FILTER (WHERE merge_mode='replace_confirmed') FROM {relation}
    """).fetchone()
    invalid = connection.execute(
        f"SELECT count(*) FROM {relation} WHERE {_confirmed_invalid_predicate()}",
    ).fetchone()[0]
    if invalid or counts[0] != counts[1] or counts[0] > STOCK_SUSPEND_CONFIRMED_COUNTS[0]:
        return ValidationResult(False, "invalid_values_or_keys", counts[0], max(invalid, counts[0] - counts[1]))
    digest = confirmed_logical_sha256(connection, relation_name)
    # At most the two approved keys; do not return the full dataset to Python.
    overrides = connection.execute(f"""
        SELECT ts_code, strftime(trade_date, '%Y-%m-%d') FROM {relation}
        WHERE merge_mode='replace_confirmed' ORDER BY ts_code, trade_date LIMIT 3
    """).fetchall()
    passed = (
        counts == STOCK_SUSPEND_CONFIRMED_COUNTS
        and tuple(overrides) == STOCK_SUSPEND_CONFIRMED_OVERRIDE_KEYS
        and digest == STOCK_SUSPEND_CONFIRMED_APPROVED_LOGICAL_SHA256
    )
    samples = () if passed else ({"counts": list(counts), "override_keys": overrides},)
    return ValidationResult(passed, "ok" if passed else "approved_content_mismatch", counts[0], 0 if passed else counts[0], samples, digest)


def confirmed_facts_summary(connection, relation_name: str) -> ConfirmedFactsSummary:
    validation = validate_confirmed_content(connection, relation_name)
    if not validation.passed:
        raise ConfirmedFactsError("固定事实不是批准内容", validation.reason_code)
    relation = suspend_relation_identifier(relation_name)
    first, last = connection.execute(
        f"SELECT min(trade_date)::VARCHAR, max(trade_date)::VARCHAR FROM {relation}",
    ).fetchone()
    rows, _, codes, dates, added, replaced = STOCK_SUSPEND_CONFIRMED_COUNTS
    return ConfirmedFactsSummary(STOCK_SUSPEND_CONFIRMED_VERSION, validation.logical_sha256, rows, codes, dates, added, replaced, first, last)
