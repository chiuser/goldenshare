"""Bounded identity/date evidence for boards awaiting their first observed quote."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from threading import Timer
from time import monotonic
from zoneinfo import ZoneInfo

from orchestrator.defs.paths import raw_dc_daily_path, silver_trade_calendar_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.dc_board import (
    DC_DAILY_HISTORY_START_DATE,
    DC_QUOTE_COVERAGE_METADATA_BYTES,
    DC_QUOTE_COVERAGE_POLICY_VERSION,
    DC_QUOTE_COVERAGE_SAMPLE_LIMIT,
    DC_QUOTE_HISTORY_BATCH_FILES,
    DC_QUOTE_HISTORY_BATCH_SQL_DEADLINE_SECONDS,
    DC_QUOTE_HISTORY_DEADLINE_SECONDS,
    DC_QUOTE_HISTORY_MAX_CODES,
    DC_QUOTE_HISTORY_MAX_FILE_BYTES,
    DC_QUOTE_HISTORY_MAX_PROJECTED_ROWS,
    DC_QUOTE_HISTORY_MAX_TARGETS,
    DC_QUOTE_HISTORY_MEMORY_LIMIT,
    DC_QUOTE_HISTORY_THREADS,
)

AWAITING_QUOTE = "awaiting_first_observed_quote"
MISSING_OBSERVED_QUOTE = "missing_previously_observed_quote"
HISTORY_UNVERIFIABLE = "quote_history_unverifiable"
_BOARD_CODE = re.compile(r"BK[0-9]{4}\.DC\Z")


def coverage_digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class BoardQuoteEvidence:
    code: str
    state: str
    observed_quote_date: str | None = None


@dataclass(frozen=True, slots=True)
class BoardQuoteCoverageResult:
    target_date: str
    details: tuple[BoardQuoteEvidence, ...]
    history_end: str | None
    history_complete: bool
    file_signatures: tuple[tuple[str, int, int], ...] = ()
    calendar_dates: tuple[str, ...] = ()
    error: str | None = None
    calendar_signature: tuple[str, int, int] | None = None
    index_count: int | None = None
    daily_count: int | None = None
    sample_labels: tuple[tuple[str, str | None, str | None], ...] = ()

    @property
    def ready(self) -> bool:
        return all(item.state == AWAITING_QUOTE for item in self.details)

    @property
    def gap_count(self) -> int:
        return len(self.details)

    @property
    def evidence_digest(self) -> str:
        return coverage_digest({
            "policy_version": DC_QUOTE_COVERAGE_POLICY_VERSION,
            "target_date": self.target_date,
            "history_start": DC_DAILY_HISTORY_START_DATE,
            "history_end": self.history_end,
            "history_complete": self.history_complete,
            "calendar_dates": self.calendar_dates,
            "calendar_signature": self.calendar_signature,
            "files": self.file_signatures,
            "details": [(x.code, x.state, x.observed_quote_date) for x in self.details],
        })

    def metadata(self) -> dict[str, object]:
        scanned = tuple(sorted(sig[0].split("trade_date=", 1)[1].split("/", 1)[0] for sig in self.file_signatures))
        labels = {code: (name, category) for code, name, category in self.sample_labels}
        details = [{"ts_code": x.code, "state": x.state,
                    "evidence_start": scanned[0] if scanned else None,
                    "evidence_end": scanned[-1] if scanned else None,
                    "history_complete": self.history_complete,
                    "observed_quote_date": x.observed_quote_date} for x in self.details]
        result: dict[str, object] = {
            "policy_version": DC_QUOTE_COVERAGE_POLICY_VERSION,
            "partition_key": self.target_date,
            "missing_quote_count": self.gap_count,
            "index_code_count": self.index_count,
            "daily_code_count": self.daily_count,
            "awaiting_count": sum(x.state == AWAITING_QUOTE for x in self.details),
            "previously_observed_missing_count": sum(x.state == MISSING_OBSERVED_QUOTE for x in self.details),
            "unverifiable_count": sum(x.state == HISTORY_UNVERIFIABLE for x in self.details),
            "missing_quote_details": details,
            "quote_coverage_samples": [{**detail, "name": labels.get(detail["ts_code"], (None, None))[0],
                                         "category": labels.get(detail["ts_code"], (None, None))[1]}
                                        for detail in details[:DC_QUOTE_COVERAGE_SAMPLE_LIMIT]],
            "history_start": DC_DAILY_HISTORY_START_DATE,
            "history_end": self.history_end,
            "history_complete": self.history_complete,
            "history_file_count": len(self.file_signatures),
            "source_confirmation": "not_evaluated",
            "reason_code": (HISTORY_UNVERIFIABLE if any(x.state == HISTORY_UNVERIFIABLE for x in self.details)
                            else MISSING_OBSERVED_QUOTE if any(x.state == MISSING_OBSERVED_QUOTE for x in self.details)
                            else AWAITING_QUOTE if self.details else "no_missing_quote"),
            "evidence_digest": self.evidence_digest,
            "metadata_truncated": False,
            "retained_quote_detail_count": len(details),
        }
        if self.error:
            result["history_error"] = self.error[:500]
        for sample in result["quote_coverage_samples"]:
            for field, value in tuple(sample.items()):
                if isinstance(value, str):
                    limit = 200 if field == "name" else 80
                    if len(value) > limit:
                        sample[field] = value[:limit]
                        result["metadata_truncated"] = True
        def encoded_size() -> int:
            return len(json.dumps(result, ensure_ascii=False).encode())
        if encoded_size() > DC_QUOTE_COVERAGE_METADATA_BYTES:
            result["metadata_truncated"] = True
            low, high = 0, len(details)
            while low < high:
                count = (low + high + 1) // 2
                result["missing_quote_details"] = details[:count]
                result["retained_quote_detail_count"] = count
                if encoded_size() <= DC_QUOTE_COVERAGE_METADATA_BYTES:
                    low = count
                else:
                    high = count - 1
            result["missing_quote_details"] = details[:low]
            result["retained_quote_detail_count"] = low
        return result


QUOTE_COVERAGE_METADATA_KEYS = (
    "policy_version", "partition_key", "index_code_count", "daily_code_count", "missing_quote_count",
    "awaiting_count", "previously_observed_missing_count", "unverifiable_count", "missing_quote_details",
    "quote_coverage_samples", "history_start", "history_end", "history_complete", "history_file_count",
    "source_confirmation", "reason_code", "evidence_digest", "metadata_truncated", "retained_quote_detail_count", "history_error",
)


def quote_coverage_metadata(summary: Mapping[str, object]) -> dict[str, object]:
    """Project shared physical evidence unchanged into a runless core event."""
    return {key: summary[key] for key in QUOTE_COVERAGE_METADATA_KEYS if key in summary}


def empty_quote_coverage(target_date: str) -> BoardQuoteCoverageResult:
    """No gap means no history IO, not a claim that the lake has no history."""
    return BoardQuoteCoverageResult(target_date, (), None, True)


def _signature(path: Path, root: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return str(path.relative_to(root)), stat.st_size, stat.st_mtime_ns


def batch_board_quote_coverage(
    *,
    lake_root: Path,
    gaps_by_date: Mapping[str, Sequence[str]],
    duckdb_resource: DuckDBResource,
) -> dict[str, BoardQuoteCoverageResult]:
    """One history connection, <=64 files per query, no OHLC or event IO."""
    gaps = {day: tuple(sorted(set(codes))) for day, codes in gaps_by_date.items()}
    results = {day: empty_quote_coverage(day) for day, codes in gaps.items() if not codes}
    active = {day: codes for day, codes in gaps.items() if codes}
    if not active:
        return results
    known: dict[tuple[str, str], str] = {}
    signatures: dict[str, tuple[str, int, int]] = {}
    expected: tuple[str, ...] = ()
    invalid_dates: set[str] = set()
    error: str | None = None
    complete = False
    calendar_signature = None
    deadline = monotonic() + DC_QUOTE_HISTORY_DEADLINE_SECONDS

    def check_budget() -> None:
        if monotonic() >= deadline:
            raise TimeoutError("history_budget_exceeded")

    def query(connection, sql: str, parameters: list[object]):
        check_budget()
        timer = Timer(min(DC_QUOTE_HISTORY_BATCH_SQL_DEADLINE_SECONDS, deadline - monotonic()), connection.interrupt)
        timer.start()
        try:
            return connection.execute(sql, parameters).fetchall()
        finally:
            timer.cancel()
            timer.join()

    try:
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        if any(date.fromisoformat(day) > today or day < DC_DAILY_HISTORY_START_DATE for day in active):
            raise ValueError("invalid_history_target_date")
        all_codes = sorted({code for codes in active.values() for code in codes})
        if len(active) > DC_QUOTE_HISTORY_MAX_TARGETS or len(all_codes) > DC_QUOTE_HISTORY_MAX_CODES:
            raise ValueError("history_budget_exceeded: target/code capacity")
        if any(not _BOARD_CODE.fullmatch(code) for code in all_codes):
            raise ValueError("invalid_board_identity")
        with duckdb_resource.connect() as connection:
            connection.execute(f"SET memory_limit='{DC_QUOTE_HISTORY_MEMORY_LIMIT}'")
            connection.execute(f"SET threads={DC_QUOTE_HISTORY_THREADS}")
            connection.execute("SET max_temp_directory_size='0B'")
            calendar_signature = _signature(silver_trade_calendar_path(lake_root), lake_root)
            calendar = query(connection, """
                SELECT trade_date FROM read_parquet(?, hive_partitioning=false)
                WHERE exchange='SSE' AND is_open AND trade_date>=CAST(? AS DATE)
                  AND trade_date<CAST(? AS DATE) ORDER BY trade_date DESC
            """, [str(silver_trade_calendar_path(lake_root)), DC_DAILY_HISTORY_START_DATE, max(active)])
            expected = tuple(str(row[0]) for row in calendar)
            if len(set(expected)) != len(expected) or len(expected) > (date.fromisoformat(max(active)) - date.fromisoformat(DC_DAILY_HISTORY_START_DATE)).days:
                raise ValueError("invalid_history_calendar")
            total_rows = 0
            total_bytes = 0
            for offset in range(0, len(expected), DC_QUOTE_HISTORY_BATCH_FILES):
                check_budget()
                batch_dates = expected[offset:offset + DC_QUOTE_HISTORY_BATCH_FILES]
                paths = []
                for day in batch_dates:
                    path = raw_dc_daily_path(lake_root, day)
                    if not path.is_file() or not path.stat().st_size:
                        invalid_dates.add(day)
                    else:
                        signatures[day] = _signature(path, lake_root)
                        paths.append(str(path))
                total_bytes += sum(signatures[d][1] for d in batch_dates if d in signatures)
                if total_bytes > DC_QUOTE_HISTORY_MAX_FILE_BYTES:
                    raise ValueError("history_budget_exceeded: file bytes")
                if not paths:
                    continue
                footer = query(connection, """
                    SELECT f.file_name, f.num_rows,
                      count(*) FILTER (WHERE s.name IN ('ts_code','trade_date')
                        AND s.type='BYTE_ARRAY' AND s.converted_type='UTF8')
                    FROM parquet_file_metadata(?) f JOIN parquet_schema(?) s ON f.file_name=s.file_name
                    GROUP BY f.file_name, f.num_rows
                """, [paths, paths])
                valid_paths = []
                for name, count, columns in footer:
                    if int(count) <= 0 or int(columns) != 2:
                        invalid_dates.add(Path(name).parent.name.removeprefix("trade_date="))
                    else:
                        total_rows += int(count)
                        valid_paths.append(name)
                if total_rows > DC_QUOTE_HISTORY_MAX_PROJECTED_ROWS:
                    raise ValueError("history_budget_exceeded: projected rows")
                if not valid_paths:
                    continue
                stats = query(connection, """
                    SELECT filename,
                      count(*) FILTER (WHERE ts_code IS NULL OR NOT regexp_full_match(ts_code,'BK[0-9]{4}\\.DC')),
                      count(*) FILTER (WHERE trade_date IS NULL OR NOT regexp_full_match(trade_date,'[0-9]{8}')
                        OR trade_date<>replace(regexp_extract(filename,'trade_date=([0-9-]{10})',1),'-',''))
                    FROM read_parquet(?, hive_partitioning=false, filename=true) GROUP BY filename
                """, [valid_paths])
                trusted = []
                for name, bad_code, bad_date in stats:
                    if bad_code or bad_date:
                        invalid_dates.add(Path(name).parent.name.removeprefix("trade_date="))
                    else:
                        trusted.append(name)
                if trusted:
                    observations = query(connection, """
                        WITH candidates AS (SELECT unnest(?) AS ts_code),
                          targets AS (SELECT unnest(?) AS target_date)
                        SELECT t.target_date,s.ts_code,max(s.trade_date)
                        FROM read_parquet(?,hive_partitioning=false) s JOIN candidates c USING(ts_code)
                        CROSS JOIN targets t WHERE s.trade_date<replace(t.target_date,'-','')
                        GROUP BY t.target_date,s.ts_code
                    """, [all_codes, sorted(active), trusted])
                    for day, code, observed in observations:
                        if code in active[day]:
                            observed_iso = date.fromisoformat(observed).isoformat()
                            known[(day, code)] = max(known.get((day, code), observed_iso), observed_iso)
                if all((day, code) in known for day, codes in active.items() for code in codes):
                    break
            else:
                complete = True
            check_budget()
            try:
                changed = any(_signature(raw_dc_daily_path(lake_root, day), lake_root) != sig
                              for day, sig in signatures.items())
                changed = changed or _signature(silver_trade_calendar_path(lake_root), lake_root) != calendar_signature
            except OSError:
                changed = True
            if changed:
                raise ValueError("history_files_changed")
    except Exception as exc:  # noqa: BLE001 - unavailable evidence must fail closed.
        error = str(exc)[:500]
        # An interrupted scan has not completed its closing signature checks.
        # Do not label intermediate positive matches as verified evidence.
        known.clear()

    for day, codes in active.items():
        relevant = tuple(sorted(d for d in expected if d < day))
        verified = complete and not error and not any(d < day for d in invalid_dates)
        details = tuple(BoardQuoteEvidence(code,
            MISSING_OBSERVED_QUOTE if (day, code) in known else AWAITING_QUOTE if verified else HISTORY_UNVERIFIABLE,
            known.get((day, code))) for code in codes)
        results[day] = BoardQuoteCoverageResult(day, details,
            relevant[-1] if relevant else None, verified,
            tuple(signatures[d] for d in sorted(signatures) if d < day), relevant, error, calendar_signature)
    return results
