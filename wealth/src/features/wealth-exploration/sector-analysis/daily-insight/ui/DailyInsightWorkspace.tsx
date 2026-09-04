import { useCallback, useEffect, useState } from "react";
import type { DailyInsightRowViewModel } from "../api/sectorDailyInsightTypes";
import { dailyInsightDestination, type DailyInsightDestination } from "../model/sectorDailyInsightNavigation";
import type { SectorDailyInsightController } from "../model/useSectorDailyInsightController";
import { DailyInsightExplanationDialog } from "./DailyInsightExplanationDialog";
import { DailyInsightOverview } from "./DailyInsightOverview";
import { DailyInsightPanel } from "./DailyInsightPanel";
import { DailyInsightStateSurface } from "./DailyInsightStateSurface";
import { DailyInsightToolbar } from "./DailyInsightToolbar";
import "./sector-daily-insight.css";

export function DailyInsightWorkspace({ controller, onNavigate }: { controller: SectorDailyInsightController; onNavigate: (destination: DailyInsightDestination) => void }) {
  const { viewState, identity } = controller;
  const snapshot = viewState.kind === "ready" || viewState.kind === "delayed" ? viewState.snapshot : null;
  const [explanation, setExplanation] = useState<{ identity: string; row: DailyInsightRowViewModel; trigger: HTMLButtonElement } | null>(null);
  const closeExplanation = useCallback(() => setExplanation(null), []);
  useEffect(closeExplanation, [identity, closeExplanation]);
  const active = snapshot && explanation?.identity === identity ? explanation : null;
  const explain = (row: DailyInsightRowViewModel, trigger: HTMLButtonElement) => setExplanation({ identity, row, trigger });
  const goToSector = (row: DailyInsightRowViewModel) => { if (snapshot) onNavigate(dailyInsightDestination(row, snapshot.facts.observedTradeDate)); };
  const previousMissing = Boolean(snapshot?.facts.summary.missingPreviousBatchCount);
  return <div className="daily-insight-workspace">
    <DailyInsightToolbar controller={controller} />
    {!snapshot ? <DailyInsightStateSurface kind={viewState.kind === "error" ? "error" : viewState.kind === "empty" ? "empty" : "loading"} message={viewState.message} retryable={viewState.retryable} onRetry={controller.retry} /> : <>
      <DailyInsightOverview snapshot={snapshot} />
      <div className="daily-insight-panels">
        <DailyInsightPanel title="头部上涨" subtitle="按当日涨幅排序" rows={snapshot.headGainers} emptyMessage="当日无上涨行业" selected={active?.row ?? null} onSector={goToSector} onExplain={explain} />
        <DailyInsightPanel title="显著转强" subtitle="较上一交易日" rows={snapshot.strengthening} emptyMessage={previousMissing ? "上一交易日事实不可比较" : "当日无显著转强行业"} selected={active?.row ?? null} onSector={goToSector} onExplain={explain} />
        <DailyInsightPanel title="头部下跌" subtitle="按当日跌幅排序" rows={snapshot.headLosers} emptyMessage="当日无下跌行业" selected={active?.row ?? null} onSector={goToSector} onExplain={explain} />
        <DailyInsightPanel title="显著转弱" subtitle="较上一交易日" rows={snapshot.weakening} emptyMessage={previousMissing ? "上一交易日事实不可比较" : "当日无显著转弱行业"} selected={active?.row ?? null} onSector={goToSector} onExplain={explain} />
      </div>
    </>}
    {active && snapshot ? <DailyInsightExplanationDialog row={active.row} tradeDate={snapshot.facts.observedTradeDate} trigger={active.trigger} onClose={closeExplanation} onNavigate={(destination) => { closeExplanation(); onNavigate(destination); }} /> : null}
  </div>;
}
