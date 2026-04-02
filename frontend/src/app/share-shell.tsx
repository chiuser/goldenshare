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
import { useDisclosure } from "@mantine/hooks";
import { IconChartCandle, IconLogout, IconSettings } from "@tabler/icons-react";
import { Link, Outlet, useLocation, useNavigate } from "@tanstack/react-router";

import { useAuth, useCurrentUser } from "../features/auth/auth-context";


const shareLinks = [
  { to: "/share", label: "市场快照", icon: IconChartCandle },
];

export function ShareShell() {
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
            <img src="/app/brand/logo-icon.png" alt="财势乾坤图标" className="app-brand-mark" />
            <Stack gap={0}>
              <Text fw={800} size="xl">财势乾坤</Text>
              <Text c="dimmed" size="sm">行情展示台</Text>
            </Stack>
          </Group>
          <Group gap="sm">
            <Badge radius="xl" size="lg" color="brand" variant="filled">行情展示</Badge>
            <Stack gap={0} align="flex-end">
              <Text fw={600}>{userQuery.data?.display_name || userQuery.data?.username || "管理员"}</Text>
              <Text c="dimmed" size="xs">{userQuery.data?.is_admin ? "管理员" : "操作员"}</Text>
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
            {shareLinks.map((link) => (
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
              to="/ops/data-status"
              label="进入运维管理"
              leftSection={<IconSettings size={18} />}
              variant="light"
              color="brand"
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
