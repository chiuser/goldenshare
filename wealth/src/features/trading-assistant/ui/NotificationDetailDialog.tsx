import { useEffect, useState } from "react";
import type { NotificationDetail } from "../api/generatedContracts";
import { getNotification } from "../api/robotApi";
import { getAuthEpoch } from "../../auth/model/authStorage";
import { ruleTime } from "../model/rulePresentation";
import { AccountingWriteFlow } from "./AccountingWriteFlow";
import { TradingAssistantAction, TradingAssistantDialog } from "./TradingAssistantForm";

const labels = { PENDING: "待发送", SENDING: "发送中", IN_FLIGHT: "发送中", SUCCEEDED: "发送成功", FAILED: "发送失败", UNKNOWN: "结果待核对" };
export function NotificationDetailDialog({ notificationId, onClose, onUpdated }: {
  notificationId: string; onClose: () => void; onUpdated: () => void;
}) {
  const [data, setData] = useState<NotificationDetail | null>(null), [error, setError] = useState(false);
  const [cursor, setCursor] = useState<string | null>(null), [reload, setReload] = useState(0), [loading, setLoading] = useState(false);
  const [retry, setRetry] = useState(false);
  const [retryVersion, setRetryVersion] = useState<string | null>(null);
  useEffect(() => {
    const abort = new AbortController(), epoch = getAuthEpoch(); setLoading(true); setError(false);
    getNotification(notificationId, cursor, abort.signal).then(value => {
      if (abort.signal.aborted || epoch !== getAuthEpoch()) return;
      setData(previous => cursor && previous ? { ...value, items: [...previous.items, ...value.items] } : value);
    }).catch(() => { if (!abort.signal.aborted && epoch === getAuthEpoch()) setError(true); })
      .finally(() => { if (!abort.signal.aborted && epoch === getAuthEpoch()) setLoading(false); });
    return () => abort.abort();
  }, [notificationId, cursor, reload]);
  const refresh = () => { setCursor(null); setReload(v => v + 1); };
  return <>
    <TradingAssistantDialog variant="rule" title="飞书通知记录" onClose={onClose} footer={<><TradingAssistantAction onClick={onClose}>关闭</TradingAssistantAction><TradingAssistantAction primary disabled={loading} onClick={refresh}>刷新状态</TradingAssistantAction></>}>
      {data && <><section className="ta-rule-evidence"><h3>{labels[data.state]}</h3><p>接收机器人：{data.robotName}</p>{data.reason && <p>{data.reason}</p>}<p className="ta-note">通知发送与条件触发是两件事。重试不会重新判断条件，也不会生成交易。</p></section>
        {data.items.map(item => <section className="ta-rule-evidence" key={item.attemptId}><h3>第 {item.attemptNo} 次 · {labels[item.outcome]}</h3><p>{item.robotName} · {ruleTime(item.startedAt)}</p>{item.reason && <p>{item.reason}</p>}</section>)}
        {!data.items.length && <p className="ta-note">尚未开始发送。</p>}
        {data.nextCursor && <TradingAssistantAction disabled={loading} onClick={() => setCursor(data.nextCursor)}>加载更多通知记录</TradingAssistantAction>}
        {data.canRetry && <TradingAssistantAction disabled={loading || error} onClick={() => { setRetryVersion(data.stateVersion); setRetry(true); }}>重试失败通知</TradingAssistantAction>}
        {data.state === "UNKNOWN" && <p className="ta-note">结果待核对，不自动重发，也不提供重试。</p>}</>}
      {loading && <p role="status">正在读取通知记录…</p>}{error && <p className="ta-form-error" role="alert">通知记录暂时无法读取，请刷新状态。</p>}
    </TradingAssistantDialog>
    {retry && data && <AccountingWriteFlow scope={{ scopeType: "NOTIFICATION", notificationId }} onClose={() => setRetry(false)} onSaved={async () => { await getNotification(notificationId, null); refresh(); onUpdated(); }} onRestore={async input => { if (input.operationType !== "NOTIFICATION_RETRY") throw new Error("Unexpected notification input"); setRetryVersion(input.input.expectedStateVersion); }}>{session =>
      <TradingAssistantDialog title="重试失败通知" onClose={() => setRetry(false)} footer={<><TradingAssistantAction onClick={() => setRetry(false)}>取消</TradingAssistantAction><TradingAssistantAction primary disabled={!session.canSave || !retryVersion} onClick={() => void session.save("NOTIFICATION_RETRY", { expectedStateVersion: retryVersion })}>确认重试</TradingAssistantAction></>}>
        <p>使用发送时最新确认的机器人配置重试这条失败通知，不会重新验证交易条件。</p>
      </TradingAssistantDialog>}
    </AccountingWriteFlow>}
  </>;
}
