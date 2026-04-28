import { Alert, Button, Center, Group, Loader, Stack, Text } from "@mantine/core";
import {
  Outlet,
  createRootRoute,
  createRoute,
  createRouter,
  useNavigate,
  useSearch,
} from "@tanstack/react-router";
import { useEffect, useState, type ReactNode } from "react";

import { useAuth, useCurrentUser } from "../features/auth/auth-context";
import { LoginPage } from "../pages/login-page";
import { RegisterPage } from "../pages/register-page";
import { ForgotPasswordPage } from "../pages/forgot-password-page";
import { MarketHomepagePage } from "../pages/market-homepage/market-homepage-page";
import { ResetPasswordPage } from "../pages/reset-password-page";
import { OpsTaskDetailPage } from "../pages/ops-task-detail-page";
import { OpsTodayPage } from "../pages/ops-today-page";
import { OpsV21BiyingPage } from "../pages/ops-v21-biying-page";
import { OpsV21AccountPage } from "../pages/ops-v21-account-page";
import { OpsV21DatasetDetailPage } from "../pages/ops-v21-dataset-detail-page";
import { OpsV21OverviewPage } from "../pages/ops-v21-overview-page";
import { OpsV21ReviewBoardPage } from "../pages/ops-v21-review-board-page";
import { OpsV21ReviewIndexPage } from "../pages/ops-v21-review-index-page";
import { OpsV21TaskCenterPage } from "../pages/ops-v21-task-center-page";
import { OpsV21TusharePage } from "../pages/ops-v21-tushare-page";
import { PlatformCheckPage } from "../pages/platform-check-page";
import { UserOverviewPage } from "../pages/user-overview-page";
import { OpsShell } from "./shell";


function AppRoot() {
  return <Outlet />;
}

function HomeRoutePage() {
  const { token, clearToken } = useAuth();
  const userQuery = useCurrentUser();
  const navigate = useNavigate();

  useEffect(() => {
    if (!token) {
      void navigate({ to: "/login", replace: true });
      return;
    }
    if (userQuery.error) {
      clearToken();
      void navigate({ to: "/login", replace: true });
      return;
    }
    if (!userQuery.data) {
      return;
    }
    void navigate({ to: userQuery.data.is_admin ? "/ops/v21/overview" : "/user/overview", replace: true });
  }, [clearToken, navigate, token, userQuery.data, userQuery.error]);

  return (
    <Center mih="100vh">
      <Loader />
    </Center>
  );
}

function RequireAuthenticated({ children }: { children: ReactNode }) {
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
          <Alert color="warning" title="登录态恢复超时">
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

  return <>{children}</>;
}

function RequireAdmin({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const userQuery = useCurrentUser();

  useEffect(() => {
    if (userQuery.data && !userQuery.data.is_admin) {
      void navigate({ to: "/user/overview", replace: true });
    }
  }, [navigate, userQuery.data]);

  if (!userQuery.data?.is_admin) {
    return (
      <Center mih="100vh">
        <Loader />
      </Center>
    );
  }

  return <>{children}</>;
}

function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <RequireAuthenticated>
      <RequireAdmin>
        {children}
      </RequireAdmin>
    </RequireAuthenticated>
  );
}

function UserLayout({ children }: { children: ReactNode }) {
  return <RequireAuthenticated>{children}</RequireAuthenticated>;
}

function OpsLayout() {
  return (
    <AdminLayout>
      <OpsShell />
    </AdminLayout>
  );
}

function UserOverviewLayout() {
  return (
    <UserLayout>
      <UserOverviewPage />
    </UserLayout>
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

function RedirectToTaskCenterTab({ tab }: { tab: "records" | "manual" | "auto" }) {
  const navigate = useNavigate();
  const search = useSearch({ strict: false });
  useEffect(() => {
    const current = (search as Record<string, unknown>) || {};
    void navigate({
      to: "/ops/v21/datasets/tasks",
      search: { ...current, tab },
      replace: true,
    });
  }, [navigate, search, tab]);
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

const registerRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/register",
  component: RegisterPage,
});

const forgotPasswordRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/forgot-password",
  component: ForgotPasswordPage,
});

const resetPasswordRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/reset-password",
  component: ResetPasswordPage,
});

const userOverviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/user/overview",
  component: UserOverviewLayout,
});

const platformCheckRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/platform-check",
  component: PlatformCheckPage,
});

const marketHomepageRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/market",
  component: MarketHomepagePage,
});

const opsLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/ops",
  component: OpsLayout,
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
  component: () => <RedirectTo to="/ops/v21/overview" />,
});

const opsSchedulesRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/automation",
  component: () => <RedirectToTaskCenterTab tab="auto" />,
});

const opsTaskRunsRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/tasks",
  component: () => <RedirectToTaskCenterTab tab="records" />,
});

const opsTaskRunDetailRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/tasks/$taskRunId",
  component: function OpsTaskDetailRouteComponent() {
    const params = opsTaskRunDetailRoute.useParams();
    return <OpsTaskDetailPage taskRunId={Number(params.taskRunId)} />;
  },
});

const opsV21OverviewRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/v21/overview",
  component: OpsV21OverviewPage,
});

const opsV21TodayRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/v21/today",
  component: OpsTodayPage,
});

const opsV21AccountRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/v21/account",
  component: OpsV21AccountPage,
});

const opsV21ReviewIndexRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/v21/review/index",
  component: OpsV21ReviewIndexPage,
});

const opsV21ReviewBoardRoute = createRoute({
  getParentRoute: () => opsLayoutRoute,
  path: "/v21/review/board",
  component: OpsV21ReviewBoardPage,
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
  validateSearch: (search: Record<string, unknown>) => search,
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

const routeTree = rootRoute.addChildren([
  homeRoute,
  loginRoute,
  registerRoute,
  forgotPasswordRoute,
  resetPasswordRoute,
  userOverviewRoute,
  platformCheckRoute,
  marketHomepageRoute,
  opsLayoutRoute.addChildren([
    opsIndexRoute,
    opsOverviewRoute,
    opsFreshnessRoute,
    opsSchedulesRoute,
    opsV21OverviewRoute,
    opsV21TodayRoute,
    opsV21ReviewIndexRoute,
    opsV21ReviewBoardRoute,
    opsV21DatasetsTushareRoute,
    opsV21DatasetsBiyingRoute,
    opsV21DatasetsTasksRoute,
    opsV21DatasetDetailRoute,
    opsTaskRunsRoute,
    opsTaskRunDetailRoute,
    opsV21AccountRoute,
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
      <Alert color="error" title="页面加载失败">
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
