from __future__ import annotations

import argparse
from datetime import date
import json
import math
from pathlib import Path
import sys
import time
from typing import Any, Sequence

from src.biz.queries.wealth.market.index_detail_minutes.index_detail_minutes_query_service import (
    IndexDetailMinutesQueryService,
)
from src.biz.services.wealth.market.index_detail.index_detail_universe import (
    IndexDetailUniverseService,
)
from src.biz.services.wealth.market.index_detail_minutes.index_minute_response_policy import (
    MAX_INDEX_MINUTE_RESPONSE_BYTES,
)
from src.foundation.clients.local_lake.major_index_mins_contract import (
    FORMAL_LAKE_ROOT,
    GOLD_INDICATOR_COLUMN_SPECS,
    GOLD_INDICATOR_VERSION,
    GOLD_PARAMS_KEY,
    MAX_INDEX_MINUTE_LIMIT,
    MAX_INDEX_MINUTE_PARTITION_FILES,
    GOLD_BAR_COLUMN_SPECS,
    SUPPORTED_INDEX_MINUTE_FREQS,
    TRADE_DATE_PARTITION_PATTERN,
    IndexMinuteDataset,
    major_index_minute_frequency_root,
)
from src.foundation.clients.local_lake.major_index_mins_reader import (
    IndexMinuteReaderError,
)


SOURCE_NOT_READY = "SOURCE_NOT_READY"
READY = "READY"
FAILED = "FAILED"
SOURCE_NOT_READY_CODE = "IM_SOURCE_NOT_READY"
CONTRACT_INVALID_CODE = "IM_SOURCE_CONTRACT_INVALID"
QUERY_FAILED_CODE = "IM_QUERY_FAILED"
REQUEST_INVALID_CODE = "ID_REQUEST_INVALID"
KNOWN_UNSUPPORTED_MINUTE_CODES = frozenset({"899050.BJ"})
PERFORMANCE_TARGET_MS = 1_500.0
PERFORMANCE_HARD_GATE_MS = 5_000.0
SAFE_RESPONSE_LIMIT = 5_000
RESPONSE_TOO_LARGE_MESSAGE = "响应超过 5MB"


class GoldAcceptanceContractError(RuntimeError):
    pass


def _positive_int(raw_value: str) -> int:
    value = int(raw_value)
    if value < 1:
        raise argparse.ArgumentTypeError("必须是正整数")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="只读验收正式主要指数分钟 Gold 指标文件。",
    )
    parser.add_argument(
        "--runs",
        type=_positive_int,
        default=10,
        help="每个页面指数、每个频率的默认 500 根性能采样次数；默认 10。",
    )
    parser.add_argument(
        "--full-alignment",
        action="store_true",
        help="检查全部 Gold bar/indicator 共同分区；默认只检查最新共同分区。",
    )
    parser.add_argument(
        "--include-max",
        action="store_true",
        help=(
            "额外对代表性 1 分钟序列执行 10000 根/5MB 拒绝语义，"
            "以及固定 5000 根正常响应和分页游标验收。"
        ),
    )
    return parser


def _contains_symlink(path: Path, *, stop: Path) -> bool:
    current = path
    while current != stop:
        if current.is_symlink():
            return True
        parent = current.parent
        if parent == current:
            return True
        current = parent
    return False


def _partition_files(
    lake_root: Path,
    *,
    dataset: IndexMinuteDataset,
    freq: int,
) -> dict[date, Path]:
    frequency_root = major_index_minute_frequency_root(lake_root, dataset, freq)
    if not frequency_root.is_dir():
        return {}

    root = lake_root.expanduser().resolve()
    dataset_root = frequency_root.parent.resolve()
    partitions: dict[date, Path] = {}
    for candidate in frequency_root.glob("trade_date=*/part-000.parquet"):
        match = TRADE_DATE_PARTITION_PATTERN.fullmatch(candidate.parent.name)
        if match is None:
            continue
        if _contains_symlink(candidate, stop=root):
            raise GoldAcceptanceContractError(f"分区不得使用符号链接：{candidate}")
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root) or not resolved.is_relative_to(
            dataset_root
        ):
            raise GoldAcceptanceContractError(f"分区路径越界：{candidate}")
        if resolved.name != "part-000.parquet" or not resolved.is_file():
            continue
        trade_date = date.fromisoformat(match.group(1))
        if trade_date in partitions:
            raise GoldAcceptanceContractError(
                f"同一频率存在重复交易日分区：freq={freq}, tradeDate={trade_date}"
            )
        partitions[trade_date] = resolved
    return partitions


def _normalize_duckdb_type(raw_value: object) -> str:
    value = str(raw_value).upper()
    if value.startswith("TIMESTAMP"):
        return "TIMESTAMP"
    if value in {"TEXT", "STRING"}:
        return "VARCHAR"
    return value


def _schema(
    connection: Any,
    path: Path,
) -> tuple[tuple[str, str], ...]:
    description = connection.execute(
        "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=false)",
        [str(path)],
    ).fetchall()
    return tuple((str(row[0]), _normalize_duckdb_type(row[1])) for row in description)


def _audit_partition_alignment(
    connection: Any,
    *,
    bar_path: Path,
    gold_path: Path,
    freq: int,
    trade_date: date,
) -> dict[str, Any]:
    try:
        bar_schema = _schema(connection, bar_path)
        gold_schema = _schema(connection, gold_path)
    except Exception as exc:
        raise GoldAcceptanceContractError(
            f"Parquet schema 无法按合同读取：freq={freq}, tradeDate={trade_date}"
        ) from exc
    if bar_schema != GOLD_BAR_COLUMN_SPECS:
        raise GoldAcceptanceContractError(
            f"Gold bar schema 不符合合同：freq={freq}, tradeDate={trade_date}"
        )
    if gold_schema != GOLD_INDICATOR_COLUMN_SPECS:
        raise GoldAcceptanceContractError(
            f"Gold schema 不符合合同：freq={freq}, tradeDate={trade_date}"
        )

    row = connection.execute(
        """
        WITH bar_source AS MATERIALIZED (
          SELECT * FROM read_parquet(?, hive_partitioning=false)
        ),
        gold_source AS MATERIALIZED (
          SELECT * FROM read_parquet(?, hive_partitioning=false)
        ),
        bar_keys AS (
          SELECT ts_code, trade_time FROM bar_source
        ),
        gold_keys AS (
          SELECT ts_code, trade_time FROM gold_source
        )
        SELECT
          (SELECT count(*) FROM bar_source) AS bar_rows,
          (SELECT count(*) FROM gold_source) AS gold_rows,
          (
            SELECT count(*)
            FROM bar_source
            WHERE NOT COALESCE(
              freq = ?
              AND regexp_full_match(ts_code, '^[0-9]{6}\\.(SH|SZ|BJ)$')
              AND CAST(trade_time AS DATE) = CAST(? AS DATE)
              AND isfinite(open) AND isfinite(high) AND isfinite(low)
              AND isfinite(close) AND isfinite(vol) AND isfinite(amount)
              AND exchange <> '',
              FALSE
            )
          ) AS bar_invalid_rows,
          (
            SELECT count(*)
            FROM gold_source
            WHERE NOT COALESCE(
              freq = ?
              AND regexp_full_match(ts_code, '^[0-9]{6}\\.(SH|SZ|BJ)$')
              AND trade_date = CAST(? AS DATE)
              AND CAST(trade_time AS DATE) = CAST(? AS DATE)
              AND observation_count >= 1
              AND params_key = ?
              AND indicator_version = ?
              AND (ma_5 IS NULL OR isfinite(ma_5))
              AND (ma_10 IS NULL OR isfinite(ma_10))
              AND (ma_20 IS NULL OR isfinite(ma_20))
              AND (ma_30 IS NULL OR isfinite(ma_30))
              AND (ma_60 IS NULL OR isfinite(ma_60))
              AND (ma_90 IS NULL OR isfinite(ma_90))
              AND (ma_250 IS NULL OR isfinite(ma_250))
              AND (boll_mid IS NULL OR isfinite(boll_mid))
              AND (boll_upper IS NULL OR isfinite(boll_upper))
              AND (boll_lower IS NULL OR isfinite(boll_lower))
              AND isfinite(macd_dif) AND isfinite(macd_dea) AND isfinite(macd)
              AND isfinite(kdj_k) AND isfinite(kdj_d) AND isfinite(kdj_j),
              FALSE
            )
          ) AS gold_invalid_rows,
          (
            SELECT count(*) - count(DISTINCT (ts_code, trade_time))
            FROM bar_keys
          ) AS bar_duplicate_keys,
          (
            SELECT count(*) - count(DISTINCT (ts_code, trade_time))
            FROM gold_keys
          ) AS gold_duplicate_keys,
          (
            SELECT count(*) FROM (
              SELECT ts_code, trade_time FROM bar_keys
              EXCEPT
              SELECT ts_code, trade_time FROM gold_keys
            )
          ) AS bar_only_keys,
          (
            SELECT count(*) FROM (
              SELECT ts_code, trade_time FROM gold_keys
              EXCEPT
              SELECT ts_code, trade_time FROM bar_keys
            )
          ) AS gold_only_keys
        """,
        [
            str(bar_path),
            str(gold_path),
            freq,
            trade_date,
            freq,
            trade_date,
            trade_date,
            GOLD_PARAMS_KEY,
            GOLD_INDICATOR_VERSION,
        ],
    ).fetchone()
    names = (
        "barRows",
        "goldRows",
        "barInvalidRows",
        "goldInvalidRows",
        "barDuplicateKeys",
        "goldDuplicateKeys",
        "barOnlyKeys",
        "goldOnlyKeys",
    )
    result = dict(zip(names, map(int, row), strict=True))
    result["tradeDate"] = trade_date.isoformat()
    result["status"] = READY if all(result[name] == 0 for name in names[2:]) else FAILED
    return result


def _audit_frequency(
    connection: Any,
    *,
    lake_root: Path,
    freq: int,
    full_alignment: bool,
) -> dict[str, Any]:
    bars = _partition_files(lake_root, dataset="bars", freq=freq)
    gold = _partition_files(lake_root, dataset="indicators", freq=freq)
    bar_dates = set(bars)
    gold_dates = set(gold)
    missing_gold_dates = sorted(bar_dates - gold_dates)
    unexpected_gold_dates = sorted(gold_dates - bar_dates)
    common_dates = sorted(bar_dates & gold_dates)
    result: dict[str, Any] = {
        "freq": freq,
        "barPartitionCount": len(bars),
        "goldPartitionCount": len(gold),
        "commonPartitionCount": len(common_dates),
        "missingGoldPartitionCount": len(missing_gold_dates),
        "missingGoldPartitionSample": [
            item.isoformat() for item in missing_gold_dates[:10]
        ],
        "unexpectedGoldPartitionCount": len(unexpected_gold_dates),
        "unexpectedGoldPartitionSample": [
            item.isoformat() for item in unexpected_gold_dates[:10]
        ],
        "checkedPartitionCount": 0,
        "alignmentFailures": [],
    }
    if not bar_dates or not gold_dates or missing_gold_dates:
        result["status"] = SOURCE_NOT_READY
        result["code"] = SOURCE_NOT_READY_CODE
        return result
    if unexpected_gold_dates:
        result["status"] = FAILED
        result["code"] = CONTRACT_INVALID_CODE
        return result

    if full_alignment and len(common_dates) > MAX_INDEX_MINUTE_PARTITION_FILES:
        result["status"] = FAILED
        result["code"] = REQUEST_INVALID_CODE
        result["message"] = (
            "全量对齐将超过每频率 5000 个分区的只读扫描上界，"
            "需要先缩小正式验收窗口或评审新的扫描策略。"
        )
        return result

    dates_to_check = common_dates if full_alignment else common_dates[-1:]
    failures: list[dict[str, Any]] = []
    for partition_date in dates_to_check:
        alignment = _audit_partition_alignment(
            connection,
            bar_path=bars[partition_date],
            gold_path=gold[partition_date],
            freq=freq,
            trade_date=partition_date,
        )
        if alignment["status"] != READY:
            failures.append(alignment)
    result["checkedPartitionCount"] = len(dates_to_check)
    result["latestCheckedTradeDate"] = dates_to_check[-1].isoformat()
    result["alignmentFailures"] = failures[:10]
    result["status"] = READY if not failures else FAILED
    result["code"] = None if not failures else CONTRACT_INVALID_CODE
    return result


def _nearest_rank_p95(values: Sequence[float]) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return ordered[index]


def _performance_matrix(
    *,
    lake_root: Path,
    ts_codes: Sequence[str],
    frequencies: Sequence[int],
    runs: int,
) -> dict[str, Any]:
    service = IndexDetailMinutesQueryService(lake_root)
    frequency_results: list[dict[str, Any]] = []
    overall_status = READY
    for freq in frequencies:
        code_results: list[dict[str, Any]] = []
        frequency_samples: list[float] = []
        for ts_code in ts_codes:
            samples: list[float] = []
            response_bytes = 0
            error: str | None = None
            for _ in range(runs):
                started = time.perf_counter()
                try:
                    response = service.read_indicators(
                        ts_code=ts_code,
                        freq=freq,
                        start_date=None,
                        end_date=None,
                        limit=500,
                        cursor=None,
                    )
                    payload = response.model_dump_json().encode("utf-8")
                except IndexMinuteReaderError as exc:
                    error = f"{exc.code}: {exc}"
                    break
                elapsed_ms = (time.perf_counter() - started) * 1000
                if response.dataStatus.status != READY:
                    error = f"{response.dataStatus.code}: {response.dataStatus.message}"
                    break
                if len(payload) > MAX_INDEX_MINUTE_RESPONSE_BYTES:
                    error = "响应超过 5MB"
                    break
                samples.append(elapsed_ms)
                response_bytes = len(payload)

            if error is not None or not samples:
                code_result = {
                    "tsCode": ts_code,
                    "status": FAILED,
                    "error": error or "没有性能样本",
                }
                overall_status = FAILED
            else:
                p95_ms = _nearest_rank_p95(samples)
                target_passed = p95_ms <= PERFORMANCE_TARGET_MS
                hard_gate_passed = max(samples) <= PERFORMANCE_HARD_GATE_MS
                code_result = {
                    "tsCode": ts_code,
                    "status": READY if target_passed and hard_gate_passed else FAILED,
                    "sampleCount": len(samples),
                    "p95Ms": round(p95_ms, 3),
                    "maxMs": round(max(samples), 3),
                    "responseBytes": response_bytes,
                    "targetPassed": target_passed,
                    "hardGatePassed": hard_gate_passed,
                }
                if code_result["status"] != READY:
                    overall_status = FAILED
                frequency_samples.extend(samples)
            code_results.append(code_result)

        frequency_results.append(
            {
                "freq": freq,
                "status": READY
                if code_results
                and all(item["status"] == READY for item in code_results)
                else FAILED,
                "sampleCount": len(frequency_samples),
                "p95Ms": round(_nearest_rank_p95(frequency_samples), 3)
                if frequency_samples
                else None,
                "codes": code_results,
            }
        )
    return {
        "status": overall_status,
        "limit": 500,
        "runsPerCodeFrequency": runs,
        "targetP95Ms": PERFORMANCE_TARGET_MS,
        "hardGateMs": PERFORMANCE_HARD_GATE_MS,
        "frequencies": frequency_results,
    }


def _maximum_response_acceptance(
    *,
    lake_root: Path,
    ts_code: str,
    freq: int,
) -> dict[str, Any]:
    service = IndexDetailMinutesQueryService(lake_root)
    maximum_started = time.perf_counter()
    maximum_result: dict[str, Any]
    try:
        maximum_page = service.read_indicators(
            ts_code=ts_code,
            freq=freq,
            start_date=None,
            end_date=None,
            limit=MAX_INDEX_MINUTE_LIMIT,
            cursor=None,
        )
        maximum_payload = maximum_page.model_dump_json().encode("utf-8")
        maximum_elapsed_ms = (time.perf_counter() - maximum_started) * 1000
        maximum_cursor_valid = _cursor_order_valid(
            service,
            page=maximum_page,
            ts_code=ts_code,
            freq=freq,
        )
        maximum_passed = (
            maximum_page.dataStatus.status == READY
            and len(maximum_payload) <= MAX_INDEX_MINUTE_RESPONSE_BYTES
            and maximum_cursor_valid
            and maximum_elapsed_ms <= PERFORMANCE_HARD_GATE_MS
        )
        maximum_result = {
            "status": READY if maximum_passed else FAILED,
            "outcome": "RETURNED",
            "limit": MAX_INDEX_MINUTE_LIMIT,
            "count": len(maximum_page.items),
            "elapsedMs": round(maximum_elapsed_ms, 3),
            "responseBytes": len(maximum_payload),
            "responseSizePassed": len(maximum_payload)
            <= MAX_INDEX_MINUTE_RESPONSE_BYTES,
            "hasMore": maximum_page.meta.hasMore,
            "cursorOrderValid": maximum_cursor_valid,
            "hardGatePassed": maximum_elapsed_ms <= PERFORMANCE_HARD_GATE_MS,
        }
    except IndexMinuteReaderError as exc:
        expected_rejection = (
            exc.code == REQUEST_INVALID_CODE and RESPONSE_TOO_LARGE_MESSAGE in str(exc)
        )
        maximum_result = {
            "status": READY if expected_rejection else FAILED,
            "outcome": "REJECTED_AS_EXPECTED" if expected_rejection else "FAILED",
            "limit": MAX_INDEX_MINUTE_LIMIT,
            "elapsedMs": round(
                (time.perf_counter() - maximum_started) * 1000,
                3,
            ),
            "error": f"{exc.code}: {exc}",
            "responseTooLargeRejected": expected_rejection,
        }

    safe_started = time.perf_counter()
    try:
        safe_page = service.read_indicators(
            ts_code=ts_code,
            freq=freq,
            start_date=None,
            end_date=None,
            limit=SAFE_RESPONSE_LIMIT,
            cursor=None,
        )
        safe_payload = safe_page.model_dump_json().encode("utf-8")
        safe_elapsed_ms = (time.perf_counter() - safe_started) * 1000
        safe_cursor_valid = _cursor_order_valid(
            service,
            page=safe_page,
            ts_code=ts_code,
            freq=freq,
        )
        safe_passed = (
            safe_page.dataStatus.status == READY
            and len(safe_payload) <= MAX_INDEX_MINUTE_RESPONSE_BYTES
            and safe_cursor_valid
            and safe_elapsed_ms <= PERFORMANCE_HARD_GATE_MS
        )
        safe_result = {
            "status": READY if safe_passed else FAILED,
            "limit": SAFE_RESPONSE_LIMIT,
            "count": len(safe_page.items),
            "elapsedMs": round(safe_elapsed_ms, 3),
            "responseBytes": len(safe_payload),
            "responseSizePassed": len(safe_payload) <= MAX_INDEX_MINUTE_RESPONSE_BYTES,
            "hasMore": safe_page.meta.hasMore,
            "cursorPresentWhenRequired": not safe_page.meta.hasMore
            or bool(safe_page.meta.nextCursor),
            "cursorOrderValid": safe_cursor_valid,
            "hardGatePassed": safe_elapsed_ms <= PERFORMANCE_HARD_GATE_MS,
        }
    except IndexMinuteReaderError as exc:
        safe_result = {
            "status": FAILED,
            "limit": SAFE_RESPONSE_LIMIT,
            "error": f"{exc.code}: {exc}",
        }

    return {
        "status": READY
        if maximum_result["status"] == READY and safe_result["status"] == READY
        else FAILED,
        "tsCode": ts_code,
        "freq": freq,
        "maximumRequest": maximum_result,
        "safePage": safe_result,
    }


def _cursor_order_valid(
    service: IndexDetailMinutesQueryService,
    *,
    page: Any,
    ts_code: str,
    freq: int,
) -> bool:
    if not page.meta.hasMore:
        return True
    if not page.meta.nextCursor or not page.items:
        return False
    second = service.read_indicators(
        ts_code=ts_code,
        freq=freq,
        start_date=None,
        end_date=None,
        limit=1,
        cursor=page.meta.nextCursor,
    )
    return bool(second.items and second.items[-1].tradeTime < page.items[0].tradeTime)


def run_gold_acceptance(
    *,
    lake_root: Path,
    ts_codes: Sequence[str],
    frequencies: Sequence[int] = SUPPORTED_INDEX_MINUTE_FREQS,
    runs: int = 10,
    full_alignment: bool = False,
    include_max: bool = False,
) -> dict[str, Any]:
    resolved_root = lake_root.expanduser().resolve()
    if not ts_codes:
        return {
            "status": FAILED,
            "code": QUERY_FAILED_CODE,
            "lakeRoot": str(resolved_root),
            "readOnly": True,
            "message": "页面指数名单为空，无法执行正式性能验收。",
            "frequencies": [],
            "performance": None,
        }
    if not resolved_root.is_dir():
        return {
            "status": SOURCE_NOT_READY,
            "code": SOURCE_NOT_READY_CODE,
            "lakeRoot": str(resolved_root),
            "readOnly": True,
            "message": "正式 Lake 根不存在或不可读。",
            "frequencies": [],
            "performance": None,
        }

    try:
        import duckdb
    except ImportError:
        return {
            "status": FAILED,
            "code": QUERY_FAILED_CODE,
            "lakeRoot": str(resolved_root),
            "readOnly": True,
            "message": "DuckDB 依赖不可用。",
            "frequencies": [],
            "performance": None,
        }

    connection = duckdb.connect(database=":memory:")
    try:
        frequency_results = [
            _audit_frequency(
                connection,
                lake_root=resolved_root,
                freq=freq,
                full_alignment=full_alignment,
            )
            for freq in frequencies
        ]
    except GoldAcceptanceContractError as exc:
        return {
            "status": FAILED,
            "code": CONTRACT_INVALID_CODE,
            "lakeRoot": str(resolved_root),
            "readOnly": True,
            "message": str(exc),
            "frequencies": [],
            "performance": None,
        }
    except Exception as exc:
        return {
            "status": FAILED,
            "code": QUERY_FAILED_CODE,
            "lakeRoot": str(resolved_root),
            "readOnly": True,
            "message": f"只读验收查询失败：{exc}",
            "frequencies": [],
            "performance": None,
        }
    finally:
        connection.close()

    if any(item["status"] == FAILED for item in frequency_results):
        status = FAILED
        code = next(
            item["code"]
            for item in frequency_results
            if item["status"] == FAILED and item.get("code") is not None
        )
    elif any(item["status"] == SOURCE_NOT_READY for item in frequency_results):
        status = SOURCE_NOT_READY
        code = SOURCE_NOT_READY_CODE
    else:
        status = READY
        code = None

    result: dict[str, Any] = {
        "status": status,
        "code": code,
        "lakeRoot": str(resolved_root),
        "readOnly": True,
        "fullAlignment": full_alignment,
        "frequencies": frequency_results,
        "performance": None,
        "maximumResponse": None,
    }
    if status != READY:
        return result

    performance = _performance_matrix(
        lake_root=resolved_root,
        ts_codes=ts_codes,
        frequencies=frequencies,
        runs=runs,
    )
    result["performance"] = performance
    if performance["status"] != READY:
        result["status"] = FAILED
        result["code"] = None

    if include_max:
        representative_freq = min(frequencies)
        maximum = _maximum_response_acceptance(
            lake_root=resolved_root,
            ts_code=ts_codes[0],
            freq=representative_freq,
        )
        result["maximumResponse"] = maximum
        if maximum["status"] != READY:
            result["status"] = FAILED
            result["code"] = None
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    universe = IndexDetailUniverseService().load_universe()
    ts_codes = tuple(
        code
        for code in universe.ordered_codes
        if code not in KNOWN_UNSUPPORTED_MINUTE_CODES
    )
    result = run_gold_acceptance(
        lake_root=FORMAL_LAKE_ROOT,
        ts_codes=ts_codes,
        runs=args.runs,
        full_alignment=args.full_alignment,
        include_max=args.include_max,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if result["status"] == READY:
        return 0
    if result["status"] == SOURCE_NOT_READY:
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
