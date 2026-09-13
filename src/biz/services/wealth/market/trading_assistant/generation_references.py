"""Resolve new or proven-reused days without recursive generation traversal."""
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select

from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, DayResult
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from src.biz.models.wealth.trading_assistant.publication import PublicationDay, PublicationReceipt
from .calculation_inputs import CalculationInputMismatch
from .prefix_proof import verify_prefix_price_proof


class GenerationReferences:
    def __init__(self, inputs):
        self.inputs = inputs

    def result(self, session, *, account_id, generation_id, business_date):
        rows = session.scalars(select(DayResult).where(DayResult.account_id == account_id,
            DayResult.origin_generation_id == generation_id, DayResult.trade_date == business_date).limit(2)).all()
        marker = session.get(CalculationBatch, (account_id, generation_id, business_date, "PREFIX_DATE", "", "1"))
        if marker is None:
            if len(rows) > 1:
                raise CalculationInputMismatch("Multiple results for one generation date")
            return rows[0] if rows else None
        if rows or marker.input_digest != sha256(self.inputs._encoded(marker.accumulator)).digest():
            raise CalculationInputMismatch("Reused date has conflicting or damaged evidence")
        current = session.get(CalculationGeneration, generation_id)
        source_id = UUID(marker.accumulator["sourceGenerationId"])
        source = session.get(CalculationGeneration, source_id)
        receipt = session.get(PublicationReceipt, (account_id, source_id))
        if (current is None or source is None or current.account_id != account_id or source.account_id != account_id
                or source.stage != "PUBLISHED" or source.target_version >= current.target_version
                or (source.fact_version, source.initialization_id, source.rule_version, source.from_date) != (
                    current.fact_version, current.initialization_id, current.rule_version, current.from_date)
                or receipt is None or receipt.target_version != source.target_version
                or not source.from_date <= business_date <= source.through_date
                or marker.accumulator["sourceManifestDigest"] != receipt.manifest_digest.hex()):
            raise CalculationInputMismatch("Reused date has incompatible source publication")
        direct = session.get(PublicationDay, (account_id, source_id, business_date))
        day = session.get(DayResult, direct.day_result_id) if direct else None
        if ((str(day.day_result_id) if day else None) != marker.accumulator["dayId"]
                or (day.input_digest.hex() if day else None) != marker.accumulator["dayDigest"]
                or (day is not None and (day.account_id != account_id or day.trade_date != business_date or day.status != "SEALED"))):
            raise CalculationInputMismatch("Reused direct result differs from the verified source")
        for stage in ("DATE_INPUT", "CASH_BALANCE", "DATE_COMPLETE"):
            old = session.get(CalculationBatch, (account_id, source_id, business_date, stage, "", "1"))
            copied = session.get(CalculationBatch, (account_id, generation_id, business_date, stage, "", "1"))
            if (old is None or copied is None or (copied.input_digest, copied.accumulator, copied.cursor, copied.row_count) != (
                    old.input_digest, old.accumulator, old.cursor, old.row_count)
                    or old.input_digest != sha256(self.inputs._encoded(old.accumulator)).digest()):
                raise CalculationInputMismatch("Reused cash/date continuation differs from saved facts")
        end = session.get(CalculationBatch, (account_id, generation_id, business_date, "PREFIX_PRICE_CHECK", "", "END"))
        if (end is None or end.input_digest != sha256(self.inputs._encoded(end.accumulator)).digest()
                or marker.accumulator["priceProofDigest"] != end.input_digest.hex()
                or not end.accumulator["done"] or end.accumulator["sourceGenerationId"] != str(source_id)):
            raise CalculationInputMismatch("Reused date has no complete price proof")
        verify_prefix_price_proof(session, account_id=account_id, generation_id=generation_id,
            business_date=business_date, source_generation_id=source_id, manifest_digest=receipt.manifest_digest,
            price_origin_id=day.origin_generation_id if day else None)
        return day

    def previous(self, session, *, account_id, generation_id, before):
        completed = session.scalar(select(CalculationBatch).where(CalculationBatch.account_id == account_id,
            CalculationBatch.generation_id == generation_id, CalculationBatch.stage == "DATE_COMPLETE",
            CalculationBatch.stock_key == "", CalculationBatch.row_count == 1, CalculationBatch.trade_date < before)
            .order_by(CalculationBatch.trade_date.desc()).limit(1))
        if completed is None:
            return None
        day = self.result(session, account_id=account_id, generation_id=generation_id, business_date=completed.trade_date)
        if day is None or day.status != "SEALED":
            raise CalculationInputMismatch("Previous completed date lacks a sealed direct result")
        return day.day_result_id
