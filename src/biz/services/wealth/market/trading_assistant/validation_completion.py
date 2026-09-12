"""Read-back proof of all required scans, never an authorization to publish."""
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.biz.models.wealth.trading_assistant.recovery import ValidationCandidate, ValidationCheckpoint
from .execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from .market_facts import apply_sql_budget
from .validation_checkpoints import ValidationCheckpoints
from .write_protocol import WriteProtocolConflict


@dataclass(frozen=True, slots=True)
class CompletedValidation:
    candidate_id: UUID
    run_id: UUID
    basis_digest: bytes
    # (stage, stock, final checkpoint, checked rows), includes CASH even for zero rows.
    scans: tuple[tuple[str, str, UUID, int], ...]


def read_completion(session: Session, *, owner_id: int, account_id: UUID, candidate_id: UUID,
                    run_id: UUID, basis_digest: bytes, affected_stocks: tuple[str, ...],
                    checkpoints: ValidationCheckpoints, policy: TradingAssistantExecutionPolicyV1,
                    deadline: Deadline) -> CompletedValidation:
    if len(basis_digest) != 32 or tuple(sorted(set(affected_stocks))) != affected_stocks:
        raise ValueError("Invalid completion basis or affected stock set")
    apply_sql_budget(session, deadline, policy)
    candidate = session.scalar(select(ValidationCandidate.candidate_id).where(
        ValidationCandidate.candidate_id == candidate_id, ValidationCandidate.owner_id == owner_id,
        ValidationCandidate.account_id == account_id))
    if candidate is None:
        raise WriteProtocolConflict("TA_OBJECT_NOT_FOUND")
    # One bounded query per required stage, not a full checkpoint-history load.
    scans = []
    for stage, stock in (("CASH", ""), *(("QUANTITY", stock) for stock in affected_stocks)):
        apply_sql_budget(session, deadline, policy)
        rows = session.scalars(select(ValidationCheckpoint).where(
            ValidationCheckpoint.candidate_id == candidate_id,
            ValidationCheckpoint.validation_run_id == run_id,
            ValidationCheckpoint.stage == stage, ValidationCheckpoint.stock_key == stock,
            ValidationCheckpoint.completed_range["complete"].as_boolean().is_(True)).limit(2)).all()
        if not rows:
            raise ValueError("Required validation scan is incomplete")
        if len(rows) != 1:
            raise ValueError("Multiple completion checkpoints for one scan")
        final = rows[0]
        page = checkpoints.restore(final, basis_digest=basis_digest)
        if not page.complete:
            raise ValueError("Incomplete validation checkpoint")
        scans.append((stage, stock, final.checkpoint_id, page.state.checked_rows))
    deadline.remaining_ms()
    return CompletedValidation(candidate_id, run_id, basis_digest, tuple(scans))
