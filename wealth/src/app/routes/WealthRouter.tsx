import { useEffect, useState } from "react";

import { useAuth } from "../../features/auth/model/AuthProvider";
import { LoginPage } from "../../features/auth/ui/LoginPage";
import { MarketOverviewPage } from "../../pages/market-overview/MarketOverviewPage";
import {
  addWealthRouteListener,
  buildLoginPath,
  DEFAULT_WEALTH_PATH,
  isLoginPath,
  navigateWealth,
  readRedirectPath,
  readWealthLocation,
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

  return <MarketOverviewPage />;
}

function AuthRedirect({ redirectPath }: { redirectPath: string }) {
  useEffect(() => {
    navigateWealth(buildLoginPath(redirectPath), { replace: true });
  }, [redirectPath]);
  return <LoginPage redirectPath={redirectPath} onAuthenticated={(path) => navigateWealth(path || DEFAULT_WEALTH_PATH)} />;
}

