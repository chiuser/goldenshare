import { useCallback, useEffect, useState } from "react";
import type { ResultFilter, Task } from "../api/contracts";
import { dataCenterApi } from "../api/dataCenterApi";
import { phaseText, timeText } from "../model/presentation";
import { useObserver } from "../model/useObserver";
import { Button, Empty, Notice, Pagination, Panel } from "./primitives";
const labels = { pending: "未完成", processing: "处理中", succeeded: "成功", reused: "复用", failed: "失败" };
export function RunResults({ task, busy, revision, onRetry, onSelect }: { task: Task; busy: boolean; revision: number; onRetry: (key: string | null) => void; onSelect: (id: string) => void }) {
  const [filter, setFilter] = useState<ResultFilter>(task.failed > 0 ? "failed" : "all");
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [relatedCursors, setRelatedCursors] = useState<(string | null)[]>([null]);
  useEffect(() => { setCursors([null]); setRelatedCursors([null]); setFilter(task.failed > 0 ? "failed" : "all"); }, [task.runId]);
  const read = useCallback((s: AbortSignal) => dataCenterApi.files(task.runId, filter, cursors.at(-1), s), [task.runId, filter, cursors, revision]);
  const relatedRead = useCallback((s: AbortSignal) => dataCenterApi.related(task.runId, relatedCursors.at(-1), s), [task.runId, relatedCursors, revision]);
  const files = useObserver(read); const related = useObserver(relatedRead);
  return <>
    <Panel title={filter === "failed" ? `失败文件 · ${task.failed} 个` : "文件结果"} description={`原批次失败 ${task.failed} 个 · 尚未解决 ${task.unresolvedFailureCount} 个；原始结果保持不变。`}
      action={<div className="dc-actions"><select aria-label="文件结果筛选" value={filter} onChange={e => { setFilter(e.target.value as ResultFilter); setCursors([null]); }}>{(["all", "failed", "pending", "succeeded", "reused"] as const).map(k => <option key={k} value={k}>{k === "all" ? "全部结果" : labels[k]}</option>)}</select>
        {task.failed > 0 && <Button tone="primary" disabled={busy || !task.actions.canRetryFailed} onClick={() => onRetry(null)}>重试全部失败项</Button>}</div>}>
      {files.error && <Notice>{files.error}<Button onClick={files.refresh}>重新读取</Button></Notice>}
      {!files.value && !files.error && <Empty title="正在读取文件结果…" />}
      {files.value?.items.length === 0 && <Empty title="没有匹配的文件结果" />}
      {!!files.value?.items.length && <div className="dc-table-scroll"><table className="dc-table dc-files"><colgroup><col /><col /><col /><col /><col /></colgroup><thead><tr><th>公告日期</th><th>公司代码</th><th>标题</th><th>结果 / 原始原因</th><th>操作</th></tr></thead><tbody>{files.value.items.map(f => <tr key={f.artifactKey}><td className="num">{f.annDate ?? "—"}</td><td className="num">{f.tsCode ?? "—"}</td>
        <td><details className="dc-long"><summary title={f.title ?? undefined}>{f.title || "—"}</summary><p>{f.companyName} · {f.title || "—"}</p></details></td>
        <td>{f.lastError ? <details className="dc-long"><summary title={f.lastError.message}>{f.lastError.httpStatus ? `HTTP ${f.lastError.httpStatus} · ` : ""}{f.lastError.message} · 已尝试 {f.attempts} 次</summary><p>{f.lastError.message}{f.lastError.httpStatus ? `（HTTP ${f.lastError.httpStatus}）` : ""} · 本批尝试 {f.attempts} 次</p></details> : labels[f.result]}</td>
        <td>{f.result === "failed" ? <button className="dc-link" type="button" disabled={busy || !f.canRetry || !task.actions.canRetryFailed} onClick={() => onRetry(f.artifactKey)}>重试</button> : "—"}</td></tr>)}</tbody></table></div>}
      <Pagination previous={cursors.length > 1} next={!!files.value?.nextCursor} disabled={files.loading} onPrevious={() => setCursors(c => c.slice(0, -1))} onNext={() => setCursors(c => [...c, files.value!.nextCursor])}>第 {cursors.length} 页 · 每页最多 50 个文件</Pagination>
    </Panel>
    <Panel title="关联任务" description="原日期任务及关联重试批次分别计数；查看任一批次不会改变原结果。">
      <div className="dc-actions"><button type="button" className="dc-link" onClick={() => onSelect(task.rootRunId)}>查看原日期任务</button>{task.retryOfRunId && <button type="button" className="dc-link" onClick={() => onSelect(task.retryOfRunId!)}>查看重试来源批次</button>}</div>
      {related.error && <Notice>{related.error}</Notice>}
      {related.value?.items.map(r => <div className="dc-related" key={r.runId}><span>{timeText(r.createdAt)} · {phaseText[r.phase as Task["phase"]] ?? r.phase} · 成功 {r.succeeded} / 复用 {r.reused} / 失败 {r.failed}</span><button type="button" className="dc-link" onClick={() => onSelect(r.runId)}>查看详情</button></div>)}
      <Pagination previous={relatedCursors.length > 1} next={!!related.value?.nextCursor} disabled={related.loading} onPrevious={() => setRelatedCursors(c => c.slice(0, -1))} onNext={() => setRelatedCursors(c => [...c, related.value!.nextCursor])}>第 {relatedCursors.length} 页 · 每页最多 20 个任务</Pagination>
    </Panel>
  </>;
}
