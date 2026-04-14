import { Alert, Button, Center, Group, Loader, Stack, Text } from "@mantine/core";
import {
  Outlet,
  createRootRoute,
  createRoute,
  createRouter,
  useNavigate,
} from "@tanstack/react-router";
import { useEffect, useState, type ReactNode } from "react";

import { useAuth, useCurrentUser } from "../features/auth/auth-context";
import { LoginPage } from "../pages/login-page";
import { OpsAutomationPage } from "../pages/ops-automation-page";
import { OpsDataStatusPage } from "../pages/ops-data-status-page";
import { OpsManualSyncPage } from "../pages/ops-manual-sync-page";
import { OpsTaskDetailPage } from "../pages/ops-task-detail-page";
import { OpsTasksPage } from "../pages/ops-tasks-page";
import { OpsTodayPage } from "../pages/ops-today-page";
import { OpsSourceManagementPage } from "../pages/ops-source-management-page";
import { OpsV21BiyingPage } from "../pages/ops-v21-biying-page";
import { OpsV21DatasetDetailPage } from "../pages/ops-v21-dataset-detail-page";
import { OpsV21OverviewPage } from "../pages/ops-v21-overview-page";
import { OpsV21TaskCenterPage } from "../pages/ops-v21-task-center-page";
import { OpsV21TusharePage } from "../pages/ops-v21-tushare-page";
import { PlatformCheckPage } from "../pages/platform-check-page";
import { ShareMarketPage } from "../pages/share-market-page";
import { OpsShell } from "./shell";
import { ShareShell } from "./share-shell";


function AppRoot() {
  return <Outlet />;
}

function HomeRoutePage() {
  const { token } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    void navigate({ to: token ? "/ops/v21/overview" : "/login", replace: true });
  }, [navigate, token]);

  return (
    <Center mih="100vh">
      <Loader />
    </Center>
  );
}

function RequireAdmin({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const { token, clearToken } = useAuth();
  const userQuery = useCurrentUser();
  const [stuck, setStuck] = useState(false);

  useEffect(() => {
    if (!token) {
      void navigate({ to: "/login", replace: true });
    }
  }, [navigate, token]);

  useEffect(() => {
    if (!token || !userQuery.isPending) {
      setStuck(false);
      return;
    }

    const timer = window.setTimeout(() => {
      setStuck(true);
    }, 4000);

    return () => {
      window.clearTimeout(timer);
    };
  }, [token, userQuery.isPending]);

  useEffect(() => {
    if (userQuery.error) {
      clearToken();
      void navigate({ to: "/login", replace: true });
    }
  }, [clearToken, navigate, userQuery.error]);

  if (!token || userQuery.isLoading) {
    if (stuck) {
      return (
        <Center mih="100vh">
          <Alert color="yellow" title="登录态恢复超时">
            <Stack gap="sm">
              <Text size="sm">
                当前前端在恢复本地登录态时超时了。为了避免页面一直卡在中间转圈，我已经准备好帮你回到登录页重新进入。
              </Text>
              <Group gap="sm">
                <Button
                  size="xs"
                  onClick={() => {
                    clearToken();
                    void navigate({ to: "/login", replace: true });
                  }}
                >
                  清除本地登录态并返回登录
                </Button>
                <Button size="xs" variant="light" onClick={() => window.location.reload()}>
                  刷新页面
                </Button>
              </Group>
            </Stack>
          </Alert>
        </Center>
      );
    }

    return (
      <Center mih="100vh">
        <Loader />
      </Center>
    );
  }

  if (!userQuery.data?.is_admin) {
    return (
      <Center mih="100vh">
        <Alert color="red" title="无权访问">
          当前账号不是管理员，无法进入运维系统。
        </Alert>
      </Center>
    );
  }

  return <>{children}</>;
}

function OpsLayout() {
  return (
    <RequireAdmin>
      <OpsShell />
    </RequireAdmin>
  );
}

function ShareLayout() {
  return (
    <RequireAdmin>
      <ShareShell />
    </RequireAdmin>
  );
}

function OpsIndexRedirect() {
  const navigate = useNavigate();
  useEffect(() => {
    void navigate({ to: "/ops/v21/overview", replace: true });
  }, [navigate]);
  return (
    <Center mih="100vh">
      <Loader />
    </Center>
  );
}

function RedirectTo({ to }: { to: string }) {
  const navigate = useNavigate();
  useEffect(() => {
    void navigate({ to, replace: true });
  }, [navigate, to]);
  return (
    <Center mih="100vh">
      <Loader />
    </Center>
  );
}

function NotFoundPage() {
  return (
    <Center mih="100vh">
      <Stack align="center" gap="xs">
        <Text fw={700}>页面不存在</Text>
        <Text c="dimmed" size="sm">
          当前前端应用已经接管 `/app`，但这个路由还没有实现。
        </Text>
      </Stack>
    </Center>
  );
}

const rootRoute = createRootRoute({
  component: AppRoot,
  notFoundComponent: NotFoundPage,
});

const homeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: HomeRoutePage,
});

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  component: LoginPage,
});

const platformCheckRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/platform-check",
  component: PlatformCheckPage,
});

const opsLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/ops",
  component: OpsLayout,
});

const shareLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/share",
  component: ShareLayout,
});

const opsIndexRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/",
  component: OpsIndexRedirect,
});

const opsOverviewRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/today",
  component: OpsTodayPage,
});

const opsFreshnessRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/data-status",
  component: OpsDataStatusPage,
});

const opsSchedulesRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/automation",
  component: OpsAutomationPage,
});

const opsExecutionsRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/tasks",
  component: OpsTasksPage,
});

const opsExecutionDetailRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/tasks/$executionId",
  component: function OpsTaskDetailRouteComponent() {
    const params = opsExecutionDetailRoute.useParams();
    return <OpsTaskDetailPage executionId={Number(params.executionId)} />;
  },
});

const opsManualSyncRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/manual-sync",
  component: OpsManualSyncPage,
});

const opsSourceManagementRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/source-management",
  component: OpsSourceManagementPage,
});

const opsV21OverviewRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/v21/overview",
  component: OpsV21OverviewPage,
});

const opsV21DatasetsTushareRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/v21/datasets/tushare",
  component: OpsV21TusharePage,
});

const opsV21DatasetsBiyingRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/v21/datasets/biying",
  component: OpsV21BiyingPage,
});

const opsV21DatasetsTasksRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/v21/datasets/tasks",
  component: OpsV21TaskCenterPage,
});

const opsV21DatasetDetailRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/v21/datasets/detail/$datasetKey",
  component: function OpsV21DatasetDetailRouteComponent() {
    const params = opsV21DatasetDetailRoute.useParams();
    return <OpsV21DatasetDetailPage datasetKey={params.datasetKey} />;
  },
});

const opsLegacyOverviewRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/overview",
  component: () => <RedirectTo to="/ops/today" />,
});

const opsLegacyFreshnessRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/freshness",
  component: () => <RedirectTo to="/ops/data-status" />,
});

const opsLegacySchedulesRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/schedules",
  component: () => <RedirectTo to="/ops/automation" />,
});

const opsLegacyExecutionsRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/executions",
  component: () => <RedirectTo to="/ops/tasks" />,
});

const opsLegacyExecutionDetailRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/executions/$executionId",
  component: function OpsLegacyExecutionDetailRouteComponent() {
    const params = opsLegacyExecutionDetailRoute.useParams();
    return <RedirectTo to={`/ops/tasks/${params.executionId}`} />;
  },
});

const opsLegacyCatalogRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/catalog",
  component: () => <RedirectTo to="/ops/manual-sync" />,
});

const shareIndexRoute = createRoute({
  getParentRoute: () => shareLayoutRoute,
  path: "/",
  component: ShareMarketPage,
});

const routeTree = rootRoute.addChildren([
  homeRoute,
  loginRoute,
  platformCheckRoute,
  opsLayoutRoute.addChildren([
    opsIndexRoute,
    opsOverviewRoute,
    opsFreshnessRoute,
    opsSchedulesRoute,
    opsSourceManagementRoute,
    opsV21OverviewRoute,
    opsV21DatasetsTushareRoute,
    opsV21DatasetsBiyingRoute,
    opsV21DatasetsTasksRoute,
    opsV21DatasetDetailRoute,
    opsManualSyncRoute,
    opsExecutionsRoute,
    opsExecutionDetailRoute,
    opsLegacyOverviewRoute,
    opsLegacyFreshnessRoute,
    opsLegacySchedulesRoute,
    opsLegacyExecutionsRoute,
    opsLegacyExecutionDetailRoute,
    opsLegacyCatalogRoute,
  ]),
  shareLayoutRoute.addChildren([
    shareIndexRoute,
  ]),
]);

export const router = createRouter({
  routeTree,
  basepath: "/app",
  defaultPreload: "intent",
  defaultPendingComponent: () => (
    <Center mih="100vh">
      <Loader />
    </Center>
  ),
  defaultErrorComponent: ({ error }) => (
    <Center mih="100vh">
      <Alert color="red" title="页面加载失败">
        {error instanceof Error ? error.message : "未知错误"}
      </Alert>
    </Center>
  ),
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
