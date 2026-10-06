import { useState } from "react";
import type { Context } from "../api/contracts";
import { canContinue, isActive, numberText, recheckKind, timeText } from "../model/presentation";
import { useDownloads } from "../model/useDownloads";
import { Button, Empty, Field, Metrics, Notice, Panel } from "./primitives";
import { HistoryPanel } from "./HistoryPanel";
import { RunResults } from "./RunResults";
import { StopDialog } from "./StopDialog";
import { TaskProgress } from "./TaskProgress";
export function DownloadPanel({ context, enabled, routeRunId, onSelect, refreshContext }: { context: Context; enabled: boolean; routeRunId: string | null; onSelect: (id: string | null) => void; refreshContext: () => void }) {
  const d = useDownloads(context, enabled, routeRunId, onSelect, refreshContext);
  const [confirm, setConfirm] = useState(false); const [showResults, setShowResults] = useState(false);
  const t = d.run; const p = d.preview; const disabled = d.busy || d.unresolvedCommand;
  const ready = context.archiveAvailability === "ready" && context.sourceAvailability === "ready";
  return <>
    {context.currentRunId && context.currentRunId.replaceAll("-", "") !== routeRunId?.replaceAll("-", "") && routeRunId && <Notice danger={false}>另有活动任务。<Button onClick={() => onSelect(context.currentRunId)}>查看当前任务</Button></Notice>}
    {d.error && <Notice>{d.error}{d.unresolvedCommand && <div className="dc-actions"><Button onClick={d.refresh}>重新读取任务</Button><Button disabled={d.busy} onClick={d.retryCommand}>使用原操作重试</Button></div>}</Notice>}
    {!t && !d.runId ? <Panel title="创建下载" description="仅按公告日期下载该范围内全部公司、全部标题的公告。">
      <div className="dc-download-fields">
        <Field label="公告开始日期 *"><input aria-label="下载公告开始日期" type="date" value={d.startDate} aria-invalid={!!d.startDate && !!d.endDate && !!d.validation} onChange={e => d.setStart(e.target.value)} disabled={disabled || p?.state === "preparing"} /></Field>
        <Field label="公告结束日期 *"><input aria-label="下载公告结束日期" type="date" value={d.endDate} aria-invalid={!!d.startDate && !!d.endDate && !!d.validation} onChange={e => d.setEnd(e.target.value)} disabled={disabled || p?.state === "preparing"} /></Field>
        <Field label="请求间隔（秒）"><input aria-label="请求间隔（秒）" className="num" type="number" min="0" step="any" value={d.interval} onChange={e => d.setInterval(e.target.value)} disabled={disabled || p?.state === "preparing"} /></Field>
        <Field label="归档位置"><input aria-label="归档位置" className="num" value={context.archiveLocation} disabled /></Field>
        <div className="dc-preview-action"><Button tone="primary" disabled={disabled || !!d.validation || !ready || p?.state === "preparing"} onClick={d.prepare}>预览下载范围</Button></div>
      </div>
      <p className={d.validation && d.startDate && d.endDate ? "dc-danger" : "dc-secondary"}>{d.validation && d.startDate && d.endDate ? d.validation : `${ready ? "外盘已连接" : "外盘或公告来源暂不可用"} · 起止日期均包含 · 已有可用文件会复用 · 0 秒仅供调试`}</p>
    </Panel> : t ? <section className="dc-panel dc-range"><div><p>公告日期：<span className="num">{t.startDate} — {t.endDate}</span> · {t.batchKind === "date" ? "全部公司、全部标题" : "仅原任务失败文件"}</p><p className="dc-muted num">请求间隔 {t.intervalSeconds} 秒 · {t.archiveLocation}</p></div>
      <span className="dc-badge">{isActive(t) ? "已有活动任务" : t.batchKind === "date" ? "原日期任务" : "关联重试批次"}</span>
      {t.actions.canCreateNew && <Button disabled={disabled} onClick={() => { d.newDownload(); setShowResults(false); }}>新建日期下载</Button>}
    </section> : null}
    {p && <Panel title={p.state === "preparing" ? "正在准备下载范围" : "确认下载范围"} description={`${p.startDate} — ${p.endDate} · 全部公司、全部标题 · 间隔 ${p.intervalSeconds} 秒`}>
      {p.state === "preparing" ? <><p>已扫描 {p.preparation.datesScanned} / {p.preparation.datesTotal} 个公告日期 · {numberText(p.preparation.recordsScanned)} 条公告记录</p><div className="dc-progress indeterminate" role="progressbar" aria-label="正在准备下载范围" /><Button tone="danger" disabled={disabled} onClick={() => void d.stopPreview()}>停止准备</Button></> : <>
        <Metrics items={[["匹配公告记录", p.recordCount], ["对应归档文件", p.artifactCount], ["预计已有可复用", p.reusableEstimate], ["预计需下载", p.downloadEstimate, "dc-brand"], ["无 URL 公告", p.missingUrlCount, "muted"]]} />
        <p className="dc-secondary">公告记录与文件分别计数。无 URL 公告保留但无法下载，不计为下载失败。复用数量执行时再次核验。</p>
        {p.error && <Notice>{p.error.message}</Notice>}{p.state === "empty" && <Empty title="该日期范围没有可下载文件" />}{p.state === "cancelled" && <Notice danger={false}>范围准备已停止，可调整日期重新预览。</Notice>}
        <div className="dc-actions"><Button tone="primary" disabled={disabled || !p.canStart || p.state !== "ready"} onClick={d.start}>开始下载</Button><Button disabled={disabled} onClick={d.adjust}>调整日期</Button></div>
      </>}
    </Panel>}
    {t ? <>
      <TaskProgress task={t} error={d.observationError} busy={disabled} onStop={() => setConfirm(true)} />
      {t.blockedReason && <Panel title="任务阻断"><Notice>{t.blockedReason.message}。已归档成果保留，停止领取新文件。</Notice><div className="dc-actions">
        <Button tone="primary" disabled={disabled || !t.actions.canRecheck || t.check?.state === "checking"} onClick={() => d.recheck(recheckKind(t))}>{recheckKind(t) === "volume" ? "重新检查外盘" : "重新检查来源"}</Button><span className="dc-secondary">检查通过后，再手动继续未完成项。</span></div>
        {t.check && <p className="dc-secondary">{t.check.state === "checking" ? "检查中…" : t.check.state === "passed" ? "检查已通过" : "检查尚未通过"} · {timeText(t.check.updatedAt)}</p>}
      </Panel>}
      <div className="dc-actions dc-task-actions">{canContinue(t) && <Button tone="primary" disabled={disabled} onClick={d.continueRun}>继续未完成项</Button>}
        <Button disabled={disabled} onClick={() => setShowResults(v => !v)}>{showResults ? "收起文件结果" : t.failed > 0 ? "查看失败项" : "查看文件结果"}</Button>
        <Button disabled={d.observing} onClick={d.refresh}>重新读取任务</Button><Button onClick={() => { onSelect(null); setShowResults(false); }}>返回历史</Button></div>
      {(showResults || t.phase === "partial_failed") && <RunResults key={t.runId} task={t} busy={disabled} revision={d.historyRevision} onRetry={d.retry} onSelect={onSelect} />}
      {confirm && <StopDialog task={t} busy={d.busy} onCancel={() => setConfirm(false)} onConfirm={() => { d.stop(); setConfirm(false); }} />}
    </> : d.runId ? <Panel title="任务详情">{d.observationError ? <><Notice>{d.observationError}，任务暂不可获取。</Notice><Button onClick={d.refresh}>重新读取</Button><Button onClick={() => onSelect(null)}>返回历史</Button></> : <Empty title="正在读取任务…" />}</Panel> : !p && <Panel title="当前任务"><Empty title="当前没有运行中的下载任务">设置公告起止日期，预览范围后即可开始。关闭网页不会停止已启动的后台任务。</Empty></Panel>}
    {enabled && <HistoryPanel revision={d.historyRevision} onSelect={onSelect} />}
  </>;
}
