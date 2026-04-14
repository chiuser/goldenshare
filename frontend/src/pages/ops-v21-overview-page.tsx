import { Alert, Badge, Button, Grid, Group, Loader, Paper, Stack, Switch, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "../shared/api/client";
import type { LayerSnapshotLatestResponse, OpsFreshnessResponse } from "../shared/api/types";
import { formatDateTimeLabel } from "../shared/date-format";
import { SectionCard } from "../shared/ui/section-card";
import { StatusBadge } from "../shared/ui/status-badge";
import { buildFreshnessDisplayNameMap, groupDatasetSummaries } from "./ops-v21-shared";


function cardTone(status: "healthy" | "warning" | "failed" | "unknown") {
  if (status === "healthy") {
    return {
      border: "1px solid rgba(34, 197, 94, 0.35)",
      background: "linear-gradient(180deg, rgba(34,197,94,0.16), rgba(34,197,94,0.07))",
    };
  }
  if (status === "failed") {
    return {
      border: "1px solid rgba(244, 63, 94, 0.35)",
      background: "linear-gradient(180deg, rgba(244,63,94,0.14), rgba(244,63,94,0.06))",
    };
  }
  if (status === "warning") {
    return {
      border: "1px solid rgba(245, 158, 11, 0.35)",
      background: "linear-gradient(180deg, rgba(245,158,11,0.14), rgba(245,158,11,0.06))",
    };
  }
  return {
    border: "1px solid rgba(99, 102, 241, 0.2)",
    background: "linear-gradient(180deg, rgba(99,102,241,0.08), rgba(99,102,241,0.04))",
  };
}

export function OpsV21OverviewPage() {
  const freshnessQuery = useQuery({
    queryKey: ["ops", "freshness", "v21-overview"],
    queryFn: () => apiRequest<OpsFreshnessResponse>("/api/v1/ops/freshness"),
  });
  const latestQuery = useQuery({
    queryKey: ["ops", "layer-snapshot", "latest", "v21-overview"],
    queryFn: () => apiRequest<LayerSnapshotLatestResponse>("/api/v1/ops/layer-snapshots/latest?limit=1000"),
  });

  const isLoading = freshnessQuery.isLoading || latestQuery.isLoading;
  const error = freshnessQuery.error || latestQuery.error;

  const displayNameMap = buildFreshnessDisplayNameMap(freshnessQuery.data);
  const summaries = groupDatasetSummaries(latestQuery.data?.items || [], displayNameMap);

  return (
    <Stack gap="lg">
      <SectionCard
        title="数据状态总览（V2.1）"
        description="每个卡片代表一个数据集，点击可进入详情页。当前先接入已有能力，后续继续补充策略和发布细节。"
      >
        {isLoading ? <Loader size="sm" /> : null}
        {error ? (
          <Alert color="red" title="读取总览失败">
            {error instanceof Error ? error.message : "未知错误"}
          </Alert>
        ) : null}
      </SectionCard>

      <Grid>
        {summaries.map((item) => (
          <Grid.Col key={item.datasetKey} span={{ base: 12, md: 6, xl: 4 }}>
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
                    <Text c="dimmed" fw={600}>{item.displayName}</Text>
                  </Stack>
                  <Switch size="md" onLabel="" offLabel="" />
                </Group>

                <Group gap={6}>
                  {item.sourceKeys.map((source) => (
                    <Badge key={source} size="sm" radius="xl" variant="light" color="teal">
                      {source}
                    </Badge>
                  ))}
                </Group>

                <Group grow>
                  {(["raw", "std", "serving"] as const).map((stage) => (
                    <Paper key={stage} radius="sm" p="xs" bg="rgba(255,255,255,0.55)">
                      <Text size="sm" c="dimmed" ff="IBM Plex Mono, SFMono-Regular, monospace">{stage}</Text>
                      <Group gap={6}>
                        <StatusBadge value={item.stageMap[stage]?.status || "unknown"} />
                      </Group>
                      <Text size="sm" fw={700}>
                        {item.stageMap[stage] ? formatDateTimeLabel(item.stageMap[stage]?.calculated_at) : "—"}
                      </Text>
                    </Paper>
                  ))}
                </Group>

                <Group justify="space-between" align="center">
                  <Text size="sm" c="dimmed">
                    最近计算：{item.lastCalculatedAt ? formatDateTimeLabel(item.lastCalculatedAt) : "—"}
                  </Text>
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
