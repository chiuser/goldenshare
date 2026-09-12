"""First-save fee choice, PRD §6.4.11; not historical fee reconstruction."""
from .calculation_inputs import CalculationInputs, CalculationInputMismatch
from .current_fee_basis import current_fee_basis
from .initial_fee_basis import initial_fee_version


def new_valuation_fee_version(session, execution, lease, *, generation_id, business_date, deadline):
    """Choose for a new, unfrozen date inside the caller's input transaction.

    Frozen dates must be restored by GenerationDispatch/CalculationInputs;
    this selector neither overwrites historical bases nor commits anything.
    """
    from sqlalchemy import select
    from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch, ValuationBasis

    with execution.batch(session, lease, deadline=deadline) as account:
        CalculationInputs(execution)._generation(session, lease, account, generation_id,
            business_date, stages=("PREPARING", "CALCULATING"))
        if session.scalar(select(ValuationBasis.basis_id).where(
                ValuationBasis.account_id == lease.account_id,
                ValuationBasis.trade_date == business_date).limit(1)) is not None:
            raise CalculationInputMismatch("Restore historical valuation fees instead of selecting new fees")
        if session.scalar(select(CalculationBatch.page_key).where(
                CalculationBatch.account_id == lease.account_id,
                CalculationBatch.generation_id == generation_id,
                CalculationBatch.trade_date == business_date,
                CalculationBatch.stage.in_(("VALUATION", "VALUATION_END", "DATE_INPUT")))
                .limit(1)) is not None:
            raise CalculationInputMismatch("Restore the saved date basis instead of selecting new fees")
        if business_date <= account.initialized_on:
            return initial_fee_version(session, owner_id=account.owner_id, account_id=lease.account_id,
                policy=execution.policy, deadline=deadline)
        return current_fee_basis(session, owner_id=account.owner_id, account_id=lease.account_id,
            policy=execution.policy, deadline=deadline).fee_version_id
