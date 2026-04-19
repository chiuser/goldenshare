import { Alert, Grid, Loader, Stack, Table } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";

import { useCurrentUser } from "../features/auth/auth-context";
import { apiRequest } from "../shared/api/client";
import type { HealthResponse } from "../shared/api/types";
import { formatEnvironmentLabel, formatHealthStatusLabel, formatServiceNameLabel } from "../shared/ops-display";
import { PageHeader } from "../shared/ui/page-header";
import { SectionCard } from "../shared/ui/section-card";
import { StatCard } from "../shared/ui/stat-card";


export function PlatformCheckPage() {
  const healthQuery = useQuery({
    queryKey: ["platform", "health"],
    queryFn: () => apiRequest<HealthResponse>("/api/health"),
    staleTime: 10_000,
  });
  const userQuery = useCurrentUser();

  return (
    <Stack gap="lg">
      <PageHeader
        title="平台检查"
        description="这是前端应用的防腐页，用来验证新前端、接口层和认证链路是否健康。"
      />

      <Grid>
        <Grid.Col span={{ base: 12, md: 4 }}>
          <StatCard
            label="服务健康"
            value={formatHealthStatusLabel(healthQuery.data?.status ?? "loading")}
            hint={
              healthQuery.data
                ? `${formatServiceNameLabel(healthQuery.data.service)} / ${formatEnvironmentLabel(healthQuery.data.env)}`
                : "正在读取"
            }
          />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 4 }}>
          <StatCard
            label="登录状态"
            value={userQuery.data ? "已登录" : "未登录"}
            hint={userQuery.data ? userQuery.data.username : "未登录时只检查服务健康"}
          />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 4 }}>
          <StatCard
            label="应用入口"
            value="已接通"
            hint="新前端应用已经独立挂载，不会直接影响现有平台检查页和旧控制台。"
          />
        </Grid.Col>
      </Grid>

      <SectionCard title="当前状态" description="这里用于快速确认服务、环境和当前登录上下文是否一致。">
        <Stack gap="md">
          {healthQuery.isLoading ? <Loader size="sm" /> : null}
          {healthQuery.error ? (
            <Alert color="red" title="健康检查失败">
              {healthQuery.error instanceof Error ? healthQuery.error.message : "未知错误"}
            </Alert>
          ) : null}
          {!healthQuery.error && healthQuery.data ? (
            <Table highlightOnHover>
              <Table.Tbody>
                <Table.Tr>
                  <Table.Th>服务</Table.Th>
                  <Table.Td>{formatServiceNameLabel(healthQuery.data.service)}</Table.Td>
                </Table.Tr>
                <Table.Tr>
                  <Table.Th>状态</Table.Th>
                  <Table.Td>{formatHealthStatusLabel(healthQuery.data.status)}</Table.Td>
                </Table.Tr>
                <Table.Tr>
                  <Table.Th>环境</Table.Th>
                  <Table.Td>{formatEnvironmentLabel(healthQuery.data.env)}</Table.Td>
                </Table.Tr>
                <Table.Tr>
                  <Table.Th>当前用户</Table.Th>
                  <Table.Td>{userQuery.data?.display_name || userQuery.data?.username || "未登录"}</Table.Td>
                </Table.Tr>
              </Table.Tbody>
            </Table>
          ) : null}
        </Stack>
      </SectionCard>
    </Stack>
  );
}
