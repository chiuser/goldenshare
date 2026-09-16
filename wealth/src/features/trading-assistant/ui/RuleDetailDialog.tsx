import { useEffect, useRef, useState } from "react";
import type { AlertDetail, PlanDetail, Conditions } from "../api/generatedContracts";
import { getRule, type RuleKind } from "../api/rulesApi";
import { getAuthEpoch } from "../../auth/model/authStorage";
import { checkLabel, conditionText, evidenceNumber, notificationLabel, resultLabel, ruleTime } from "../model/rulePresentation";
import { TradingAssistantAction, TradingAssistantDialog } from "./TradingAssistantForm";
import { RuleMaintenanceDialog } from "./RuleMaintenanceDialog";
import { RuleHistoryDialog } from "./RuleHistoryDialog";
import { AccountingWriteFlow } from "./AccountingWriteFlow";

export function RuleDetailDialog({ kind, ruleId, onClose, onUpdated }: { kind: RuleKind; ruleId: string; onClose: () => void; onUpdated: () => void }) {
  const [detail, setDetail] = useState<PlanDetail | AlertDetail | null>(null);
  const [error, setError] = useState(false), [reload, setReload] = useState(0);
  const [overlay, setOverlay] = useState<"EDIT" | "CLOSE" | "CHECKS" | "VERSIONS" | null>(null);
  const [restored, setRestored] = useState<Conditions | null>(null);
  const [writeGeneration, setWriteGeneration] = useState(0);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    const controller = new AbortController(), epoch = getAuthEpoch(); setError(false); setDetail(null);
    getRule(kind, ruleId, controller.signal).then(value => { if (!controller.signal.aborted && epoch === getAuthEpoch()) setDetail(value); })
      .catch(() => { if (!controller.signal.aborted && epoch === getAuthEpoch()) setError(true); });
    return () => controller.abort();
  }, [kind, ruleId, reload]);
  const refreshSaved = async () => {
    const epoch = getAuthEpoch(); const value = await getRule(kind, ruleId);
    if (!alive.current || epoch !== getAuthEpoch()) return;
    setDetail(value); setOverlay(null); setRestored(null); onUpdated();
    // The completed command has been read back. A new session must discover
    // pending operations afresh; it must not retain the previous receipt.
    setWriteGeneration(value => value + 1);
  };
  const result = detail?.finalResult;
  return <AccountingWriteFlow key={writeGeneration} scope={{ scopeType: "RULE", ruleType: kind, ruleId }} onClose={() => { if (overlay) setOverlay(null); else onClose(); }} onSaved={refreshSaved}
    onRestore={async input => {
      if (input.operationType !== "RULE_CONDITIONS_UPDATE" && input.operationType !== "RULE_CLOSE") throw new Error("Unexpected rule operation");
      const epoch = getAuthEpoch(); const fresh = await getRule(kind, ruleId);
      if (!alive.current || epoch !== getAuthEpoch()) return;
      setDetail(fresh);
      setRestored(input.operationType === "RULE_CONDITIONS_UPDATE" ? { priceCondition: input.input.priceCondition, volumeCondition: input.input.volumeCondition } : null);
      setOverlay(input.operationType === "RULE_CLOSE" ? "CLOSE" : "EDIT");
    }}>{session => <>
    <TradingAssistantDialog variant="rule" title={detail ? `${detail.stockRef.name} · ${kind === "PLAN" ? "交易计划" : "独立提醒"}` : "规则详情"} onClose={onClose}
      footer={<><TradingAssistantAction onClick={onClose}>返回列表</TradingAssistantAction><TradingAssistantAction primary disabled={!detail} onClick={() => setOverlay("CHECKS")}>查看验证记录</TradingAssistantAction></>}>
      {!detail && !error && <p role="status">正在读取详情…</p>}{error && <><p className="ta-form-error" role="alert">详情暂时无法读取。</p><TradingAssistantAction onClick={() => setReload(v => v + 1)}>重新读取</TradingAssistantAction></>}
      {detail && <>
        <div className="ta-rule-evidence"><strong className="ta-rule-result-title">{resultLabel(detail)}</strong><p>{checkLabel(detail.checkStatus)}</p>{result?.firstTriggeredAt && <p>首次满足：{ruleTime(result.firstTriggeredAt)}</p>}{detail.failureReason && <p>{detail.failureReason}</p>}</div>
        {"accountRef" in detail && <p className="ta-note">{detail.accountRef.name} · {detail.accountRef.brokerName} · {detail.direction === "BUY" ? "买入" : "卖出"}</p>}
        <p className="ta-note">{detail.stockRef.tsCode} · 创建：{ruleTime(detail.createdAt)}<br />生效：{ruleTime(detail.effectiveAt)} · 截止：{ruleTime(detail.deadlineAt)}</p>
        <section className="ta-rule-evidence"><h3>当前条件 · 版本 {detail.currentConditionVersion.versionNo}</h3><p>{detail.conditionSummary}</p></section>
        {result && <section className="ta-rule-evidence"><h3>条件证据</h3>
          {result.triggered && <p>{conditionText({ priceCondition: result.priceCheck, volumeCondition: result.volumeCheck })}</p>}
          {result.priceCheck && <p>分钟收盘价：<span className="num" title={`来源精度：${result.priceCheck.actualValue}`}>{evidenceNumber(result.priceCheck.actualValue)}</span> 元 · {result.priceCheck.satisfied ? "满足" : "不满足"} · {ruleTime(result.priceCheck.checkpointAt)}</p>}
          {result.volumeCheck && <p>当日累计成交量：<span className="num" title={`来源精度：${result.volumeCheck.actualValue}`}>{evidenceNumber(result.volumeCheck.actualValue)}</span> 手 · {result.volumeCheck.satisfied ? "满足" : "不满足"} · {ruleTime(result.volumeCheck.checkpointAt)}</p>}
          <p>{result.coverageSummary}</p><p className="ta-note">盘后判定：{ruleTime(result.decidedAt)}</p></section>}
        <p className="ta-note">{detail.coverageSummary}<br />盘后验证：{ruleTime(detail.checkedAt)} · 行情读取：{ruleTime(detail.marketObservedAt)}</p>
        {detail.missingRanges.map(range => <p className="ta-note" key={range.from}>等待数据：{ruleTime(range.from)} — {ruleTime(range.through)}</p>)}
        <div className="ta-rule-evidence"><h3>飞书通知 · {notificationLabel(detail.notificationSummary)}</h3><p>{detail.notificationSummary.robotName ?? "未配置接收机器人"}</p>{detail.notificationSummary.reason && <p>{detail.notificationSummary.reason}</p>}</div>
        <p className="ta-note">这不是成交记录。实际买卖请另行登记，持仓与现金不会自动变化。</p>
        <div className="ta-rule-actions"><TradingAssistantAction onClick={() => setOverlay("VERSIONS")}>条件版本历史</TradingAssistantAction><TradingAssistantAction disabled={!detail.maintenance.canEditConditions} title={detail.maintenance.editUnavailableReason ?? undefined} onClick={() => setOverlay("EDIT")}>修改条件</TradingAssistantAction><TradingAssistantAction danger disabled={!detail.maintenance.canClose} title={detail.maintenance.closeUnavailableReason ?? undefined} onClick={() => setOverlay("CLOSE")}>关闭规则</TradingAssistantAction></div>
        {(detail.maintenance.editUnavailableReason || detail.maintenance.closeUnavailableReason) && <p className="ta-note">{detail.maintenance.editUnavailableReason ?? detail.maintenance.closeUnavailableReason}</p>}
      </>}
    </TradingAssistantDialog>
    {detail && (overlay === "EDIT" || overlay === "CLOSE") && <RuleMaintenanceDialog kind={kind} detail={detail} action={overlay} onClose={() => setOverlay(null)} session={session} restored={restored} />}
    {(overlay === "CHECKS" || overlay === "VERSIONS") && <RuleHistoryDialog kind={kind} ruleId={ruleId} mode={overlay} onClose={() => setOverlay(null)} />}
  </>}</AccountingWriteFlow>;
}
