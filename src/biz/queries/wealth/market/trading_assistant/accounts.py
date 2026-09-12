"""Owned account facts, read from one transaction rather than derived positions."""
from uuid import UUID

from sqlalchemy import select, tuple_

from src.biz.models.wealth.trading_assistant.accounts import Account, FeeVersion, Initialization, InitialPosition
from src.biz.schemas.wealth.market.trading_assistant import accounts as dto
from src.biz.services.wealth.market.trading_assistant.calculation.precision import format_cents
from src.biz.services.wealth.market.trading_assistant.ledger_preparation import scaled_integer
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.persistence_values import numeric_cents
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict


def account_summary(account):
    return dto.AccountSummary(accountId=str(account.account_id), name=account.name, brokerName=account.broker_name,
        initializedOn=account.initialized_on.isoformat(), factVersion=str(account.fact_version),
        feeVersionId=str(account.current_fee_version_id))


def fee_settings(fee):
    return dto.FeeSettingsDto(accountId=str(fee.account_id), feeVersionId=str(fee.fee_version_id),
        commissionRateWan=format_cents(scaled_integer(fee.commission_rate, 6)),
        minimumCommission=format_cents(numeric_cents(fee.minimum_commission)),
        stampTaxRatePct=format_cents(scaled_integer(fee.stamp_tax_rate, 4)))


class AccountQueries:
    def __init__(self, policy, market):
        self.policy, self.market = policy, market

    def owned(self, session, *, owner_id: int, account_id: UUID, deadline):
        apply_sql_budget(session, deadline, self.policy)
        account = session.scalar(select(Account).where(Account.owner_id == owner_id, Account.account_id == account_id))
        if account is None:
            raise WriteProtocolConflict("TA_ACCOUNT_NOT_FOUND")
        return account

    def list(self, session, *, owner_id, deadline):
        items, after = [], None
        while True:
            apply_sql_budget(session, deadline, self.policy)
            query = select(Account).where(Account.owner_id == owner_id)
            if after is not None:
                query = query.where(tuple_(Account.created_at, Account.account_id) > tuple_(*after))
            rows = session.scalars(query.order_by(Account.created_at, Account.account_id).limit(self.policy.page_rows)).all()
            items.extend(account_summary(row) for row in rows)
            if len(rows) < self.policy.page_rows:
                break
            after = (rows[-1].created_at, rows[-1].account_id)
        deadline.remaining_ms()
        return dto.AccountsResponse(items=items)

    def fees(self, session, *, owner_id, account_id, deadline):
        account = self.owned(session, owner_id=owner_id, account_id=account_id, deadline=deadline)
        fee = session.get(FeeVersion, account.current_fee_version_id)
        if fee is None or fee.account_id != account.account_id:
            raise ValueError("Account fee reference is inconsistent")
        return fee_settings(fee)

    def initialization(self, session, *, owner_id, account_id, deadline):
        account = self.owned(session, owner_id=owner_id, account_id=account_id, deadline=deadline)
        initial = session.get(Initialization, account.current_initialization_id)
        if initial is None or initial.account_id != account.account_id:
            raise ValueError("Account initialization reference is inconsistent")
        positions, after = [], None
        while True:
            apply_sql_budget(session, deadline, self.policy)
            query = select(InitialPosition).where(InitialPosition.initialization_id == initial.initialization_id)
            if after is not None:
                query = query.where(InitialPosition.ts_code > after)
            rows = session.scalars(query.order_by(InitialPosition.ts_code).limit(self.policy.page_rows)).all()
            for row in rows:
                security = self.market.resolve_security(session, row.ts_code, deadline)
                cost = numeric_cents(row.cost_price)
                positions.append(dto.InitializationPosition(clientRowId=row.client_row_id, tsCode=row.ts_code,
                    quantity=row.quantity, availableQuantity=row.available_quantity, costPrice=format_cents(cost),
                    stockRef={"tsCode":row.ts_code, "name":security.name}, costAmount=format_cents(cost * row.quantity)))
            if len(rows) < self.policy.page_rows:
                break
            after = rows[-1].ts_code
        deadline.remaining_ms()
        return dto.InitializationDetail(accountId=str(account_id), name=account.name, brokerName=account.broker_name,
            factVersion=str(account.fact_version), initializedOn=account.initialized_on.isoformat(),
            initializationId=str(initial.initialization_id), initializationRevision=str(initial.revision),
            initialCash=format_cents(numeric_cents(initial.initial_cash)), initialPositions=positions)
