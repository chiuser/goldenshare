import { useRef, useState } from "react";
import type { AccountSummary, InitializationCorrectionInput, InitializationDetail } from "../api/generatedContracts";
import { getCashDetail, getEntryContext, getInitialization, getTradeDetail } from "../api/tradingAssistantApi";
import { beijingInputDate, type EntryDraft } from "../model/entryDraft";
import { AccountingWriteFlow } from "./AccountingWriteFlow";
import { InitializationCorrectionForm } from "./InitializationCorrectionDialog";
import { LedgerEntryForm } from "./LedgerEntryDialog";
import { RecordMaintenanceForm, recordDraft, type MaintenanceRecord } from "./RecordMaintenanceForm";
import { RecordDetailDialog, type SavedRecordDetail } from "./RecordDetailDialog";

type LedgerView = { kind: "entry"; draft: EntryDraft } | { kind: "initial"; initial: InitializationDetail; restored?: InitializationCorrectionInput }
  | { kind: "maintenance"; source: MaintenanceRecord; action: "CORRECT" | "VOID"; restored?: EntryDraft };
export function AccountLedgerFlow({ account, initial, direction = "BUY", onClose, onUpdated }: {
  account: AccountSummary; initial?: InitializationDetail; direction?: "BUY" | "SELL" | "IN";
  onClose: () => void; onUpdated: () => Promise<void>;
}) {
  const [view, setView] = useState<LedgerView>(() => initial ? { kind: "initial", initial } : { kind: "entry", draft: {
    kind: direction === "IN" ? "CASH" : "TRADE", direction, stock: null, date: beijingInputDate(), price: "", quantity: "", amount: "", note: "" } });
  const [formVersion, setFormVersion] = useState(0);
  const [sessionVersion, setSessionVersion] = useState(0);
  const [detail, setDetail] = useState<SavedRecordDetail | null>(null);
  const saved = useRef<SavedRecordDetail | null>(null);
  if (detail) return <RecordDetailDialog value={detail} onClose={onClose} onMaintain={(source, action) => {
    saved.current = null; setDetail(null); setView({ kind: "maintenance", source, action }); setSessionVersion(v => v + 1);
  }} />;
  return <AccountingWriteFlow key={sessionVersion} scope={{ scopeType: "ACCOUNT_LEDGER", accountId: account.accountId }} onClose={() => {
    if (saved.current) setDetail(saved.current); else onClose();
  }}
    onRestore={async recovered => {
      if (recovered.operationType === "INITIALIZATION_CORRECT") {
        setView({ kind: "initial", initial: await getInitialization(account.accountId), restored: recovered.input });
      } else if (recovered.operationType === "TRADE_CREATE") {
        const input = recovered.input;
        const context = await getEntryContext(account.accountId, input.tradeDate, input.tsCode);
        setView({ kind: "entry", draft: { kind: "TRADE", direction: input.direction, stock: context.stockRef, date: input.tradeDate,
          price: input.price, quantity: String(input.quantity), amount: "", note: input.note ?? "", noteWasNull: input.note === null } });
      } else if (recovered.operationType === "CASH_FLOW_CREATE") {
        const input = recovered.input;
        await getEntryContext(account.accountId, input.occurredOn);
        setView({ kind: "entry", draft: { kind: "CASH", direction: input.direction, stock: null, date: input.occurredOn,
          price: "", quantity: "", amount: input.amount, note: input.note ?? "", noteWasNull: input.note === null } });
      } else if (recovered.operationType === "TRADE_CORRECT" || recovered.operationType === "TRADE_VOID") {
        const detail = await getTradeDetail(account.accountId, recovered.target.recordId);
        const source: MaintenanceRecord = { kind: "TRADE", record: detail.record };
        let restored: EntryDraft | undefined;
        if (recovered.operationType === "TRADE_CORRECT") {
          const input = recovered.input;
          const context = await getEntryContext(account.accountId, input.tradeDate, input.tsCode);
          restored = { ...recordDraft(source), stock: context.stockRef, direction: input.direction, date: input.tradeDate,
            price: input.price, quantity: String(input.quantity), note: input.note ?? "", noteWasNull: input.note === null };
        }
        setView({ kind: "maintenance", source, action: recovered.operationType === "TRADE_VOID" ? "VOID" : "CORRECT", restored });
      } else if (recovered.operationType === "CASH_FLOW_CORRECT" || recovered.operationType === "CASH_FLOW_VOID") {
        const detail = await getCashDetail(account.accountId, recovered.target.recordId);
        const source: MaintenanceRecord = { kind: "CASH_FLOW", record: detail.record };
        const restored = recovered.operationType === "CASH_FLOW_CORRECT" ? { ...recordDraft(source), direction: recovered.input.direction,
          date: recovered.input.occurredOn, amount: recovered.input.amount, note: recovered.input.note ?? "", noteWasNull: recovered.input.note === null } : undefined;
        setView({ kind: "maintenance", source, action: recovered.operationType === "CASH_FLOW_VOID" ? "VOID" : "CORRECT", restored });
      } else throw new Error("Unexpected operation in account ledger scope");
      setFormVersion(v => v + 1);
    }} onSaved={async receipt => {
      let next: SavedRecordDetail | null = null;
      if (receipt.operationType === "INITIALIZATION_CORRECT") await getInitialization(account.accountId);
      else if (receipt.operationType === "TRADE_CREATE" || receipt.operationType === "TRADE_CORRECT" || receipt.operationType === "TRADE_VOID") next = { kind: "TRADE", detail: await getTradeDetail(account.accountId, receipt.result.tradeId) };
      else if (receipt.operationType === "CASH_FLOW_CREATE" || receipt.operationType === "CASH_FLOW_CORRECT" || receipt.operationType === "CASH_FLOW_VOID") next = { kind: "CASH_FLOW", detail: await getCashDetail(account.accountId, receipt.result.cashFlowId) };
      else throw new Error("Unexpected ledger receipt");
      await onUpdated();
      saved.current = next;
    }}>
    {session => view.kind === "initial" ? <InitializationCorrectionForm key={formVersion} account={account} initial={view.initial} restored={view.restored} session={session} onClose={onClose} />
      : view.kind === "maintenance" ? <RecordMaintenanceForm key={formVersion} account={account} source={view.source} action={view.action} restored={view.restored} session={session} onClose={onClose} />
      : <LedgerEntryForm key={formVersion} account={account} draft={view.draft} onChange={draft => setView({ kind: "entry", draft })} session={session} onClose={onClose} />}
  </AccountingWriteFlow>;
}
