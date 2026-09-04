export function DailyInsightStateSurface({ kind, message, retryable, onRetry }: { kind: "loading" | "empty" | "error"; message?: string; retryable?: boolean; onRetry?: () => void }) {
  return <section className={`daily-insight-state ${kind}`} role={kind === "error" ? "alert" : "status"} aria-label={kind === "loading" ? "每日洞察加载中" : undefined}>
    <span className="daily-insight-state-icon" aria-hidden="true">{kind === "loading" ? "…" : kind === "error" ? "!" : "—"}</span>
    <strong>{kind === "loading" ? "正在加载每日洞察" : kind === "empty" ? "暂无每日洞察" : "每日洞察加载失败"}</strong>
    <span>{message ?? "正在读取当日板块事实，请稍候。"}</span>
    {kind === "error" && retryable ? <button type="button" onClick={onRetry}>重新加载</button> : null}
  </section>;
}
