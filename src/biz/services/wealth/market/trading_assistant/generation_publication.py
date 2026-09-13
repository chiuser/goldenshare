"""Direct date manifests and one fenced, atomic account-pointer publication."""
from datetime import timedelta
from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, DayResult
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from src.biz.models.wealth.trading_assistant.publication import PublicationDay, PublicationReceipt
from .calendar_inputs import CalendarInputs
from .calculation_inputs import CalculationInputs, CalculationInputMismatch
from .generation_references import GenerationReferences


class GenerationPublication:
    def __init__(self, execution):
        self.execution = execution
        self.inputs = CalculationInputs(execution)

    def _latest(self, session, lease, generation_id):
        return session.scalar(select(CalculationBatch).where(CalculationBatch.account_id == lease.account_id,
            CalculationBatch.generation_id == generation_id, CalculationBatch.stage == "MANIFEST",
            CalculationBatch.stock_key == "").order_by(CalculationBatch.trade_date.desc()).limit(1))

    def advance(self, session, lease, *, generation_id, deadline):
        """Choose one persisted publication unit; caller commits the transaction.

        Do not wrap publish in execution.batch: publish verifies its fence then
        deletes the pending row atomically. Lost commit replies use confirmed().
        """
        account, _ = self.execution._lock(session, lease, deadline)
        candidate = session.get(CalculationGeneration, generation_id, populate_existing=True)
        if candidate is None:
            raise CalculationInputMismatch("Missing generation")
        generation = self.inputs._generation(session, lease, account, generation_id, candidate.from_date,
            stages=("PREPARING", "CALCULATING", "VERIFYING", "PUBLISHING"))
        if (generation.total_trade_date_count is None
                or generation.completed_trade_date_count != generation.total_trade_date_count):
            raise CalculationInputMismatch("All trading dates must be sealed before publication steps")
        latest = self._latest(session, lease, generation_id)
        if latest is None or not latest.cursor["done"]:
            self.append_next(session, lease, generation_id=generation_id, deadline=deadline)
            return "MANIFEST"
        source, marker = aliased(CalculationBatch), aliased(CalculationBatch)
        checked = select(marker.page_key).where(marker.account_id == source.account_id,
            marker.generation_id == source.generation_id, marker.trade_date == source.trade_date,
            marker.stage == "MANIFEST_CHECK", marker.stock_key == source.stock_key,
            marker.page_key == source.page_key, marker.input_digest == source.input_digest,
            marker.cursor == source.cursor, marker.row_count == source.row_count).exists()
        unchecked = session.scalar(select(source.trade_date).where(source.account_id == lease.account_id,
            source.generation_id == generation_id, source.stage == "MANIFEST", source.stock_key == "",
            ~checked).order_by(source.trade_date).limit(1))
        if unchecked is not None:
            self.verify_date(session, lease, generation_id=generation_id,
                business_date=unchecked, deadline=deadline)
            return "MANIFEST_CHECK"
        self.publish(session, lease, generation_id=generation_id, deadline=deadline)
        return "PUBLISHED"

    def append_next(self, session, lease, *, generation_id, deadline):
        with self.execution.batch(session, lease, deadline=deadline) as account:
            candidate = session.get(CalculationGeneration, generation_id)
            if candidate is None:
                raise CalculationInputMismatch("Missing generation")
            generation = self.inputs._generation(session, lease, account, generation_id, candidate.from_date,
                stages=("PREPARING", "CALCULATING", "VERIFYING", "PUBLISHING"))
            if (generation.total_trade_date_count is None
                    or generation.completed_trade_date_count != generation.total_trade_date_count):
                raise CalculationInputMismatch("All trading dates must be sealed before the manifest")
            previous = self._latest(session, lease, generation_id)
            if previous and previous.cursor["done"]:
                return True
            current = previous.trade_date + timedelta(days=1) if previous else generation.from_date
            calendar = CalendarInputs(self.execution).read_date(session, lease, generation_id=generation_id,
                business_date=current, deadline=deadline)
            resolved = GenerationReferences(self.inputs).result(session, account_id=lease.account_id,
                generation_id=generation_id, business_date=current)
            results = [resolved] if resolved else []
            evidence = None
            if calendar["is_open"]:
                if len(results) != 1 or results[0].status != "SEALED":
                    raise CalculationInputMismatch("Manifest date has no unique sealed result")
                day = results[0]
                session.add(PublicationDay(account_id=lease.account_id, generation_id=generation_id,
                    trade_date=current, day_result_id=day.day_result_id))
                evidence = {"id": str(day.day_result_id), "digest": day.input_digest.hex()}
            elif results:
                raise CalculationInputMismatch("Nontrading date has a stock day result")
            count = (int(previous.accumulator["count"]) if previous else 0) + int(calendar["is_open"])
            cursor = {"date": current.isoformat(), "done": current == generation.through_date}
            accumulator = {"count": str(count), "calendar": calendar, "day": evidence}
            digest = sha256(self.inputs._encoded({"previous": previous.input_digest.hex() if previous else None,
                "cursor": cursor, "accumulator": accumulator})).digest()
            if cursor["done"] and count != generation.total_trade_date_count:
                raise CalculationInputMismatch("Manifest date coverage differs from frozen calendar")
            now = session.scalar(select(func.clock_timestamp()))
            row = CalculationBatch(account_id=lease.account_id, generation_id=generation_id, trade_date=current,
                stage="MANIFEST", stock_key="", page_key="1", cursor=cursor, accumulator=accumulator,
                input_digest=digest, row_count=int(calendar["is_open"]), completed_at=now)
            session.add(row)
            session.flush()
            session.refresh(row)
            if (row.input_digest, row.cursor, row.accumulator) != (digest, cursor, accumulator):
                raise CalculationInputMismatch("Manifest checkpoint readback differs")
            if evidence:
                saved = session.get(PublicationDay, (lease.account_id, generation_id, current), populate_existing=True)
                if saved is None or str(saved.day_result_id) != evidence["id"]:
                    raise CalculationInputMismatch("Manifest direct reference readback differs")
            generation.stage = "PUBLISHING" if cursor["done"] else "VERIFYING"
            generation.last_business_updated_at = now
            return cursor["done"]

    def publish(self, session, lease, *, generation_id, deadline):
        # The pending row is deliberately deleted only AFTER the last fence
        # check, while both account and pending locks remain held until commit.
        account, pending = self.execution._lock(session, lease, deadline)
        generation = session.get(CalculationGeneration, generation_id)
        if generation is None:
            raise CalculationInputMismatch("Missing generation")
        self.inputs._generation(session, lease, account, generation_id, generation.through_date, stages=("PUBLISHING",))
        manifest = self._latest(session, lease, generation_id)
        if manifest is None or not manifest.cursor["done"] or manifest.trade_date != generation.through_date:
            raise CalculationInputMismatch("Manifest is incomplete")
        source, check = aliased(CalculationBatch), aliased(CalculationBatch)
        checked = select(check.page_key).where(check.account_id == source.account_id,
            check.generation_id == source.generation_id, check.trade_date == source.trade_date,
            check.stage == "MANIFEST_CHECK", check.stock_key == "", check.page_key == "1",
            check.input_digest == source.input_digest, check.cursor == source.cursor).exists()
        if session.scalar(select(source.trade_date).where(source.account_id == lease.account_id,
            source.generation_id == generation_id, source.stage == "MANIFEST", ~checked).limit(1)) is not None:
            raise CalculationInputMismatch("Manifest readback is not complete")
        count = session.scalar(select(func.count()).select_from(PublicationDay).where(
            PublicationDay.account_id == lease.account_id, PublicationDay.generation_id == generation_id))
        if count != generation.total_trade_date_count or count != int(manifest.accumulator["count"]):
            raise CalculationInputMismatch("Published day count differs from the complete manifest")
        invalid = session.scalar(select(PublicationDay.trade_date).join(DayResult,
            DayResult.day_result_id == PublicationDay.day_result_id).where(
                PublicationDay.account_id == lease.account_id, PublicationDay.generation_id == generation_id,
                DayResult.status != "SEALED").limit(1))
        if invalid is not None:
            raise CalculationInputMismatch("Manifest contains an unsealed day")
        now = session.scalar(select(func.clock_timestamp()))
        receipt = PublicationReceipt(account_id=lease.account_id, generation_id=generation_id,
            target_version=lease.target_version, published_at=now, manifest_digest=manifest.input_digest, day_count=count)
        session.add(receipt)
        account.published_generation_id = generation_id
        generation.stage = "PUBLISHED"
        generation.last_business_updated_at = now
        generation.reason = None
        session.flush()
        session.refresh(receipt)
        if (receipt.manifest_digest, receipt.day_count) != (manifest.input_digest, count):
            raise CalculationInputMismatch("Publication receipt readback differs")
        self.execution._verify(session, lease, account, pending, deadline)
        session.delete(pending)
        session.flush()

    def verify_date(self, session, lease, *, generation_id, business_date, deadline):
        with self.execution.batch(session, lease, deadline=deadline) as account:
            generation = self.inputs._generation(session, lease, account, generation_id, business_date,
                                                 stages=("VERIFYING", "PUBLISHING"))
            row = session.get(CalculationBatch,
                (lease.account_id, generation_id, business_date, "MANIFEST", "", "1"), populate_existing=True)
            previous_date = business_date - timedelta(days=1)
            previous = session.get(CalculationBatch,
                (lease.account_id, generation_id, previous_date, "MANIFEST", "", "1")) if business_date > generation.from_date else None
            if row is None or (business_date > generation.from_date and previous is None):
                raise CalculationInputMismatch("Manifest chain has a missing date")
            calendar = CalendarInputs(self.execution).read_date(session, lease, generation_id=generation_id,
                business_date=business_date, deadline=deadline)
            direct = session.get(PublicationDay, (lease.account_id, generation_id, business_date), populate_existing=True)
            evidence = None
            if calendar["is_open"]:
                day = GenerationReferences(self.inputs).result(session, account_id=lease.account_id,
                    generation_id=generation_id, business_date=business_date)
                if (day is None or day.status != "SEALED" or day.account_id != lease.account_id
                        or day.trade_date != business_date or direct is None or direct.day_result_id != day.day_result_id):
                    raise CalculationInputMismatch("Manifest reference does not resolve to this sealed day")
                evidence = {"id": str(day.day_result_id), "digest": day.input_digest.hex()}
            elif direct is not None:
                raise CalculationInputMismatch("Manifest contains a nontrading date")
            count = (int(previous.accumulator["count"]) if previous else 0) + int(calendar["is_open"])
            cursor = {"date": business_date.isoformat(), "done": business_date == generation.through_date}
            accumulator = {"count": str(count), "calendar": calendar, "day": evidence}
            digest = sha256(self.inputs._encoded({"previous": previous.input_digest.hex() if previous else None,
                "cursor": cursor, "accumulator": accumulator})).digest()
            if (row.cursor, row.accumulator, row.input_digest, row.row_count) != (cursor, accumulator, digest, int(calendar["is_open"])):
                raise CalculationInputMismatch("Manifest no longer matches actual date references")
            identity = (lease.account_id, generation_id, business_date, "MANIFEST_CHECK", "", "1")
            marker = session.get(CalculationBatch, identity, populate_existing=True)
            if marker is None:
                now = session.scalar(select(func.clock_timestamp()))
                session.add(CalculationBatch(account_id=lease.account_id, generation_id=generation_id,
                    trade_date=business_date, stage="MANIFEST_CHECK", stock_key="", page_key="1",
                    cursor=cursor, accumulator={}, input_digest=digest, row_count=row.row_count, completed_at=now))
                generation.last_business_updated_at = now
            elif (marker.cursor, marker.input_digest, marker.row_count) != (cursor, digest, row.row_count):
                raise CalculationInputMismatch("Manifest verification marker differs")
            return cursor["done"]

    @staticmethod
    def confirmed(session, *, owner_id, account_id, generation_id, target_version):
        """Resolve an uncertain commit without trying to claim already-cleared work."""
        from src.biz.models.wealth.trading_assistant.accounts import Account
        return session.scalar(select(PublicationReceipt.generation_id).join(Account,
            Account.account_id == PublicationReceipt.account_id).where(Account.owner_id == owner_id,
            Account.account_id == account_id, PublicationReceipt.generation_id == generation_id,
            PublicationReceipt.target_version == target_version)) is not None
