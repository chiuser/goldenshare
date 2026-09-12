"""Account commands inside the final short acceptance transaction (§4.21).

The caller validates securities before this phase and obtains protocol locks first.
No method commits, reads wall time, installs a fee default, or computes returns.
"""
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.biz.models.wealth.trading_assistant.accounts import Account, FeeVersion, Initialization, InitialPosition
from src.biz.models.wealth.trading_assistant.calculation import Recalculation
from src.biz.schemas.wealth.market.trading_assistant import accounts as dto
from src.biz.schemas.wealth.market.trading_assistant.receipts import AccountCreateReceipt, FeesUpdateReceipt
from src.biz.schemas.wealth.market.trading_assistant.targets import LedgerTarget
from .calculation.fees import FeeSnapshot
from .calculation.precision import format_cents, parse_money_cents
from .market_facts import SecurityFact
from .persistence_values import money_numeric
from .write_protocol import WriteProtocol, WriteProtocolConflict, canonical_input


def assert_retained_input(request, command):
    payload = command.model_dump(mode="json", exclude={"requestId", "attemptId", "expectedRequestStateVersion"})
    _, digest = canonical_input(request.operation_type,request.scope_key,payload,
                               LedgerTarget.model_validate(request.target) if request.target else None)
    if digest != request.input_digest:
        raise WriteProtocolConflict("TA_REQUEST_ID_CONFLICT")


def scaled_decimal(units: int, scale: int) -> Decimal:
    """Integer construction avoids ambient Decimal precision for large fee inputs."""
    whole, fraction = divmod(units, 10**scale)
    return Decimal(f"{whole}.{fraction:0{scale}d}")


def new_fee(account_id: UUID, values: dto.FeeInputs, now: datetime) -> FeeVersion:
    parsed = FeeSnapshot.from_inputs(values.commissionRateWan, values.minimumCommission, values.stampTaxRatePct)
    return FeeVersion(fee_version_id=uuid4(), account_id=account_id,
        commission_rate=scaled_decimal(parsed.commission_rate_millionths, 6),
        minimum_commission=money_numeric(parsed.minimum_commission_cents),
        stamp_tax_rate=scaled_decimal(parsed.stamp_tax_rate_ten_thousandths, 4), created_at=now)


def fee_dto(account_id: UUID, fee_id: UUID, values: dto.FeeInputs) -> dto.FeeSettingsDto:
    return dto.FeeSettingsDto(accountId=str(account_id),feeVersionId=str(fee_id),
        **values.model_dump(include={"commissionRateWan", "minimumCommission", "stampTaxRatePct"}))


def accepted_time(now: datetime) -> str:
    if now.tzinfo is None:
        raise ValueError("Acceptance requires timezone-aware server time")
    return now.astimezone(ZoneInfo("Asia/Shanghai")).isoformat()


class AccountAcceptance:
    def __init__(self, protocol: WriteProtocol):
        self.protocol = protocol

    def create(self, session: Session, locked: tuple, command: dto.CreateAccountCommand,
               *, securities: dict[str, SecurityFact], now: datetime):
        _, request, attempt = locked
        if (request.operation_type != "ACCOUNT_CREATE" or str(request.request_id) != command.requestId
                or str(attempt.attempt_id) != command.attemptId):
            raise ValueError("Account command and locked request differ")
        assert_retained_input(request,command)
        # No silently dropped, inferred, or foreign securities in the supplied proof.
        if set(securities) != {row.tsCode for row in command.initialPositions} or any(
                code != fact.ts_code for code,fact in securities.items()):
            raise ValueError("Incomplete security validation")
        timestamp = accepted_time(now)
        initialized_on = now.astimezone(ZoneInfo("Asia/Shanghai")).date()
        account_id, initialization_id = uuid4(), uuid4()
        fee = new_fee(account_id, command, now)
        account = Account(account_id=account_id,owner_id=request.owner_id,name=command.name,
            broker_name=command.brokerName,initialized_on=initialized_on,created_at=now,
            current_initialization_id=initialization_id,current_fee_version_id=fee.fee_version_id,
            fact_version=1,calculation_target_version=1)
        session.add(account)
        session.flush()
        session.add_all([fee, Initialization(initialization_id=initialization_id,account_id=account_id,
            revision=1,accepted_fact_version=1,initial_cash=money_numeric(parse_money_cents(command.initialCash)),created_at=now)])
        session.flush()
        positions = []
        for row in command.initialPositions:
            cost = parse_money_cents(row.costPrice)
            session.add(InitialPosition(initialization_id=initialization_id,account_id=account_id,
                client_row_id=row.clientRowId,ts_code=row.tsCode,quantity=row.quantity,
                available_quantity=row.availableQuantity,cost_price=money_numeric(cost)))
            positions.append(dto.InitializationPosition(**row.model_dump(),
                stockRef={"tsCode":row.tsCode,"name":securities[row.tsCode].name},
                costAmount=format_cents(cost * row.quantity)))
        session.add(Recalculation(account_id=account_id,target_version=1,affected_from_date=initialized_on,
            next_attempt_at=now,fence=0,transient_failure_count=0,updated_at=now))
        receipt = AccountCreateReceipt(requestId=command.requestId,attemptId=command.attemptId,
            operationType="ACCOUNT_CREATE",acceptedAt=timestamp,
            result=dto.CreateAccountResult(
                account=dto.AccountSummary(accountId=str(account_id),name=command.name,brokerName=command.brokerName,
                    initializedOn=initialized_on.isoformat(),factVersion="1",feeVersionId=str(fee.fee_version_id)),
                initialization=dto.Initialization(accountId=str(account_id),initializedOn=initialized_on.isoformat(),
                    initializationId=str(initialization_id),initializationRevision="1",
                    initialCash=command.initialCash,initialPositions=positions),
                fees=fee_dto(account_id,fee.fee_version_id,command)))
        return self.protocol.saved(session,locked,receipt.model_dump(mode="json"),now)

    def update_fees(self, session: Session, locked: tuple, command: dto.UpdateFeesCommand,
                    *, account_id: UUID, now: datetime):
        _, request, attempt = locked
        if (request.operation_type != "FEES_UPDATE" or str(request.request_id) != command.requestId
                or str(attempt.attempt_id) != command.attemptId
                or request.scope_key != f"ACCOUNT_FEES:{account_id}"):
            raise ValueError("Fee command and locked request differ")
        assert_retained_input(request,command)
        account = session.scalar(select(Account).where(Account.owner_id == request.owner_id,
            Account.account_id == account_id).with_for_update().execution_options(populate_existing=True))
        if account is None:
            raise WriteProtocolConflict("TA_ACCOUNT_NOT_FOUND")
        if str(account.current_fee_version_id) != command.expectedFeeVersionId:
            raise WriteProtocolConflict("TA_FEE_VERSION_CONFLICT")
        old = session.get(FeeVersion,account.current_fee_version_id)
        proposed = new_fee(account_id,command,now)
        if any(getattr(old,field) != getattr(proposed,field) for field in (
                "commission_rate", "minimum_commission", "stamp_tax_rate")):
            session.add(proposed)
            session.flush()
            account.current_fee_version_id = proposed.fee_version_id
        receipt = FeesUpdateReceipt(requestId=command.requestId,attemptId=command.attemptId,
            operationType="FEES_UPDATE",acceptedAt=accepted_time(now),
            result=fee_dto(account_id,account.current_fee_version_id,command))
        # No fact version change or recalculation request for a fee edit.
        return self.protocol.saved(session,locked,receipt.model_dump(mode="json"),now)
