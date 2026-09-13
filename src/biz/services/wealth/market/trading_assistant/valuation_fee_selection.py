"""Restore the original day's fees across targets; only new days select current."""
from hashlib import sha256
from uuid import UUID

from sqlalchemy import and_, select

from src.biz.models.wealth.trading_assistant.accounts import FeeVersion
from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from .calculation_inputs import CalculationInputs, CalculationInputMismatch
from .new_valuation_fees import new_valuation_fee_version


def valuation_fee_version(session, execution, lease, *, generation_id, business_date, deadline):
    """Called before the first page of a target/date, within its write transaction.

    Only the fee reference is reused: corrected market prices still belong to
    the new target. This is not a reuse of old positions, profits or checkpoints.
    """
    inputs = CalculationInputs(execution)
    with execution.batch(session, lease, deadline=deadline) as account:
        inputs._generation(session, lease, account, generation_id, business_date,
            stages=("PREPARING", "CALCULATING"))
        saved = session.scalar(select(CalculationBatch).join(CalculationGeneration, and_(
            CalculationGeneration.account_id == CalculationBatch.account_id,
            CalculationGeneration.generation_id == CalculationBatch.generation_id)).where(
                CalculationBatch.account_id == lease.account_id,
                CalculationBatch.trade_date == business_date,
                CalculationBatch.stock_key == "",
                CalculationBatch.stage.in_(("VALUATION", "VALUATION_END")),
                CalculationGeneration.target_version <= lease.target_version)
            # Account targets are ordered by accepted transitions, never UUID or
            # created_at. Preserve the first actually retained date basis.
            .order_by(CalculationGeneration.target_version, CalculationBatch.stage,
                CalculationBatch.page_key).limit(1))
        if saved is None:
            return new_valuation_fee_version(session, execution, lease, generation_id=generation_id,
                business_date=business_date, deadline=deadline)
        if saved.stage == "VALUATION":
            frozen = inputs._read_saved_page(session, lease.account_id, saved.generation_id,
                business_date, saved.page_key)
            if frozen is None:
                raise CalculationInputMismatch("Missing retained historical fee page")
            fee_id = frozen.fee_version_id
        else:
            # VALUATION sorts first above. END without any valuation page is
            # the valid empty-stock case, not a reason to consult current fees.
            binding = saved.accumulator
            if (saved.row_count != 0 or saved.page_key != "1"
                    or saved.cursor != {"afterStock": None, "done": True}
                    or binding.get("lastPageDigest") is not None
                    or saved.input_digest != sha256(inputs._encoded(binding)).digest()):
                raise CalculationInputMismatch("Invalid retained empty valuation scope")
            try:
                fee_id = UUID(binding["feeVersionId"])
            except (KeyError, ValueError, TypeError, AttributeError) as exc:
                raise CalculationInputMismatch("Invalid retained fee identity") from exc
        if session.scalar(select(FeeVersion.fee_version_id).where(
                FeeVersion.account_id == lease.account_id, FeeVersion.fee_version_id == fee_id)) is None:
            raise CalculationInputMismatch("Retained fee does not belong to the account")
        deadline.remaining_ms()
        return fee_id
