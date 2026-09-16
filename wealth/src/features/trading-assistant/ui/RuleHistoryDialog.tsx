import { useEffect, useRef, useState } from "react";
import type { CheckRecord, HistoricalConditionVersion } from "../api/generatedContracts";
import { getRuleChecks, getRuleVersions, type RuleKind } from "../api/rulesApi";
import { getAuthEpoch } from "../../auth/model/authStorage";
import { checkTitle, ruleTime } from "../model/rulePresentation";
import { TradingAssistantAction, TradingAssistantDialog } from "./TradingAssistantForm";

export function RuleHistoryDialog({ kind, ruleId, mode, onClose }: { kind: RuleKind; ruleId: string; mode: "CHECKS" | "VERSIONS"; onClose: () => void }) {
  const [rows, setRows] = useState<(CheckRecord | HistoricalConditionVersion)[]>([]);
  const [cursor, setCursor] = useState<string | null>(null), [loading, setLoading] = useState(true), [error, setError] = useState(false);
  const more = useRef<(cursor: string | null) => void>(() => {});
  useEffect(() => {
    const controller = new AbortController(), epoch = getAuthEpoch(); let busy = false;
    setRows([]); setCursor(null);
    async function load(after: string | null) {
      if (busy) return; busy = true; setLoading(true); setError(false);
      try {
        const page = await (mode === "CHECKS" ? getRuleChecks(kind, ruleId, after, controller.signal) : getRuleVersions(kind, ruleId, after, controller.signal));
        if (controller.signal.aborted || epoch !== getAuthEpoch()) return;
        setRows(previous => after ? [...previous, ...page.items] : page.items); setCursor(page.nextCursor);
      } catch { if (!controller.signal.aborted && epoch === getAuthEpoch()) setError(true); }
      finally { if (!controller.signal.aborted && epoch === getAuthEpoch()) { busy = false; setLoading(false); } }
    }
    more.current = after => void load(after); void load(null);
    return () => controller.abort();
  }, [kind, ruleId, mode]);
  return <TradingAssistantDialog variant="rule" title={mode === "CHECKS" ? "验证记录" : "条件版本历史"} onClose={onClose}
    footer={<><TradingAssistantAction onClick={onClose}>返回详情</TradingAssistantAction><TradingAssistantAction disabled={loading || (!cursor && !error)} onClick={() => more.current(cursor)}>{error ? "重新读取" : "加载更多"}</TradingAssistantAction></>}>
    {loading && <p role="status">正在读取…</p>}{error && <p className="ta-form-error" role="alert">记录暂时无法读取，请重试。</p>}
    {!loading && !error && !rows.length && <p>暂无{mode === "CHECKS" ? "验证记录" : "条件历史"}</p>}
    {rows.map(row => <section className="ta-rule-evidence" key={"checkId" in row ? row.checkId : row.ruleVersionId}>
      {"checkId" in row ? <><h3>{checkTitle(row)}</h3><p>{ruleTime(row.requestedFrom)} — {ruleTime(row.requestedThrough)}</p><p>{row.coverageSummary}</p><p>{row.evidenceSummary}</p>{row.failureReason && <p>{row.failureReason}</p>}{row.missingRanges.map(range => <p key={range.from}>缺少：{ruleTime(range.from)} — {ruleTime(range.through)}</p>)}</>
        : <><h3>条件版本 {row.versionNo}</h3><p>{row.conditionSummary}</p><p>{ruleTime(row.effectiveAt)} 之后，至 {ruleTime(row.validThroughAt)}（含）</p></>}
    </section>)}
  </TradingAssistantDialog>;
}
