"""Read-only, fully paginated stock technical factor code admission."""

from dataclasses import dataclass, replace
from datetime import date

from duckdb import ConstraintException

from orchestrator.defs.asset_guards.stk_factor_pro_readiness import (
    calculate_stk_factor_pro_coverage,
)
from orchestrator.defs.bootstrap.stk_factor_pro_bootstrap_records import (
    resource_cleanup,
)
from orchestrator.defs.run_contracts.stk_factor_pro import StkFactorProCoverageCounts
from orchestrator.tushare_download.configuration import ConfigurationSnapshot
from orchestrator.tushare_download.contracts.stk_factor_pro import (
    STK_FACTOR_PRO_CONTRACT,
)
from orchestrator.tushare_download.dataset_transport_mapping import (
    BINDINGS,
    DatasetTransportMapping,
)
from orchestrator.tushare_download.download_errors import (
    DownloadCancelled,
    DownloadError,
    DownloadErrorCode,
    ErrorDetails,
)
from orchestrator.tushare_download.download_models import (
    Clock,
    DownloadControl,
    PagePosition,
    PageRequest,
    RequestCounters,
    SessionCounters,
    UnitCounters,
)
from orchestrator.tushare_download.download_session import SessionControl
from orchestrator.tushare_download.http_transport import HttpProTransport
from orchestrator.tushare_download.unit_memory import UnitMemory

_FIELDS = ("ts_code", "trade_date")
_SOURCE = "stk_factor_pro_source_probe"


@dataclass(frozen=True, slots=True)
class StkFactorProSourceProbeResult:
    target_trade_date: date
    ready: bool
    reason: str
    source_row_count: int = 0
    source_code_count: int | None = None
    coverage_counts: StkFactorProCoverageCounts | None = None
    optional_count: int | None = None
    optional_present_count: int | None = None
    optional_sample_codes: tuple[str, ...] = ()
    request_count: int = 0
    page_count: int = 0
    elapsed_ms: float = 0
    error_code: DownloadErrorCode | None = None


def probe_stk_factor_pro_source(
    connection,
    *,
    target_trade_date: date,
    coverage_inputs,
    config: ConfigurationSnapshot,
    clock: Clock,
    control: DownloadControl,
) -> StkFactorProSourceProbeResult:
    """Consume this connection's prepared T inputs; never open files or a session."""
    started = clock.monotonic()
    result = StkFactorProSourceProbeResult(target_trade_date, False, "")
    if coverage_inputs["unknown_input_kinds"] or coverage_inputs["is_open"] is not True:
        return replace(
            result,
            reason=coverage_inputs["reason"] or "目标日尚未确认开市",
            elapsed_ms=(clock.monotonic() - started) * 1000,
        )

    deadline = started + config.request_timeout_seconds
    memory = UnitMemory(config)
    cancellation = SessionControl(control.is_cancelled, "stk_factor_pro_source_probe")
    counters = RequestCounters(SessionCounters(), UnitCounters())
    transport = HttpProTransport(clock)
    created = False
    rows = pages = 0
    failure_reason = ""
    outcome = page = codes = days = None
    source_day = target_trade_date.strftime("%Y%m%d")
    limit = STK_FACTOR_PRO_CONTRACT.pagination.effective_limit

    def release_source():
        if created:
            connection.execute(f"DROP TABLE {_SOURCE}")

    try:
        with resource_cleanup(
            transport.close, memory.clear, cancellation.clear, release_source
        ):
            transport.prepare(
                DatasetTransportMapping(BINDINGS).resolve(STK_FACTOR_PRO_CONTRACT),
                config,
                STK_FACTOR_PRO_CONTRACT,
            )
            connection.execute(
                f"CREATE TEMP TABLE {_SOURCE}(ts_code VARCHAR,trade_date VARCHAR,"
                "PRIMARY KEY(ts_code,trade_date))"
            )
            created = True
            offset = 0
            while True:
                cancellation.raise_if_cancelled()
                remaining = deadline - clock.monotonic()
                if remaining <= config.poll_interval_seconds:
                    failure_reason = "股票技术因子源端探测总时限已耗尽"
                    raise DownloadError(DownloadErrorCode.TRANSIENT_SOURCE)
                page_config = replace(
                    config,
                    request_timeout_seconds=remaining,
                    connect_timeout_seconds=min(
                        config.connect_timeout_seconds, remaining
                    ),
                    read_timeout_seconds=min(config.read_timeout_seconds, remaining),
                )
                request = PageRequest(
                    STK_FACTOR_PRO_CONTRACT.source_api_name,
                    _FIELDS,
                    (("trade_date", source_day), ("limit", limit), ("offset", offset)),
                    PagePosition(0, offset=offset),
                    limit,
                )
                outcome = transport.fetch_page(
                    request, page_config, memory, cancellation, counters, 1
                )
                if outcome.failure is not None:
                    failure = outcome.failure
                    raise DownloadError(
                        failure.code,
                        details=ErrorDetails(
                            source_status=failure.source_status,
                            source_code=failure.source_code,
                            cause_type=failure.cause_type,
                            cleanup_errors=failure.cleanup_errors,
                        ),
                    )
                page = outcome.page
                rows += len(page.records)
                if set(page.fields) != set(_FIELDS):
                    failure_reason = (
                        "股票技术因子源端返回字段不是ts_code、trade_date两列"
                    )
                    raise DownloadError(DownloadErrorCode.SOURCE_PROTOCOL)
                code_index, day_index = (page.fields.index(name) for name in _FIELDS)
                codes = tuple(record.values[code_index] for record in page.records)
                days = tuple(record.values[day_index] for record in page.records)
                memory.attach("probe_columns", (codes, days))
                if any(type(code) is not str or not code for code in codes):
                    failure_reason = "股票技术因子源端主键代码为空或类型错误"
                    raise DownloadError(DownloadErrorCode.SOURCE_PROTOCOL)
                if any(day != source_day for day in days):
                    failure_reason = "股票技术因子源端返回了非目标交易日"
                    raise DownloadError(DownloadErrorCode.SOURCE_PROTOCOL)
                try:
                    connection.execute(
                        f"INSERT INTO {_SOURCE} SELECT unnest(?::VARCHAR[]),unnest(?::VARCHAR[])",
                        [codes, days],
                    )
                except ConstraintException:
                    failure_reason = "股票技术因子源端存在重复主键"
                    raise DownloadError(DownloadErrorCode.SOURCE_PROTOCOL) from None
                page_size = len(page.records)
                pages += 1
                outcome = page = codes = days = None
                memory.release("probe_columns")
                memory.release("source_page")
                if page_size < limit:
                    break
                offset += limit

            cancellation.raise_if_cancelled()
            if clock.monotonic() >= deadline:
                failure_reason = "股票技术因子源端探测总时限已耗尽"
                raise DownloadError(DownloadErrorCode.TRANSIENT_SOURCE)
            calculated = calculate_stk_factor_pro_coverage(
                connection, coverage_inputs=coverage_inputs, raw_relation=_SOURCE
            )
            counts = calculated["coverage_counts"]
            known = counts is not None and counts.expected_count is not None
            optional_count = optional_present = None
            sample = ()
            if known:
                optional = coverage_inputs["coverage_keys"]["optional_relation"]
                optional_count, optional_present = connection.execute(
                    "SELECT count(*),count(a.ts_code) "
                    f"FROM {optional} f LEFT JOIN stk_factor_pro_coverage_actual a "
                    "USING(trade_date,ts_code)"
                ).fetchone()
                sample = tuple(
                    row[0]
                    for row in connection.execute(
                        f"SELECT ts_code FROM {optional} ORDER BY ts_code LIMIT 20"
                    ).fetchall()
                )
            ready = known and counts.missing_count == 0 and counts.extra_count == 0
            result = replace(
                result,
                ready=ready,
                reason=calculated["reason"]
                or ("" if ready else "股票技术因子源端代码集合尚未齐备"),
                source_code_count=rows,
                coverage_counts=counts,
                optional_count=optional_count,
                optional_present_count=optional_present,
                optional_sample_codes=sample,
            )
        if clock.monotonic() >= deadline:
            failure_reason = "股票技术因子源端探测总时限已耗尽"
            raise DownloadError(DownloadErrorCode.TRANSIENT_SOURCE)
    except DownloadCancelled:
        raise
    except DownloadError as error:
        result = StkFactorProSourceProbeResult(
            target_trade_date,
            False,
            "; ".join((failure_reason or str(error), *getattr(error, "__notes__", ()))),
            error_code=error.code,
        )
    finally:
        outcome = page = codes = days = None
    return replace(
        result,
        source_row_count=rows,
        request_count=counters.unit.request_count,
        page_count=pages,
        elapsed_ms=(clock.monotonic() - started) * 1000,
    )
