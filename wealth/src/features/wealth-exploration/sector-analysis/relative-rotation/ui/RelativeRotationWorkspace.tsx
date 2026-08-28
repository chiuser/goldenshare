import type { SectorRelativeRotationController } from "../model/useSectorRelativeRotationController";
import { RelativeRotationIndustryList } from "./RelativeRotationIndustryList";
import { RelativeRotationPlot } from "./RelativeRotationPlot";
import { RelativeRotationStateSurface } from "./RelativeRotationStateSurface";
import { RelativeRotationToolbar } from "./RelativeRotationToolbar";
import "./sector-relative-rotation.css";

export function RelativeRotationWorkspace({ controller }: { controller: SectorRelativeRotationController }) {
  const { urlState, viewState } = controller;
  const meta = "meta" in viewState ? viewState.meta : undefined;
  const results = viewState.kind === "ready" || viewState.kind === "delayed" ? viewState.results : null;
  const statusLabel = results ? buildStatusLabel(results) : "正在加载行业事实";
  return (
    <div className="relative-rotation-workspace">
      {meta && urlState ? <RelativeRotationToolbar meta={meta} state={urlState} statusLabel={statusLabel} statusTone={viewState.kind === "delayed" ? "delayed" : "ready"} onLevel1Change={controller.selectLevel1} onLevel2Change={controller.selectLevel2} onPeriodChange={controller.selectPeriod} onScopeChange={controller.selectScope} onTradeDateChange={controller.selectTradeDate} onTrailLengthChange={controller.selectTrailLength} /> : <ToolbarSkeleton />}
      {viewState.kind === "loading" ? <RelativeRotationStateSurface kind="loading" /> : null}
      {viewState.kind === "empty" ? <RelativeRotationStateSurface kind="empty" message={viewState.message} /> : null}
      {viewState.kind === "error" ? <RelativeRotationStateSurface kind="error" message={viewState.message} onRetry={controller.retry} retryable={viewState.retryable} /> : null}
      {viewState.kind === "ready" || viewState.kind === "delayed" ? <div className="relative-rotation-ready-grid"><RelativeRotationPlot controller={controller} /><RelativeRotationIndustryList controller={controller} /></div> : null}
    </div>
  );
}
function ToolbarSkeleton() { return <section aria-hidden="true" className="relative-rotation-toolbar relative-toolbar-skeleton"><i /><i /><i /><i /></section>; }
function buildStatusLabel(results: { status: "READY" | "DELAYED"; pageStatus: { displayText: string }; tradingDay: { observedTradeDate: string | null; observedAvailability: string | null; observedValidSectorCount: number; expectedSectorCount: number } }) {
  if (results.status === "DELAYED") return `当前展示 ${results.tradingDay.observedTradeDate ?? "--"} 盘后数据`;
  if (results.tradingDay.observedAvailability === "PARTIAL") return `部分数据 ${results.tradingDay.observedValidSectorCount}/${results.tradingDay.expectedSectorCount}`;
  return results.pageStatus.displayText;
}
