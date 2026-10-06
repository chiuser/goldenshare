import type { Phase, RecheckKind, Task } from "../api/contracts";
export const numberText = (value: number | null) => value === null ? "—" : value.toLocaleString("en-US");
export const phaseText: Record<Phase, string> = { preparing: "正在准备", downloading: "正在下载", stopping: "停止中", completed: "全部成功", partial_failed: "已结束，存在失败项", cancelled: "准备已停止", blocked: "已阻断", stopped: "已停止", interrupted: "已中断" };
export const isActive = (t: Task) => ["preparing", "downloading", "stopping"].includes(t.phase) || t.check?.state === "checking";
export function sourceLink(value: string | null): string | null {
  if (!value) return null;
  try { const url = new URL(value); return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : null; } catch { return null; }
}
export function dateError(start: string, end: string): string | null {
  if (!start || !end) return "请选择公告起止日期";
  const valid = (s: string) => /^\d{4}-\d{2}-\d{2}$/.test(s) && Number.isFinite(Date.parse(s)) && new Date(s).toISOString().slice(0, 10) === s;
  if (!valid(start) || !valid(end)) return "请输入有效的公告日期";
  return end < start ? "结束日期不能早于开始日期，请调整后再预览。" : null;
}
export function intervalError(value: string): string | null {
  return value.trim() !== "" && Number.isFinite(Number(value)) && Number(value) >= 0 ? null : "请求间隔必须是非负有限数值";
}
export function recheckKind(task: Task): RecheckKind {
  const code = task.blockedReason?.code ?? "";
  if (code === "DC_REMOTE_BLOCKED") return "remoteSource";
  if (code.startsWith("DC_SOURCE") || code === "DC_INDEX_FAILED" || code === "DC_DEPENDENCY_UNAVAILABLE") return "localSource";
  return "volume";
}
export function canContinue(task: Task): boolean {
  return task.actions.canContinue && (task.blockedReason?.code !== "DC_REMOTE_BLOCKED" || (task.check?.kind === "remoteSource" && task.check.state === "passed"));
}
export function byteText(value: number): string { return value < 1024 * 1024 ? `${numberText(value)} B` : `${(value / 1024 / 1024).toFixed(1)} MB`; }
export function timeText(value: string | null): string {
  return value ? new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }) : "—";
}
export function waitText(task: Task, now: number): string | null {
  if (!task.wait) return null;
  const labels = { interval: "等待下一次请求", backoff: "等待重试退避", cooldown: "等待源站冷却" };
  const seconds = Math.max(0, Math.ceil((Date.parse(task.wait.until) - now) / 1000));
  return `${labels[task.wait.kind]} ${seconds} 秒`;
}
