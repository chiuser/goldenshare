import type { TopMarketNavKey } from "../../shared/ui/top-market-bar/topMarketBarTypes";
import {
  EXPLORATION_SECTOR_DAILY_INSIGHT_PATH,
  EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH,
  EXPLORATION_SECTOR_MOMENTUM_PATH,
  EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH,
  EXPLORATION_TURNOVER_PATH,
} from "../../features/wealth-exploration/navigation/explorationNavigation";

export const DEFAULT_WEALTH_PATH = "/wealth/market/overview";
export const WEALTH_WATCHLIST_PATH = "/wealth/market/watchlist";

export function buildWatchlistPath(): string { return WEALTH_WATCHLIST_PATH; }
export function isWatchlistPath(pathname: string): boolean {
  return pathname === WEALTH_WATCHLIST_PATH || pathname === "/market/watchlist";
}
export const WEALTH_EXPLORATION_PATH = "/wealth/exploration";
export const WEALTH_EXPLORATION_TURNOVER_PATH = EXPLORATION_TURNOVER_PATH;
export const WEALTH_EXPLORATION_SECTOR_PATH = "/wealth/exploration/sector-analysis";
export const WEALTH_EXPLORATION_SECTOR_DAILY_INSIGHT_PATH = EXPLORATION_SECTOR_DAILY_INSIGHT_PATH;
export const WEALTH_EXPLORATION_SECTOR_MOMENTUM_PATH = EXPLORATION_SECTOR_MOMENTUM_PATH;
export const WEALTH_EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH = EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH;
export const WEALTH_EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH = EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH;
export const WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH = "/wealth/exploration/sector-analysis/member-breadth";
export const WEALTH_EXPLORATION_SECTOR_PRICE_VOLUME_PATH = "/wealth/exploration/sector-analysis/price-volume";

const ROUTE_CHANGE_EVENT = "wealth-route-change";
const WEALTH_NAVIGATION_STATE_KEY = "__goldenshareWealthNavigation";

interface WealthNavigationState {
  hasWealthReferrer: boolean;
}

export interface WealthLocation {
  pathname: string;
  search: string;
}

export function readWealthLocation(): WealthLocation {
  return {
    pathname: window.location.pathname,
    search: window.location.search,
  };
}

export function navigateWealth(path: string, options: { replace?: boolean } = {}) {
  const state = buildWealthNavigationState();
  if (options.replace) {
    window.history.replaceState(state, "", path);
  } else {
    window.history.pushState(state, "", path);
  }
  window.dispatchEvent(new Event(ROUTE_CHANGE_EVENT));
}

export function returnToWealthOverview() {
  const state = readWealthNavigationState(window.history.state);
  if (state?.hasWealthReferrer) {
    window.history.back();
    return;
  }
  navigateWealth(DEFAULT_WEALTH_PATH, { replace: true });
}

export function addWealthRouteListener(listener: () => void) {
  window.addEventListener("popstate", listener);
  window.addEventListener(ROUTE_CHANGE_EVENT, listener);
  return () => {
    window.removeEventListener("popstate", listener);
    window.removeEventListener(ROUTE_CHANGE_EVENT, listener);
  };
}

export function isLoginPath(pathname: string): boolean {
  return pathname === "/wealth/login" || pathname === "/login";
}

export function buildLoginPath(redirectPath: string): string {
  return `/wealth/login?redirect=${encodeURIComponent(redirectPath)}`;
}

export function buildStockDetailPath(tsCode: string): string {
  const normalized = tsCode.trim().toUpperCase();
  return `/wealth/market/stock/${encodeURIComponent(normalized)}`;
}

export function buildIndexDetailPath(tsCode: string): string {
  const normalized = tsCode.trim().toUpperCase();
  return `/wealth/market/index/${encodeURIComponent(normalized)}`;
}

export type WealthExplorationRoute =
  | { kind: "landing" }
  | { kind: "turnover-insight" }
  | { kind: "sector-analysis-redirect" }
  | { kind: "sector-analysis-daily-insight" }
  | { kind: "sector-analysis-momentum" }
  | { kind: "sector-analysis-dual-momentum" }
  | { kind: "sector-analysis-relative-rotation" }
  | { kind: "sector-analysis-member-breadth" }
  | { kind: "sector-analysis-price-volume" }
  | { kind: "not-exploration" };

type RouteSearch = URLSearchParams | string | undefined;

export function buildWealthExplorationPath(search?: RouteSearch): string {
  return appendSearch(WEALTH_EXPLORATION_PATH, search);
}

export function buildTurnoverInsightPath(search?: RouteSearch): string {
  return appendSearch(WEALTH_EXPLORATION_TURNOVER_PATH, search);
}

export function buildSectorAnalysisPath(search?: RouteSearch): string {
  return appendSearch(WEALTH_EXPLORATION_SECTOR_PATH, search);
}

export function buildSectorAnalysisMomentumPath(search?: RouteSearch): string {
  return appendSearch(WEALTH_EXPLORATION_SECTOR_MOMENTUM_PATH, search);
}

export function buildSectorAnalysisDailyInsightPath(search?: RouteSearch): string {
  return appendSearch(WEALTH_EXPLORATION_SECTOR_DAILY_INSIGHT_PATH, search);
}

export function buildSectorAnalysisDualMomentumPath(search?: RouteSearch): string {
  return appendSearch(WEALTH_EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH, search);
}

export function buildSectorAnalysisRelativeRotationPath(search?: RouteSearch): string {
  return appendSearch(WEALTH_EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH, search);
}

export function buildSectorAnalysisMemberBreadthPath(search?: RouteSearch): string {
  return appendSearch(WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH, search);
}

export function buildSectorAnalysisPriceVolumePath(search?: RouteSearch): string {
  return appendSearch(WEALTH_EXPLORATION_SECTOR_PRICE_VOLUME_PATH, search);
}

export function resolveWealthExplorationRoute(pathname: string): WealthExplorationRoute {
  if (pathname === WEALTH_EXPLORATION_PATH) return { kind: "landing" };
  if (pathname === WEALTH_EXPLORATION_TURNOVER_PATH) return { kind: "turnover-insight" };
  if (pathname === WEALTH_EXPLORATION_SECTOR_PATH) return { kind: "sector-analysis-redirect" };
  if (pathname === WEALTH_EXPLORATION_SECTOR_DAILY_INSIGHT_PATH) return { kind: "sector-analysis-daily-insight" };
  if (pathname === WEALTH_EXPLORATION_SECTOR_MOMENTUM_PATH) return { kind: "sector-analysis-momentum" };
  if (pathname === WEALTH_EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH) return { kind: "sector-analysis-dual-momentum" };
  if (pathname === WEALTH_EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH) return { kind: "sector-analysis-relative-rotation" };
  if (pathname === WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH) return { kind: "sector-analysis-member-breadth" };
  if (pathname === WEALTH_EXPLORATION_SECTOR_PRICE_VOLUME_PATH) return { kind: "sector-analysis-price-volume" };
  return { kind: "not-exploration" };
}

export function resolveTopMarketNavPath(target: TopMarketNavKey): string | null {
  if (target === "market") return DEFAULT_WEALTH_PATH;
  if (target === "exploration") return WEALTH_EXPLORATION_PATH;
  return null;
}

export function readRedirectPath(search: string): string {
  const redirect = new URLSearchParams(search).get("redirect");
  if (!redirect) return DEFAULT_WEALTH_PATH;
  if (!redirect.startsWith("/")) return DEFAULT_WEALTH_PATH;
  if (redirect.startsWith("//")) return DEFAULT_WEALTH_PATH;
  return redirect;
}

function buildWealthNavigationState(): Record<string, unknown> {
  const existingState = isRecord(window.history.state) ? window.history.state : {};
  return {
    ...existingState,
    [WEALTH_NAVIGATION_STATE_KEY]: {
      hasWealthReferrer: isWealthRoute(window.location.pathname),
    } satisfies WealthNavigationState,
  };
}

function readWealthNavigationState(state: unknown): WealthNavigationState | null {
  if (!isRecord(state)) return null;
  const navigationState = state[WEALTH_NAVIGATION_STATE_KEY];
  if (!isRecord(navigationState) || typeof navigationState.hasWealthReferrer !== "boolean") return null;
  return { hasWealthReferrer: navigationState.hasWealthReferrer };
}

function isWealthRoute(pathname: string): boolean {
  return resolveWealthExplorationRoute(pathname).kind !== "not-exploration"
    || pathname === DEFAULT_WEALTH_PATH
    || pathname.startsWith("/wealth/market/");
}

function appendSearch(path: string, search: RouteSearch): string {
  if (search === undefined) return path;
  const query = typeof search === "string"
    ? search.replace(/^\?/, "")
    : search.toString();
  return query ? `${path}?${query}` : path;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
