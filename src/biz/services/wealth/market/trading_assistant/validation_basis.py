"""Recheck retained source evidence without loading checkpoint history into RAM."""
from datetime import date
from sqlalchemy import select, text

from src.biz.models.wealth.trading_assistant.recovery import ValidationCandidate
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
    changed = session.scalar(text("""
        SELECT EXISTS (
            SELECT 1 FROM app.wealth_ta_validation_checkpoint p
            CROSS JOIN LATERAL jsonb_array_elements(p.completed_range->'calendarFacts') f
            LEFT JOIN core_serving.trade_calendar c
              ON c.exchange = 'SSE' AND c.trade_date = (f->>0)::date
            WHERE p.candidate_id = :candidate AND p.validation_run_id = :run
              AND (c.trade_date IS NULL OR c.is_open IS DISTINCT FROM (f->>1)::boolean
                   OR c.pretrade_date IS DISTINCT FROM (f->>2)::date)
        )
    """), {"candidate":job.candidate_id, "run":job.run_id})
    deadline.remaining_ms()
    if changed:
        raise ValidationBasisChanged()
