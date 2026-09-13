"""Reuse only direct, compatible and fully verified historical references."""
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_published_source_check import (
    database, migrated, publication_db, interruptions_db, cutoff_db, published, DAY)
from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, DayResult
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from src.biz.services.wealth.market.trading_assistant.calculation_inputs import CalculationInputs, CalculationInputMismatch
from src.biz.services.wealth.market.trading_assistant.generation_references import GenerationReferences
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.recalculation_execution import RecalculationExecution


@pytest.mark.parametrize("case", ["valid", "missing_page", "damaged_end", "cash", "mixed_day", "bad_manifest", "incompatible_facts"])
def test_reused_prefix_cannot_hide_incompatible_or_missing_evidence(published, case):
    engine, account_id, generation_id = published
    inputs = CalculationInputs(RecalculationExecution(TradingAssistantExecutionPolicyV1()))
    refs = GenerationReferences(inputs)
    with Session(engine) as session:
        marker = session.get(CalculationBatch, (account_id, generation_id, DAY, "PREFIX_DATE", "", "1"))
        assert marker is not None
        if case == "missing_page":
            session.execute(delete(CalculationBatch).where(CalculationBatch.account_id == account_id,
                CalculationBatch.generation_id == generation_id, CalculationBatch.trade_date == DAY,
                CalculationBatch.stage == "PREFIX_PRICE_CHECK", CalculationBatch.page_key == "601011.SH"))
        elif case == "damaged_end":
            session.get(CalculationBatch, (account_id, generation_id, DAY, "PREFIX_PRICE_CHECK", "", "END")).input_digest = b"x"*32
        elif case == "cash":
            cash = session.get(CalculationBatch, (account_id, generation_id, DAY, "CASH_BALANCE", "", "1"))
            cash.accumulator = dict(cash.accumulator, closingCash="12300")
            cash.input_digest = sha256(inputs._encoded(cash.accumulator)).digest()
        elif case == "mixed_day":
            session.add(DayResult(day_result_id=uuid4(), account_id=account_id, origin_generation_id=generation_id,
                trade_date=DAY, input_digest=b"x"*32, status="BUILDING"))
        elif case == "bad_manifest":
            marker.accumulator = dict(marker.accumulator, sourceManifestDigest="a"*64)
            marker.input_digest = sha256(inputs._encoded(marker.accumulator)).digest()
        elif case == "incompatible_facts":
            session.get(CalculationGeneration, generation_id).fact_version += 1
        session.flush()
        if case == "valid":
            day = refs.result(session, account_id=account_id, generation_id=generation_id, business_date=DAY)
            assert day.status == "SEALED" and day.origin_generation_id != generation_id
        else:
            with pytest.raises(CalculationInputMismatch):
                refs.result(session, account_id=account_id, generation_id=generation_id, business_date=DAY)
        session.rollback()
