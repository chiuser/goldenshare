import { useCallback } from "react";

import {
  buildSectorAnalysisDualMomentumPath,
  buildSectorAnalysisMomentumPath,
  buildSectorAnalysisMemberBreadthPath,
  buildSectorAnalysisRelativeRotationPath,
  navigateWealth,
} from "../../app/routes/routerState";
import { useSectorMemberBreadthController } from "../../features/wealth-exploration/sector-analysis/member-breadth/model/useSectorMemberBreadthController";
import { MemberBreadthStateSurface } from "../../features/wealth-exploration/sector-analysis/member-breadth/ui/MemberBreadthStateSurface";
import { MemberBreadthWorkspace } from "../../features/wealth-exploration/sector-analysis/member-breadth/ui/MemberBreadthWorkspace";
import { useSectorDualMomentumController } from "../../features/wealth-exploration/sector-analysis/dual-momentum/model/useSectorDualMomentumController";
import { DualMomentumStateSurface } from "../../features/wealth-exploration/sector-analysis/dual-momentum/ui/DualMomentumStateSurface";
import { DualMomentumWorkspace } from "../../features/wealth-exploration/sector-analysis/dual-momentum/ui/DualMomentumWorkspace";
import { SectorAnalysisMethodBar, type SectorAnalysisMethod } from "../../features/wealth-exploration/sector-analysis/navigation/SectorAnalysisMethodBar";
import { useSectorRelativeRotationController } from "../../features/wealth-exploration/sector-analysis/relative-rotation/model/useSectorRelativeRotationController";
import { RelativeRotationStateSurface } from "../../features/wealth-exploration/sector-analysis/relative-rotation/ui/RelativeRotationStateSurface";
import { RelativeRotationWorkspace } from "../../features/wealth-exploration/sector-analysis/relative-rotation/ui/RelativeRotationWorkspace";
import { useMomentumRankingController } from "../../features/wealth-exploration/sector-analysis/momentum-ranking/model/useMomentumRankingController";
import { MomentumRankingWorkspace } from "../../features/wealth-exploration/sector-analysis/momentum-ranking/ui/MomentumRankingWorkspace";
import { MomentumStateSurface } from "../../features/wealth-exploration/sector-analysis/momentum-ranking/ui/MomentumStateSurface";
import { WealthExplorationShell } from "./layout/WealthExplorationShell";
import type { WealthExplorationShellRenderProps } from "./layout/WealthExplorationShell";
import "./wealth-exploration-page.css";

interface SectorAnalysisPageProps {
  method: SectorAnalysisMethod;
  search?: string;
}

export function SectorAnalysisPage({ method, search }: SectorAnalysisPageProps) {
  return (
    <WealthExplorationShell activeShortcutKey="sector-analysis" currentPageLabel="板块分析" search={search}>
      {(shell) => <SectorAnalysisContent method={method} search={search} shell={shell} />}
    </WealthExplorationShell>
  );
}

function SectorAnalysisContent({ method, search, shell }: { method: SectorAnalysisMethod; search?: string; shell: WealthExplorationShellRenderProps }) {
  const routeSearch = search ?? window.location.search;
  const requestedTradeDate = new URLSearchParams(routeSearch).get("tradeDate");
  const contextMatchesRoute = requestedTradeDate === null
    || shell.model.pageContext?.tradeDate === requestedTradeDate;
  const handleMethodSelect = useCallback((nextMethod: SectorAnalysisMethod) => {
    if (nextMethod === method) return;
    const sharedSearch = buildSharedMethodSearch(routeSearch);
    const path = nextMethod === "momentum-ranking"
      ? buildSectorAnalysisMomentumPath(sharedSearch)
      : nextMethod === "dual-momentum"
        ? buildSectorAnalysisDualMomentumPath(sharedSearch)
        : nextMethod === "relative-rotation"
          ? buildSectorAnalysisRelativeRotationPath(sharedSearch)
          : buildSectorAnalysisMemberBreadthPath(buildMemberBreadthSharedSearch(routeSearch));
    navigateWealth(path);
  }, [method, routeSearch]);

  return (
    <>
      <SectorAnalysisMethodBar
        activeMethod={method}
        onSelect={handleMethodSelect}
        onUnavailable={() => shell.showToast("待建设")}
      />
      {method === "momentum-ranking" ? <MomentumMethodContent contextMatchesRoute={contextMatchesRoute} routeSearch={routeSearch} shell={shell} /> : null}
      {method === "dual-momentum" ? <DualMomentumMethodContent contextMatchesRoute={contextMatchesRoute} routeSearch={routeSearch} shell={shell} /> : null}
      {method === "relative-rotation" ? <RelativeRotationMethodContent contextMatchesRoute={contextMatchesRoute} routeSearch={routeSearch} shell={shell} /> : null}
      {method === "member-breadth" ? <MemberBreadthMethodContent contextMatchesRoute={contextMatchesRoute} routeSearch={routeSearch} shell={shell} /> : null}
    </>
  );
}

function MemberBreadthMethodContent({ contextMatchesRoute, routeSearch, shell }: { contextMatchesRoute: boolean; routeSearch: string; shell: WealthExplorationShellRenderProps }) {
  const handleNavigateSearch = useCallback((nextSearch: string, options?: { replace?: boolean }) => {
    navigateWealth(buildSectorAnalysisMemberBreadthPath(nextSearch), options);
  }, []);
  const controller = useSectorMemberBreadthController({
    enabled: shell.model.contextState === "ready" && contextMatchesRoute,
    search: routeSearch,
    onNavigateSearch: handleNavigateSearch,
  });
  if (shell.model.contextState === "error") return <div className="member-breadth-workspace"><MemberBreadthStateSurface kind="error" message={shell.contextErrorMessage ?? "页面时间上下文加载失败。"} onRetry={shell.model.retryContext} retryable /></div>;
  return <MemberBreadthWorkspace controller={controller} />;
}

function MomentumMethodContent({ contextMatchesRoute, routeSearch, shell }: { contextMatchesRoute: boolean; routeSearch: string; shell: WealthExplorationShellRenderProps }) {
  const handleNavigateSearch = useCallback((nextSearch: string, options?: { replace?: boolean }) => {
    navigateWealth(buildSectorAnalysisMomentumPath(nextSearch), options);
  }, []);
  const controller = useMomentumRankingController({
    enabled: shell.model.contextState === "ready" && contextMatchesRoute,
    search: routeSearch,
    onNavigateSearch: handleNavigateSearch,
  });

  if (shell.model.contextState === "error") return (
    <div className="momentum-ranking-workspace"><MomentumStateSurface kind="error" message={shell.contextErrorMessage ?? "页面时间上下文加载失败。"} onRetry={shell.model.retryContext} retryable /></div>
  );
  return <MomentumRankingWorkspace controller={controller} />;
}

function DualMomentumMethodContent({ contextMatchesRoute, routeSearch, shell }: { contextMatchesRoute: boolean; routeSearch: string; shell: WealthExplorationShellRenderProps }) {
  const handleNavigateSearch = useCallback((nextSearch: string, options?: { replace?: boolean }) => {
    navigateWealth(buildSectorAnalysisDualMomentumPath(nextSearch), options);
  }, []);
  const controller = useSectorDualMomentumController({
    enabled: shell.model.contextState === "ready" && contextMatchesRoute,
    search: routeSearch,
    onNavigateSearch: handleNavigateSearch,
  });
  if (shell.model.contextState === "error") return (
    <div className="dual-momentum-workspace"><DualMomentumStateSurface kind="error" message={shell.contextErrorMessage ?? "页面时间上下文加载失败。"} onRetry={shell.model.retryContext} retryable /></div>
  );
  return <DualMomentumWorkspace controller={controller} />;
}

function RelativeRotationMethodContent({ contextMatchesRoute, routeSearch, shell }: { contextMatchesRoute: boolean; routeSearch: string; shell: WealthExplorationShellRenderProps }) {
  const handleNavigateSearch = useCallback((nextSearch: string, options?: { replace?: boolean }) => {
    navigateWealth(buildSectorAnalysisRelativeRotationPath(nextSearch), options);
  }, []);
  const controller = useSectorRelativeRotationController({
    enabled: shell.model.contextState === "ready" && contextMatchesRoute,
    search: routeSearch,
    onNavigateSearch: handleNavigateSearch,
  });
  if (shell.model.contextState === "error") return (
    <div className="relative-rotation-workspace"><RelativeRotationStateSurface kind="error" message={shell.contextErrorMessage ?? "页面时间上下文加载失败。"} onRetry={shell.model.retryContext} retryable /></div>
  );
  return <RelativeRotationWorkspace controller={controller} />;
}

function buildSharedMethodSearch(search: string): string {
  const source = new URLSearchParams(search);
  const target = new URLSearchParams();
  const market = source.get("market");
  const debug = source.get("debug");
  const tradeDate = source.get("tradeDate");
  if (market === "CN_A") target.set("market", market);
  if (debug === "1") target.set("debug", debug);
  if (tradeDate) target.set("tradeDate", tradeDate);
  const query = target.toString();
  return query ? `?${query}` : "";
}

function buildMemberBreadthSharedSearch(search: string): string {
  const source = new URLSearchParams(search);
  const target = new URLSearchParams();
  const market = source.get("market");
  const tradeDate = source.get("tradeDate");
  if (market === "CN_A") target.set("market", market);
  if (tradeDate) target.set("tradeDate", tradeDate);
  const query = target.toString();
  return query ? `?${query}` : "";
}
