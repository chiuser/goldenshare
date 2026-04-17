import { Alert, Button, Center, Grid, Loader, Paper, Stack, Text, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";

import { useAuth } from "../features/auth/auth-context";
import { apiRequest } from "../shared/api/client";
import type { OpsOverviewSummaryResponse } from "../shared/api/types";
import { StatCard } from "../shared/ui/stat-card";


export function UserOverviewPage() {
  const navigate = useNavigate();
  const { clearToken } = useAuth();
  const summaryQuery = useQuery({
    queryKey: ["ops", "overview-summary", "user"],
    queryFn: () => apiRequest<OpsOverviewSummaryResponse>("/api/v1/ops/overview-summary"),
  });

  return (
    <div
      className="app-gradient-shell"
      style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24 }}
    >
      <Paper className="glass-card" radius="xl" p={32} miw={360} maw={1100} w="100%">
        <Stack gap="lg">
          <Stack gap={6}>
            <Text c="dimmed" fw={700} size="sm" tt="uppercase">
              数据状态总览
            </Text>
            <Title order={2}>状态概览</Title>
            <Text c="dimmed" size="sm">
              当前页面为普通用户只读视图，仅展示总体状态统计。
            </Text>
          </Stack>

          {summaryQuery.isLoading ? (
            <Center py="md">
              <Loader size="sm" />
            </Center>
          ) : null}

          {summaryQuery.error ? (
            <Alert color="red" title="读取状态概览失败">
              {summaryQuery.error instanceof Error ? summaryQuery.error.message : "未知错误"}
            </Alert>
          ) : null}

          {summaryQuery.data ? (
            <Grid>
              <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
                <StatCard label="数据集总数" value={summaryQuery.data.freshness_summary.total_datasets} />
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
                <StatCard label="状态正常" value={summaryQuery.data.freshness_summary.fresh_datasets} />
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
                <StatCard label="需要关注" value={summaryQuery.data.freshness_summary.lagging_datasets} />
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
                <StatCard
                  label="严重滞后 / 未知"
                  value={summaryQuery.data.freshness_summary.stale_datasets + summaryQuery.data.freshness_summary.unknown_datasets}
                />
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
                <StatCard label="已停用" value={summaryQuery.data.freshness_summary.disabled_datasets} />
              </Grid.Col>
            </Grid>
          ) : null}

          <Button
            variant="light"
            color="gray"
            onClick={async () => {
              clearToken();
              await navigate({ to: "/login" });
            }}
          >
            退出登录
          </Button>
        </Stack>
      </Paper>
    </div>
  );
}
