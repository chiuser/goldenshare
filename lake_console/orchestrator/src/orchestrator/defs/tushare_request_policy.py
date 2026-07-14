"""Bounded request policy primitives for code-scoped Tushare ingestion."""

from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass
from time import perf_counter, sleep
from typing import Any, Generic, TypeVar


TushareResponse = TypeVar("TushareResponse")

TUSHARE_FAILURE_RATE_LIMIT = "rate_limit"
TUSHARE_FAILURE_TRANSIENT = "transient"
TUSHARE_FAILURE_NON_RETRYABLE = "non_retryable"
TUSHARE_FAILURE_RETRY_BUDGET = "retry_budget_exhausted"


@dataclass(frozen=True, slots=True)
class TushareRequestPolicy:
    """Bounded safety policy for one full code-scoped partition request."""

    minimum_interval_seconds: float = 0.13
    max_retries: int = 3
    backoff_base_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 8.0
    max_requests: int = 1_200
    max_elapsed_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.minimum_interval_seconds < 0:
            raise ValueError("minimum_interval_seconds must not be negative.")
        if self.max_retries < 0:
            raise ValueError("max_retries must not be negative.")
        if self.backoff_base_seconds <= 0:
            raise ValueError("backoff_base_seconds must be positive.")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be at least 1.")
        if self.max_backoff_seconds < self.backoff_base_seconds:
            raise ValueError("max_backoff_seconds must cover the base backoff.")
        if self.max_requests <= 0:
            raise ValueError("max_requests must be positive.")
        if self.max_elapsed_seconds <= 0:
            raise ValueError("max_elapsed_seconds must be positive.")

    def backoff_seconds(self, retry_index: int) -> float:
        if retry_index < 0:
            raise ValueError("retry_index must not be negative.")
        return min(
            self.max_backoff_seconds,
            self.backoff_base_seconds * (self.backoff_multiplier**retry_index),
        )

    def to_details(self) -> dict[str, Any]:
        return {
            "minimum_interval_seconds": self.minimum_interval_seconds,
            "max_retries": self.max_retries,
            "backoff_base_seconds": self.backoff_base_seconds,
            "backoff_multiplier": self.backoff_multiplier,
            "max_backoff_seconds": self.max_backoff_seconds,
            "max_requests": self.max_requests,
            "max_elapsed_seconds": self.max_elapsed_seconds,
        }


@dataclass(frozen=True, slots=True)
class TushareCodeFailure:
    code: str
    category: str
    message: str
    attempts: int
    retryable: bool

    def to_details(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "category": self.category,
            "message": self.message,
            "attempts": self.attempts,
            "retryable": self.retryable,
        }


@dataclass(frozen=True, slots=True)
class BoundedCodeRequestResult(Generic[TushareResponse]):
    """In-memory outcome for one bounded, all-code request batch."""

    rows_by_code: Mapping[str, list[dict[str, Any]]]
    page_counts: Mapping[str, int]
    successful_codes: tuple[str, ...]
    empty_codes: tuple[str, ...]
    failed_codes: tuple[TushareCodeFailure, ...]
    unattempted_codes: tuple[str, ...]
    request_count: int
    retry_count: int
    elapsed_ms: float
    budget_exceeded: bool
    budget_reason: str | None

    @property
    def completed(self) -> bool:
        return not self.unattempted_codes and not self.budget_exceeded

    @property
    def ready(self) -> bool:
        return self.completed and not self.failed_codes

    @property
    def blocked_reason(self) -> str | None:
        if self.budget_exceeded:
            return self.budget_reason or "request_budget_exceeded"
        if self.failed_codes:
            return "code_request_failed"
        if self.unattempted_codes:
            return "code_request_incomplete"
        return None

    def to_details(self, *, max_failure_samples: int = 20) -> dict[str, Any]:
        if max_failure_samples < 0:
            raise ValueError("max_failure_samples must not be negative.")
        return {
            "ready": self.ready,
            "completed": self.completed,
            "blocked_reason": self.blocked_reason,
            "successful_code_count": len(self.successful_codes),
            "multi_page_code_count": sum(
                page_count > 1 for page_count in self.page_counts.values()
            ),
            "empty_code_count": len(self.empty_codes),
            "empty_codes": list(self.empty_codes),
            "failed_code_count": len(self.failed_codes),
            "failed_codes": [
                failure.to_details() for failure in self.failed_codes[:max_failure_samples]
            ],
            "failed_code_list_truncated": len(self.failed_codes) > max_failure_samples,
            "unattempted_code_count": len(self.unattempted_codes),
            "unattempted_codes": list(self.unattempted_codes[:max_failure_samples]),
            "unattempted_code_list_truncated": len(self.unattempted_codes) > max_failure_samples,
            "request_count": self.request_count,
            "retry_count": self.retry_count,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "budget_exceeded": self.budget_exceeded,
            "budget_reason": self.budget_reason,
        }


@dataclass(frozen=True, slots=True)
class BoundedPageRequestResult(Generic[TushareResponse]):
    """In-memory outcome for one bounded, offset-paginated request."""

    rows: tuple[dict[str, Any], ...]
    page_count: int
    page_offsets: tuple[int, ...]
    failed_pages: tuple[TushareCodeFailure, ...]
    request_count: int
    retry_count: int
    elapsed_ms: float
    budget_exceeded: bool
    budget_reason: str | None

    @property
    def completed(self) -> bool:
        return not self.budget_exceeded and not self.failed_pages

    @property
    def ready(self) -> bool:
        return self.completed

    @property
    def blocked_reason(self) -> str | None:
        if self.budget_exceeded:
            return self.budget_reason or "request_budget_exceeded"
        if self.failed_pages:
            return "page_request_failed"
        return None

    def to_details(self, *, max_failure_samples: int = 20) -> dict[str, Any]:
        if max_failure_samples < 0:
            raise ValueError("max_failure_samples must not be negative.")
        return {
            "ready": self.ready,
            "completed": self.completed,
            "blocked_reason": self.blocked_reason,
            "page_count": self.page_count,
            "page_offsets": list(self.page_offsets),
            "failed_page_count": len(self.failed_pages),
            "failed_pages": [
                failure.to_details() for failure in self.failed_pages[:max_failure_samples]
            ],
            "failed_page_list_truncated": len(self.failed_pages) > max_failure_samples,
            "request_count": self.request_count,
            "retry_count": self.retry_count,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "budget_exceeded": self.budget_exceeded,
            "budget_reason": self.budget_reason,
        }


def classify_tushare_error(error: BaseException) -> tuple[str, bool]:
    """Classify source errors without retrying deterministic contract failures."""

    message = f"{type(error).__name__}: {error}".lower()
    rate_limit_markers = (
        "频率超限",
        "请求频率",
        "rate limit",
        "too many requests",
        "500次/分钟",
        "429",
    )
    transient_markers = (
        "timeout",
        "timed out",
        "connection reset",
        "connection aborted",
        "temporarily unavailable",
        "service unavailable",
        "bad gateway",
        "gateway timeout",
        "502",
        "503",
        "504",
    )
    if any(marker in message for marker in rate_limit_markers):
        return TUSHARE_FAILURE_RATE_LIMIT, True
    if isinstance(error, (ConnectionError, TimeoutError, OSError)) or any(
        marker in message for marker in transient_markers
    ):
        return TUSHARE_FAILURE_TRANSIENT, True
    return TUSHARE_FAILURE_NON_RETRYABLE, False


class _RequestRateLimiter:
    def __init__(self, minimum_interval_seconds: float, clock: Callable[[], float]) -> None:
        self._minimum_interval_seconds = minimum_interval_seconds
        self._clock = clock
        self._last_request_started_at: float | None = None

    def wait_seconds(self) -> float:
        if self._last_request_started_at is None:
            return 0.0
        elapsed = self._clock() - self._last_request_started_at
        return max(self._minimum_interval_seconds - elapsed, 0.0)

    def mark_request_started(self) -> None:
        self._last_request_started_at = self._clock()


@dataclass(frozen=True, slots=True)
class _RequestOutcome:
    rows: list[dict[str, Any]] | None
    failure: TushareCodeFailure | None
    budget_exceeded: bool
    budget_reason: str | None


class _BoundedRequestRunner:
    def __init__(
        self,
        *,
        policy: TushareRequestPolicy,
        clock: Callable[[], float],
        sleep_fn: Callable[[float], None],
    ) -> None:
        self.policy = policy
        self.clock = clock
        self.sleep_fn = sleep_fn
        self.started_at = clock()
        self.limiter = _RequestRateLimiter(policy.minimum_interval_seconds, clock)
        self.request_count = 0
        self.retry_count = 0

    def elapsed_seconds(self) -> float:
        return self.clock() - self.started_at

    def execute(
        self,
        *,
        code: str,
        request: Callable[[], Sequence[Mapping[str, Any]]],
    ) -> _RequestOutcome:
        for attempt_index in range(self.policy.max_retries + 1):
            if self.request_count >= self.policy.max_requests:
                return _RequestOutcome(
                    rows=None,
                    failure=None,
                    budget_exceeded=True,
                    budget_reason="max_requests_exceeded",
                )

            remaining_seconds = self.policy.max_elapsed_seconds - self.elapsed_seconds()
            if remaining_seconds <= 0:
                return _RequestOutcome(
                    rows=None,
                    failure=None,
                    budget_exceeded=True,
                    budget_reason="max_elapsed_seconds_exceeded",
                )

            wait_seconds = self.limiter.wait_seconds()
            if wait_seconds > remaining_seconds:
                return _RequestOutcome(
                    rows=None,
                    failure=None,
                    budget_exceeded=True,
                    budget_reason="rate_limit_wait_exceeds_time_budget",
                )
            if wait_seconds:
                self.sleep_fn(wait_seconds)
            self.limiter.mark_request_started()
            self.request_count += 1

            try:
                response_rows = [dict(row) for row in request()]
            except Exception as error:  # noqa: BLE001 - classify source failure below.
                category, retryable = classify_tushare_error(error)
                if retryable and attempt_index < self.policy.max_retries:
                    self.retry_count += 1
                    backoff_seconds = self.policy.backoff_seconds(attempt_index)
                    remaining_seconds = self.policy.max_elapsed_seconds - self.elapsed_seconds()
                    if backoff_seconds > remaining_seconds:
                        return _RequestOutcome(
                            rows=None,
                            failure=TushareCodeFailure(
                                code=code,
                                category=TUSHARE_FAILURE_RETRY_BUDGET,
                                message=(
                                    f"{category}: retry backoff {backoff_seconds:.3f}s "
                                    "would exceed the partition time budget."
                                ),
                                attempts=attempt_index + 1,
                                retryable=True,
                            ),
                            budget_exceeded=True,
                            budget_reason="retry_backoff_exceeds_time_budget",
                        )
                    self.sleep_fn(backoff_seconds)
                    continue

                return _RequestOutcome(
                    rows=None,
                    failure=TushareCodeFailure(
                        code=code,
                        category=category,
                        message=str(error),
                        attempts=attempt_index + 1,
                        retryable=retryable,
                    ),
                    budget_exceeded=False,
                    budget_reason=None,
                )

            return _RequestOutcome(
                rows=response_rows,
                failure=None,
                budget_exceeded=False,
                budget_reason=None,
            )

        raise AssertionError("bounded request runner exhausted without an outcome")


def execute_bounded_code_requests(
    *,
    codes: Sequence[str],
    request: Callable[[str], TushareResponse],
    extract_rows: Callable[[TushareResponse], Sequence[Mapping[str, Any]]],
    policy: TushareRequestPolicy,
    clock: Callable[[], float] = perf_counter,
    sleep_fn: Callable[[float], None] = sleep,
) -> BoundedCodeRequestResult[TushareResponse]:
    """Execute one request per code with rate, retry, count, and time bounds.

    A successful empty response is recorded as an empty source result. Any
    exhausted code failure or budget stop makes the full batch not ready; a
    caller must not write a partition from a result whose ``ready`` is false.
    """

    normalized_codes = tuple(str(code).strip().upper() for code in codes)
    if any(not code for code in normalized_codes):
        raise ValueError("code request scope must contain only non-empty codes.")
    if len(set(normalized_codes)) != len(normalized_codes):
        raise ValueError("code request scope must not contain duplicate codes.")

    if len(normalized_codes) > policy.max_requests:
        return BoundedCodeRequestResult(
            rows_by_code={},
            page_counts={},
            successful_codes=(),
            empty_codes=(),
            failed_codes=(),
            unattempted_codes=normalized_codes,
            request_count=0,
            retry_count=0,
            elapsed_ms=0.0,
            budget_exceeded=True,
            budget_reason="code_scope_exceeds_max_requests",
        )

    runner = _BoundedRequestRunner(policy=policy, clock=clock, sleep_fn=sleep_fn)
    rows_by_code: dict[str, list[dict[str, Any]]] = {}
    page_counts: dict[str, int] = {}
    successful_codes: list[str] = []
    empty_codes: list[str] = []
    failed_codes: list[TushareCodeFailure] = []
    unattempted_codes: tuple[str, ...] = ()
    budget_exceeded = False
    budget_reason: str | None = None
    for code_index, code in enumerate(normalized_codes):
        outcome = runner.execute(
            code=code,
            request=lambda code=code: extract_rows(request(code)),
        )
        if outcome.budget_exceeded:
            if outcome.failure is not None:
                failed_codes.append(outcome.failure)
            budget_exceeded = True
            budget_reason = outcome.budget_reason
            unattempted_codes = normalized_codes[
                code_index if outcome.failure is None else code_index + 1 :
            ]
            break
        if outcome.failure is not None:
            failed_codes.append(outcome.failure)
            continue
        page_counts[code] = 1
        if outcome.rows:
            rows_by_code[code] = outcome.rows
            successful_codes.append(code)
        else:
            empty_codes.append(code)

    return BoundedCodeRequestResult(
        rows_by_code=rows_by_code,
        page_counts=page_counts,
        successful_codes=tuple(successful_codes),
        empty_codes=tuple(empty_codes),
        failed_codes=tuple(failed_codes),
        unattempted_codes=unattempted_codes,
        request_count=runner.request_count,
        retry_count=runner.retry_count,
        elapsed_ms=runner.elapsed_seconds() * 1000,
        budget_exceeded=budget_exceeded,
        budget_reason=budget_reason,
    )


def execute_bounded_code_pages(
    *,
    codes: Sequence[str],
    request_page: Callable[[str, int], TushareResponse],
    extract_rows: Callable[[TushareResponse], Sequence[Mapping[str, Any]]],
    page_size: int,
    policy: TushareRequestPolicy,
    row_key: Callable[[Mapping[str, Any]], Hashable] | None = None,
    clock: Callable[[], float] = perf_counter,
    sleep_fn: Callable[[float], None] = sleep,
) -> BoundedCodeRequestResult[TushareResponse]:
    """Execute paginated code requests under the same whole-day safety bounds."""

    if page_size <= 0:
        raise ValueError("page_size must be positive.")
    normalized_codes = tuple(str(code).strip().upper() for code in codes)
    if any(not code for code in normalized_codes):
        raise ValueError("code request scope must contain only non-empty codes.")
    if len(set(normalized_codes)) != len(normalized_codes):
        raise ValueError("code request scope must not contain duplicate codes.")

    if len(normalized_codes) > policy.max_requests:
        return BoundedCodeRequestResult(
            rows_by_code={},
            page_counts={},
            successful_codes=(),
            empty_codes=(),
            failed_codes=(),
            unattempted_codes=normalized_codes,
            request_count=0,
            retry_count=0,
            elapsed_ms=0.0,
            budget_exceeded=True,
            budget_reason="code_scope_exceeds_max_requests",
        )

    runner = _BoundedRequestRunner(policy=policy, clock=clock, sleep_fn=sleep_fn)
    rows_by_code: dict[str, list[dict[str, Any]]] = {}
    page_counts: dict[str, int] = {}
    successful_codes: list[str] = []
    empty_codes: list[str] = []
    failed_codes: list[TushareCodeFailure] = []
    unattempted_codes: tuple[str, ...] = ()
    budget_exceeded = False
    budget_reason: str | None = None

    for code_index, code in enumerate(normalized_codes):
        offset = 0
        code_rows: list[dict[str, Any]] = []
        seen_keys: set[Hashable] = set()
        code_page_count = 0
        while True:
            outcome = runner.execute(
                code=code,
                request=lambda code=code, offset=offset: extract_rows(
                    request_page(code, offset)
                ),
            )
            if outcome.budget_exceeded:
                if outcome.failure is not None:
                    failed_codes.append(outcome.failure)
                budget_exceeded = True
                budget_reason = outcome.budget_reason
                unattempted_codes = normalized_codes[
                    code_index if outcome.failure is None else code_index + 1 :
                ]
                break
            if outcome.failure is not None:
                failed_codes.append(outcome.failure)
                break

            page_rows = outcome.rows or []
            if row_key is not None:
                duplicate_rows = 0
                for row in page_rows:
                    key = row_key(row)
                    if key in seen_keys:
                        duplicate_rows += 1
                    else:
                        seen_keys.add(key)
                if duplicate_rows:
                    failed_codes.append(
                        TushareCodeFailure(
                            code=code,
                            category=TUSHARE_FAILURE_NON_RETRYABLE,
                            message=(
                                f"source returned {duplicate_rows} duplicate row(s) "
                                "across pages for the same code."
                            ),
                            attempts=1,
                            retryable=False,
                        )
                    )
                    break
            code_rows.extend(page_rows)
            code_page_count += 1
            if len(page_rows) < page_size:
                page_counts[code] = code_page_count
                if code_rows:
                    rows_by_code[code] = code_rows
                    successful_codes.append(code)
                else:
                    empty_codes.append(code)
                break
            offset += page_size

        if budget_exceeded:
            break

    return BoundedCodeRequestResult(
        rows_by_code=rows_by_code,
        page_counts=page_counts,
        successful_codes=tuple(successful_codes),
        empty_codes=tuple(empty_codes),
        failed_codes=tuple(failed_codes),
        unattempted_codes=unattempted_codes,
        request_count=runner.request_count,
        retry_count=runner.retry_count,
        elapsed_ms=runner.elapsed_seconds() * 1000,
        budget_exceeded=budget_exceeded,
        budget_reason=budget_reason,
    )


def execute_bounded_pages(
    *,
    request_page: Callable[[int], TushareResponse],
    extract_rows: Callable[[TushareResponse], Sequence[Mapping[str, Any]]],
    page_size: int,
    policy: TushareRequestPolicy,
    scope: str,
    row_key: Callable[[Mapping[str, Any]], Hashable] | None = None,
    clock: Callable[[], float] = perf_counter,
    sleep_fn: Callable[[float], None] = sleep,
) -> BoundedPageRequestResult[TushareResponse]:
    """Execute one offset-paginated request with bounded retry and dedupe rules.

    A short or empty page is the only successful termination condition. Full
    pages advance by ``page_size``. If ``row_key`` is supplied, duplicate keys
    across pages fail the whole request before any caller can write a target
    partition.
    """

    if page_size <= 0:
        raise ValueError("page_size must be positive.")
    if not str(scope).strip():
        raise ValueError("scope must be non-empty.")

    runner = _BoundedRequestRunner(policy=policy, clock=clock, sleep_fn=sleep_fn)
    rows: list[dict[str, Any]] = []
    page_offsets: list[int] = []
    failed_pages: list[TushareCodeFailure] = []
    seen_keys: set[Hashable] = set()
    offset = 0
    while True:
        if page_offsets and offset <= page_offsets[-1]:
            failed_pages.append(
                TushareCodeFailure(
                    code=str(scope),
                    category=TUSHARE_FAILURE_NON_RETRYABLE,
                    message="pagination offset did not increase.",
                    attempts=1,
                    retryable=False,
                )
            )
            break
        page_offsets.append(offset)
        outcome = runner.execute(
            code=f"{scope}@offset={offset}",
            request=lambda offset=offset: extract_rows(request_page(offset)),
        )
        if outcome.budget_exceeded:
            if outcome.failure is not None:
                failed_pages.append(outcome.failure)
            return BoundedPageRequestResult(
                rows=tuple(rows),
                page_count=len(page_offsets),
                page_offsets=tuple(page_offsets),
                failed_pages=tuple(failed_pages),
                request_count=runner.request_count,
                retry_count=runner.retry_count,
                elapsed_ms=runner.elapsed_seconds() * 1000,
                budget_exceeded=True,
                budget_reason=outcome.budget_reason,
            )
        if outcome.failure is not None:
            failed_pages.append(outcome.failure)
            break

        page_rows = outcome.rows or []
        duplicate_rows = 0
        if row_key is not None:
            for row in page_rows:
                key = row_key(row)
                if key in seen_keys:
                    duplicate_rows += 1
                else:
                    seen_keys.add(key)
        if duplicate_rows:
            failed_pages.append(
                TushareCodeFailure(
                    code=str(scope),
                    category=TUSHARE_FAILURE_NON_RETRYABLE,
                    message=(
                        f"source returned {duplicate_rows} duplicate row(s) "
                        "across pages."
                    ),
                    attempts=1,
                    retryable=False,
                )
            )
            break

        rows.extend(page_rows)
        if len(page_rows) < page_size:
            break
        offset += page_size

    return BoundedPageRequestResult(
        rows=tuple(rows),
        page_count=len(page_offsets),
        page_offsets=tuple(page_offsets),
        failed_pages=tuple(failed_pages),
        request_count=runner.request_count,
        retry_count=runner.retry_count,
        elapsed_ms=runner.elapsed_seconds() * 1000,
        budget_exceeded=False,
        budget_reason=None,
    )
