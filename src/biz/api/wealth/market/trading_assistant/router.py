"""M2 accounting HTTP surface, using the approved backend schemas."""
from datetime import date
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends

from src.biz.schemas.wealth.market.trading_assistant import accounts as dto, receipts
from src.biz.schemas.wealth.market.trading_assistant import previews
from src.biz.schemas.wealth.market.trading_assistant.records import TradeDetail, CashFlowDetail
from src.biz.schemas.wealth.market.trading_assistant.recovery import RecoveryStatusDto, PendingRecoveryResponse
from src.biz.schemas.wealth.market.trading_assistant.recovered_inputs import RecoveryInputResponse
from src.biz.schemas.wealth.market.trading_assistant.scopes import AccountCreateScope, AccountFeesScope, AccountLedgerScope
from src.biz.schemas.wealth.market.trading_assistant.targets import TradeTarget, CashFlowTarget
from src.biz.schemas.wealth.market.trading_assistant.value_types import EntityId, BusinessDate, StockCode
from src.biz.services.wealth.market.trading_assistant.defaults import INITIALIZATION_DEFAULTS
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict
from .dependencies import TradingAssistantDependencies
from .errors import TradingAssistantRoute, command_response
from src.biz.schemas.wealth.market.trading_assistant.calculation_status import CalculationStatus


def create_trading_assistant_router(*, auth_dependency, dependencies_dependency):
    router = APIRouter(prefix="/wealth/market/trading-assistant", tags=["trading-assistant"], route_class=TradingAssistantRoute)
    auth, services = Depends(auth_dependency), Depends(dependencies_dependency)

    @router.get("/accounts", response_model=dto.AccountsResponse)
    async def accounts(owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await deps.read(lambda s,d:deps.account_queries.list(s,owner_id=owner_id,deadline=d))

    @router.get("/account-initialization/defaults", response_model=dto.InitializationDefaults)
    async def defaults(owner_id: int = auth):
        return INITIALIZATION_DEFAULTS

    @router.post("/accounts", response_model=receipts.AccountCreateReceipt)
    async def create_account(command: dto.CreateAccountCommand, owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return command_response(await deps.accounts.create(owner_id=owner_id,command=command))

    @router.get("/accounts/{account_id}/initialization", response_model=dto.InitializationDetail)
    async def initialization(account_id: EntityId, owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await deps.read(lambda s,d:deps.account_queries.initialization(s,owner_id=owner_id,account_id=UUID(account_id),deadline=d))

    @router.get("/accounts/{account_id}/fees", response_model=dto.FeeSettingsDto)
    async def fees(account_id: EntityId, owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await deps.read(lambda s,d:deps.account_queries.fees(s,owner_id=owner_id,account_id=UUID(account_id),deadline=d))

    @router.get("/accounts/{account_id}/calculation-status", response_model=CalculationStatus)
    async def calculation_status(account_id: EntityId, owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await deps.read(lambda s,d:deps.calculation_status.read(s,owner_id=owner_id,
            account_id=UUID(account_id),deadline=d))

    @router.put("/accounts/{account_id}/fees", response_model=receipts.FeesUpdateReceipt)
    async def update_fees(account_id: EntityId, command: dto.UpdateFeesCommand, owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return command_response(await deps.accounts.update_fees(owner_id=owner_id,account_id=UUID(account_id),command=command))

    @router.get("/accounts/{account_id}/entry-context", response_model=dto.EntryContext)
    async def context(account_id: EntityId, occurredOn: BusinessDate, tsCode: StockCode | None = None,
                      owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await deps.read(lambda s,d:deps.entry_context.read(s,owner_id=owner_id,account_id=UUID(account_id),
            occurred_on=date.fromisoformat(occurredOn),ts_code=tsCode,now=deps.now(),deadline=d))

    async def save(deps, owner_id, account_id, operation, command, target=None):
        return command_response(await deps.ledger.save(owner_id=owner_id,account_id=UUID(account_id),
            operation=operation,command=command,target=target))

    @router.post("/accounts/{account_id}/trades/preview", response_model=previews.TradePreview)
    async def trade_preview(account_id: EntityId, command: dto.TradePreviewInput,
                            owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await deps.previews.preview(owner_id=owner_id, account_id=UUID(account_id), command=command)

    @router.post("/accounts/{account_id}/trades/{record_id}/correction-preview", response_model=previews.TradeCorrectionPreview)
    async def trade_correction_preview(account_id: EntityId, record_id: EntityId, command: previews.TradeCorrectionPreviewInput,
                                       owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await deps.previews.preview(owner_id=owner_id, account_id=UUID(account_id), command=command,
            target=TradeTarget(accountId=account_id, kind="TRADE", recordId=record_id))

    @router.post("/accounts/{account_id}/cash-flows/{record_id}/correction-preview", response_model=previews.CashCorrectionPreview)
    async def cash_correction_preview(account_id: EntityId, record_id: EntityId, command: previews.CashCorrectionPreviewInput,
                                      owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await deps.previews.preview(owner_id=owner_id, account_id=UUID(account_id), command=command,
            target=CashFlowTarget(accountId=account_id, kind="CASH_FLOW", recordId=record_id))

    @router.post("/accounts/{account_id}/trades", response_model=receipts.TradeCreateReceipt)
    async def trade(account_id: EntityId, command: dto.TradeCommand, owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await save(deps,owner_id,account_id,"TRADE_CREATE",command)

    @router.post("/accounts/{account_id}/cash-flows", response_model=receipts.CashCreateReceipt)
    async def cash(account_id: EntityId, command: dto.CashFlowCommand, owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await save(deps,owner_id,account_id,"CASH_FLOW_CREATE",command)

    @router.post("/accounts/{account_id}/trades/{record_id}/corrections", response_model=receipts.TradeCorrectReceipt)
    async def correct_trade(account_id: EntityId, record_id: EntityId, command: dto.CorrectTradeCommand,
                            owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await save(deps,owner_id,account_id,"TRADE_CORRECT",command,TradeTarget(accountId=account_id,kind="TRADE",recordId=record_id))

    @router.post("/accounts/{account_id}/cash-flows/{record_id}/corrections", response_model=receipts.CashCorrectReceipt)
    async def correct_cash(account_id: EntityId, record_id: EntityId, command: dto.CorrectCashFlowCommand,
                           owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await save(deps,owner_id,account_id,"CASH_FLOW_CORRECT",command,CashFlowTarget(accountId=account_id,kind="CASH_FLOW",recordId=record_id))

    @router.post("/accounts/{account_id}/trades/{record_id}/voids", response_model=receipts.TradeVoidReceipt)
    async def void_trade(account_id: EntityId, record_id: EntityId, command: dto.VoidCommand,
                         owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await save(deps,owner_id,account_id,"TRADE_VOID",command,TradeTarget(accountId=account_id,kind="TRADE",recordId=record_id))

    @router.post("/accounts/{account_id}/cash-flows/{record_id}/voids", response_model=receipts.CashVoidReceipt)
    async def void_cash(account_id: EntityId, record_id: EntityId, command: dto.VoidCommand,
                        owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await save(deps,owner_id,account_id,"CASH_FLOW_VOID",command,CashFlowTarget(accountId=account_id,kind="CASH_FLOW",recordId=record_id))

    @router.post("/accounts/{account_id}/initialization/corrections", response_model=receipts.InitializationCorrectReceipt)
    async def correct_initialization(account_id: EntityId, command: dto.CorrectInitializationCommand,
                                     owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await save(deps,owner_id,account_id,"INITIALIZATION_CORRECT",command)

    @router.post("/accounts/{account_id}/initialization/correction-preview", response_model=previews.InitializationCorrectionPreview)
    async def initial_preview(account_id: EntityId, command: previews.InitializationCorrectionPreviewInput,
                              owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await deps.initialization_preview.preview(owner_id=owner_id, account_id=UUID(account_id), command=command)

    @router.get("/write-requests/pending", response_model=PendingRecoveryResponse)
    async def pending(scopeType: Literal["ACCOUNT_CREATE","ACCOUNT_FEES","ACCOUNT_LEDGER"], accountId: EntityId | None = None,
                      owner_id: int = auth, deps: TradingAssistantDependencies = services):
        if (scopeType == "ACCOUNT_CREATE") != (accountId is None):
            raise WriteProtocolConflict("TA_REQUEST_INVALID")
        scope = AccountCreateScope(scopeType=scopeType) if accountId is None else (
            AccountFeesScope(scopeType=scopeType,accountId=accountId) if scopeType == "ACCOUNT_FEES"
            else AccountLedgerScope(scopeType=scopeType,accountId=accountId))
        return await deps.read(lambda s,d:deps.recovery.pending(s,owner_id=owner_id,scope=scope,deadline=d))

    @router.get("/records/trades/{record_id}", response_model=TradeDetail)
    async def trade_detail(record_id: EntityId, cursor: str | None = None, limit: int = 20,
                           owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await deps.read(lambda s,d:deps.record_detail.read(s, owner_id=owner_id, record_id=UUID(record_id),
            kind="TRADE", cursor=cursor, limit=limit, deadline=d))

    @router.get("/records/cash-flows/{record_id}", response_model=CashFlowDetail)
    async def cash_detail(record_id: EntityId, cursor: str | None = None, limit: int = 20,
                          owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await deps.read(lambda s,d:deps.record_detail.read(s, owner_id=owner_id, record_id=UUID(record_id),
            kind="CASH_FLOW", cursor=cursor, limit=limit, deadline=d))

    @router.get("/write-requests/{request_id}", response_model=RecoveryStatusDto)
    async def status(request_id: EntityId, owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await deps.read(lambda s,d:deps.recovery.status(s,owner_id=owner_id,request_id=UUID(request_id),deadline=d))

    @router.get("/write-requests/{request_id}/input", response_model=RecoveryInputResponse)
    async def original_input(request_id: EntityId, owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await deps.read(lambda s,d:deps.recovery.recoverable_input(s,owner_id=owner_id,request_id=UUID(request_id),deadline=d))

    return router
