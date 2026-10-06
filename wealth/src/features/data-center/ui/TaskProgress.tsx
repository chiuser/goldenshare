import { useEffect, useState } from "react";
import type { Task } from "../api/contracts";
import { clientPolicy } from "../api/clientPolicy";
import { byteText, numberText, phaseText, timeText, waitText } from "../model/presentation";
import { Button, Metrics, Notice, Panel } from "./primitives";
export function TaskProgress({ task: t, error, busy, onStop }: { task: Task; error: string | null; busy: boolean; onStop: () => void }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer); }, []);
  const waiting = waitText(t, now);
  const stale = ["preparing", "downloading", "stopping"].includes(t.phase) && now - Date.parse(t.businessUpdatedAt) > clientPolicy.staleSeconds * 1000;
  const title = t.phase === "downloading" && t.batchKind === "retry" ? (t.total === 1 ? "正在重试单个失败文件" : "正在重试原任务失败项") : phaseText[t.phase];
  const current = t.current;
  return <Panel title={title} description={t.phase === "stopping" ? "正在安全结束当前文件处理；已归档成果保留，不再领取新文件。" : "范围与已归档成果已保存，任务不会因切换页面而停止。"}
    action={t.phase === "stopping" ? <Button tone="danger" disabled>停止中…</Button> : t.actions.canStop ? <Button tone="danger" disabled={busy} onClick={onStop}>{t.phase === "preparing" ? "停止准备" : "停止任务"}</Button> : undefined}>
    {error && <Notice>{error}。正在显示最后读取的任务状态，执行阶段尚无法重新确认。</Notice>}
    {t.total === null ? <><p>已扫描 {numberText(t.preparation.datesScanned)} / {numberText(t.preparation.datesTotal)} 个公告日期 · {numberText(t.recordCount)} 条公告记录 · 正在统计文件总量</p>
      <div className="dc-progress indeterminate" role="progressbar" aria-label="正在准备文件总量" /><p className="dc-secondary">总量尚未确定，暂不显示百分比。{t.preparation.currentDate ? `当前日期：${t.preparation.currentDate}` : ""}</p></> : <>
      <Metrics items={[["新下载成功", t.succeeded, "dc-brand"], ["已有文件复用", t.reused], ["失败", t.failed, t.failed ? "dc-danger" : "muted"], ["剩余", t.remaining], ["无 URL 公告", t.missingUrlCount, "muted"]]} />
      <p>{t.batchKind === "retry" ? "本次重试" : ""}已处理 <span className="num">{numberText(t.processed)} / {numberText(t.total)}</span> 个文件{t.percent === null ? "" : `（${numberText(t.percent)}%）`}</p>
      <div className="dc-progress" role="progressbar" aria-label="文件处理进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={t.percent ?? undefined}>
        {t.percent !== null && <span style={{ width: `${t.percent}%` }} />}
      </div>
    </>}
    {current && <div className="dc-current"><div><p title={current.title ?? undefined}>{current.annDate} · {current.tsCode ?? "—"} {current.companyName} · {current.title ?? "—"}</p>
      <p className="dc-secondary">自动尝试 {current.attemptNumber} / {current.maxAttempts} · {current.transferState === "verifying" ? "正在校验，完成后计入成功" : `已接收 ${byteText(current.bytesReceived)}${current.bytesTotal == null ? " · 文件总字节未知" : ` / ${byteText(current.bytesTotal)}（${Math.min(100, current.bytesTotal > 0 ? current.bytesReceived / current.bytesTotal * 100 : 0).toFixed(1)}%）`}`}</p></div>
      <span className="dc-info">{waiting ?? (current.transferState === "verifying" ? "校验中" : "下载中")}</span></div>}
    {!current && waiting && <p className="dc-info">{waiting}</p>}
    {t.phase === "partial_failed" && <p className="dc-secondary">处理进度已完成，仍有 {numberText(t.failed)} 个文件失败。已成功的文件不会重复请求。</p>}
    {t.phase === "completed" && <p className="dc-secondary">全部 {numberText(t.total)} 个归档文件处理成功。另有 {numberText(t.missingUrlCount)} 条无 URL 公告已保留，无法下载。</p>}
    {t.phase === "interrupted" && <p className="dc-secondary">后端执行已中断。成果保留，请手动继续原任务未完成项。</p>}
    {t.phase === "stopped" && <p className="dc-secondary">保留已完成文件；继续只处理原任务剩余 {numberText(t.remaining)} 个文件，失败项另行重试。</p>}
    {t.phase === "cancelled" && <p className="dc-secondary">准备已停止；本次准备不能继续下载，可重新设置日期并预览。</p>}
    {t.actions.reason && !["preparing", "downloading", "stopping"].includes(t.phase) && <Notice danger={false}>{t.actions.reason}</Notice>}
    {t.batchKind === "retry" && <Notice danger={false}>仅恢复原任务失败文件。本次重试作为关联批次；原始结果保留，不扩大到同日或同公司公告。</Notice>}
    <p className="dc-muted">请求间隔 {t.intervalSeconds} 秒 · 最近业务更新 {timeText(t.businessUpdatedAt)} · 存活确认 {timeText(t.heartbeatAt)} · 剩余时间暂无法估算</p>
    {stale && <Notice danger={false}>超过 15 秒没有新的业务进度。任务阶段保持最后读取值，存活确认不代表文件已完成。</Notice>}
  </Panel>;
}
