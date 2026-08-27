import { useEffect, useState, type ReactNode } from "react";

import {
  buildIndexDetailPath,
  DEFAULT_WEALTH_PATH,
  navigateWealth,
  resolveTopMarketNavPath,
  WEALTH_EXPLORATION_PATH,
} from "../../../app/routes/routerState";
import { ExplorationShortcutBar } from "../../../features/wealth-exploration/navigation/ExplorationShortcutBar";
import type { ExplorationShortcutKey } from "../../../features/wealth-exploration/navigation/explorationNavigation";
import { PageBreadcrumb } from "../../../shared/ui/page-breadcrumb/PageBreadcrumb";
import { TopMarketBar } from "../../../shared/ui/top-market-bar/TopMarketBar";
import type { TopMarketNavKey } from "../../../shared/ui/top-market-bar/topMarketBarTypes";
import {
  useWealthExplorationShell,
  type WealthExplorationShellModel,
} from "./useWealthExplorationShell";

interface WealthExplorationShellRenderProps {
  model: WealthExplorationShellModel;
  contextErrorMessage: string | null;
  showToast: (message: string) => void;
}

interface WealthExplorationShellProps {
  activeShortcutKey: ExplorationShortcutKey | null;
  children?: (props: WealthExplorationShellRenderProps) => ReactNode;
  currentPageLabel?: string;
  search?: string;
}

export function WealthExplorationShell({
  activeShortcutKey,
  children,
  currentPageLabel,
  search,
}: WealthExplorationShellProps) {
  const { model, contextErrorMessage } = useWealthExplorationShell(search);
  const [toast, setToast] = useState("");

  useEffect(() => {
    if (!toast) return undefined;
    const timeoutId = window.setTimeout(() => setToast(""), 1800);
    return () => window.clearTimeout(timeoutId);
  }, [toast]);

  function showToast(message: string) {
    setToast(message);
  }

  function handleTopNavigate(target: TopMarketNavKey) {
    const path = resolveTopMarketNavPath(target);
    if (path) {
      navigateWealth(path);
      return;
    }
    showToast("该入口暂未开放");
  }

  const breadcrumbItems = currentPageLabel
    ? [
        { label: "财势乾坤", path: DEFAULT_WEALTH_PATH },
        { label: "财势探查", path: WEALTH_EXPLORATION_PATH },
        { label: currentPageLabel },
      ]
    : [
        { label: "财势乾坤", path: DEFAULT_WEALTH_PATH },
        { label: "财势探查" },
      ];

  return (
    <div className="market-terminal wealth-exploration-page">
      <TopMarketBar
        activeNav="exploration"
        onNavigate={handleTopNavigate}
        onTickerSelect={(tsCode) => navigateWealth(buildIndexDetailPath(tsCode))}
        tickers={model.tickers}
      />
      <main className="page-shell wealth-exploration-shell">
        <PageBreadcrumb
          items={breadcrumbItems}
          onNavigate={navigateWealth}
          sessionStatus={model.pageContext?.sessionStatus ?? "CLOSED"}
        />
        <ExplorationShortcutBar activeKey={activeShortcutKey} onNavigate={navigateWealth} />
        {children?.({ model, contextErrorMessage, showToast })}
      </main>
      {toast ? <div id="toast">{toast}</div> : null}
    </div>
  );
}
