import { Alert, Badge, Box, Button, Grid, Group, Loader, Paper, SimpleGrid, Stack, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "../shared/api/client";
import type { DatasetPipelineModeListResponse, LayerSnapshotLatestResponse } from "../shared/api/types";
import { formatDateLabel, formatDateTimeLabel } from "../shared/date-format";
import { SectionCard } from "../shared/ui/section-card";
import { StatusBadge } from "../shared/ui/status-badge";

type CardStatus = "healthy" | "warning" | "failed" | "unknown";
type StageKey = "raw" | "std" | "resolution" | "serving";

function toCardStatus(rawStatus: string | null | undefined): CardStatus {
  const key = (rawStatus || "").toLowerCase();
  if (key === "failed" || key === "stale") return "failed";
  if (key === "warning" || key === "lagging") return "warning";
  if (key === "healthy" || key === "fresh" || key === "success") return "healthy";
  return "unknown";
}

function statusDotColor(status: CardStatus) {
  if (status === "healthy") return "rgb(34, 197, 94)";
  if (status === "failed") return "rgb(244, 63, 94)";
  if (status === "warning") return "rgb(245, 158, 11)";
  return "rgb(148, 163, 184)";
}

function modeLabel(mode: string): string {
  if (mode === "single_source_direct") return "单源直出";
  if (mode === "multi_source_pipeline") return "多源流水线";
  if (mode === "raw_only") return "仅原始层";
  if (mode === "legacy_core_direct") return "旧链路直出";
  return "未定义";
}

function modeColor(mode: string): string {
  if (mode === "single_source_direct") return "teal";
  if (mode === "multi_source_pipeline") return "indigo";
  if (mode === "raw_only") return "gray";
  if (mode === "legacy_core_direct") return "orange";
  return "gray";
}

function modeTone(mode: string) {
  if (mode === "single_source_direct") {
    return { background: "rgba(34, 197, 94, 0.14)", color: "#166534", border: "rgba(34, 197, 94, 0.28)" };
  }
  if (mode === "multi_source_pipeline") {
    return { background: "rgba(79, 70, 229, 0.14)", color: "#3730a3", border: "rgba(79, 70, 229, 0.26)" };
  }
  if (mode === "legacy_core_direct") {
    return { background: "rgba(251, 146, 60, 0.14)", color: "#9a3412", border: "rgba(251, 146, 60, 0.24)" };
  }
  return { background: "rgba(100, 116, 139, 0.14)", color: "#334155", border: "rgba(100, 116, 139, 0.24)" };
}

function expectedStages(mode: string): StageKey[] {
  if (mode === "single_source_direct") return ["raw", "serving"];
  if (mode === "multi_source_pipeline") return ["raw", "std", "resolution", "serving"];
  if (mode === "raw_only") return ["raw"];
  if (mode === "legacy_core_direct") return ["raw"];
  return ["raw", "serving"];
}

function stageLabel(stage: StageKey): string {
  if (stage === "raw") return "原始层";
  if (stage === "std") return "标准层";
  if (stage === "resolution") return "融合层";
  return "服务层";
}

function stageTableName(stage: StageKey, item: DatasetPipelineModeListResponse["items"][number]): string | null {
  if (stage === "raw") return item.raw_table;
  if (stage === "std") return item.std_table_hint;
  if (stage === "serving") return item.serving_table;
  return null;
}

export function OpsV21OverviewPage() {
  const modeQuery = useQuery({
    queryKey: ["ops", "pipeline-modes", "v21-overview"],
    queryFn: () => apiRequest<DatasetPipelineModeListResponse>("/api/v1/ops/pipeline-modes?limit=1000"),
  });
  const latestQuery = useQuery({
    queryKey: ["ops", "layer-snapshot", "latest", "v21-overview"],
    queryFn: () => apiRequest<LayerSnapshotLatestResponse>("/api/v1/ops/layer-snapshots/latest?limit=3000"),
  });

  const isLoading = modeQuery.isLoading || latestQuery.isLoading;
  const error = modeQuery.error || latestQuery.error;

  const latestItems = latestQuery.data?.items || [];
  const stageLatestByDataset = new Map<string, Partial<Record<StageKey, LayerSnapshotLatestResponse["items"][number]>>>();
  for (const item of latestItems) {
    const stage = item.stage as StageKey;
    if (!["raw", "std", "resolution", "serving"].includes(stage)) continue;
    const existing = stageLatestByDataset.get(item.dataset_key) || {};
    const previous = existing[stage];
    if (!previous || new Date(item.calculated_at).getTime() > new Date(previous.calculated_at).getTime()) {
      existing[stage] = item;
      stageLatestByDataset.set(item.dataset_key, existing);
    }
  }

  const cards = (modeQuery.data?.items || []).sort((a, b) => {
    const d = a.domain_display_name.localeCompare(b.domain_display_name, "zh-CN");
    if (d !== 0) return d;
    return a.display_name.localeCompare(b.display_name, "zh-CN");
  });
  const groupedCards = new Map<string, typeof cards>();
  for (const item of cards) {
    const key = `${item.domain_key}::${item.domain_display_name}`;
    const list = groupedCards.get(key) || [];
    list.push(item);
    groupedCards.set(key, list);
  }

  return (
    <Stack gap="lg">
      <SectionCard title="数据状态总览" description="按数据集展示当前运行模式、分层状态与链路关系。">
        {isLoading ? <Loader size="sm" /> : null}
        {error ? (
          <Alert color="red" title="读取数据状态总览失败">
            {error instanceof Error ? error.message : "未知错误"}
          </Alert>
        ) : null}
      </SectionCard>

      {!isLoading && !error && cards.length === 0 ? (
        <Alert color="blue" title="暂无可展示的数据集">
          当前还没有 pipeline_mode 记录，请先执行一次初始化。
        </Alert>
      ) : null}

      {Array.from(groupedCards.entries()).map(([groupKey, groupItems]) => {
        const [, groupDisplayName] = groupKey.split("::");
        return (
          <SectionCard key={groupKey} title={groupDisplayName} description={`共 ${groupItems.length} 个数据集`}>
            <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="md" verticalSpacing="md">
              {groupItems.map((item) => {
          const status = toCardStatus(item.freshness_status);
          const stages = expectedStages(item.mode);
          const stageMap = stageLatestByDataset.get(item.dataset_key) || {};
          const statusUpdatedAt = stages
            .map((stage) => stageMap[stage]?.calculated_at || null)
            .filter((value): value is string => Boolean(value))
            .sort()
            .at(-1);
          const flags: Array<{ label: string; on: boolean }> = [
            { label: "映射规则", on: item.std_mapping_configured },
            { label: "清洗规则", on: item.std_cleansing_configured },
            { label: "融合策略", on: item.resolution_policy_configured },
          ];

                return (
                  <Paper
                    key={item.dataset_key}
                    radius="md"
                    p="md"
                    style={{
                      border: "1px solid rgba(15, 23, 42, 0.16)",
                      background: "rgba(250, 204, 21, 0.10)",
                      minHeight: 278,
                    }}
                  >
                    <Stack gap={8} h="100%">
                      <Group justify="space-between" align="center" wrap="nowrap" gap={10}>
                        <Stack gap={2} justify="center" style={{ minWidth: 0, flex: 1 }}>
                          <Group gap={8} align="center" wrap="nowrap">
                            <Box
                              w={9}
                              h={9}
                              style={{ borderRadius: "50%", background: statusDotColor(status), flex: "0 0 auto" }}
                            />
                            <Text fw={800} size="xl" lineClamp={1} style={{ minWidth: 0 }}>
                              {item.display_name}
                            </Text>
                          </Group>
                          <Text size="xs" c="dimmed" ml={17} lineClamp={1}>
                            {item.dataset_key}
                          </Text>
                        </Stack>
                        <Stack gap={4} align="flex-start" justify="center" style={{ flex: "0 0 auto", minWidth: 0 }}>
                          <Badge variant="light" color="blue" size="sm" styles={{ root: { background: "rgba(59, 130, 246, 0.12)", border: "1px solid rgba(59,130,246,0.25)" } }}>
                            最新业务日期：{item.latest_business_date ? formatDateLabel(item.latest_business_date) : "—"}
                          </Badge>
                          <Badge variant="light" color="gray" size="sm" styles={{ root: { background: "rgba(100, 116, 139, 0.12)", border: "1px solid rgba(100,116,139,0.22)" } }}>
                            状态更新时间：{statusUpdatedAt ? formatDateTimeLabel(statusUpdatedAt) : "—"}
                          </Badge>
                        </Stack>
                        <Badge
                          variant="light"
                          color={modeColor(item.mode)}
                          size="md"
                          style={{ flex: "0 0 auto", fontSize: 14 }}
                          styles={{
                            root: {
                              background: modeTone(item.mode).background,
                              color: modeTone(item.mode).color,
                              border: `1px solid ${modeTone(item.mode).border}`,
                              fontWeight: 700,
                            },
                          }}
                        >
                          {modeLabel(item.mode)}
                        </Badge>
                      </Group>

                      <Stack gap={6}>
                        {stages.map((stage) => (
                          <Group key={stage} justify="space-between" align="center">
                            <Text size="sm" c="dimmed">
                              {stageLabel(stage)}
                              {stageTableName(stage, item) ? `（${stageTableName(stage, item)}）` : ""}
                            </Text>
                            <StatusBadge value={stageMap[stage]?.status || "unknown"} />
                          </Group>
                        ))}
                      </Stack>

                      <Grid gutter={6}>
                        {flags.map((flag) => (
                          <Grid.Col key={flag.label} span={4}>
                            <Paper
                              radius="sm"
                              p="xs"
                              style={{
                                background: "rgba(254, 249, 220, 0.92)",
                                border: "1px solid rgba(180, 160, 90, 0.24)",
                              }}
                            >
                              <Text size="xs" c="dimmed">{flag.label}</Text>
                              <Badge
                                size="xs"
                                variant="light"
                                styles={{
                                  root: flag.on
                                    ? {
                                      background: "rgba(34, 197, 94, 0.16)",
                                      color: "#166534",
                                      border: "1px solid rgba(34, 197, 94, 0.28)",
                                    }
                                    : {
                                      background: "rgba(148, 163, 184, 0.14)",
                                      color: "#475569",
                                      border: "1px solid rgba(148, 163, 184, 0.24)",
                                    },
                                }}
                              >
                                {flag.on ? "已配置" : "未配置"}
                              </Badge>
                            </Paper>
                          </Grid.Col>
                        ))}
                      </Grid>

                      <Group justify="space-between" mt="auto">
                        <Button
                          component="a"
                          href={`/app/ops/v21/datasets/detail/${encodeURIComponent(item.dataset_key)}`}
                          size="xs"
                          variant="light"
                          color="brand"
                        >
                          查看详情
                        </Button>
                      </Group>
                    </Stack>
                  </Paper>
                );
              })}
            </SimpleGrid>
          </SectionCard>
        );
      })}
    </Stack>
  );
}
