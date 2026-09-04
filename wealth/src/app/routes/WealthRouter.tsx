import { useEffect, useState } from "react";

import { useAuth } from "../../features/auth/model/AuthProvider";
import { LoginPage } from "../../features/auth/ui/LoginPage";
import { MarketOverviewPage } from "../../pages/market-overview/MarketOverviewPage";
import { IndexDetailPage } from "../../pages/index-detail/IndexDetailPage";
import { StockDetailPage } from "../../pages/stock-detail/StockDetailPage";
import { WatchlistPage } from "../../pages/watchlist/WatchlistPage";
import { SectorAnalysisPage } from "../../pages/wealth-exploration/SectorAnalysisPage";
import { TurnoverInsightPage } from "../../pages/wealth-exploration/TurnoverInsightPage";
import { WealthExplorationLandingPage } from "../../pages/wealth-exploration/WealthExplorationLandingPage";
import {
  addWealthRouteListener,
  buildSectorAnalysisDailyInsightPath,
  buildLoginPath,
  DEFAULT_WEALTH_PATH,
  isLoginPath,
  isWatchlistPath,
  navigateWealth,
  readRedirectPath,
  readWealthLocation,
  resolveWealthExplorationRoute,
  type WealthLocation,
} from "./routerState";

export function WealthRouter() {
  const auth = useAuth();
  const [location, setLocation] = useState<WealthLocation>(() => readWealthLocation());
  const currentPath = `${location.pathname}${location.search}`;

  useEffect(() => addWealthRouteListener(() => setLocation(readWealthLocation())), []);

  if (isLoginPath(location.pathname)) {
    return (
      <LoginPage
        redirectPath={readRedirectPath(location.search)}
        onAuthenticated={(path) => navigateWealth(path || DEFAULT_WEALTH_PATH, { replace: true })}
      />
    );
  }

  if (auth.status === "unauthenticated") {
    return <AuthRedirect redirectPath={currentPath} />;
  }

  if (isWatchlistPath(location.pathname)) return <WatchlistPage search={location.search} />;

  const stockDetailTsCode = parseStockDetailTsCode(location.pathname);
  if (stockDetailTsCode) {
    return <StockDetailPage tsCode={stockDetailTsCode} />;
  }

  const indexDetailTsCode = parseIndexDetailTsCode(location.pathname);
  if (indexDetailTsCode) {
    return <IndexDetailPage search={location.search} tsCode={indexDetailTsCode} />;
  }

  const explorationRoute = resolveWealthExplorationRoute(location.pathname);
  if (explorationRoute.kind === "landing") return <WealthExplorationLandingPage search={location.search} />;
  if (explorationRoute.kind === "turnover-insight") return <TurnoverInsightPage search={location.search} />;
  if (explorationRoute.kind === "sector-analysis-redirect") {
    return <ExplorationRedirect search={location.search} />;
  }
  if (explorationRoute.kind === "sector-analysis-momentum") {
    return <SectorAnalysisPage method="momentum-ranking" search={location.search} />;
  }
  if (explorationRoute.kind === "sector-analysis-daily-insight") {
    return <SectorAnalysisPage method="daily-insight" search={location.search} />;
  }
  if (explorationRoute.kind === "sector-analysis-dual-momentum") {
    return <SectorAnalysisPage method="dual-momentum" search={location.search} />;
  }
  if (explorationRoute.kind === "sector-analysis-relative-rotation") {
    return <SectorAnalysisPage method="relative-rotation" search={location.search} />;
  }
  if (explorationRoute.kind === "sector-analysis-member-breadth") {
    return <SectorAnalysisPage method="member-breadth" search={location.search} />;
  }
  if (explorationRoute.kind === "sector-analysis-price-volume") {
    return <SectorAnalysisPage method="price-volume" search={location.search} />;
  }

  return <MarketOverviewPage search={location.search} />;
}

function parseStockDetailTsCode(pathname: string): string | null {
  const match = pathname.match(/^(?:\/wealth)?\/market\/stock\/([^/]+)$/);
  if (!match?.[1]) return null;
  return decodeURIComponent(match[1]);
}

function parseIndexDetailTsCode(pathname: string): string | null {
  const match = pathname.match(/^(?:\/wealth)?\/market\/index\/([^/]+)$/);
  if (!match?.[1]) return null;
  return decodeURIComponent(match[1]);
}

function AuthRedirect({ redirectPath }: { redirectPath: string }) {
  useEffect(() => {
    navigateWealth(buildLoginPath(redirectPath), { replace: true });
  }, [redirectPath]);
  return <LoginPage redirectPath={redirectPath} onAuthenticated={(path) => navigateWealth(path || DEFAULT_WEALTH_PATH)} />;
}

function ExplorationRedirect({ search }: { search: string }) {
  useEffect(() => {
    navigateWealth(buildSectorAnalysisDailyInsightPath(search), { replace: true });
  }, [search]);
  return null;
}
