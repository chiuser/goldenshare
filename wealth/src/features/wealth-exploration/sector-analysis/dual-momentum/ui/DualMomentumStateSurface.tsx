interface DualMomentumStateSurfaceProps {
  kind: "loading" | "empty" | "error";
  message?: string;
  retryable?: boolean;
  onRetry?: () => void;
}

export function DualMomentumStateSurface({ kind, message, retryable = false, onRetry }: DualMomentumStateSurfaceProps) {
  if (kind === "loading") {
    return (
      <section aria-busy="true" aria-label="双动量加载中" className="dual-state-surface dual-loading-state">
        <div>{Array.from({ length: 10 }, (_, index) => <i key={index} />)}</div><div><i /><i /><i /></div>
      </section>
    );
  }
  return (
    <section className={`dual-state-surface dual-${kind}-state`} role={kind === "error" ? "alert" : "status"}>
      <div className="dual-state-icon" aria-hidden="true">{kind === "error" ? "!" : "—"}</div>
      <strong>{kind === "error" ? "双动量加载失败" : "当前条件下暂无可计算数据"}</strong>
      <span>{message ?? (kind === "error" ? "请稍后重试。" : "可以调整日期、范围或观察周期后再查看。")}</span>
      {kind === "error" && retryable && onRetry ? <button type="button" onClick={onRetry}>重新加载</button> : null}
    </section>
  );
}
