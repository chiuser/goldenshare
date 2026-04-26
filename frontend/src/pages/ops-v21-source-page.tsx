import { Alert, Badge, Box, Button, Group, Loader, Paper, SimpleGrid, Stack, Text, Tooltip } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "../shared/api/client";
import type { DatasetCardListResponse } from "../shared/api/types";
import { formatDateLabel, formatDateTimeLabel } from "../shared/date-format";
import { buildManualTaskHref } from "../shared/ops-links";
import { SectionCard } from "../shared/ui/section-card";
import { StatusBadge } from "../shared/ui/status-badge";

type CardStatus = "running" | "healthy" | "warning" | "failed" | "unknown";
type SourceKey = "tushare" | "biying";
type DatasetCard = DatasetCardListResponse["groups"][number]["items"][number];

interface SourceCardItem {
  datasetKey: string;
  displayName: string;
  domainKey: string;
  domainDisplayName: string;
  rawTableLabel: string;
  status: CardStatus;
  lastSyncText: string;
  dateRangeText: string;
  cadenceText: string;
  primaryActionKey: string | null;
  autoEnabled: boolean;
  autoTooltip: string;
  probeEnabled: boolean;
  probeTooltip: string;
}

function toCardStatus(rawStatus: string | null | undefined): CardStatus {
  const key = (rawStatus || "").toLowerCase();
  if (key === "running" || key === "queued" || key === "canceling") return "running";
  if (key === "failed" || key === "stale") return "failed";
  if (key === "warning" || key === "lagging") return "warning";
  if (key === "healthy" || key === "fresh" || key === "success") return "healthy";
  return "unknown";
}

function statusDotColor(status: CardStatus) {
  if (status === "running") return "var(--mantine-color-info-5)";
  if (status === "healthy") return "var(--mantine-color-success-5)";
  if (status === "failed") return "var(--mantine-color-error-5)";
  if (status === "warning") return "var(--mantine-color-warning-5)";
  return "var(--mantine-color-neutral-5)";
}

function statusLabel(status: CardStatus): string {
  if (status === "running") return "执行中";
  if (status === "healthy") return "正常";
  if (status === "failed") return "失败";
  if (status === "warning") return "滞后";
  return "未知";
}

function buildDateRangeText(item: DatasetCard): string {
  if (item.latest_observed_at) {
    if (item.earliest_observed_at && item.earliest_observed_at !== item.latest_observed_at) {
      return `${formatDateTimeLabel(item.earliest_observed_at)} ~ ${formatDateTimeLabel(item.latest_observed_at)}`;
    }
    return `最新时间：${formatDateTimeLabel(item.latest_observed_at)}`;
  }
  if (item.latest_business_date) {
    if (item.earliest_business_date && item.earliest_business_date !== item.latest_business_date) {
      return `${formatDateLabel(item.earliest_business_date)} ~ ${formatDateLabel(item.latest_business_date)}`;
    }
    return `最新业务日：${formatDateLabel(item.latest_business_date)}`;
  }
  if (item.last_sync_date) {
    return `最近同步：${formatDateLabel(item.last_sync_date)}`;
  }
  return "—";
}

export function OpsV21SourcePage({ sourceKey, title }: { sourceKey: SourceKey; title: string }) {
  const cardQuery = useQuery({
    queryKey: ["ops", "dataset-cards", `v21-source-${sourceKey}`],
    queryFn: () => apiRequest<DatasetCardListResponse>(`/api/v1/ops/dataset-cards?source_key=${sourceKey}`),
    refetchInterval: 5000,
  });

  const isLoading = cardQuery.isLoading;
  const error = cardQuery.error;

  const cards: SourceCardItem[] = (cardQuery.data?.groups || [])
    .flatMap((group) => group.items.map((item) => ({ group, item })))
    .map(({ group, item }) => {
      const activeExecutionStatus = (item.active_execution_status || "").toLowerCase();
      const hasActiveExecution = activeExecutionStatus === "queued" || activeExecutionStatus === "running" || activeExecutionStatus === "canceling";
      const status = toCardStatus(item.status);
      const lastSyncText = hasActiveExecution
        ? (
            item.active_execution_started_at
              ? `执行中（开始于 ${formatDateTimeLabel(item.active_execution_started_at)}）`
              : "执行中"
          )
        : item.last_sync_date
          ? formatDateLabel(item.last_sync_date)
          : "—";
      return {
        datasetKey: item.card_key,
        displayName: item.display_name || "未命名数据集",
        domainKey: group.domain_key || item.domain_key || "uncategorized",
        domainDisplayName: group.domain_display_name || item.domain_display_name || "未分类",
        rawTableLabel: item.raw_table_label || "—",
        status,
        lastSyncText,
        dateRangeText: buildDateRangeText(item),
        cadenceText: item.cadence_display_name,
        primaryActionKey: item.primary_action_key || null,
        autoEnabled: item.auto_schedule_active > 0,
        autoTooltip:
          item.auto_schedule_total > 0
            ? `已配置自动任务 ${item.auto_schedule_active}/${item.auto_schedule_total} 条，下一次：${item.auto_schedule_next_run_at ? formatDateTimeLabel(item.auto_schedule_next_run_at) : "待计算"}`
            : "未配置自动任务",
        probeEnabled: item.probe_total > 0,
        probeTooltip: item.probe_total > 0
          ? `已配置自动探测规则 ${item.probe_active}/${item.probe_total} 条`
          : "未配置自动探测规则",
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
          <Alert color="error" title="读取数据源状态失败">
            {error instanceof Error ? error.message : "未知错误"}
          </Alert>
        ) : null}
      </SectionCard>

      {!isLoading && !error && cards.length === 0 ? (
        <Alert color="info" title={`暂无 ${title} 数据`}>
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
                  withBorder
                  radius="md"
                  p="md"
                  style={{
                    minHeight: 228,
                    height: "100%",
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
                        <Text size="sm">最近同步：{item.lastSyncText}</Text>
                        <StatusBadge value={item.status} label={statusLabel(item.status)} size="xs" />
                      </Group>
                      <Text size="sm">更新频率：{item.cadenceText}</Text>
                      <Text size="sm">时间范围：{item.dateRangeText}</Text>
                    </Stack>

                    <Group justify="space-between" mt="auto">
                      <Group gap={6}>
                        {item.autoEnabled ? (
                          <Tooltip label={item.autoTooltip} withArrow multiline w={280}>
                            <Badge variant="light" color="warning">
                              自动
                            </Badge>
                          </Tooltip>
                        ) : null}
                        {item.probeEnabled ? (
                          <Tooltip label={item.probeTooltip} withArrow multiline w={260}>
                            <Badge variant="light" color="info">
                              自动探测
                            </Badge>
                          </Tooltip>
                        ) : null}
                        {!item.autoEnabled && !item.probeEnabled ? (
                          <Text size="xs" c="dimmed">未配置自动更新</Text>
                        ) : null}
                      </Group>
                      {item.status !== "healthy" && item.primaryActionKey ? (
                        <Button
                          component="a"
                          href={buildManualTaskHref({ actionKey: item.primaryActionKey, actionType: "dataset_action" })}
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
