import { Alert, Badge, Button, Group, Loader, Paper, SimpleGrid, Stack, Switch, Text } from "@mantine/core";
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
  primaryExecutionSpecKey: string | null;
  autoEnabled: boolean;
}

function inferSource(datasetKey: string, targetTable: string): SourceKey {
  if (datasetKey.startsWith("biying_")) return "biying";
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

function cardTone(status: CardStatus) {
  if (status === "healthy") {
    return {
      border: "1px solid rgba(16,185,129,0.42)",
      background: "linear-gradient(180deg, rgba(34,197,94,0.35) 0%, rgba(16,185,129,0.16) 70%, rgba(16,185,129,0.08) 100%)",
    };
  }
  if (status === "failed") {
    return {
      border: "1px solid rgba(244,63,94,0.42)",
      background: "linear-gradient(180deg, rgba(244,63,94,0.30) 0%, rgba(244,63,94,0.15) 70%, rgba(244,63,94,0.08) 100%)",
    };
  }
  if (status === "warning") {
    return {
      border: "1px solid rgba(245,158,11,0.42)",
      background: "linear-gradient(180deg, rgba(245,158,11,0.30) 0%, rgba(245,158,11,0.15) 70%, rgba(245,158,11,0.08) 100%)",
    };
  }
  return {
    border: "1px solid rgba(148,163,184,0.35)",
    background: "linear-gradient(180deg, rgba(148,163,184,0.22) 0%, rgba(148,163,184,0.12) 70%, rgba(148,163,184,0.07) 100%)",
  };
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

  const cards: SourceCardItem[] = (freshnessQuery.data?.groups || [])
    .flatMap((group) =>
      group.items
        .filter((item) => inferSource(item.dataset_key, item.target_table) === sourceKey)
        .map((item) => {
          const rawLatest = rawLatestByDataset.get(item.dataset_key);
          const status = toCardStatus(rawLatest?.status || item.freshness_status);
          return {
            datasetKey: item.dataset_key,
            displayName: formatResourceLabel(item.dataset_key),
            domainKey: group.domain_key,
            domainDisplayName: group.domain_display_name,
            rawTableLabel:
              sourceKey === "tushare"
                ? `raw_tushare.${item.dataset_key}`
                : `raw_biying.${item.dataset_key.replace(/^biying_/, "")}`,
            status,
            recentSyncAt: rawLatest?.calculated_at || (item.latest_success_at ? item.latest_success_at : null),
            recentSyncResult: status === "failed" ? "失败" : status === "warning" ? "告警" : status === "healthy" ? "成功" : "未知",
            dateRangeText: buildDateRangeText(item),
            primaryExecutionSpecKey: item.primary_execution_spec_key,
            autoEnabled: item.auto_schedule_active > 0,
          };
        }),
    )
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
            <SimpleGrid cols={{ base: 1, md: 2, lg: 3, xl: 5 }} spacing="md" verticalSpacing="md">
              {items.map((item) => (
                <Paper key={item.datasetKey} radius="md" p="md" style={{ ...cardTone(item.status), height: 260, minHeight: 260 }}>
                  <Stack gap={8} h="100%">
                    <Group justify="space-between" align="flex-start">
                      <Text fw={800} size="lg" lineClamp={1}>{item.displayName}</Text>
                      <Switch checked={item.autoEnabled} onChange={() => undefined} size="md" />
                    </Group>
                    <Text size="xs" c="dimmed">{item.datasetKey}</Text>

                    <Stack gap={2}>
                      <Text size="sm">数据表：{item.rawTableLabel}</Text>
                      <Text size="sm">最近同步时间：{item.recentSyncAt ? formatDateTimeLabel(item.recentSyncAt) : "—"}</Text>
                      <Text size="sm">最近同步状态：{item.recentSyncResult}</Text>
                      <Text size="sm">时间范围：{item.dateRangeText}</Text>
                    </Stack>

                    <Group justify="space-between" mt="auto">
                      <Badge variant="light" color="orange">自动</Badge>
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
