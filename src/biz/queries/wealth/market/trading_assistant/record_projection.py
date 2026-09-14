"""Original amounts and captured fee inputs; never recalculate with today's rates."""
from src.biz.schemas.wealth.market.trading_assistant.records import TradeRecord, CashFlowRecord
from src.biz.services.wealth.market.trading_assistant.account_acceptance import accepted_time
from src.biz.services.wealth.market.trading_assistant.calculation.precision import format_cents
from src.biz.services.wealth.market.trading_assistant.ledger_preparation import scaled_integer
from src.biz.services.wealth.market.trading_assistant.persistence_values import numeric_cents


def project_record(row, *, account_ref, stock_ref=None, closed_state=None, closed_reason=None):
    money = lambda value: format_cents(numeric_cents(value))
    common = dict(accountRef=account_ref, revision=str(row.revision), recordedAt=accepted_time(row.recorded_at),
        acceptedAt=accepted_time(row.accepted_at), direction=row.direction, note=row.note, status=row.status,
        netCashChange=money(row.net_cash_change))
    if row.kind == "CASH_FLOW":
        return CashFlowRecord(**common, cashFlowId=str(row.ledger_id), occurredOn=row.occurred_on.isoformat(),
            amount=money(row.cash_amount))
    return TradeRecord(**common, tradeId=str(row.ledger_id), tradeDate=row.occurred_on.isoformat(), stockRef=stock_ref,
        closedDataStatus=closed_state, closedReason=closed_reason,
        quantity=row.quantity, price=money(row.price), grossAmount=money(row.gross_amount),
        commissionAmount=money(row.commission_amount), stampTaxAmount=money(row.stamp_tax_amount),
        feeVersionId=str(row.fee_version_id), commissionRateWan=format_cents(scaled_integer(row.commission_rate, 6)),
        minimumCommission=money(row.minimum_commission), stampTaxRatePct=format_cents(scaled_integer(row.stamp_tax_rate, 4)))
