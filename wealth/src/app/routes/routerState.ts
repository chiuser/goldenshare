export const DEFAULT_WEALTH_PATH = "/wealth/market/overview";

const ROUTE_CHANGE_EVENT = "wealth-route-change";

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
  if (options.replace) {
    window.history.replaceState({}, "", path);
  } else {
    window.history.pushState({}, "", path);
  }
  window.dispatchEvent(new Event(ROUTE_CHANGE_EVENT));
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

export function readRedirectPath(search: string): string {
  const redirect = new URLSearchParams(search).get("redirect");
  if (!redirect) return DEFAULT_WEALTH_PATH;
  if (!redirect.startsWith("/")) return DEFAULT_WEALTH_PATH;
  if (redirect.startsWith("//")) return DEFAULT_WEALTH_PATH;
  return redirect;
}
