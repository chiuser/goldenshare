import { useCallback } from "react";

import {
  buildSectorAnalysisMomentumPath,
  navigateWealth,
} from "../../app/routes/routerState";
import { SectorAnalysisMethodBar } from "../../features/wealth-exploration/sector-analysis/navigation/SectorAnalysisMethodBar";
import { useMomentumRankingController } from "../../features/wealth-exploration/sector-analysis/momentum-ranking/model/useMomentumRankingController";
import { MomentumRankingWorkspace } from "../../features/wealth-exploration/sector-analysis/momentum-ranking/ui/MomentumRankingWorkspace";
import { MomentumStateSurface } from "../../features/wealth-exploration/sector-analysis/momentum-ranking/ui/MomentumStateSurface";
import { WealthExplorationShell } from "./layout/WealthExplorationShell";
import type { WealthExplorationShellRenderProps } from "./layout/WealthExplorationShell";
import "./wealth-exploration-page.css";

interface SectorAnalysisPageProps {
  search?: string;
}

export function SectorAnalysisPage({ search }: SectorAnalysisPageProps) {
  return (
    <WealthExplorationShell activeShortcutKey="sector-analysis" currentPageLabel="板块分析" search={search}>
      {(shell) => <SectorAnalysisContent search={search} shell={shell} />}
    </WealthExplorationShell>
  );
}

function SectorAnalysisContent({ search, shell }: { search?: string; shell: WealthExplorationShellRenderProps }) {
  const routeSearch = search ?? window.location.search;
  const requestedTradeDate = new URLSearchParams(routeSearch).get("tradeDate");
  const contextMatchesRoute = requestedTradeDate === null
    || shell.model.pageContext?.tradeDate === requestedTradeDate;
  const handleNavigateSearch = useCallback((nextSearch: string, options?: { replace?: boolean }) => {
    navigateWealth(buildSectorAnalysisMomentumPath(nextSearch), options);
  }, []);
  const controller = useMomentumRankingController({
    enabled: shell.model.contextState === "ready" && contextMatchesRoute,
    search: routeSearch,
    onNavigateSearch: handleNavigateSearch,
  });

  return (
    <>
      <SectorAnalysisMethodBar onUnavailable={() => shell.showToast("待建设")} />
      {shell.model.contextState === "error" ? (
        <div className="momentum-ranking-workspace">
          <MomentumStateSurface
            kind="error"
            message={shell.contextErrorMessage ?? "页面时间上下文加载失败。"}
            onRetry={shell.model.retryContext}
            retryable
          />
        </div>
      ) : <MomentumRankingWorkspace controller={controller} />}
    </>
  );
}
