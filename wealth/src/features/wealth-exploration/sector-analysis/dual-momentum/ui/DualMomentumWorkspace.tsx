import type { SectorDualMomentumController } from "../model/useSectorDualMomentumController";
import { DualMomentumResultPanel } from "./DualMomentumResultPanel";
import { DualMomentumScatterPlot } from "./DualMomentumScatterPlot";
import { DualMomentumSelectedSummary } from "./DualMomentumSelectedSummary";
import { DualMomentumStateSurface } from "./DualMomentumStateSurface";
import { DualMomentumToolbar } from "./DualMomentumToolbar";
import "./sector-dual-momentum.css";

export function DualMomentumWorkspace({ controller }: { controller: SectorDualMomentumController }) {
  const { urlState, viewState } = controller;
  const meta = "meta" in viewState ? viewState.meta : undefined;
  const results = viewState.kind === "ready" || viewState.kind === "delayed" ? viewState.results : null;
  const statusLabel = results ? buildStatusLabel(results) : "正在加载行业事实";
  return (
    <div className="dual-momentum-workspace">
      {meta && urlState ? (
        <DualMomentumToolbar
          meta={meta}
          state={urlState}
          statusLabel={statusLabel}
          statusTone={viewState.kind === "delayed" ? "delayed" : "ready"}
          onLevel1Change={controller.selectLevel1}
          onLevel2Change={controller.selectLevel2}
          onPeriodChange={controller.selectPeriod}
          onScopeChange={controller.selectScope}
          onThresholdChange={controller.selectThreshold}
          onTradeDateChange={controller.selectTradeDate}
        />
      ) : <ToolbarSkeleton />}
      {viewState.kind === "loading" ? <DualMomentumStateSurface kind="loading" /> : null}
      {viewState.kind === "empty" ? <DualMomentumStateSurface kind="empty" message={viewState.message} /> : null}
      {viewState.kind === "error" ? <DualMomentumStateSurface kind="error" message={viewState.message} onRetry={controller.retry} retryable={viewState.retryable} /> : null}
      {viewState.kind === "ready" || viewState.kind === "delayed" ? (
        <div className="dual-momentum-ready-grid">
          <DualMomentumResultPanel controller={controller} />
          <div className="dual-momentum-right-column">
            <DualMomentumSelectedSummary controller={controller} />
            <DualMomentumScatterPlot controller={controller} />
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ToolbarSkeleton() {
  return <section aria-hidden="true" className="dual-momentum-toolbar dual-toolbar-skeleton"><i /><i /><i /><i /></section>;
}

function buildStatusLabel(results: { status: "READY" | "DELAYED"; pageStatus: { displayText: string }; tradingDay: { observedTradeDate: string | null; observedAvailability: string | null; observedValidSectorCount: number; expectedSectorCount: number } }) {
  if (results.status === "DELAYED") return `当前展示 ${results.tradingDay.observedTradeDate ?? "--"} 盘后数据`;
  if (results.tradingDay.observedAvailability === "PARTIAL") return `部分数据 ${results.tradingDay.observedValidSectorCount}/${results.tradingDay.expectedSectorCount}`;
  return results.pageStatus.displayText;
}
