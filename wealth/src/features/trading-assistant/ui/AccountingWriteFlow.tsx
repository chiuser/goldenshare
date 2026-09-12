import { useEffect, useRef, useState, type ReactNode } from "react";
import type { RecoveryInputResponse, RecoveryStatusDto } from "../api/generatedContracts";
import { useWriteSession } from "../model/useWriteSession";
import type { AccountingScope } from "../model/writeOperation";
import { WriteRecoveryDialog } from "./WriteRecoveryDialog";
import { TradingAssistantAction, TradingAssistantDialog } from "./TradingAssistantForm";

export type AccountingWriteSession = ReturnType<typeof useWriteSession>;
export function AccountingWriteFlow({ scope, onClose, onSaved, onRestore, children }: {
  scope: AccountingScope; onClose: () => void;
  onSaved: (receipt: NonNullable<RecoveryStatusDto["receipt"]>) => Promise<void>;
  onRestore: (input: RecoveryInputResponse) => Promise<void>;
  children: (session: AccountingWriteSession) => ReactNode;
}) {
  const session = useWriteSession(scope);
  const [detailsFailed, setDetailsFailed] = useState(false);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [restoreError, setRestoreError] = useState(false);
  const callbacks = useRef({ onSaved, onClose, onRestore }); callbacks.current = { onSaved, onClose, onRestore };
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  async function loadDetails() {
    if (!session.receipt || loadingDetails) return;
    setLoadingDetails(true); setDetailsFailed(false);
    try { await callbacks.current.onSaved(session.receipt); if (alive.current) callbacks.current.onClose(); }
    catch { if (alive.current) setDetailsFailed(true); }
    finally { if (alive.current) setLoadingDetails(false); }
  }
  useEffect(() => { if (session.receipt) void loadDetails(); }, [session.receipt]);
  async function restore() {
    if (restoring) return;
    setRestoring(true); setRestoreError(false);
    try {
      const input = await session.restore();
      if (input && alive.current) await callbacks.current.onRestore(input);
    } catch { if (alive.current) setRestoreError(true); }
    finally { if (alive.current) setRestoring(false); }
  }
  const effective = { ...session, canSave: session.canSave && !restoring && !restoreError };
  return <>
    {children(effective)}
    {!session.ready && session.error && <TradingAssistantDialog title="暂时无法核对保存状态" subtitle={session.error} onClose={onClose}
      footer={<><TradingAssistantAction onClick={onClose}>关闭提示</TradingAssistantAction>
        <TradingAssistantAction primary onClick={session.retryInitialLookup}>重新读取</TradingAssistantAction></>}>请先核对该范围内的原操作，避免重复提交。</TradingAssistantDialog>}
    {restoreError && <TradingAssistantDialog title="原表单信息暂时无法恢复" onClose={onClose}
      footer={<><TradingAssistantAction onClick={onClose}>关闭提示</TradingAssistantAction>
        <TradingAssistantAction primary onClick={() => void restore()}>重新读取</TradingAssistantAction></>}>当前填写内容仍保留，暂不能再次保存。</TradingAssistantDialog>}
    {session.recovery && (!session.editing || session.receipt) && (!session.busy || session.receipt) && <WriteRecoveryDialog
      state={session.recovery} checking={session.busy || restoring || loadingDetails} confirmedSaved={!!session.receipt}
      detailsFailed={detailsFailed} failureMessage={session.error} onClose={onClose} onCheck={() => void session.check()}
      onEdit={() => void restore()} onLoadDetails={() => void loadDetails()} />}
  </>;
}
