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
  IconCalendarTime,
  IconGauge,
  IconLogout,
  IconListDetails,
  IconPlayerPlay,
  IconShieldLock,
  IconSparkles,
} from "@tabler/icons-react";
import { Link, Outlet, useLocation, useNavigate } from "@tanstack/react-router";
import { useDisclosure } from "@mantine/hooks";
import type { PropsWithChildren } from "react";

import { useAuth, useCurrentUser } from "../features/auth/auth-context";
const opsLinks = [
  { to: "/ops/today", label: "今日运行", icon: IconGauge },
  { to: "/ops/automation", label: "自动运行", icon: IconCalendarTime },
  { to: "/ops/manual-sync", label: "手动同步", icon: IconPlayerPlay },
  { to: "/ops/tasks", label: "任务记录", icon: IconListDetails },
  { to: "/ops/data-status", label: "数据状态", icon: IconActivityHeartbeat },
];

export function OpsShell(_props: PropsWithChildren) {
  const [opened, { toggle }] = useDisclosure(false);
  const location = useLocation();
  const navigate = useNavigate();
  const { clearToken } = useAuth();
  const userQuery = useCurrentUser();

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
            <Stack gap={0}>
              <Text fw={800} size="xl">
                财势乾坤
              </Text>
              <Text c="dimmed" size="sm">
                数据运行管理台
              </Text>
            </Stack>
          </Group>
          <Group gap="sm">
            <Badge radius="xl" size="lg" color="cyan">
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
            {opsLinks.map((link) => (
              <NavLink
                key={link.to}
                component={Link}
                to={link.to}
                label={link.label}
                leftSection={<link.icon size={18} />}
                active={location.pathname === link.to || location.pathname.startsWith(`${link.to}/`)}
                variant="filled"
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
              variant="filled"
            />
            <NavLink
              label="当前重点：先看今日运行，再处理任务记录里的失败项。"
              leftSection={<IconSparkles size={18} />}
              disabled
              variant="light"
            />
          </Stack>
        </AppShell.Section>
      </AppShell.Navbar>

      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
