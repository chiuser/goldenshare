import {
  ActionIcon,
  AppShell,
  Badge,
  Burger,
  Group,
  NavLink,
  ScrollArea,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import {
  IconActivityHeartbeat,
  IconApps,
  IconBuildingCommunity,
  IconGauge,
  IconLogout,
  IconListDetails,
  IconShieldLock,
  IconSparkles,
  IconStack2,
  IconTopologyRing3,
} from "@tabler/icons-react";
import { Link, Outlet, useLocation, useNavigate } from "@tanstack/react-router";
import { useDisclosure } from "@mantine/hooks";
import type { PropsWithChildren } from "react";

import { useAuth, useCurrentUser } from "../features/auth/auth-context";
const opsV21Links = [
  { to: "/ops/v21/overview", label: "数据状态总览", icon: IconActivityHeartbeat },
  { to: "/ops/v21/today", label: "今日运行", icon: IconGauge },
  { to: "/ops/v21/account", label: "帐号管理", icon: IconShieldLock },
];

const opsV21SourceLinks = [
  { to: "/ops/v21/datasets/tushare", label: "Tushare", icon: IconTopologyRing3 },
  { to: "/ops/v21/datasets/biying", label: "Biying", icon: IconTopologyRing3 },
  { to: "/ops/v21/datasets/tasks", label: "任务中心", icon: IconListDetails },
];

const opsV21ReviewLinks = [
  { to: "/ops/v21/review/index", label: "指数", icon: IconApps },
  { to: "/ops/v21/review/board", label: "板块", icon: IconBuildingCommunity },
];

export function OpsShell(_props: PropsWithChildren) {
  const [opened, { toggle }] = useDisclosure(false);
  const location = useLocation();
  const navigate = useNavigate();
  const { clearToken } = useAuth();
  const userQuery = useCurrentUser();
  const versionText = `v${__APP_VERSION__} · ${__APP_COMMIT__}`;
  const buildTimeText = __APP_BUILD_TIME__.replace("T", " ").replace("Z", " UTC");

  const logout = async () => {
    clearToken();
    await navigate({ to: "/login" });
  };

  return (
    <AppShell
      className="app-gradient-shell"
      header={{ height: 72 }}
      navbar={{ width: 280, breakpoint: "md", collapsed: { mobile: !opened } }}
      padding="lg"
    >
      <AppShell.Header className="app-shell-header" px="lg">
        <Group justify="space-between" h="100%">
          <Group gap="sm">
            <Burger opened={opened} onClick={toggle} hiddenFrom="md" size="sm" />
            <img
              src="/app/brand/logo-icon.png"
              alt="财势乾坤图标"
              className="app-brand-mark"
            />
            <Stack gap={0}>
              <Text className="app-shell-brand-title" fw={600} size="lg">
                财势乾坤
              </Text>
              <Text className="app-shell-brand-subtitle" size="xs">
                数据运营管理综合平台
              </Text>
            </Stack>
          </Group>
          <Group gap="sm">
            <Badge size="md" color="brand" variant="light">
              运行管理
            </Badge>
            <Stack className="app-shell-user-meta" gap={2} align="flex-end">
              <Text className="app-shell-user-name" fw={600} size="sm">
                {userQuery.data?.display_name || userQuery.data?.username || "管理员"}
              </Text>
              <Text className="app-shell-user-role" size="xs">
                {userQuery.data?.is_admin ? "管理员" : "操作员"}
              </Text>
            </Stack>
            <Tooltip label="退出登录">
              <ActionIcon variant="subtle" color="gray" size="lg" onClick={() => void logout()}>
                <IconLogout size={18} />
              </ActionIcon>
            </Tooltip>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar className="app-shell-navbar" p="md">
        <AppShell.Section grow component={ScrollArea} scrollbars="y">
          <Stack gap="xs">
            {opsV21Links.map((link) => (
              <NavLink
                key={link.to}
                component={Link}
                to={link.to}
                label={link.label}
                leftSection={<link.icon size={18} />}
                active={location.pathname === link.to || location.pathname.startsWith(`${link.to}/`)}
                variant="light"
                color="brand"
              />
            ))}
            <ShellSectionLabel label="数据源" />
            {opsV21SourceLinks.map((link) => (
              <NavLink
                key={link.to}
                component={Link}
                to={link.to}
                label={link.label}
                leftSection={<link.icon size={16} />}
                active={location.pathname === link.to || location.pathname.startsWith(`${link.to}/`)}
                variant="subtle"
                color="brand"
                style={{ marginLeft: 8 }}
              />
            ))}

            <ShellSectionLabel label="审查中心" />
            {opsV21ReviewLinks.map((link) => (
              <NavLink
                key={link.to}
                component={Link}
                to={link.to}
                label={link.label}
                leftSection={<link.icon size={16} />}
                active={location.pathname === link.to || location.pathname.startsWith(`${link.to}/`)}
                variant="subtle"
                color="brand"
                style={{ marginLeft: 8 }}
              />
            ))}

            <NavLink
              label="融合策略中心（即将开放）"
              leftSection={<IconSparkles size={16} />}
              disabled
              variant="subtle"
              style={{ marginLeft: 10 }}
            />
            <NavLink
              label="发布中心（即将开放）"
              leftSection={<IconSparkles size={16} />}
              disabled
              variant="subtle"
              style={{ marginLeft: 10 }}
            />
          </Stack>
        </AppShell.Section>
        <AppShell.Section>
          <Stack gap="xs">
            <NavLink
              component={Link}
              to="/platform-check"
              label="平台检查"
              leftSection={<IconShieldLock size={18} />}
              active={location.pathname === "/platform-check"}
              variant="light"
              color="brand"
            />
            <Stack className="app-shell-footer-meta" gap={2} mt={8} px="sm">
              <Text size="xs" c="dimmed">
                版本：{versionText}
              </Text>
              <Text size="xs" c="dimmed">
                构建：{buildTimeText}
              </Text>
              <Group gap={4} align="center" wrap="nowrap">
                <img
                  src="/app/brand/gxbicon.png"
                  alt="京ICP备图标"
                  style={{ width: "1em", height: "1em", display: "block", flex: "0 0 auto" }}
                />
                <Text className="app-shell-license" size="xs">
                  京ICP备2026018630号-1
                </Text>
              </Group>
              <Group gap={4} align="center" wrap="nowrap">
                <img
                  src="/app/brand/logoga.png"
                  alt="公安备案图标"
                  style={{ width: "1em", height: "1em", display: "block", flex: "0 0 auto" }}
                />
                <Text className="app-shell-license" size="xs">
                  京公网安备11010502060216号
                </Text>
              </Group>
            </Stack>
          </Stack>
        </AppShell.Section>
      </AppShell.Navbar>

      <AppShell.Main className="app-shell-main">
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}

function ShellSectionLabel({ label }: { label: string }) {
  return (
    <Group gap={8} px="xs" pt="sm" pb={4}>
      <IconStack2 size={16} color="var(--gs-neutral-6)" />
      <Text className="app-shell-section-caption" size="xs" fw={600}>
        {label}
      </Text>
    </Group>
  );
}
