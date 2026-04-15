import { Alert, Badge, Box, Button, Group, Loader, Paper, SimpleGrid, Stack, Text, Tooltip } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "../shared/api/client";
import type { LayerSnapshotLatestResponse, OpsFreshnessResponse } from "../shared/api/types";
import { formatDateLabel, formatDateTimeLabel } from "../shared/date-format";
import { formatResourceLabel } from "../shared/ops-display";
import { SectionCard } from "../shared/ui/section-card";

type SourceKey = "tushare" | "biying";
type CardStatus = "healthy" | "warning" | "failed" | "unknown";

interface SourceCardItem {
  datasetKey: string;
  displayName: string;
  domainKey: string;
  domainDisplayName: string;
  rawTableLabel: string;
  status: CardStatus;
  recentSyncAt: string | null;
  recentSyncResult: string;
  dateRangeText: string;
  cadenceText: string;
  primaryExecutionSpecKey: string | null;
  autoEnabled: boolean;
  autoTooltip: string;
}

function inferSource(datasetKey: string, rawTable: string | null, targetTable: string): SourceKey {
  if (datasetKey.startsWith("biying_")) return "biying";
  if ((rawTable || "").toLowerCase().startsWith("raw_biying.")) return "biying";
  if ((targetTable || "").toLowerCase().startsWith("raw_biying.")) return "biying";
  return "tushare";
}

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

function statusTag(status: CardStatus): { text: string; color: string } {
  if (status === "healthy") return { text: "成功", color: "green" };
  if (status === "failed") return { text: "失败", color: "red" };
  if (status === "warning") return { text: "滞后", color: "yellow" };
  return { text: "未知", color: "gray" };
}

function cadenceLabel(cadence: string): string {
  const key = (cadence || "").toLowerCase();
  if (key === "daily") return "每日";
  if (key === "weekly") return "每周";
  if (key === "monthly") return "每月";
  if (key === "intraday") return "盘中";
  if (key === "on_demand") return "按需";
  return "未定义";
}

function buildDateRangeText(item: OpsFreshnessResponse["groups"][number]["items"][number]): string {
  if (item.earliest_business_date && item.latest_business_date) {
    return `${formatDateLabel(item.earliest_business_date)} ~ ${formatDateLabel(item.latest_business_date)}`;
  }
  if (item.last_sync_date) {
    return `最近同步：${formatDateLabel(item.last_sync_date)}`;
  }
  return "—";
}

export function OpsV21SourcePage({ sourceKey, title }: { sourceKey: SourceKey; title: string }) {
  const freshnessQuery = useQuery({
    queryKey: ["ops", "freshness", `v21-source-${sourceKey}`],
    queryFn: () => apiRequest<OpsFreshnessResponse>("/api/v1/ops/freshness"),
  });
  const latestQuery = useQuery({
    queryKey: ["ops", "layer-snapshot", "latest", `v21-source-${sourceKey}`],
    queryFn: () => apiRequest<LayerSnapshotLatestResponse>(`/api/v1/ops/layer-snapshots/latest?source_key=${sourceKey}&stage=raw&limit=1000`),
  });

  const isLoading = freshnessQuery.isLoading || latestQuery.isLoading;
  const error = freshnessQuery.error || latestQuery.error;

  const rawLatestByDataset = new Map(
    (latestQuery.data?.items || [])
      .filter((item) => item.stage === "raw")
      .map((item) => [item.dataset_key, item] as const),
  );
  const freshnessByDataset = new Map(
    (freshnessQuery.data?.groups || [])
      .flatMap((group) => group.items.map((item) => [item.dataset_key, { group, item }] as const)),
  );

  const cards: SourceCardItem[] = (latestQuery.data?.items || [])
    .filter((item) => item.stage === "raw")
    .filter((item) => (item.source_key || "").toLowerCase() === sourceKey)
    .map((rawLatest) => {
      const freshMeta = freshnessByDataset.get(rawLatest.dataset_key);
      const freshGroup = freshMeta?.group;
      const freshItem = freshMeta?.item;
      const fallbackRawTable = `${sourceKey === "biying" ? "raw_biying" : "raw_tushare"}.${rawLatest.dataset_key.replace(/^biying_/, "")}`;
      const sourceScopedRawTable = (freshItem?.raw_table || "").replace(/^raw_tushare\./i, sourceKey === "biying" ? "raw_biying." : "raw_tushare.");
      const status = toCardStatus(rawLatest.status || freshItem?.freshness_status);
      return {
        datasetKey: rawLatest.dataset_key,
        displayName: formatResourceLabel(rawLatest.dataset_key),
        domainKey: freshGroup?.domain_key || "uncategorized",
        domainDisplayName: freshGroup?.domain_display_name || "未分类",
        rawTableLabel: sourceScopedRawTable || fallbackRawTable,
        status,
        recentSyncAt: rawLatest.calculated_at || (freshItem?.latest_success_at || null),
        recentSyncResult: status === "failed" ? "失败" : status === "warning" ? "告警" : status === "healthy" ? "成功" : "未知",
        dateRangeText: freshItem ? buildDateRangeText(freshItem) : "—",
        cadenceText: cadenceLabel(freshItem?.cadence || ""),
        primaryExecutionSpecKey: freshItem?.primary_execution_spec_key || null,
        autoEnabled: (freshItem?.auto_schedule_active || 0) > 0,
        autoTooltip:
          (freshItem?.auto_schedule_total || 0) > 0
            ? `已配置自动任务 ${freshItem?.auto_schedule_active || 0}/${freshItem?.auto_schedule_total || 0} 条，下一次：${freshItem?.auto_schedule_next_run_at ? formatDateTimeLabel(freshItem.auto_schedule_next_run_at) : "待计算"}`
            : "未配置自动任务",
      };
    })
    .sort((a, b) => a.displayName.localeCompare(b.displayName, "zh-CN"));

  const groupedCards = new Map<string, SourceCardItem[]>();
  for (const card of cards) {
    const key = `${card.domainKey}::${card.domainDisplayName}`;
    const list = groupedCards.get(key) || [];
    list.push(card);
    groupedCards.set(key, list);
  }

  return (
    <Stack gap="lg">
      <SectionCard
        title={title}
        description="仅展示数据源侧原始下载状态（raw）。这里不展示 std / serving。"
      >
        {isLoading ? <Loader size="sm" /> : null}
        {error ? (
          <Alert color="red" title="读取数据源状态失败">
            {error instanceof Error ? error.message : "未知错误"}
          </Alert>
        ) : null}
      </SectionCard>

      {!isLoading && !error && cards.length === 0 ? (
        <Alert color="blue" title={`暂无 ${title} 数据`}>
          当前没有可展示的 raw 数据源状态。
        </Alert>
      ) : null}

      {Array.from(groupedCards.entries()).map(([groupKey, items]) => {
        const [, groupDisplayName] = groupKey.split("::");
        return (
          <SectionCard key={groupKey} title={groupDisplayName} description={`共 ${items.length} 个数据集`}>
            <SimpleGrid cols={{ base: 1, sm: 2, md: 3, lg: 4, xl: 5 }} spacing="md" verticalSpacing="md">
              {items.map((item) => (
                <Paper
                  key={item.datasetKey}
                  radius="md"
                  p="md"
                  style={{
                    border: "1px solid rgba(15, 23, 42, 0.18)",
                    background: "rgba(250, 204, 21, 0.10)",
                    minHeight: 228,
                  }}
                >
                  <Stack gap={10} h="100%">
                    <Group justify="space-between" align="center">
                      <Stack gap={2}>
                        <Group gap={8} align="center">
                          <Box
                            w={9}
                            h={9}
                            style={{ borderRadius: "50%", background: statusDotColor(item.status), flex: "0 0 auto" }}
                          />
                          <Text fw={700} size="sm" lineClamp={1}>
                            {item.displayName}
                          </Text>
                        </Group>
                        <Text size="xs" c="dimmed" ml={17} lineClamp={1}>
                          {item.rawTableLabel}
                        </Text>
                      </Stack>
                    </Group>

                    <Stack gap={6}>
                      <Group gap={6} wrap="wrap">
                        <Text size="sm">最近同步：{item.recentSyncAt ? formatDateTimeLabel(item.recentSyncAt) : "—"}</Text>
                        <Badge size="xs" variant="light" color={statusTag(item.status).color}>
                          {statusTag(item.status).text}
                        </Badge>
                      </Group>
                      <Text size="sm">更新频率：{item.cadenceText}</Text>
                      <Text size="sm">时间范围：{item.dateRangeText}</Text>
                    </Stack>

                    <Group justify="space-between" mt="auto">
                      {item.autoEnabled ? (
                        <Tooltip label={item.autoTooltip} withArrow multiline w={280}>
                          <Badge variant="light" color="orange">
                            自动
                          </Badge>
                        </Tooltip>
                      ) : (
                        <Text size="xs" c="dimmed">未配置自动更新</Text>
                      )}
                      {item.status !== "healthy" ? (
                        <Button
                          component="a"
                          href={`/app/ops/manual-sync?spec_key=${encodeURIComponent(item.primaryExecutionSpecKey || "")}&spec_type=job`}
                          size="xs"
                          variant="light"
                          color="brand"
                        >
                          去操作
                        </Button>
                      ) : <span />}
                    </Group>
                  </Stack>
                </Paper>
              ))}
            </SimpleGrid>
          </SectionCard>
        );
      })}
    </Stack>
  );
}
