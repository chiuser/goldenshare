import { Alert, Badge, Box, Button, Group, Loader, Paper, SimpleGrid, Stack, Text, Tooltip } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "../shared/api/client";
import type { DatasetCardListResponse } from "../shared/api/types";
import { formatDateLabel, formatDateTimeLabel } from "../shared/date-format";
import { buildManualTaskHref } from "../shared/ops-links";
import { SectionCard } from "../shared/ui/section-card";
import { StatusBadge } from "../shared/ui/status-badge";

type CardStatus = "running" | "healthy" | "warning" | "stale" | "failed" | "unconfirmed" | "unknown";
type SourceKey = "tushare" | "biying" | "biz_tableset";
type DatasetCard = DatasetCardListResponse["groups"][number]["items"][number];

const RAW_SOURCE_DESCRIPTION = "展示数据集当前健康度、最近同步和业务日期范围；健康度统一来自服务端 freshness 口径。";

interface SourceCardItem {
  datasetKey: string;
  displayName: string;
  tableLabel: string;
  status: CardStatus;
  lastSyncLabel: string;
  lastSyncText: string;
  observedText: string;
  primaryActionType: "dataset_action" | "maintenance_action" | null;
  primaryActionKey: string | null;
  autoEnabled: boolean;
  autoScheduleStatus: string;
  autoTooltip: string;
  autoTooltipText: string;
  probeEnabled: boolean;
  probeTooltip: string;
}

function toCardStatus(rawStatus: string | null | undefined, freshnessStatus?: string | null): CardStatus {
  const freshnessKey = (freshnessStatus || "").toLowerCase();
  if (freshnessKey === "unconfirmed") return "unconfirmed";
  const key = (rawStatus || "").toLowerCase();
  if (key === "running" || key === "queued" || key === "canceling") return "running";
  if (key === "failed") return "failed";
  if (key === "stale") return "stale";
  if (key === "unconfirmed") return "unconfirmed";
  if (key === "warning" || key === "lagging") return "warning";
  if (key === "healthy" || key === "fresh" || key === "success") return "healthy";
  return "unknown";
}

function statusDotColor(status: CardStatus) {
  if (status === "running") return "var(--mantine-color-info-5)";
  if (status === "healthy") return "var(--mantine-color-success-5)";
  if (status === "stale") return "var(--mantine-color-error-5)";
  if (status === "failed") return "var(--mantine-color-error-5)";
  if (status === "warning" || status === "unconfirmed") return "var(--mantine-color-warning-5)";
  return "var(--mantine-color-neutral-5)";
}

function statusLabel(status: CardStatus): string {
  if (status === "running") return "执行中";
  if (status === "healthy") return "正常";
  if (status === "stale") return "严重滞后";
  if (status === "failed") return "失败";
  if (status === "unconfirmed") return "未确认";
  if (status === "warning") return "滞后";
  return "未知";
}

function formatApiObservedValue(value: string): string {
  return value.includes("T") ? formatDateTimeLabel(value) : formatDateLabel(value);
}

function buildObservedText(item: DatasetCard): string {
  if (item.latest_observed_date_label && item.latest_observed_date) {
    return `${item.latest_observed_date_label}：${formatApiObservedValue(item.latest_observed_date)}`;
  }
  if (item.latest_observed_at) {
    if (item.earliest_observed_at && item.earliest_observed_at !== item.latest_observed_at) {
      return `观测范围：${formatDateTimeLabel(item.earliest_observed_at)} ~ ${formatDateTimeLabel(item.latest_observed_at)}`;
    }
    return `最新观测时间：${formatDateTimeLabel(item.latest_observed_at)}`;
  }
  if (item.latest_business_date) {
    if (item.earliest_business_date && item.earliest_business_date !== item.latest_business_date) {
      return `观测范围：${formatDateLabel(item.earliest_business_date)} ~ ${formatDateLabel(item.latest_business_date)}`;
    }
    return `最新观测日期：${formatDateLabel(item.latest_business_date)}`;
  }
  if (item.last_sync_date) {
    return `最近同步日期：${formatDateLabel(item.last_sync_date)}`;
  }
  return "—";
}

function isBizTableCard(item: DatasetCard): boolean {
  return item.delivery_mode === "biz_table_snapshot";
}

function resolveTableLabel(item: DatasetCard, isBizTable: boolean): string {
  if (isBizTable) {
    return item.target_table || "—";
  }
  if (item.raw_table_label) {
    return item.raw_table_label;
  }
  return item.target_table ? `服务表：${item.target_table}` : "—";
}

function buildLastSyncText(item: DatasetCard, hasActiveTaskRun: boolean): string {
  if (hasActiveTaskRun) {
    return item.active_task_run_started_at
      ? `执行中（开始于 ${formatDateTimeLabel(item.active_task_run_started_at)}）`
      : "执行中";
  }
  if (item.latest_success_at) {
    return formatDateTimeLabel(item.latest_success_at);
  }
  return "—";
}

export function OpsV21SourcePage({
  sourceKey,
  title,
  description,
}: {
  sourceKey: SourceKey;
  title: string;
  description?: string;
}) {
  const cardQuery = useQuery({
    queryKey: ["ops", "dataset-cards", `v21-source-${sourceKey}`],
    queryFn: () => apiRequest<DatasetCardListResponse>(`/api/v1/ops/dataset-cards?source_key=${sourceKey}`),
    refetchInterval: 5000,
  });

  const isLoading = cardQuery.isLoading;
  const error = cardQuery.error;

  const groupedCards = (cardQuery.data?.groups || []).map((group) => ({
    groupKey: group.group_key,
    groupLabel: group.group_label,
    items: group.items.map((item): SourceCardItem => {
      const activeTaskRunStatus = (item.active_task_run_status || "").toLowerCase();
      const hasActiveTaskRun = activeTaskRunStatus === "queued" || activeTaskRunStatus === "running" || activeTaskRunStatus === "canceling";
      const status = toCardStatus(item.status, item.freshness_status);
      const isBizTable = isBizTableCard(item);
      return {
        datasetKey: item.card_key,
        displayName: item.display_name,
        tableLabel: resolveTableLabel(item, isBizTable),
        status,
        lastSyncLabel: item.last_success_label || (isBizTable ? "最近构建成功时间" : "最近维护成功时间"),
        lastSyncText: buildLastSyncText(item, hasActiveTaskRun),
        observedText: buildObservedText(item),
        primaryActionType: item.primary_action_type || null,
        primaryActionKey: item.primary_action_key || null,
        autoEnabled: item.auto_schedule_active > 0,
        autoScheduleStatus: item.auto_schedule_status,
        autoTooltip:
          item.auto_schedule_total > 0
            ? `已配置自动任务 ${item.auto_schedule_active}/${item.auto_schedule_total} 条，下一次：${item.auto_schedule_next_run_at ? formatDateTimeLabel(item.auto_schedule_next_run_at) : "待计算"}`
            : "未配置自动任务",
        probeEnabled: item.probe_total > 0,
        probeTooltip: item.probe_total > 0
          ? `已配置自动探测规则 ${item.probe_active}/${item.probe_total} 条`
          : "未配置自动探测规则",
        autoTooltipText: isBizTable ? "只读展示" : "未配置自动更新",
      };
    }),
  })).filter((group) => group.items.length > 0);
  const cards = groupedCards.flatMap((group) => group.items);

  return (
    <Stack gap="lg">
      <SectionCard
        title={title}
        description={description || RAW_SOURCE_DESCRIPTION}
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
          {sourceKey === "biz_tableset" ? "当前没有可展示的 Biz 表状态。" : "当前没有可展示的数据集状态。"}
        </Alert>
      ) : null}

      {groupedCards.map((group) => {
        const { groupKey, groupLabel, items } = group;
        return (
          <SectionCard key={groupKey} title={groupLabel} description={`共 ${items.length} 个数据集`}>
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
                    <Group justify="space-between" align="center" wrap="nowrap" w="100%">
                      <Stack gap={2} style={{ minWidth: 0, flex: 1 }}>
                        <Group gap={8} align="center" wrap="nowrap">
                          <Box
                            w={9}
                            h={9}
                            style={{ borderRadius: "50%", background: statusDotColor(item.status), flex: "0 0 auto" }}
                          />
                          <Text fw={700} size="sm" lineClamp={1} style={{ minWidth: 0 }}>
                            {item.displayName}
                          </Text>
                        </Group>
                        <Text
                          c="dimmed"
                          ml={17}
                          title={item.tableLabel}
                          style={{
                            minWidth: 0,
                            fontSize: 11,
                            lineHeight: 1.15,
                            display: "-webkit-box",
                            WebkitBoxOrient: "vertical",
                            WebkitLineClamp: 3,
                            overflow: "hidden",
                            overflowWrap: "anywhere",
                          }}
                        >
                          {item.tableLabel}
                        </Text>
                      </Stack>
                    </Group>

                    <Stack gap={6}>
                      <Group gap={6} wrap="wrap">
                        <Text size="sm">{item.lastSyncLabel}：{item.lastSyncText}</Text>
                        <StatusBadge value={item.status} label={statusLabel(item.status)} size="xs" />
                      </Group>
                      <Text size="sm">{item.observedText}</Text>
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
                        {!item.autoEnabled && item.autoScheduleStatus === "paused" ? (
                          <Tooltip label={item.autoTooltip} withArrow multiline w={280}>
                            <Text size="xs" c="dimmed">自动已暂停</Text>
                          </Tooltip>
                        ) : null}
                        {item.probeEnabled ? (
                          <Tooltip label={item.probeTooltip} withArrow multiline w={260}>
                            <Badge variant="light" color="info">
                              自动探测
                            </Badge>
                          </Tooltip>
                        ) : null}
                        {!item.autoEnabled && item.autoScheduleStatus !== "paused" && !item.probeEnabled ? (
                          <Text size="xs" c="dimmed">
                            {sourceKey === "biz_tableset" && item.primaryActionKey
                              ? "未配置自动更新"
                              : item.autoTooltipText}
                          </Text>
                        ) : null}
                      </Group>
                      {item.primaryActionType && item.primaryActionKey && (sourceKey === "biz_tableset" || item.status !== "healthy") ? (
                        <Button
                          component="a"
                          href={buildManualTaskHref({
                            actionKey: item.primaryActionKey,
                            actionType: item.primaryActionType,
                          })}
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
