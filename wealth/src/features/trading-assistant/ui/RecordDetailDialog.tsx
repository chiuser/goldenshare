import type { CashFlowDetail, TradeDetail } from "../api/generatedContracts";
import type { MaintenanceRecord } from "./RecordMaintenanceForm";
import { TradingAssistantAction, TradingAssistantDialog } from "./TradingAssistantForm";

export type SavedRecordDetail = { kind: "TRADE"; detail: TradeDetail } | { kind: "CASH_FLOW"; detail: CashFlowDetail };
export function RecordDetailDialog({ value, onClose, onMaintain }: { value: SavedRecordDetail; onClose: () => void;
  onMaintain: (source: MaintenanceRecord, action: "CORRECT" | "VOID") => void;
}) {
  const record = value.detail.record;
  const source: MaintenanceRecord = value.kind === "TRADE" ? { kind: "TRADE", record: value.detail.record } : { kind: "CASH_FLOW", record: value.detail.record };
  return <TradingAssistantDialog variant="fees" title={value.kind === "TRADE" ? "原始成交详情" : "资金流水 · 原始收支"} onClose={onClose}
    footer={<TradingAssistantAction onClick={onClose}>关闭</TradingAssistantAction>}>
    <div className="ta-recovery-summary">{value.kind === "TRADE" ? `${value.detail.record.stockRef.name} · ${record.direction === "BUY" ? "买入" : "卖出"}`
      : record.direction === "IN" ? "资金转入" : "资金转出"}{record.status === "VOID" ? " · 已作废" : ""}</div>
    <p className="ta-note">{record.accountRef.name} · {value.kind === "TRADE" ? value.detail.record.tradeDate : value.detail.record.occurredOn}</p>
    <dl className="ta-record-facts">
      {value.kind === "TRADE" ? <><dt>成交数量</dt><dd>{value.detail.record.quantity} 股</dd><dt>成交价格</dt><dd>{value.detail.record.price}</dd>
        <dt>成交金额</dt><dd>{value.detail.record.grossAmount}</dd><dt>自动佣金</dt><dd>{value.detail.record.commissionAmount}</dd>
        <dt>印花税</dt><dd>{value.detail.record.stampTaxAmount}</dd></> : <><dt>金额</dt><dd>{value.detail.record.amount}</dd></>}
      <dt>现金变动</dt><dd>{record.netCashChange}</dd><dt>备注</dt><dd>{record.note || "—"}</dd>
    </dl>
    {value.kind === "TRADE" && record.direction === "SELL" && <div className="ta-note">
      {value.detail.closedTrade ? <dl className="ta-record-facts"><dt>本笔闭环收益</dt><dd>{value.detail.closedTrade.profitAmount}</dd>
        <dt>本笔收益率</dt><dd>{value.detail.closedTrade.returnPct}%</dd></dl>
        : value.detail.reason ?? "闭环核算结果暂不可用"}
    </div>}
    {value.kind === "CASH_FLOW" && <p className="ta-note">资金进出不计入收益。<br />只登记入账 / 出账，不提供跨账户转账概念。</p>}
    {record.status === "ACTIVE" && <div className="ta-record-actions">
      <TradingAssistantAction primary onClick={() => onMaintain(source, "CORRECT")}>{value.kind === "TRADE" ? "更正交易" : "更正流水"}</TradingAssistantAction>
      <TradingAssistantAction danger onClick={() => onMaintain(source, "VOID")}>{value.kind === "TRADE" ? "作废记录" : "作废流水"}</TradingAssistantAction>
    </div>}
  </TradingAssistantDialog>;
}
