"""Atomic validation page evidence. Never creates accepted ledger facts."""
from dataclasses import asdict
from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.biz.models.wealth.trading_assistant.recovery import ValidationCandidate, ValidationCheckpoint
from .execution_policy import Deadline
from .validation import CashValidation, QuantityValidation
from .validation_pages import ValidationPage
from .write_protocol import AttemptState, WriteProtocol, WriteProtocolConflict


def encode_state(state: CashValidation | QuantityValidation) -> dict:
    return {name: (value.isoformat() if isinstance(value,date) else str(value) if type(value) is int else value)
            for name,value in asdict(state).items()}


def decode_state(stage: str, data: dict):
    cls = CashValidation if stage == "CASH" else QuantityValidation if stage == "QUANTITY" else None
    if cls is None or set(data) != set(cls.__dataclass_fields__):
        raise ValueError("Invalid checkpoint accumulator shape")
    fields = {}
    for name,value in data.items():
        if name in ("initialized_on", "current_day"):
            fields[name] = None if value is None else date.fromisoformat(value)
        else:
            if not isinstance(value,str) or str(int(value)) != value:
                raise ValueError("Invalid checkpoint integer")
            fields[name] = int(value)
    return cls(**fields)


def encode_cursor(after: tuple[date, UUID] | None):
    return {"date":after[0].isoformat(),"ledgerId":str(after[1])} if after is not None else None


class ValidationCheckpoints:
    def __init__(self, protocol: WriteProtocol):
        self.protocol = protocol

    def store(self, session: Session, *, owner_id: int, candidate_id: UUID, run_id: UUID,
              stock: str | None, basis_digest: bytes, before: tuple[date, UUID] | None,
              page: ValidationPage, now: datetime, deadline: Deadline,
              execution: AttemptState | None = None, executor_id: str | None = None) -> ValidationCheckpoint:
        if len(basis_digest) != 32 or isinstance(page.state,QuantityValidation) != (stock is not None):
            raise ValueError("Invalid checkpoint basis or stage")
        if execution is not None:
            if execution.owner_id != owner_id:
                raise WriteProtocolConflict("TA_RECOVERY_STATE_CHANGED")
            self.protocol.lock_execution(session,execution,now=now,executor_id=executor_id,deadline=deadline)
        candidate = session.scalar(select(ValidationCandidate).where(
            ValidationCandidate.candidate_id == candidate_id,ValidationCandidate.owner_id == owner_id))
        if candidate is None:
            raise WriteProtocolConflict("TA_OBJECT_NOT_FOUND")
        if candidate.purpose == "SAVE":
            if execution is None or candidate.request_id != execution.request_id:
                raise WriteProtocolConflict("TA_RECOVERY_STATE_CHANGED")
        elif execution is not None:
            raise ValueError("A preview cannot borrow save execution rights")
        stage = "CASH" if stock is None else "QUANTITY"
        page_key = "START" if before is None else f"{before[0].isoformat()}:{before[1]}"
        cursor = {"after":encode_cursor(page.after)}
        accumulator = encode_state(page.state)
        completed = {"complete":page.complete,"rows":page.rows,"bytes":page.bytes_read,
                     "calendarExchange":"SSE" if stock is not None else None,
                     "calendarFacts":[list(f) for f in page.calendar_facts]}
        existing = session.scalar(select(ValidationCheckpoint).where(
            ValidationCheckpoint.candidate_id == candidate_id,
            ValidationCheckpoint.validation_run_id == run_id,
            ValidationCheckpoint.stage == stage,ValidationCheckpoint.stock_key == (stock or ""),
            ValidationCheckpoint.page_key == page_key))
        if existing is not None:
            if (existing.basis_digest != basis_digest or existing.cursor != cursor
                    or existing.accumulator != accumulator or existing.completed_range != completed
                    or existing.checked_row_count != page.state.checked_rows):
                raise ValueError("Checkpoint replay changed its basis or result")
            return existing
        # One validation run cannot be resumed with a different basis under a new page key.
        prior = session.scalar(select(ValidationCheckpoint.basis_digest).where(
            ValidationCheckpoint.candidate_id == candidate_id,
            ValidationCheckpoint.validation_run_id == run_id).limit(1))
        if prior is not None and prior != basis_digest:
            raise ValueError("Changed validation basis requires a new run")
        if before is None:
            previous_count = 0
        else:
            predecessor = session.scalar(select(ValidationCheckpoint).where(
                ValidationCheckpoint.candidate_id == candidate_id,
                ValidationCheckpoint.validation_run_id == run_id,
                ValidationCheckpoint.stage == stage,ValidationCheckpoint.stock_key == (stock or ""),
                ValidationCheckpoint.cursor == {"after":encode_cursor(before)}))
            if predecessor is None or predecessor.completed_range["complete"]:
                raise ValueError("Checkpoint cursor has no incomplete predecessor")
            previous_count = predecessor.checked_row_count
        if page.state.checked_rows != previous_count + page.rows:
            raise ValueError("Checkpoint cursor and accumulated row count diverge")
        if page.rows and (page.after is None or (before is not None and page.after <= before)):
            raise ValueError("Nonempty checkpoint must advance its cursor")
        checkpoint = ValidationCheckpoint(checkpoint_id=uuid4(),candidate_id=candidate_id,
            validation_run_id=run_id,attempt_id=execution.attempt_id if execution else None,
            stage=stage,stock_key=stock or "",page_key=page_key,basis_digest=basis_digest,
            cursor=cursor,accumulator=accumulator,completed_range=completed,
            checked_row_count=page.state.checked_rows,updated_at=now)
        session.add(checkpoint)
        session.flush()
        deadline.remaining_ms()
        return checkpoint

    def restore(self, checkpoint: ValidationCheckpoint, *, basis_digest: bytes) -> ValidationPage:
        if checkpoint.basis_digest != basis_digest:
            raise ValueError("Cannot reuse a checkpoint from different facts")
        state = decode_state(checkpoint.stage,checkpoint.accumulator)
        if state.checked_rows != checkpoint.checked_row_count:
            raise ValueError("Checkpoint count and accumulator disagree")
        raw = checkpoint.cursor["after"]
        after = (date.fromisoformat(raw["date"]),UUID(raw["ledgerId"])) if raw else None
        result = checkpoint.completed_range
        if type(result["complete"]) is not bool:
            raise ValueError("Invalid completion evidence")
        return ValidationPage(state,after,result["complete"],result["rows"],result["bytes"],
                              tuple(tuple(f) for f in result["calendarFacts"]))
