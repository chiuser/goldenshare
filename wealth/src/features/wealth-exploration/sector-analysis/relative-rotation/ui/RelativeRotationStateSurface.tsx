interface RelativeRotationStateSurfaceProps {
  kind: "loading" | "empty" | "error";
  message?: string;
  retryable?: boolean;
  onRetry?: () => void;
}
export function RelativeRotationStateSurface({ kind, message, retryable = false, onRetry }: RelativeRotationStateSurfaceProps) {
  if (kind === "loading") {
    return (
      <section aria-busy="true" aria-label="相对轮动加载中" className="relative-state-surface relative-loading-state">
        <div><i /><i /><i /></div><div>{Array.from({ length: 12 }, (_, index) => <i key={index} />)}</div>
      </section>
    );
  }
  return (
    <section className={`relative-state-surface relative-${kind}-state`} role={kind === "error" ? "alert" : "status"}>
      <div className="relative-state-icon" aria-hidden="true">{kind === "error" ? "!" : "—"}</div>
      <strong>{kind === "error" ? "相对轮动加载失败" : "当前条件下暂无可计算数据"}</strong>
      <span>{message ?? (kind === "error" ? "请稍后重试。" : "可以调整日期、比较范围或强度周期后再查看。")}</span>
      {kind === "error" && retryable && onRetry ? <button type="button" onClick={onRetry}>重新加载</button> : null}
    </section>
  );
}
