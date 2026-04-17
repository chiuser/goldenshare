import { Alert, Badge, Box, Button, Grid, Group, Loader, Paper, SimpleGrid, Stack, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "../shared/api/client";
import type {
  DatasetPipelineModeListResponse,
  LayerSnapshotLatestResponse,
  OpsOverviewResponse,
} from "../shared/api/types";
import { formatDateLabel, formatDateTimeLabel } from "../shared/date-format";
import { SectionCard } from "../shared/ui/section-card";
import { StatCard } from "../shared/ui/stat-card";
import { StatusBadge } from "../shared/ui/status-badge";

type CardStatus = "healthy" | "warning" | "failed" | "unknown";
type StageKey = "raw" | "std" | "resolution" | "serving" | "light";

interface MergedCardItem {
  cardKey: string;
  canonicalDatasetKey: string;
  detailDatasetKey: string;
  displayName: string;
  domainKey: string;
  domainDisplayName: string;
  mode: string;
  freshnessStatus: string;
  latestBusinessDate: string | null;
  stdTableHint: string | null;
  servingTable: string | null;
  stdMappingConfigured: boolean;
  stdCleansingConfigured: boolean;
  resolutionPolicyConfigured: boolean;
  stageMap: Partial<Record<StageKey, LayerSnapshotLatestResponse["items"][number]>>;
  rawSources: Array<{
    sourceKey: string;
    tableName: string | null;
    status: string | null;
    snapshot: LayerSnapshotLatestResponse["items"][number] | null;
  }>;
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

function canonicalDatasetKey(rawKey: string): string {
  const lower = rawKey.toLowerCase();
  if (lower.startsWith("biying_")) return rawKey.slice("biying_".length);
  if (lower.startsWith("tushare_")) return rawKey.slice("tushare_".length);
  return rawKey;
}

function inferSourceKey(item: { dataset_key: string; raw_table: string | null; source_scope?: string | null }): string {
  const datasetKey = item.dataset_key.toLowerCase();
  if (datasetKey.startsWith("biying_")) return "biying";
  if (datasetKey.startsWith("tushare_")) return "tushare";
  const rawTable = (item.raw_table || "").toLowerCase();
  if (rawTable.startsWith("raw_biying.")) return "biying";
  if (rawTable.startsWith("raw_tushare.")) return "tushare";
  const scope = (item.source_scope || "").toLowerCase();
  if (scope === "biying") return "biying";
  if (scope === "tushare") return "tushare";
  return "tushare";
}

function pickWorseStatus(current: string | null, next: string | null): string | null {
  const rank: Record<string, number> = {
    failed: 4,
    stale: 3,
    lagging: 2,
    warning: 2,
    healthy: 1,
    fresh: 1,
    success: 1,
    unknown: 0,
  };
  const currentKey = (current || "unknown").toLowerCase();
  const nextKey = (next || "unknown").toLowerCase();
  return (rank[nextKey] || 0) > (rank[currentKey] || 0) ? next : current;
}

function expectedStages(
  mode: string,
  datasetKey: string,
  stageMap: Partial<Record<StageKey, LayerSnapshotLatestResponse["items"][number]>>,
): StageKey[] {
  let base: StageKey[];
  if (mode === "single_source_direct") base = ["raw", "serving"];
  else if (mode === "multi_source_pipeline") base = ["raw", "std", "resolution", "serving"];
  else if (mode === "raw_only") base = ["raw"];
  else if (mode === "legacy_core_direct") base = ["raw"];
  else base = ["raw", "serving"];
  if (datasetKey === "daily" || stageMap.light) {
    return [...base, "light"];
  }
  return base;
}

function stageLabel(stage: StageKey): string {
  if (stage === "raw") return "原始层";
  if (stage === "std") return "标准层";
  if (stage === "resolution") return "融合层";
  if (stage === "light") return "轻量层";
  return "服务层";
}

function stageTableName(stage: StageKey, item: MergedCardItem): string | null {
  if (stage === "raw") return item.rawSources[0]?.tableName || null;
  if (stage === "std") return item.stdTableHint;
  if (stage === "light") return item.canonicalDatasetKey === "daily" ? "core_serving_light.equity_daily_bar_light" : null;
  if (stage === "serving") return item.servingTable;
  return null;
}

export function OpsV21OverviewPage() {
  const summaryQuery = useQuery({
    queryKey: ["ops", "overview", "v21-overview-summary"],
    queryFn: () => apiRequest<OpsOverviewResponse>("/api/v1/ops/overview"),
  });
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
  const stageLatestByCanonical = new Map<string, Partial<Record<StageKey, LayerSnapshotLatestResponse["items"][number]>>>();
  const rawLatestByCanonicalAndSource = new Map<string, Map<string, LayerSnapshotLatestResponse["items"][number]>>();
  for (const item of latestItems) {
    const stage = item.stage as StageKey;
    if (!["raw", "std", "resolution", "serving", "light"].includes(stage)) continue;
    const canonicalKey = canonicalDatasetKey(item.dataset_key);
    const existing = stageLatestByCanonical.get(canonicalKey) || {};
    const previous = existing[stage];
    if (!previous || new Date(item.calculated_at).getTime() > new Date(previous.calculated_at).getTime()) {
      existing[stage] = item;
      stageLatestByCanonical.set(canonicalKey, existing);
    }
    if (stage === "raw") {
      const source = (item.source_key || inferSourceKey({ dataset_key: item.dataset_key, raw_table: null })).toLowerCase();
      const sourceMap = rawLatestByCanonicalAndSource.get(canonicalKey) || new Map<string, LayerSnapshotLatestResponse["items"][number]>();
      const prev = sourceMap.get(source);
      if (!prev || new Date(item.calculated_at).getTime() > new Date(prev.calculated_at).getTime()) {
        sourceMap.set(source, item);
      }
      rawLatestByCanonicalAndSource.set(canonicalKey, sourceMap);
    }
  }

  const rawCards = modeQuery.data?.items || [];
  const mergedCardsMap = new Map<string, MergedCardItem>();
  for (const item of rawCards) {
    const canonicalKey = canonicalDatasetKey(item.dataset_key);
    const sourceKey = inferSourceKey(item);
    const existing = mergedCardsMap.get(canonicalKey);
    if (!existing) {
      const rawSourceSnapshot = rawLatestByCanonicalAndSource.get(canonicalKey)?.get(sourceKey) || null;
      mergedCardsMap.set(canonicalKey, {
        cardKey: canonicalKey,
        canonicalDatasetKey: canonicalKey,
        detailDatasetKey: item.dataset_key,
        displayName: item.display_name,
        domainKey: item.domain_key,
        domainDisplayName: item.domain_display_name,
        mode: item.mode,
        freshnessStatus: item.freshness_status,
        latestBusinessDate: item.latest_business_date,
        stdTableHint: item.std_table_hint,
        servingTable: item.serving_table,
        stdMappingConfigured: item.std_mapping_configured,
        stdCleansingConfigured: item.std_cleansing_configured,
        resolutionPolicyConfigured: item.resolution_policy_configured,
        stageMap: stageLatestByCanonical.get(canonicalKey) || {},
        rawSources: [
          {
            sourceKey,
            tableName: item.raw_table,
            status: rawSourceSnapshot?.status || item.freshness_status,
            snapshot: rawSourceSnapshot,
          },
        ],
      });
      continue;
    }

    const preferAsPrimary = !item.dataset_key.toLowerCase().startsWith("biying_")
      && !item.dataset_key.toLowerCase().startsWith("tushare_");
    if (preferAsPrimary) {
      existing.detailDatasetKey = item.dataset_key;
      existing.displayName = item.display_name;
      existing.domainKey = item.domain_key;
      existing.domainDisplayName = item.domain_display_name;
      existing.mode = item.mode;
      existing.latestBusinessDate = item.latest_business_date;
      existing.stdTableHint = item.std_table_hint;
      existing.servingTable = item.serving_table;
    }
    if (item.mode === "multi_source_pipeline") {
      existing.mode = item.mode;
    }
    existing.freshnessStatus = (pickWorseStatus(existing.freshnessStatus, item.freshness_status) || existing.freshnessStatus);
    if (!existing.latestBusinessDate || (item.latest_business_date && item.latest_business_date > existing.latestBusinessDate)) {
      existing.latestBusinessDate = item.latest_business_date;
    }
    existing.stdMappingConfigured = existing.stdMappingConfigured || item.std_mapping_configured;
    existing.stdCleansingConfigured = existing.stdCleansingConfigured || item.std_cleansing_configured;
    existing.resolutionPolicyConfigured = existing.resolutionPolicyConfigured || item.resolution_policy_configured;
    existing.stageMap = stageLatestByCanonical.get(canonicalKey) || existing.stageMap;

    if (!existing.rawSources.some((row) => row.sourceKey === sourceKey)) {
      const rawSourceSnapshot = rawLatestByCanonicalAndSource.get(canonicalKey)?.get(sourceKey) || null;
      existing.rawSources.push({
        sourceKey,
        tableName: item.raw_table,
        status: rawSourceSnapshot?.status || item.freshness_status,
        snapshot: rawSourceSnapshot,
      });
    }
  }

  const cards = Array.from(mergedCardsMap.values()).sort((a, b) => {
    const d = a.domainDisplayName.localeCompare(b.domainDisplayName, "zh-CN");
    if (d !== 0) return d;
    return a.displayName.localeCompare(b.displayName, "zh-CN");
  });
  const groupedCards = new Map<string, MergedCardItem[]>();
  for (const item of cards) {
    const key = `${item.domainKey}::${item.domainDisplayName}`;
    const list = groupedCards.get(key) || [];
    list.push(item);
    groupedCards.set(key, list);
  }

  return (
    <Stack gap="lg">
      <SectionCard
        title="状态概览"
        description="先看整体分布，再往下看各数据集当前链路状态。"
      >
        {summaryQuery.isLoading ? <Loader size="sm" /> : null}
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
      </SectionCard>

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
          const status = toCardStatus(item.freshnessStatus);
          const stages = expectedStages(item.mode, item.canonicalDatasetKey, item.stageMap);
          const stageMap = item.stageMap;
          const statusUpdatedAt = stages
            .map((stage) => {
              if (stage === "raw" && item.rawSources.length > 0) {
                const timestamps = item.rawSources
                  .map((entry) => entry.snapshot?.calculated_at || null)
                  .filter((value): value is string => Boolean(value));
                return timestamps.sort().at(-1) || null;
              }
              return stageMap[stage]?.calculated_at || null;
            })
            .filter((value): value is string => Boolean(value))
            .sort()
            .at(-1);
          const flags: Array<{ label: string; on: boolean }> = [
            { label: "映射规则", on: item.stdMappingConfigured },
            { label: "清洗规则", on: item.stdCleansingConfigured },
            { label: "融合策略", on: item.resolutionPolicyConfigured },
          ];

                return (
                  <Paper
                    key={item.cardKey}
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
                              {item.displayName}
                            </Text>
                          </Group>
                          <Text size="xs" c="dimmed" ml={17} lineClamp={1}>
                            {item.canonicalDatasetKey}
                          </Text>
                        </Stack>
                        <Stack gap={4} align="flex-start" justify="center" style={{ flex: "0 0 auto", minWidth: 0 }}>
                          <Badge variant="light" color="blue" size="sm" styles={{ root: { background: "rgba(59, 130, 246, 0.12)", border: "1px solid rgba(59,130,246,0.25)" } }}>
                            最新业务日期：{item.latestBusinessDate ? formatDateLabel(item.latestBusinessDate) : "—"}
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
                        {stages.map((stage) => {
                          if (stage === "raw" && item.rawSources.length > 1) {
                            return (
                              <Stack key={stage} gap={4}>
                                <Text size="sm" c="dimmed">
                                  {stageLabel(stage)}
                                </Text>
                                {item.rawSources
                                  .slice()
                                  .sort((a, b) => a.sourceKey.localeCompare(b.sourceKey))
                                  .map((entry) => (
                                    <Group key={`${item.cardKey}-${entry.sourceKey}`} justify="space-between" align="center">
                                      <Text size="sm" c="dimmed">
                                        {entry.sourceKey}
                                        {entry.tableName ? `（${entry.tableName}）` : ""}
                                      </Text>
                                      <StatusBadge value={entry.snapshot?.status || entry.status || "unknown"} />
                                    </Group>
                                  ))}
                              </Stack>
                            );
                          }
                          return (
                            <Group key={stage} justify="space-between" align="center">
                              <Text size="sm" c="dimmed">
                                {stageLabel(stage)}
                                {stageTableName(stage, item)
                                  ? `（${stageTableName(stage, item)}）`
                                  : ""}
                              </Text>
                              <StatusBadge value={stageMap[stage]?.status || "unknown"} />
                            </Group>
                          );
                        })}
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
                          href={`/app/ops/v21/datasets/detail/${encodeURIComponent(item.detailDatasetKey)}`}
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
