import type { MomentumRankingController } from "../model/useMomentumRankingController";
import { MomentumControlBar } from "./MomentumControlBar";
import { MomentumDetailPanel } from "./MomentumDetailPanel";
import { MomentumRankingPanel } from "./MomentumRankingPanel";
import { MomentumStateSurface } from "./MomentumStateSurface";
import "./sector-momentum.css";

export function MomentumRankingWorkspace({ controller }: { controller: MomentumRankingController }) {
  const { urlState, viewState } = controller;
  const meta = "meta" in viewState ? viewState.meta : undefined;
  const statusFacts = viewState.kind === "ready" || viewState.kind === "delayed"
    ? viewState.ranking
    : null;

  return (
    <div className="momentum-ranking-workspace">
      {meta && urlState ? (
        <MomentumControlBar
          meta={meta}
          onDirectionChange={controller.selectDirection}
          onLevel1Change={controller.selectLevel1}
          onLevel2Change={controller.selectLevel2}
          onPeriodChange={controller.selectPeriod}
          onScopeChange={controller.selectScope}
          onTradeDateChange={controller.selectTradeDate}
          state={urlState}
          statusLabel={statusFacts?.pageStatus.displayText ?? "正在加载行业事实"}
          statusTone={viewState.kind === "delayed" ? "delayed" : "ready"}
        />
      ) : <MomentumControlSkeleton />}

      {viewState.kind === "loading" ? <MomentumStateSurface kind="loading" /> : null}
      {viewState.kind === "empty" ? <MomentumStateSurface kind="empty" message={viewState.message} /> : null}
      {viewState.kind === "error" ? (
        <MomentumStateSurface kind="error" message={viewState.message} onRetry={controller.retry} retryable={viewState.retryable} />
      ) : null}
      {viewState.kind === "ready" || viewState.kind === "delayed" ? (
        <>
          {viewState.kind === "delayed" ? (
            <div className="momentum-delay-notice" role="status">
              当前展示 {viewState.ranking.tradingDay.observedTradeDate} 盘后数据；目标日期 {viewState.ranking.tradingDay.expectedTradeDate} 数据尚未完整。
            </div>
          ) : null}
          {viewState.ranking.tradingDay.observedAvailability === "PARTIAL" ? (
            <div className="momentum-partial-notice" role="status">
              当前日期部分行业缺少数据：{viewState.ranking.tradingDay.observedValidSectorCount}/{viewState.ranking.tradingDay.expectedSectorCount} 个行业已有有效事实，缺失行业仍保留在榜单中。
            </div>
          ) : null}
          <div className="momentum-ready-grid">
            <MomentumRankingPanel
              onDrillDown={controller.drillDown}
              onSelect={controller.selectSector}
              ranking={viewState.ranking}
              selectedCode={viewState.selectedCode}
            />
            <MomentumDetailPanel
              history={viewState.history}
              onRangeChange={controller.selectRange}
              period={urlState!.period}
              range={urlState!.range}
            />
          </div>
        </>
      ) : null}
    </div>
  );
}

function MomentumControlSkeleton() {
  return (
    <section className="momentum-control-bar momentum-control-skeleton" aria-hidden="true">
      <i /><i /><i /><i />
    </section>
  );
}
