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
  IconCalendarTime,
  IconGauge,
  IconLogout,
  IconListDetails,
  IconPlayerPlay,
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

const opsLegacyLinks = [
  { to: "/ops/data-status", label: "数据状态", icon: IconGauge },
  { to: "/ops/today", label: "今日运行", icon: IconGauge },
  { to: "/ops/automation", label: "自动运行", icon: IconCalendarTime },
  { to: "/ops/manual-sync", label: "手动同步", icon: IconPlayerPlay },
  { to: "/ops/tasks", label: "任务记录", icon: IconListDetails },
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
      header={{ height: 76 }}
      navbar={{ width: 280, breakpoint: "md", collapsed: { mobile: !opened } }}
      padding="lg"
    >
      <AppShell.Header px="lg">
        <Group justify="space-between" h="100%">
          <Group gap="sm">
            <Burger opened={opened} onClick={toggle} hiddenFrom="md" size="sm" />
            <img
              src="/app/brand/logo-icon.png"
              alt="财势乾坤图标"
              className="app-brand-mark"
            />
            <Stack gap={0}>
              <Text fw={800} size="xl">
                财势乾坤
              </Text>
              <Text c="dimmed" size="sm">
                数据运营管理综合平台
              </Text>
            </Stack>
          </Group>
          <Group gap="sm">
            <Badge radius="xl" size="lg" color="brand" variant="filled">
              运行管理
            </Badge>
            <Stack gap={0} align="flex-end">
              <Text fw={600}>{userQuery.data?.display_name || userQuery.data?.username || "管理员"}</Text>
              <Text c="dimmed" size="xs">
                {userQuery.data?.is_admin ? "管理员" : "操作员"}
              </Text>
            </Stack>
            <Tooltip label="退出登录">
              <ActionIcon variant="light" color="gray" radius="xl" size="lg" onClick={() => void logout()}>
                <IconLogout size={18} />
              </ActionIcon>
            </Tooltip>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="md">
        <AppShell.Section grow component={ScrollArea}>
          <Stack gap="xs">
            <Group justify="space-between" px="xs" pb={2}>
              <Text size="xs" c="dimmed" fw={700}>V2.1</Text>
              <Badge size="xs" radius="xl" variant="light" color="brand">新</Badge>
            </Group>
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
            <NavLink
              label="数据源"
              leftSection={<IconStack2 size={18} />}
              variant="light"
              color="brand"
              styles={{
                root: { pointerEvents: "none" },
                label: { fontWeight: 600, color: "var(--mantine-color-text)" },
              }}
            />
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
                style={{ marginLeft: 10 }}
              />
            ))}

            <NavLink
              label="审查中心"
              leftSection={<IconStack2 size={18} />}
              variant="light"
              color="brand"
              styles={{
                root: { pointerEvents: "none" },
                label: { fontWeight: 600, color: "var(--mantine-color-text)" },
              }}
            />
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
                style={{ marginLeft: 10 }}
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

            <Text size="xs" c="dimmed" fw={700} px="xs" pt="sm" pb={2}>旧版（过渡）</Text>
            {opsLegacyLinks.map((link) => (
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
            <NavLink
              label="当前重点：先看今日运行，再处理任务记录里的失败项。"
              leftSection={<IconSparkles size={18} />}
              disabled
              variant="light"
            />
            <Stack gap={2} mt={8} px="sm">
              <Text size="xs" c="dimmed">版本：{versionText}</Text>
              <Text size="xs" c="dimmed">构建：{buildTimeText}</Text>
              <Group gap={4} align="center" wrap="nowrap">
                <img
                  src="/app/brand/gxbicon.png"
                  alt="京ICP备图标"
                  style={{ width: "1em", height: "1em", display: "block", flex: "0 0 auto" }}
                />
                <Text size="xs" style={{ color: "var(--mantine-color-black)" }}>
                  京ICP备2026018630号-1
                </Text>
              </Group>
            </Stack>
          </Stack>
        </AppShell.Section>
      </AppShell.Navbar>

      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
