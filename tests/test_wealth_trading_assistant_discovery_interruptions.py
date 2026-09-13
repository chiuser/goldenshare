"""One bad account is paused, real SQL timeout retries retain their count."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import event, select, text
from sqlalchemy.orm import Session, sessionmaker

from tests.test_wealth_trading_assistant_published_source_check import (
    database, migrated, publication_db, interruptions_db, cutoff_db, published)
from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.calculation import Recalculation
from src.biz.models.wealth.trading_assistant.calculation_inputs import CutoffPreparation
from src.biz.services.wealth.market.trading_assistant.cutoff_discovery import CutoffDiscovery
from src.biz.services.wealth.market.trading_assistant.history_source_preparation import HistorySourcePreparation
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1


def test_failed_account_is_isolated_and_transient_retries_survive_new_instances(published, monkeypatch):
    engine, _, _ = published
    policy = TradingAssistantExecutionPolicyV1()
    with Session(engine) as session:
        ids = session.scalars(select(Account.account_id).order_by(Account.account_id)).all()
        bad, good = ids
        version = session.get(Account, bad).calculation_target_version
    original = HistorySourcePreparation.step
    calls = {bad: 0, good: 0}
    timeout_good = False
    observed = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)
    def clock(conn, cursor, statement, parameters, context, executemany):
        return statement.replace("clock_timestamp()", f"TIMESTAMPTZ '{observed.isoformat()}'"), parameters
    def probe(self, session, *, account_id, deadline):
        calls[account_id] += 1
        if account_id == bad:
            raise ValueError("private account/source detail")
        if timeout_good:
            # Real PostgreSQL statement_timeout, not a fabricated error code.
            session.execute(text("SELECT pg_sleep(2)"))
        return original(self, session, account_id=account_id, deadline=deadline)
    monkeypatch.setattr(HistorySourcePreparation, "step", probe)
    event.listen(engine, "before_cursor_execute", clock, retval=True)
    def run():
        return CutoffDiscovery(policy, sessionmaker(engine), purpose="HISTORY").run_once()
    try:
        stages = []
        for _ in range(40):
            stages.append(run())
            if stages[-1] == "IDLE":
                break
        assert stages.count("FAILED") == 1 and stages.count("VERIFIED") == 1
        assert calls[bad] == 1
        with Session(engine) as session:
            failed = session.get(CutoffPreparation, (bad, version, "HISTORY"))
            assert failed.state == "FAILED" and failed.next_attempt_at is None
            assert "private" not in failed.reason
            assert session.get(Recalculation, bad) is None
            assert session.get(Account, bad).calculation_target_version == version
        observed += timedelta(hours=1)
        timeout_good = True
        for attempt, delay in enumerate((*policy.transient_retry_delays_seconds, None), 1):
            for _ in range(3):
                stage = run()
                if stage in ("TRANSIENT", "FAILED"):
                    break
            assert stage == ("FAILED" if delay is None else "TRANSIENT")
            with Session(engine) as session:
                failed = session.get(CutoffPreparation, (good, version, "HISTORY"))
                assert failed.transient_failure_count == attempt
                assert failed.next_attempt_at == (observed+timedelta(seconds=delay) if delay else None)
                assert "pg_sleep" not in failed.reason and "点击" not in failed.reason
            if delay:
                # The global account cursor must not turn a 2/4/... second
                # account retry into an unconditional additional 60-second wait.
                observed += timedelta(seconds=delay)
        assert calls[bad] == 1
        # A maintenance repair may re-arm only this isolated failed source
        # check; it does not re-submit facts or create a new account target.
        timeout_good = False
        observed += timedelta(hours=1)
        with Session(engine) as session, session.begin():
            failed = session.get(CutoffPreparation, (good, version, "HISTORY"))
            failed.next_attempt_at = observed
        for _ in range(40):
            if run() == "VERIFIED":
                break
        else:
            raise AssertionError("Repaired historical source check did not resume")
        with Session(engine) as session:
            restored = session.get(CutoffPreparation, (good, version, "HISTORY"))
            assert restored.state == "READY" and restored.transient_failure_count == 0
            assert session.get(Account, good).calculation_target_version == version
            assert session.get(Recalculation, good) is None
    finally:
        event.remove(engine, "before_cursor_execute", clock)
