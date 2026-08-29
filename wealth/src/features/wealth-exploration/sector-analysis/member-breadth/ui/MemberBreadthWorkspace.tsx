import { useEffect, useRef, useState } from "react";

import type { SectorMemberBreadthController } from "../model/useSectorMemberBreadthController";
import type { SectorMemberBreadthDetailsState } from "../model/sectorMemberBreadthTypes";
import { MemberBreadthCompositionBars } from "./MemberBreadthCompositionBars";
import { MemberBreadthMemberTable } from "./MemberBreadthMemberTable";
import { MemberBreadthRankingPanel } from "./MemberBreadthRankingPanel";
import { MemberBreadthSelectedSummary } from "./MemberBreadthSelectedSummary";
import { MemberBreadthStateSurface } from "./MemberBreadthStateSurface";
import { MemberBreadthToolbar } from "./MemberBreadthToolbar";
import { MemberBreadthTrendChart, type MemberBreadthTrendInspection } from "./MemberBreadthTrendChart";
import "./sector-member-breadth.css";

export function MemberBreadthWorkspace({ controller }: { controller: SectorMemberBreadthController }) {
  const { urlState, viewState } = controller; const meta = "meta" in viewState ? viewState.meta : undefined;
  const ready = viewState.kind === "ready" || viewState.kind === "delayed" ? viewState : null;
  const readyDetails = ready?.details.kind === "ready" ? ready.details.data : null;
  const [trendInspection, setTrendInspection] = useState<MemberBreadthTrendInspection>(null);
  const previousTrend = useRef(readyDetails?.trend ?? null);
  useEffect(() => {
    setTrendInspection(null);
  }, [urlState?.tradeDate, urlState?.sectorCode, urlState?.direction, urlState?.maPeriod, urlState?.historyRange]);
  useEffect(() => {
    if (viewState.kind === "empty" || viewState.kind === "error" || (ready && ready.details.kind !== "ready")) {
      previousTrend.current = null;
      setTrendInspection(null);
      return;
    }
    if (!readyDetails) return;
    if (previousTrend.current && previousTrend.current !== readyDetails.trend) setTrendInspection(null);
    previousTrend.current = readyDetails.trend;
  }, [ready, readyDetails, viewState.kind]);
  const statusLabel = ready ? ready.kind === "delayed" ? `当前展示 ${ready.rankings.tradeDate} 盘后数据` : `${ready.rankings.tradeDate} 盘后数据` : "正在加载成员广度事实";
  return <div className="member-breadth-workspace">
    {meta && urlState ? <MemberBreadthToolbar controller={controller} delayed={viewState.kind === "delayed"} meta={meta} state={urlState} statusLabel={statusLabel} /> : <ToolbarSkeleton />}
    {viewState.kind === "loading" ? <MemberBreadthStateSurface kind="loading" /> : null}
    {viewState.kind === "empty" ? <MemberBreadthStateSurface kind="empty" message={viewState.message} /> : null}
    {viewState.kind === "error" ? <MemberBreadthStateSurface kind="error" message={viewState.message} onRetry={controller.retry} retryable={viewState.retryable} /> : null}
    {ready && urlState ? <div className="member-breadth-ready-grid"><MemberBreadthRankingPanel controller={controller} rankings={ready.rankings} state={urlState} /><div className="member-breadth-detail-panel">{renderDetails(controller, ready.details, trendInspection, setTrendInspection)}</div></div> : null}
  </div>;
}
function renderDetails(controller: SectorMemberBreadthController, state: SectorMemberBreadthDetailsState, trendInspection: MemberBreadthTrendInspection, setTrendInspection: (inspection: MemberBreadthTrendInspection) => void): React.ReactNode {
  if (state.kind === "idle" || state.kind === "loading") return <MemberBreadthStateSurface kind="loading" local />;
  if (state.kind === "empty") return <MemberBreadthStateSurface kind="empty" local message={state.message} />;
  if (state.kind === "error") return <MemberBreadthStateSurface kind="error" local message={state.message} onRetry={controller.retryDetails} retryable={state.retryable} />;
  return <><MemberBreadthSelectedSummary details={state.data} pending={state.pending} /><MemberBreadthCompositionBars compositions={state.data.compositions} direction={state.data.direction} maPeriod={state.data.maPeriod} /><MemberBreadthTrendChart details={state.data} inspection={trendInspection} onInspectionChange={setTrendInspection} /><MemberBreadthMemberTable details={state.data} /></>;
}
function ToolbarSkeleton() { return <section aria-hidden="true" className="member-breadth-toolbar member-breadth-toolbar-skeleton"><i /><i /><i /><i /></section>; }
