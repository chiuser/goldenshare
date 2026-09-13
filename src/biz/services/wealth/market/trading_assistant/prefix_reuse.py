"""Prove one unchanged prefix page or adopt one directly referenced date."""
from copy import deepcopy
from hashlib import sha256

from sqlalchemy import func, select

from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, DayResult, Recalculation
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from src.biz.models.wealth.trading_assistant.publication import PublicationDay, PublicationReceipt
from .calculation_inputs import CalculationInputMismatch
from .published_source_check import PublishedSourceCheck, SourcePageCheck


class PrefixReuse:
    def __init__(self, steps):
        self.steps, self.inputs, self.execution = steps, steps.inputs, steps.execution

    def step(self, session, lease, *, generation, business_date, deadline):
        with self.execution.batch(session, lease, deadline=deadline) as account:
            stop_key = (lease.account_id, generation.generation_id, generation.from_date, "PREFIX_STOP", "", "1")
            if session.get(CalculationBatch, stop_key) is not None or account.published_generation_id is None:
                return None
            source = session.get(CalculationGeneration, account.published_generation_id)
            pending = session.get(Recalculation, lease.account_id)
            receipt = session.get(PublicationReceipt, (lease.account_id, account.published_generation_id))
            already_replayed = session.scalar(select(DayResult.day_result_id).where(
                DayResult.account_id == lease.account_id, DayResult.origin_generation_id == generation.generation_id,
                DayResult.trade_date < business_date).limit(1))
            eligible = (source is not None and source.account_id == lease.account_id and source.stage == "PUBLISHED"
                and source.target_version < generation.target_version and receipt is not None
                and receipt.target_version == source.target_version
                and (source.fact_version, source.initialization_id, source.rule_version, source.from_date) == (
                    generation.fact_version, generation.initialization_id, generation.rule_version, generation.from_date)
                and pending is not None and business_date < pending.affected_from_date
                and business_date <= source.through_date and already_replayed is None)
            now = session.scalar(select(func.clock_timestamp()))
            if not eligible:
                return self._stop(session, generation, now, "no_compatible_prefix")
            calendar = self.steps.calendar.read_date(session, lease, generation_id=generation.generation_id,
                business_date=business_date, deadline=deadline)
            old_calendar = self.steps.calendar._read_saved_date(session, lease.account_id, source.generation_id, business_date)
            if old_calendar != calendar:
                return self._stop(session, generation, now, "calendar_changed")
            old_complete = session.get(CalculationBatch,
                (lease.account_id, source.generation_id, business_date, "DATE_COMPLETE", "", "1"))
            if old_complete is None:
                raise CalculationInputMismatch("Published prefix lacks a complete date checkpoint")
            self.steps._verify_completed(session, lease, source, old_complete)
            direct = session.get(PublicationDay, (lease.account_id, source.generation_id, business_date))
            day = session.get(DayResult, direct.day_result_id) if direct else None
            if bool(day) != calendar["is_open"] or (day and (day.status != "SEALED" or day.account_id != lease.account_id)):
                raise CalculationInputMismatch("Published prefix has an invalid direct date")
            identity = (lease.account_id, generation.generation_id, business_date)
            end = session.get(CalculationBatch, (*identity, "PREFIX_PRICE_CHECK", "", "END"))
            if end is None:
                previous = session.scalar(select(CalculationBatch).where(CalculationBatch.account_id == lease.account_id,
                    CalculationBatch.generation_id == generation.generation_id, CalculationBatch.trade_date == business_date,
                    CalculationBatch.stage == "PREFIX_PRICE_CHECK", CalculationBatch.stock_key == "")
                    .order_by(CalculationBatch.page_key.desc()).limit(1))
                after = previous.accumulator["nextPage"] if previous else None
                if previous and (previous.input_digest != sha256(self.inputs._encoded(previous.accumulator)).digest()
                        or previous.accumulator["sourceGenerationId"] != str(source.generation_id)):
                    raise CalculationInputMismatch("Prefix page checkpoint changed")
                result = PublishedSourceCheck(self.execution)._price_page(session, account_id=lease.account_id,
                    source_id=day.origin_generation_id, business_date=business_date, after_page=after,
                    old=old_calendar, new=calendar, deadline=deadline) if day else SourcePageCheck(calendar, calendar, (), (), None, True)
                if result.changed:
                    return self._stop(session, generation, now, "price_changed")
                source_page = session.get(CalculationBatch, (lease.account_id, day.origin_generation_id, business_date,
                    "VALUATION_END" if result.done else "VALUATION", "", "1" if result.done else result.next_page)) if day else None
                values = {"sourceGenerationId": str(source.generation_id), "sourceManifestDigest": receipt.manifest_digest.hex(),
                    "afterPage": after, "nextPage": result.next_page, "done": result.done,
                    "sourcePageDigest": source_page.input_digest.hex() if source_page else None,
                    "previousProofDigest": previous.input_digest.hex() if previous else None}
                self._save(session, generation, business_date, "PREFIX_PRICE_CHECK", "END" if result.done else result.next_page,
                    values, now, row_count=len(result.prices_before))
                generation.last_business_updated_at = now
                return "PREFIX_CHECK"
            if (end.input_digest != sha256(self.inputs._encoded(end.accumulator)).digest()
                    or not end.accumulator["done"] or end.accumulator["sourceGenerationId"] != str(source.generation_id)
                    or end.accumulator["sourceManifestDigest"] != receipt.manifest_digest.hex()):
                raise CalculationInputMismatch("Prefix completion proof changed")
            for stage in ("DATE_INPUT", "CASH_BALANCE", "DATE_COMPLETE"):
                old = session.get(CalculationBatch, (lease.account_id, source.generation_id, business_date, stage, "", "1"))
                if old is None:
                    raise CalculationInputMismatch("Missing published prefix continuation")
                session.add(CalculationBatch(account_id=lease.account_id, generation_id=generation.generation_id,
                    trade_date=business_date, stage=stage, stock_key="", page_key="1",
                    accumulator=deepcopy(old.accumulator), cursor=deepcopy(old.cursor), input_digest=old.input_digest,
                    row_count=old.row_count, completed_at=now))
            values = {"sourceGenerationId": str(source.generation_id), "sourceManifestDigest": receipt.manifest_digest.hex(),
                "dayId": str(day.day_result_id) if day else None, "dayDigest": day.input_digest.hex() if day else None,
                "priceProofDigest": end.input_digest.hex()}
            self._save(session, generation, business_date, "PREFIX_DATE", "1", values, now, row_count=int(bool(day)))
            if day:
                generation.completed_trade_date_count += 1
                generation.last_completed_trade_date = business_date
            generation.last_business_updated_at, generation.stage = now, "CALCULATING"
            session.flush()
            copied = session.get(CalculationBatch, (*identity, "DATE_COMPLETE", "", "1"))
            self.steps._verify_completed(session, lease, generation, copied)
            deadline.remaining_ms()
            return "PREFIX_DATE"

    def _stop(self, session, generation, now, reason):
        self._save(session, generation, generation.from_date, "PREFIX_STOP", "1", {"reason": reason}, now)
        generation.last_business_updated_at = now
        return "PREFIX_END"

    def _save(self, session, generation, day, stage, key, values, now, row_count=0):
        session.add(CalculationBatch(account_id=generation.account_id, generation_id=generation.generation_id,
            trade_date=day, stage=stage, stock_key="", page_key=key, cursor={"done": True}, accumulator=values,
            input_digest=sha256(self.inputs._encoded(values)).digest(), row_count=row_count, completed_at=now))
