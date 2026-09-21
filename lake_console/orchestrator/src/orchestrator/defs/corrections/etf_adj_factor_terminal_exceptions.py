"""Versioned Silver-only terminal ETF adjustment-factor exceptions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.run_contracts.etf_daily import normalize_etf_daily_trade_date

_REGISTRY_PATH = Path(__file__).with_suffix(".yaml")
_ENTRY_FIELDS = frozenset(
    {
        "ts_code",
        "effective_from",
        "effective_to",
        "frozen_adj_factor",
        "frozen_discount_rate",
        "status",
        "reason_code",
        "approval_ref",
    }
)


class EtfAdjFactorTerminalExceptionError(ValueError):
    """Raised when the terminal exception registry or source evidence is unsafe."""


@dataclass(frozen=True, slots=True)
class EtfAdjFactorTerminalException:
    ts_code: str
    effective_from: date
    effective_to: date | None
    frozen_adj_factor: Decimal
    frozen_discount_rate: Decimal | None
    status: str
    reason_code: str
    approval_ref: str

    def applies_on(self, trade_date: date) -> bool:
        return (
            self.status == "active"
            and self.effective_from <= trade_date
            and (self.effective_to is None or trade_date <= self.effective_to)
        )


@dataclass(frozen=True, slots=True)
class EtfAdjFactorTerminalExceptionRegistry:
    entries: tuple[EtfAdjFactorTerminalException, ...]
    content_hash: str

    def active_for(
        self, trade_date: date
    ) -> tuple[EtfAdjFactorTerminalException, ...]:
        return tuple(entry for entry in self.entries if entry.applies_on(trade_date))


@dataclass(frozen=True, slots=True)
class EtfAdjFactorTerminalExceptionResolution:
    partition_key: str
    registry_hash: str | None
    approved_injections: tuple[EtfAdjFactorTerminalException, ...]
    source_resumptions: tuple[EtfAdjFactorTerminalException, ...]
    eligible_entries: tuple[EtfAdjFactorTerminalException, ...]

    @property
    def approved_exception_row_count(self) -> int:
        return len(self.approved_injections)

    @property
    def source_resumption_count(self) -> int:
        return len(self.source_resumptions)

    @property
    def sample_codes(self) -> tuple[str, ...]:
        return tuple(
            entry.ts_code
            for entry in (*self.approved_injections, *self.source_resumptions)[:20]
        )

    def injection_rows_sql(self, trade_date: str) -> str:
        return _exception_rows_sql(self.approved_injections, trade_date)

    def eligible_rows_sql(self, trade_date: str) -> str:
        return _exception_rows_sql(self.eligible_entries, trade_date)


def _parse_date(value: object, *, field: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise EtfAdjFactorTerminalExceptionError(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise EtfAdjFactorTerminalExceptionError(
            f"{field} must be an ISO date"
        ) from error


def _parse_decimal(value: object, *, field: str, positive: bool = False) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise EtfAdjFactorTerminalExceptionError(f"{field} must be a finite number")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise EtfAdjFactorTerminalExceptionError(
            f"{field} must be a finite number"
        ) from error
    if not parsed.is_finite() or (positive and parsed <= 0):
        raise EtfAdjFactorTerminalExceptionError(
            f"{field} must be {'a positive ' if positive else 'a '}finite number"
        )
    return parsed


def _parse_entry(value: object) -> EtfAdjFactorTerminalException:
    if not isinstance(value, Mapping) or set(value) != _ENTRY_FIELDS:
        raise EtfAdjFactorTerminalExceptionError("registry entry fields are invalid")
    ts_code = value["ts_code"]
    if not isinstance(ts_code, str) or not ts_code.endswith((".SH", ".SZ")):
        raise EtfAdjFactorTerminalExceptionError("ts_code must use .SH or .SZ")
    effective_from = _parse_date(value["effective_from"], field="effective_from")
    effective_to = _parse_date(value["effective_to"], field="effective_to")
    if effective_from is None or (
        effective_to is not None and effective_to < effective_from
    ):
        raise EtfAdjFactorTerminalExceptionError("registry effective range is invalid")
    status = value["status"]
    if status not in {"active", "retired"}:
        raise EtfAdjFactorTerminalExceptionError("status must be active or retired")
    reason_code = value["reason_code"]
    approval_ref = value["approval_ref"]
    if (
        not isinstance(reason_code, str)
        or not reason_code.isascii()
        or not reason_code
        or not isinstance(approval_ref, str)
        or not approval_ref.strip()
    ):
        raise EtfAdjFactorTerminalExceptionError(
            "reason_code and approval_ref must be non-empty"
        )
    adj_factor = _parse_decimal(
        value["frozen_adj_factor"], field="frozen_adj_factor", positive=True
    )
    assert adj_factor is not None
    return EtfAdjFactorTerminalException(
        ts_code=ts_code,
        effective_from=effective_from,
        effective_to=effective_to,
        frozen_adj_factor=adj_factor,
        frozen_discount_rate=_parse_decimal(
            value["frozen_discount_rate"], field="frozen_discount_rate"
        ),
        status=str(status),
        reason_code=reason_code,
        approval_ref=approval_ref,
    )


def _canonical_entry(entry: EtfAdjFactorTerminalException) -> dict[str, object]:
    return {
        "ts_code": entry.ts_code,
        "effective_from": entry.effective_from.isoformat(),
        "effective_to": entry.effective_to.isoformat() if entry.effective_to else None,
        "frozen_adj_factor": str(entry.frozen_adj_factor),
        "frozen_discount_rate": (
            str(entry.frozen_discount_rate)
            if entry.frozen_discount_rate is not None
            else None
        ),
        "status": entry.status,
        "reason_code": entry.reason_code,
        "approval_ref": entry.approval_ref,
    }


def load_etf_adj_factor_terminal_exception_registry(
    path: Path | None = None,
) -> EtfAdjFactorTerminalExceptionRegistry:
    registry_path = path or _REGISTRY_PATH
    try:
        payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise EtfAdjFactorTerminalExceptionError(
            f"registry cannot be read: {registry_path}"
        ) from error
    if not isinstance(payload, Mapping) or set(payload) != {"schema_version", "entries"}:
        raise EtfAdjFactorTerminalExceptionError("registry top-level fields are invalid")
    if payload["schema_version"] != 1 or not isinstance(payload["entries"], list):
        raise EtfAdjFactorTerminalExceptionError("registry schema version or entries are invalid")
    entries = tuple(sorted((_parse_entry(row) for row in payload["entries"]), key=lambda row: row.ts_code))
    if len({entry.ts_code for entry in entries}) != len(entries):
        raise EtfAdjFactorTerminalExceptionError("registry contains duplicate ts_code")
    encoded = json.dumps(
        [_canonical_entry(entry) for entry in entries],
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return EtfAdjFactorTerminalExceptionRegistry(
        entries=entries,
        content_hash=hashlib.sha256(encoded).hexdigest(),
    )


@lru_cache(maxsize=1)
def default_etf_adj_factor_terminal_exception_registry() -> EtfAdjFactorTerminalExceptionRegistry:
    return load_etf_adj_factor_terminal_exception_registry()


def _basic_row_is_eligible(
    basic_code: object,
    exchange: object,
    list_status: object,
    list_date: object,
    trade_date: date,
) -> bool:
    if not isinstance(basic_code, str) or not basic_code.endswith((".SH", ".SZ")):
        return False
    if exchange != basic_code[-2:] or list_status != "L" or list_date is None:
        return False
    return date.fromisoformat(str(list_date)) <= trade_date


def _source_value_matches(value: object, expected: Decimal | None) -> bool:
    if expected is None:
        return value is None
    if value is None or isinstance(value, bool):
        return False
    try:
        observed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return False
    return observed.is_finite() and observed == expected


def _exception_rows_sql(
    entries: tuple[EtfAdjFactorTerminalException, ...], trade_date: str
) -> str:
    if not entries:
        return """
        SELECT
          CAST(NULL AS VARCHAR) AS ts_code,
          CAST(NULL AS DATE) AS trade_date,
          CAST(NULL AS DOUBLE) AS adj_factor,
          CAST(NULL AS DOUBLE) AS discount_rate
        WHERE FALSE
        """
    normalized_date = normalize_etf_daily_trade_date(trade_date)
    rows = ", ".join(
        "("
        + ", ".join(
            (
                duckdb_string(entry.ts_code),
                f"CAST({duckdb_string(normalized_date)} AS DATE)",
                f"CAST({duckdb_string(str(entry.frozen_adj_factor))} AS DOUBLE)",
                (
                    "CAST(NULL AS DOUBLE)"
                    if entry.frozen_discount_rate is None
                    else f"CAST({duckdb_string(str(entry.frozen_discount_rate))} AS DOUBLE)"
                ),
            )
        )
        + ")"
        for entry in entries
    )
    return (
        "SELECT ts_code, trade_date, adj_factor, discount_rate "
        f"FROM (VALUES {rows}) AS exception_rows("
        "ts_code, trade_date, adj_factor, discount_rate)"
    )


def resolve_etf_adj_factor_terminal_exceptions(
    connection: Any,
    *,
    partition_key: str,
    raw_relation_sql: str,
    basic_relation_sql: str,
    registry: EtfAdjFactorTerminalExceptionRegistry | None = None,
) -> EtfAdjFactorTerminalExceptionResolution:
    """Resolve the small approved set once for a Raw/Basic partition pair."""

    normalized_partition = normalize_etf_daily_trade_date(partition_key)
    trade_date = date.fromisoformat(normalized_partition)
    resolved_registry = registry or default_etf_adj_factor_terminal_exception_registry()
    active_entries = resolved_registry.active_for(trade_date)
    if not active_entries:
        return EtfAdjFactorTerminalExceptionResolution(
            partition_key=normalized_partition,
            registry_hash=resolved_registry.content_hash,
            approved_injections=(),
            source_resumptions=(),
            eligible_entries=(),
        )
    code_values = ", ".join(
        f"({duckdb_string(entry.ts_code)})" for entry in active_entries
    )
    rows = connection.execute(
        f"""
        WITH candidate_codes(ts_code) AS (VALUES {code_values})
        SELECT
          candidate_codes.ts_code,
          raw_rows.ts_code,
          raw_rows.adj_factor,
          raw_rows.discount_rate,
          basic_rows.ts_code,
          basic_rows.exchange,
          basic_rows.list_status,
          basic_rows.list_date
        FROM candidate_codes
        LEFT JOIN (SELECT * FROM {raw_relation_sql}) raw_rows
          ON raw_rows.ts_code = candidate_codes.ts_code
        LEFT JOIN (SELECT * FROM {basic_relation_sql}) basic_rows
          ON basic_rows.ts_code = candidate_codes.ts_code
        ORDER BY candidate_codes.ts_code
        """
    ).fetchall()
    entries_by_code = {entry.ts_code: entry for entry in active_entries}
    injections: list[EtfAdjFactorTerminalException] = []
    resumptions: list[EtfAdjFactorTerminalException] = []
    eligible: list[EtfAdjFactorTerminalException] = []
    for row in rows:
        entry = entries_by_code[str(row[0])]
        if not _basic_row_is_eligible(*row[4:], trade_date):
            continue
        eligible.append(entry)
        raw_code, adj_factor, discount_rate = row[1:4]
        if raw_code is None:
            injections.append(entry)
            continue
        if not _source_value_matches(adj_factor, entry.frozen_adj_factor) or not _source_value_matches(
            discount_rate, entry.frozen_discount_rate
        ):
            raise EtfAdjFactorTerminalExceptionError(
                "terminal_exception_source_value_changed: " + entry.ts_code
            )
        resumptions.append(entry)
    return EtfAdjFactorTerminalExceptionResolution(
        partition_key=normalized_partition,
        registry_hash=resolved_registry.content_hash,
        approved_injections=tuple(injections),
        source_resumptions=tuple(resumptions),
        eligible_entries=tuple(eligible),
    )


__all__ = [
    "EtfAdjFactorTerminalException",
    "EtfAdjFactorTerminalExceptionError",
    "EtfAdjFactorTerminalExceptionRegistry",
    "EtfAdjFactorTerminalExceptionResolution",
    "default_etf_adj_factor_terminal_exception_registry",
    "load_etf_adj_factor_terminal_exception_registry",
    "resolve_etf_adj_factor_terminal_exceptions",
]
