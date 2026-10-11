"""Bounded failure facts; neither source messages nor sampled failures decide retries."""

from dataclasses import dataclass, replace

from orchestrator.defs.run_contracts.dc_board import (
    DC_BOARD_FAILURE_SAMPLE_LIMIT,
    DC_BOARD_RECOVERY_POLICY_VERSION,
)
from orchestrator.defs.tushare_request_policy import (
    TUSHARE_FAILURE_CONTRACT,
    TUSHARE_FAILURE_PERMISSION_OR_PARAMETER,
    TUSHARE_FAILURE_RATE_LIMIT,
    TUSHARE_FAILURE_RESPONSE_UNCLASSIFIED,
    TUSHARE_FAILURE_TRANSIENT,
)

_RETRY_REASONS = {
    TUSHARE_FAILURE_RATE_LIMIT: "source_rate_limit",
    TUSHARE_FAILURE_TRANSIENT: "source_transient",
    TUSHARE_FAILURE_RESPONSE_UNCLASSIFIED: "source_response_unclassified",
}


@dataclass(frozen=True)
class DcBoardFailureFacts:
    reason_code: str
    request_retryable: bool = False
    partition_retryable: bool = False
    failed_count: int | None = None
    unattempted_count: int | None = None
    request_count: int | None = None
    retry_count: int | None = None
    budget_exceeded: bool | None = None
    budget_reason: str | None = None
    failure_samples: tuple[str, ...] = ()

    def metadata(self) -> dict[str, object]:
        return {
            "failure_policy_version": DC_BOARD_RECOVERY_POLICY_VERSION,
            "reason_code": self.reason_code,
            "request_retryable": self.request_retryable,
            "partition_retryable": self.partition_retryable,
            "failed_count": self.failed_count,
            "unattempted_count": self.unattempted_count,
            "request_count": self.request_count,
            "retry_count": self.retry_count,
            "budget_exceeded": self.budget_exceeded,
            "budget_reason": self.budget_reason,
            "failure_samples": list(
                self.failure_samples[:DC_BOARD_FAILURE_SAMPLE_LIMIT]
            ),
        }

    def with_prior_requests(self, requests: int, retries: int) -> "DcBoardFailureFacts":
        return replace(
            self,
            request_count=None
            if self.request_count is None
            else self.request_count + requests,
            retry_count=None
            if self.retry_count is None
            else self.retry_count + retries,
        )


class DcBoardRequestFailure(ValueError):
    """Source execution failed with complete statistics retained in memory."""

    def __init__(self, facts: DcBoardFailureFacts):
        self.facts = facts
        super().__init__(facts.reason_code)


def request_failure_facts(result) -> DcBoardFailureFacts:
    failures = (
        result.failed_codes if hasattr(result, "failed_codes") else result.failed_pages
    )
    unattempted = (
        len(result.unattempted_codes) if hasattr(result, "unattempted_codes") else 0
    )
    all_retryable = bool(failures) and all(
        failure.retryable and failure.category in _RETRY_REASONS for failure in failures
    )
    if result.budget_exceeded or unattempted:
        reason = "request_or_resource_budget_exhausted"
    elif not all_retryable:
        categories = {failure.category for failure in failures}
        if TUSHARE_FAILURE_CONTRACT in categories:
            reason = "source_or_data_contract"
        elif TUSHARE_FAILURE_PERMISSION_OR_PARAMETER in categories:
            reason = "source_permission_or_parameter"
        else:
            reason = "unknown_or_infrastructure"
    else:
        reasons = {_RETRY_REASONS[failure.category] for failure in failures}
        # Prefer the least classified retry reason when transient categories mix.
        reason = next(reason for reason in ("source_response_unclassified", "source_rate_limit", "source_transient")
                      if reason in reasons)
    return DcBoardFailureFacts(
        reason_code=reason,
        request_retryable=all_retryable,
        partition_retryable=all_retryable
        and not result.budget_exceeded
        and not unattempted,
        failed_count=len(failures),
        unattempted_count=unattempted,
        request_count=result.request_count,
        retry_count=result.retry_count,
        budget_exceeded=result.budget_exceeded,
        budget_reason=result.budget_reason,
        failure_samples=tuple(
            failure.code for failure in failures[:DC_BOARD_FAILURE_SAMPLE_LIMIT]
        ),
    )
