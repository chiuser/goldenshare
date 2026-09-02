import { useMemo } from "react";

import { readMarketContextRequest } from "../../features/market-context/api/marketPageContextApi";
import { useTurnoverInsightController } from "../../features/wealth-exploration/turnover-insight/model/useTurnoverInsightController";
import { useIndexTurnoverInsightController } from "../../features/wealth-exploration/turnover-insight/model/useIndexTurnoverInsightController";
import { IndexTurnoverInsightGrid } from "../../features/wealth-exploration/turnover-insight/ui/IndexTurnoverInsightGrid";
import { TurnoverInsightSection } from "../../features/wealth-exploration/turnover-insight/ui/TurnoverInsightSection";
import { WealthExplorationShell } from "./layout/WealthExplorationShell";
import type { WealthExplorationShellModel } from "./layout/useWealthExplorationShell";
import "./wealth-exploration-page.css";

interface TurnoverInsightPageProps {
  search?: string;
}

interface TurnoverInsightContentProps {
  contextErrorMessage: string | null;
  debug: 0 | 1 | undefined;
  model: WealthExplorationShellModel;
}

function TurnoverInsightContent({ contextErrorMessage, debug, model }: TurnoverInsightContentProps) {
  const contextFailed = model.contextState === "error";
  const turnoverRequest = useMemo(() => !contextFailed && model.pageContext ? {
    market: model.pageContext.market,
    tradeDate: model.pageContext.tradeDate,
    debug,
  } : null, [contextFailed, debug, model.pageContext]);
  const turnover = useTurnoverInsightController(turnoverRequest);
  const indices = useIndexTurnoverInsightController(turnoverRequest);

  return (
    <>
      <TurnoverInsightSection
        errorMessage={contextFailed ? contextErrorMessage ?? undefined : turnover.errorMessage ?? undefined}
        model={contextFailed ? null : turnover.model}
        onRetry={contextFailed ? model.retryContext : turnover.retry}
        viewState={contextFailed ? "error" : turnover.viewState}
      />
      {!contextFailed ? <IndexTurnoverInsightGrid controller={indices} /> : null}
    </>
  );
}

export function TurnoverInsightPage({ search }: TurnoverInsightPageProps) {
  const routeSearch = search ?? (typeof window === "undefined" ? "" : window.location.search);
  const debug = useMemo(() => readMarketContextRequest(routeSearch).debug, [routeSearch]);
  return (
    <WealthExplorationShell activeShortcutKey="turnover-insight" currentPageLabel="成交额洞察" search={search}>
      {({ contextErrorMessage, model }) => (
        <TurnoverInsightContent contextErrorMessage={contextErrorMessage} debug={debug} model={model} />
      )}
    </WealthExplorationShell>
  );
}
