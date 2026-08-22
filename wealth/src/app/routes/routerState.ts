import type { TopMarketNavKey } from "../../shared/ui/top-market-bar/topMarketBarTypes";

export const DEFAULT_WEALTH_PATH = "/wealth/market/overview";
export const WEALTH_EXPLORATION_PATH = "/wealth/exploration";

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

export function buildWealthExplorationPath(search?: URLSearchParams): string {
  const query = search?.toString();
  return query ? `${WEALTH_EXPLORATION_PATH}?${query}` : WEALTH_EXPLORATION_PATH;
}

export function isWealthExplorationPath(pathname: string): boolean {
  return pathname === WEALTH_EXPLORATION_PATH;
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
  return isWealthExplorationPath(pathname) || pathname === DEFAULT_WEALTH_PATH || pathname.startsWith("/wealth/market/");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
