"""Initial history uses the creation receipt's fee reference, never current fees."""
from uuid import UUID

from sqlalchemy import and_, select

from src.biz.models.wealth.trading_assistant.accounts import Account, FeeVersion
from src.biz.models.wealth.trading_assistant.recovery import WriteAttempt, WriteRequest
from .calculation_inputs import CalculationInputMismatch
from .market_facts import apply_sql_budget


def initial_fee_version(session, *, owner_id, account_id, policy, deadline):
    """Bounded projection: do not deserialize all initial positions in a receipt."""
    apply_sql_budget(session, deadline, policy)
    receipt = WriteAttempt.receipt
    fee_ref = receipt["result"]["fees"]["feeVersionId"].astext
    account_ref = receipt["result"]["account"]["accountId"].astext
    statement = select(fee_ref,
        receipt["result"]["fees"]["accountId"].astext,
        receipt["result"]["account"]["feeVersionId"].astext).select_from(WriteAttempt).join(
            WriteRequest, and_(WriteRequest.owner_id == WriteAttempt.owner_id,
                               WriteRequest.request_id == WriteAttempt.request_id)).join(
            Account, and_(Account.owner_id == WriteAttempt.owner_id,
                          Account.account_id == account_id)).where(
            Account.owner_id == owner_id, WriteRequest.operation_type == "ACCOUNT_CREATE",
            WriteAttempt.status == "SAVED", account_ref == str(account_id),
            receipt["operationType"].astext == "ACCOUNT_CREATE").limit(2)
    rows = session.execute(statement).all()
    if len(rows) != 1:
        raise CalculationInputMismatch("Missing or ambiguous account creation fee reference")
    reference, fee_account, account_fee = rows[0]
    if fee_account != str(account_id) or reference != account_fee:
        raise CalculationInputMismatch("Inconsistent account creation fee reference")
    try:
        identity = UUID(reference)
    except (ValueError, TypeError, AttributeError) as exc:
        raise CalculationInputMismatch("Invalid account creation fee reference") from exc
    fee = session.scalar(select(FeeVersion).where(FeeVersion.account_id == account_id,
                                                 FeeVersion.fee_version_id == identity))
    if fee is None:
        raise CalculationInputMismatch("Original account fee version is unavailable")
    deadline.remaining_ms()
    return fee.fee_version_id
