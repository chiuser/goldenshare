import { Alert, Badge, Button, Grid, Group, Loader, Paper, Stack, Switch, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "../shared/api/client";
import type { LayerSnapshotLatestResponse, OpsFreshnessResponse } from "../shared/api/types";
import { formatDateTimeLabel } from "../shared/date-format";
import { SectionCard } from "../shared/ui/section-card";
import { StatusBadge } from "../shared/ui/status-badge";
import { groupDatasetSummariesWithFreshnessFallback } from "./ops-v21-shared";


function cardTone(status: "healthy" | "warning" | "failed" | "unknown") {
  if (status === "healthy") {
    return {
      borderLeft: "4px solid rgba(16,185,129,0.9)",
      background: "linear-gradient(180deg, rgba(16,185,129,0.12), rgba(16,185,129,0.05))",
    };
  }
  if (status === "failed") {
    return {
      borderLeft: "4px solid rgba(244,63,94,0.9)",
      background: "linear-gradient(180deg, rgba(244,63,94,0.12), rgba(244,63,94,0.05))",
    };
  }
  if (status === "warning") {
    return {
      borderLeft: "4px solid rgba(245,158,11,0.9)",
      background: "linear-gradient(180deg, rgba(245,158,11,0.12), rgba(245,158,11,0.05))",
    };
  }
  return {
    borderLeft: "4px solid rgba(99,102,241,0.6)",
    background: "linear-gradient(180deg, rgba(99,102,241,0.08), rgba(99,102,241,0.04))",
  };
}

export function OpsV21SourcePage({ sourceKey, title }: { sourceKey: "tushare" | "biying"; title: string }) {
  const freshnessQuery = useQuery({
    queryKey: ["ops", "freshness", `v21-source-${sourceKey}`],
    queryFn: () => apiRequest<OpsFreshnessResponse>("/api/v1/ops/freshness"),
  });
  const latestQuery = useQuery({
    queryKey: ["ops", "layer-snapshot", "latest", `v21-source-${sourceKey}`],
    queryFn: () => apiRequest<LayerSnapshotLatestResponse>(`/api/v1/ops/layer-snapshots/latest?source_key=${sourceKey}&limit=1000`),
  });

  const isLoading = freshnessQuery.isLoading || latestQuery.isLoading;
  const error = freshnessQuery.error || latestQuery.error;
  const summaries = groupDatasetSummariesWithFreshnessFallback(latestQuery.data?.items || [], freshnessQuery.data)
    .filter((item) => item.sourceKeys.includes(sourceKey));

  return (
    <Stack gap="lg">
      <SectionCard
        title={title}
        description="先展示该数据源下的数据集状态卡，卡片右上角开关先保留控件位，后续再定义具体行为。"
      >
        {isLoading ? <Loader size="sm" /> : null}
        {error ? (
          <Alert color="red" title="读取数据源状态失败">
            {error instanceof Error ? error.message : "未知错误"}
          </Alert>
        ) : null}
      </SectionCard>

      {!isLoading && !error && summaries.length === 0 ? (
        <Alert color="blue" title={`暂无 ${title} 数据`}>
          当前没有可展示的来源快照记录。先运行该来源的数据同步任务，再回来查看。
        </Alert>
      ) : null}

      <Grid>
        {summaries.map((item) => (
          <Grid.Col key={item.datasetKey} span={{ base: 12, xl: 6 }}>
            <Paper radius="md" p="md" style={cardTone(item.status)}>
              <Stack gap="sm">
                <Group justify="space-between" align="flex-start">
                  <Stack gap={2}>
                    <Group gap={8}>
                      <Text fw={800} size="xl">{item.datasetKey}</Text>
                      <StatusBadge
                        value={
                          item.status === "healthy"
                            ? "fresh"
                            : item.status === "warning"
                              ? "lagging"
                              : item.status === "failed"
                                ? "failed"
                                : "unknown"
                        }
                      />
                    </Group>
                    <Text fw={600} c="dimmed">{item.displayName}</Text>
                  </Stack>
                  <Switch size="md" onLabel="" offLabel="" />
                </Group>

                <Group gap={8}>
                  {item.sourceKeys.map((source) => (
                    <Badge key={source} size="sm" radius="xl" variant="dot" color="teal">
                      {source}
                    </Badge>
                  ))}
                </Group>

                <Group grow>
                  {(["raw", "std", "serving"] as const).map((stage) => (
                    <Paper key={stage} p="xs" radius="sm" bg="rgba(255,255,255,0.56)">
                      <Text ff="IBM Plex Mono, SFMono-Regular, monospace" c="dimmed" size="sm">{stage}</Text>
                      <Group gap={6}>
                        <StatusBadge value={item.stageMap[stage]?.status || "unknown"} />
                      </Group>
                      <Text fw={700} size="lg">
                        {item.stageMap[stage] ? formatDateTimeLabel(item.stageMap[stage].calculated_at) : "—"}
                      </Text>
                    </Paper>
                  ))}
                </Group>

                <Group justify="space-between">
                  <Text size="sm" c="dimmed">最近同步：{item.lastCalculatedAt ? formatDateTimeLabel(item.lastCalculatedAt) : "—"}</Text>
                  <Button
                    component="a"
                    href={`/app/ops/v21/datasets/detail/${encodeURIComponent(item.datasetKey)}`}
                    size="sm"
                    variant="light"
                    color="brand"
                  >
                    查看详情
                  </Button>
                </Group>
              </Stack>
            </Paper>
          </Grid.Col>
        ))}
      </Grid>
    </Stack>
  );
}
