"""Seal only complete, verified day candidates; never publish an account here."""
from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from src.biz.models.wealth.trading_assistant.calculation import ClosedTrade, DayResult, PositionState
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch, ValuationBasis
from src.biz.models.wealth.trading_assistant.publication import AccountSnapshot
from .calculation_inputs import CalculationInputMismatch
from .market_facts import MarketFactsReader
from .snapshot_candidates import SnapshotCandidates
from .stock_day_batches import StockDayBatches


class DaySealing:
    def __init__(self, execution):
        self.execution = execution
        self.stocks = StockDayBatches(execution)

    def seal(self, session, lease, *, generation_id, day_result_id, deadline):
        with self.execution.batch(session, lease, deadline=deadline) as account:
            day = session.get(DayResult, day_result_id, populate_existing=True)
            if day is None or day.account_id != lease.account_id or day.origin_generation_id != generation_id:
                raise CalculationInputMismatch("Day is outside this generation")
            generation = self.stocks.inputs._generation(session, lease, account, generation_id, day.trade_date,
                stages=("PREPARING", "CALCULATING"))
            if day.status == "SEALED":
                return day.input_digest
            calendar = MarketFactsReader(self.execution.policy).read_calendar(
                session, "SSE", day.trade_date, day.trade_date, deadline)
            if not calendar.days[0].is_open:
                raise CalculationInputMismatch("Cannot seal a nontrading stock date")
            scope = self.stocks._latest(session, lease, generation_id, day.trade_date, "", "DAY_SCOPE_CHECK")
            stocks = self.stocks._latest(session, lease, generation_id, day.trade_date, "", "ACCOUNT_STOCKS")
            snapshot = session.get(AccountSnapshot, (lease.account_id, day_result_id), populate_existing=True)
            if scope is None or not scope.cursor["done"] or stocks is None or not stocks.cursor["done"] or snapshot is None:
                raise CalculationInputMismatch("Day source scope and snapshot are not complete")
            predecessor_id = scope.accumulator["binding"]["previousDayId"]
            if stocks.accumulator["binding"]["previousDayResultId"] != predecessor_id:
                raise CalculationInputMismatch("Account and stock scopes use different predecessors")
            if predecessor_id is not None:
                from uuid import UUID
                predecessor = session.get(DayResult, UUID(predecessor_id), populate_existing=True)
                if (predecessor is None or predecessor.account_id != lease.account_id
                        or predecessor.status != "SEALED" or predecessor.trade_date != calendar.days[0].previous_trade_date
                        or predecessor.input_digest.hex() != scope.accumulator["binding"]["previousDigest"]):
                    raise CalculationInputMismatch("Day predecessor is not the adjacent sealed result")
            elif generation.last_completed_trade_date is not None:
                raise CalculationInputMismatch("Cannot restart a generation's day chain without its predecessor")
            stages = ("STOCK_SUMMARY", "STOCK_BASE", "STOCK_CLOSED", "ACCOUNT_STOCKS", "ACCOUNT_CASH")
            source, marker = aliased(CalculationBatch), aliased(CalculationBatch)
            matches = select(marker.page_key).where(marker.account_id == source.account_id,
                marker.generation_id == source.generation_id, marker.trade_date == source.trade_date,
                marker.stock_key == source.stock_key, marker.stage == source.stage + "_CHECK",
                marker.page_key == source.page_key, marker.input_digest == source.input_digest,
                marker.row_count == source.row_count, marker.cursor == source.cursor).exists()
            if session.scalar(select(source.page_key).where(source.account_id == lease.account_id,
                source.generation_id == generation_id, source.trade_date == day.trade_date,
                source.stage.in_(stages), ~matches).limit(1)) is not None:
                raise CalculationInputMismatch("Day still has unverified source pages")
            state_scope = (PositionState.account_id == lease.account_id, PositionState.day_result_id == day_result_id)
            counts = session.execute(select(func.count(), func.count(func.distinct(PositionState.ts_code)))
                                     .select_from(PositionState).where(*state_scope)).one()
            if counts != (int(scope.accumulator["count"]), int(scope.accumulator["count"])):
                raise CalculationInputMismatch("Position count does not match the complete source scope")
            for stage in ("STOCK_SUMMARY", "STOCK_BASE", "STOCK_CLOSED"):
                count = session.scalar(select(func.count()).select_from(CalculationBatch).where(
                    CalculationBatch.account_id == lease.account_id, CalculationBatch.generation_id == generation_id,
                    CalculationBatch.trade_date == day.trade_date, CalculationBatch.stage == stage,
                    CalculationBatch.cursor["done"].as_boolean().is_(True)))
                if count != counts[0]:
                    raise CalculationInputMismatch("Stock reduction completion count differs from source scope")
            missing_value = ~select(ValuationBasis.basis_id).where(ValuationBasis.account_id == lease.account_id,
                ValuationBasis.generation_id == generation_id, ValuationBasis.trade_date == day.trade_date,
                ValuationBasis.ts_code == PositionState.ts_code, ValuationBasis.quality == "READY",
                ValuationBasis.price.is_not(None)).exists()
            if session.scalar(select(PositionState.ts_code).where(*state_scope,
                PositionState.quantity > 0, missing_value).limit(1)) is not None:
                raise CalculationInputMismatch("Held stock has no ready frozen valuation")
            closed_scope = (ClosedTrade.account_id == lease.account_id, ClosedTrade.day_result_id == day_result_id)
            if session.scalar(select(func.count()).select_from(ClosedTrade).where(*closed_scope)) != snapshot.closed_trade_count:
                raise CalculationInputMismatch("Closed sale count differs from snapshot")
            round_exists = select(PositionState.round_id).where(*state_scope,
                PositionState.round_id == ClosedTrade.round_id).exists()
            if session.scalar(select(ClosedTrade.sell_ledger_id).where(*closed_scope, ~round_exists).limit(1)) is not None:
                raise CalculationInputMismatch("Closed sale is outside the verified rounds")
            # Recompute and compare the actual saved scalar snapshot, not just its hash.
            SnapshotCandidates(self.execution).save(session, lease, generation_id=generation_id,
                day_result_id=day_result_id, valuation_at=snapshot.valuation_at, deadline=deadline)
            snapshot_check = session.get(CalculationBatch,
                (lease.account_id, generation_id, day.trade_date, "ACCOUNT_SNAPSHOT", "", "1"))
            digest = sha256(self.stocks.inputs._encoded({"scope": scope.input_digest.hex(),
                "snapshot": snapshot_check.input_digest.hex(), "calendar": calendar.source_version,
                "factVersion": str(generation.fact_version), "initialization": str(generation.initialization_id),
                "ruleVersion": str(generation.rule_version), "date": day.trade_date.isoformat()})).digest()
            now = session.scalar(select(func.clock_timestamp()))
            day.input_digest, day.status, day.sealed_at = digest, "SEALED", now
            generation.completed_trade_date_count += 1
            generation.last_completed_trade_date = day.trade_date
            generation.last_business_updated_at = now
            session.flush()
            session.refresh(day)
            if (day.input_digest, day.status, day.sealed_at) != (digest, "SEALED", now):
                raise CalculationInputMismatch("Sealed day readback differs")
            return digest
