import type { SectorPriceVolumeController } from "../model/useSectorPriceVolumeController";
import { PriceVolumeHistoryCharts } from "./PriceVolumeHistoryCharts";
import { PriceVolumeIndustryList } from "./PriceVolumeIndustryList";
import { PriceVolumeScatterPlot } from "./PriceVolumeScatterPlot";
import { PriceVolumeSelectedSummary } from "./PriceVolumeSelectedSummary";
import { PriceVolumeStateSurface } from "./PriceVolumeStateSurface";
import { PriceVolumeToolbar, PriceVolumeToolbarSkeleton } from "./PriceVolumeToolbar";
import "./sector-price-volume.css";

export function PriceVolumeWorkspace({ controller }: { controller: SectorPriceVolumeController }) {
  const { urlState, viewState } = controller;
  const meta = "meta" in viewState ? viewState.meta : undefined;
  const snapshot = viewState.kind === "ready" || viewState.kind === "delayed" ? viewState.snapshot : "snapshot" in viewState ? viewState.snapshot : undefined;
  const statusLabel = buildStatusLabel(viewState);
  return <div className="price-volume-workspace">
    {meta && urlState ? <PriceVolumeToolbar meta={meta} state={urlState} statusLabel={statusLabel} statusTone={viewState.kind === "delayed" ? "delayed" : viewState.kind === "error" ? "error" : viewState.kind === "loading" ? "loading" : "ready"} onLevel1Change={controller.selectLevel1} onLevel2Change={controller.selectLevel2} onPeriodChange={controller.selectPeriod} onScopeChange={controller.selectScope} onStateFilterChange={controller.selectStateFilter} onTradeDateChange={controller.selectTradeDate} /> : <PriceVolumeToolbarSkeleton />}
    {viewState.kind === "loading" ? <PriceVolumeStateSurface kind="loading" /> : null}
    {viewState.kind === "empty" ? <PriceVolumeStateSurface kind="empty" message={viewState.message} /> : null}
    {viewState.kind === "error" ? <PriceVolumeStateSurface kind="error" message={viewState.message} onRetry={controller.retry} retryable={viewState.retryable} /> : null}
    {viewState.kind === "ready" || viewState.kind === "delayed" ? <div className="price-volume-ready-grid"><PriceVolumeIndustryList controller={controller} /><div className="price-volume-right-column"><PriceVolumeSelectedSummary controller={controller} /><PriceVolumeScatterPlot controller={controller} /><PriceVolumeHistoryCharts controller={controller} /></div></div> : null}
    {viewState.kind === "empty" && snapshot ? <span className="sr-only">{snapshot.totalCount} 个行业，{snapshot.coordinateCount} 个完整坐标</span> : null}
  </div>;
}

function buildStatusLabel(viewState: SectorPriceVolumeController["viewState"]) { if (viewState.kind === "delayed") return `当前展示 ${viewState.snapshot.observedTradeDate} 盘后数据`; if (viewState.kind === "ready") return `${viewState.snapshot.totalCount} 个行业 · ${viewState.snapshot.coordinateCount} 可计算 · ${viewState.snapshot.missingCoordinateCount} 缺失`; if (viewState.kind === "empty" && viewState.snapshot) return `${viewState.snapshot.totalCount} 个行业 · 0 可计算 · ${viewState.snapshot.missingCoordinateCount} 缺失`; if (viewState.kind === "error") return "量价分布加载失败"; return "正在加载量价分布事实"; }
