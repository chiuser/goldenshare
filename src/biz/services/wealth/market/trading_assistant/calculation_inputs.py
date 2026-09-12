"""M3 input freezing in short fenced transactions, design §§4.6, 4.24.

The caller selects the fixed range and fee version. These methods never choose
the current fee for historical valuations or declare a day complete.
"""
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from uuid import UUID, uuid4

from sqlalchemy import select, func

from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, DayResult
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch, ValuationBasis
from .recalculation_execution import CalculationExecutionLost
from .valuation_facts import DailyCloseFact


class CalculationInputMismatch(RuntimeError):
    """Retain the old inputs; the caller must not overwrite a frozen page."""


class CalculationDataUnavailable(CalculationInputMismatch):
    """Required valuation evidence is unavailable, not an accounting imbalance."""


@dataclass(frozen=True, slots=True)
class FrozenValuationPage:
    facts: tuple[DailyCloseFact, ...]
    fee_version_id: UUID
    valuation_at: datetime
    after_stock: str | None


class CalculationInputs:
    def __init__(self, execution):
        self.execution = execution
        self.policy = execution.policy

    def save_initial_history_page(self, session, lease, *, generation_id, facts,
                                  valuation_at, after_stock, deadline):
        """Initial history is tied to account creation, including delayed first runs."""
        from .initial_fee_basis import initial_fee_version

        with self.execution.batch(session, lease, deadline=deadline) as account:
            if not facts or any(fact.valuation_date > account.initialized_on for fact in facts):
                raise CalculationInputMismatch("Initial history must not extend beyond initialization")
            fee_id = initial_fee_version(session, owner_id=account.owner_id, account_id=account.account_id,
                                         policy=self.policy, deadline=deadline)
            return self.save_valuation_page(session, lease, generation_id=generation_id, facts=facts,
                fee_version_id=fee_id, valuation_at=valuation_at, after_stock=after_stock, deadline=deadline)

    def prepare_generation(self, session, lease, *, from_date, through_date, rule_version, deadline):
        if (type(from_date) is not date or type(through_date) is not date or from_date > through_date
                or type(rule_version) is not int or not 1 <= rule_version <= 9223372036854775807):
            raise ValueError("Invalid fixed calculation range or rule version")
        with self.execution.batch(session, lease, deadline=deadline) as account:
            generation = session.scalar(select(CalculationGeneration).where(
                CalculationGeneration.account_id == lease.account_id,
                CalculationGeneration.target_version == lease.target_version))
            if generation is None:
                generation = CalculationGeneration(generation_id=uuid4(), account_id=lease.account_id,
                    target_version=lease.target_version, fact_version=account.fact_version,
                    initialization_id=account.current_initialization_id, rule_version=rule_version,
                    from_date=from_date, through_date=through_date, stage="PREPARING",
                    completed_trade_date_count=0, last_business_updated_at=session.scalar(select(func.clock_timestamp())))
                session.add(generation)
            elif (generation.fact_version != account.fact_version
                  or generation.initialization_id != account.current_initialization_id
                  or generation.rule_version != rule_version or generation.from_date != from_date
                  or generation.through_date != through_date):
                raise CalculationInputMismatch("Existing target has different fixed inputs")
            return generation.generation_id

    def _generation(self, session, lease, account, generation_id, trade_date, *, stages=("PREPARING",)):
        generation = session.scalar(select(CalculationGeneration).where(
            CalculationGeneration.account_id == lease.account_id,
            CalculationGeneration.generation_id == generation_id))
        if (generation is None or generation.target_version != lease.target_version
                or generation.fact_version != account.fact_version
                or generation.initialization_id != account.current_initialization_id):
            raise CalculationExecutionLost("Generation no longer matches the accepted account facts")
        if not generation.from_date <= trade_date <= generation.through_date:
            raise CalculationInputMismatch("Valuation day is outside the fixed generation")
        if generation.stage not in stages:
            raise CalculationInputMismatch("Generation is not in the required calculation stage")
        return generation

    def _encoded(self, value):
        chunks, size = [], 0
        for part in json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).iterencode(value):
            encoded = part.encode()
            size += len(encoded)
            if size > self.policy.page_bytes:
                raise ValueError("Calculation page exceeds the byte budget")
            chunks.append(encoded)
        return b"".join(chunks)

    @staticmethod
    def _rows(facts, fee_version_id, valuation_at):
        result = []
        for fact in facts:
            valid = fact.price_text is not None
            if valid and type(fact.price_text) is not str:
                raise CalculationInputMismatch("Source price must be exact decimal text")
            if (valid and (fact.price_date != fact.valuation_date or fact.reason is not None
                          or fact.source != "tushare" or not Decimal(fact.price_text).is_finite()
                          or Decimal(fact.price_text) <= 0)) or (
                    not valid and (fact.price_date is not None or not fact.reason)):
                raise CalculationInputMismatch("Inconsistent daily close fact")
            result.append(dict(ts_code=fact.ts_code, trade_date=fact.valuation_date,
                valuation_at=valuation_at, price=Decimal(fact.price_text) if valid else None,
                price_date=fact.price_date, source_ref=json.dumps({"table":"core_serving.equity_daily_bar",
                    "source":fact.source, "tsCode":fact.ts_code, "tradeDate":fact.valuation_date.isoformat(),
                    "reason":fact.reason}, sort_keys=True),
                source_version=fact.source_version, quality="READY" if valid else "UNAVAILABLE",
                fee_version_id=fee_version_id, valuation_method="SAME_DAY_CLOSE" if valid else None,
                suspension_evidence_ref=None))
        return result

    def _digest(self, facts, fee_version_id, valuation_at, after_stock):
        payload = {"facts": [{k: v.isoformat() if type(v) is date else v for k,v in asdict(f).items()} for f in facts],
                   "feeVersionId": str(fee_version_id),
                   "valuationAt": valuation_at.astimezone(timezone.utc).isoformat(), "afterStock":after_stock}
        return sha256(self._encoded(payload)).digest()

    def save_valuation_page(self, session, lease, *, generation_id, facts, fee_version_id,
                            valuation_at, after_stock, deadline):
        if not facts or len(facts) > self.policy.page_rows:
            raise ValueError("Expected a nonempty bounded valuation page")
        codes = [fact.ts_code for fact in facts]
        trade_date = facts[0].valuation_date
        if (codes != sorted(set(codes)) or any(not code or len(code) > 16 for code in codes)
                or any(fact.valuation_date != trade_date for fact in facts)
                or valuation_at.tzinfo is None or valuation_at.utcoffset() is None
                or (after_stock is not None and codes[0] <= after_stock)):
            raise CalculationInputMismatch("Valuation page order, date or cursor mismatch")
        digest = self._digest(facts, fee_version_id, valuation_at, after_stock)
        desired = self._rows(facts, fee_version_id, valuation_at)
        identity = (lease.account_id, generation_id, trade_date, "VALUATION", "", codes[-1])
        with self.execution.batch(session, lease, deadline=deadline) as account:
            generation = self._generation(session, lease, account, generation_id, trade_date,
                stages=("PREPARING", "CALCULATING"))
            existing = session.get(CalculationBatch, identity)
            if existing is not None:
                if (existing.input_digest != digest or existing.row_count != len(facts)
                        or existing.cursor != {"afterStock":codes[-1]}):
                    raise CalculationInputMismatch("Frozen page inputs changed")
                self._verify_rows(session, lease.account_id, generation_id, desired)
                return existing.cursor.copy()
            if session.get(CalculationBatch,
                    (lease.account_id, generation_id, trade_date, "VALUATION_END", "", "1")) is not None:
                raise CalculationInputMismatch("Cannot append to a completed valuation scope")
            # A generation can prepare later days while earlier days calculate.
            # Once this date starts, only exact replay of frozen pages is valid.
            if session.scalar(select(DayResult.day_result_id).where(
                    DayResult.account_id == lease.account_id,
                    DayResult.origin_generation_id == generation_id,
                    DayResult.trade_date == trade_date).limit(1)) is not None:
                raise CalculationInputMismatch("Cannot append valuation inputs after this date started")
            previous = session.scalar(select(CalculationBatch).where(
                CalculationBatch.account_id == lease.account_id, CalculationBatch.generation_id == generation_id,
                CalculationBatch.trade_date == trade_date, CalculationBatch.stage == "VALUATION",
                CalculationBatch.stock_key == "").order_by(CalculationBatch.page_key.desc()).limit(1))
            if (previous.cursor["afterStock"] if previous else None) != after_stock:
                raise CalculationInputMismatch("Resume cursor does not match the committed page")
            for row in desired:
                session.add(ValuationBasis(basis_id=uuid4(), account_id=lease.account_id,
                                           generation_id=generation_id, **row))
            now = session.scalar(select(func.clock_timestamp()))
            cursor = {"afterStock":codes[-1]}
            session.add(CalculationBatch(account_id=lease.account_id, generation_id=generation_id,
                trade_date=trade_date, stage="VALUATION", stock_key="", page_key=codes[-1], cursor=cursor,
                accumulator={"stockCount": (previous.accumulator["stockCount"] if previous else 0) + len(facts)},
                input_digest=digest, row_count=len(facts), completed_at=now))
            session.flush()
            self._verify_rows(session, lease.account_id, generation_id, desired)
            generation.last_business_updated_at = now
            return cursor

    def read_valuation_page(self, session, lease, *, generation_id, trade_date, page_key, deadline):
        """Recover actual saved values, not a fresh market query or current fees."""
        with self.execution.batch(session, lease, deadline=deadline) as account:
            self._generation(session, lease, account, generation_id, trade_date,
                stages=("PREPARING", "CALCULATING", "VERIFYING", "PUBLISHING", "WAITING_DATA", "FAILED"))
            batch = session.get(CalculationBatch,
                (lease.account_id,generation_id,trade_date,"VALUATION","",page_key))
            if batch is None:
                return None
            previous = session.scalar(select(CalculationBatch).where(
                CalculationBatch.account_id==lease.account_id, CalculationBatch.generation_id==generation_id,
                CalculationBatch.trade_date==trade_date, CalculationBatch.stage=="VALUATION",
                CalculationBatch.stock_key=="", CalculationBatch.page_key < page_key)
                .order_by(CalculationBatch.page_key.desc()).limit(1))
            after = previous.page_key if previous else None
            query = select(ValuationBasis).where(ValuationBasis.account_id==lease.account_id,
                ValuationBasis.generation_id==generation_id, ValuationBasis.trade_date==trade_date,
                ValuationBasis.ts_code<=page_key)
            if after is not None:
                query = query.where(ValuationBasis.ts_code>after)
            rows = session.scalars(query.order_by(ValuationBasis.ts_code).limit(self.policy.page_rows+1)
                                   .execution_options(populate_existing=True)).all()
            if (not rows or len(rows)>self.policy.page_rows or len(rows)!=batch.row_count
                    or batch.cursor!={"afterStock":page_key}
                    or batch.accumulator!={"stockCount":(previous.accumulator["stockCount"] if previous else 0)+len(rows)}
                    or rows[-1].ts_code!=page_key
                    or any((row.fee_version_id,row.valuation_at)!=(rows[0].fee_version_id,rows[0].valuation_at) for row in rows)):
                raise CalculationInputMismatch("Frozen valuation checkpoint is incomplete")
            facts = tuple(DailyCloseFact(row.ts_code,row.trade_date,row.price_date,
                format(row.price,"f") if row.price is not None else None,json.loads(row.source_ref)["source"],
                row.source_version,json.loads(row.source_ref)["reason"]) for row in rows)
            if self._digest(facts,rows[0].fee_version_id,rows[0].valuation_at,after)!=batch.input_digest:
                raise CalculationInputMismatch("Frozen valuation values changed")
            self._verify_rows(session,lease.account_id,generation_id,
                              self._rows(facts,rows[0].fee_version_id,rows[0].valuation_at))
            return FrozenValuationPage(facts,rows[0].fee_version_id,rows[0].valuation_at,after)

    @staticmethod
    def _verify_rows(session, account_id, generation_id, desired):
        rows = session.scalars(select(ValuationBasis).where(ValuationBasis.account_id == account_id,
            ValuationBasis.generation_id == generation_id, ValuationBasis.trade_date == desired[0]["trade_date"],
            ValuationBasis.ts_code.in_([row["ts_code"] for row in desired])).order_by(ValuationBasis.ts_code)
            .execution_options(populate_existing=True)).all()
        if len(rows) != len(desired) or any(
            any(getattr(actual, key) != value for key, value in expected.items())
            for actual, expected in zip(rows, desired, strict=True)):
            raise CalculationInputMismatch("Persisted valuation page does not match its frozen values")
