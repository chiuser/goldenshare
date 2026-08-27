interface MomentumStateSurfaceProps {
  kind: "loading" | "empty" | "error";
  message?: string;
  retryable?: boolean;
  onRetry?: () => void;
}

export function MomentumStateSurface({ kind, message, retryable = false, onRetry }: MomentumStateSurfaceProps) {
  if (kind === "loading") {
    return (
      <section className="momentum-state-surface momentum-loading-state" aria-busy="true" aria-label="动量排名加载中">
        <div className="momentum-loading-list">
          {Array.from({ length: 10 }, (_, index) => <i key={index} />)}
        </div>
        <div className="momentum-loading-charts">
          <i />
          <i />
        </div>
      </section>
    );
  }
  return (
    <section className={`momentum-state-surface momentum-${kind}-state`} role={kind === "error" ? "alert" : "status"}>
      <div className="momentum-state-icon" aria-hidden="true">{kind === "error" ? "!" : "—"}</div>
      <strong>{kind === "error" ? "板块分析加载失败" : "当前条件下暂无可计算数据"}</strong>
      <span>{message ?? (kind === "error" ? "请稍后重试。" : "可以调整日期、范围或统计周期后再查看。")}</span>
      {kind === "error" && retryable && onRetry ? <button type="button" onClick={onRetry}>重新加载</button> : null}
    </section>
  );
}
