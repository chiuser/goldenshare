"""Recheck retained source evidence without loading checkpoint history into RAM."""
from datetime import date
from sqlalchemy import select, text

from src.biz.models.wealth.trading_assistant.recovery import ValidationCandidate
from src.foundation.clients.reference_data import local_reference_data
from src.foundation.clients.reference_data_relations import bind_calendar_records
from .market_facts import apply_sql_budget, SecurityNotEligible


class ValidationBasisChanged(RuntimeError):
    """The existing request may revalidate once within its original deadline."""


def verify_source_basis(session, job, *, market, deadline, basis=None):
    apply_sql_budget(session, deadline, market.policy)
    if basis is None:
        basis = session.scalar(select(ValidationCandidate.basis).where(
            ValidationCandidate.candidate_id == job.candidate_id,
            ValidationCandidate.owner_id == job.owner_id,
            ValidationCandidate.account_id == job.change.account_id))
    if basis is None:
        raise ValueError("Missing retained validation basis")
    for initial in basis.get("initialDates", []):
        day = date.fromisoformat(initial["openedOn"])
        calendar = market.read_calendar(session, initial["exchange"], day, day, deadline)
        if calendar.source_version != initial["sourceVersion"]:
            raise ValidationBasisChanged()
    for security in basis["securities"]:
        try:
            current = market.resolve_security(session, security["ts_code"], deadline)
        except SecurityNotEligible as error:
            raise ValidationBasisChanged() from error
        if current.source_version != security["source_version"]:
            raise ValidationBasisChanged()
    apply_sql_budget(session, deadline, market.policy)
    # Existence check runs against the actual dates used by every saved page.
    # IS DISTINCT FROM handles a removed date or a changed nullable previous date.
    params = {"candidate": job.candidate_id, "run": job.run_id}
    reference = local_reference_data(session)
    calendar_source = "core_serving.trade_calendar c"
    if reference is not None:
        first, last = session.execute(text("""
            SELECT min((f->>0)::date), max((f->>0)::date)
            FROM app.wealth_ta_validation_checkpoint p
            CROSS JOIN LATERAL jsonb_array_elements(p.completed_range->'calendarFacts') f
            WHERE p.candidate_id = :candidate AND p.validation_run_id = :run
        """), params).one()
        calendar = reference.calendar.range_rows(
            exchange="SSE", start=first, end=last, timeout_seconds=deadline.remaining_ms() / 1000,
        ) if first is not None else ()
        calendar_source = ("jsonb_to_recordset(:dg_calendar_rows) c"
                           "(exchange text, trade_date date, is_open boolean, pretrade_date date)")
        apply_sql_budget(session, deadline, market.policy)
    statement = text(f"""
        SELECT EXISTS (
            SELECT 1 FROM app.wealth_ta_validation_checkpoint p
            CROSS JOIN LATERAL jsonb_array_elements(p.completed_range->'calendarFacts') f
            LEFT JOIN {calendar_source}
              ON c.exchange = 'SSE' AND c.trade_date = (f->>0)::date
            WHERE p.candidate_id = :candidate AND p.validation_run_id = :run
              AND (c.trade_date IS NULL OR c.is_open IS DISTINCT FROM (f->>1)::boolean
                   OR c.pretrade_date IS DISTINCT FROM (f->>2)::date)
        )
    """)
    if reference is not None:
        statement = bind_calendar_records(statement, calendar)
    changed = session.scalar(statement, params)
    deadline.remaining_ms()
    if changed:
        raise ValidationBasisChanged()
