import { Alert, Badge, Button, Grid, Group, Loader, Stack, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { apiRequest } from "../shared/api/client";
import type {
  ExecutionListResponse,
  LayerSnapshotHistoryResponse,
  LayerSnapshotLatestResponse,
  OpsFreshnessResponse,
  ProbeRuleListResponse,
  ResolutionReleaseListResponse,
  StdCleansingRuleListResponse,
  StdMappingRuleListResponse,
} from "../shared/api/types";
import { formatDateLabel, formatDateTimeLabel } from "../shared/date-format";
import { formatStatusLabel } from "../shared/ops-display";
import { DataTable, type DataTableColumn } from "../shared/ui/data-table";
import { EmptyState } from "../shared/ui/empty-state";
import { MetricPanel } from "../shared/ui/metric-panel";
import { SectionCard } from "../shared/ui/section-card";
import { StatusBadge } from "../shared/ui/status-badge";
import { buildFreshnessDisplayNameMap } from "./ops-v21-shared";


type ExecutionRow = ExecutionListResponse["items"][number];

function stageTitle(stage: string) {
  if (stage === "raw") return "raw";
  if (stage === "std") return "std";
  if (stage === "resolution") return "resolution";
  if (stage === "serving") return "serving";
  if (stage === "light") return "light";
  return stage;
}

function inferSourceFromTargetTable(
  targetTable: string | null | undefined,
  datasetKey: string,
): "tushare" | "biying" {
  if (datasetKey.startsWith("biying_")) return "biying";
  const table = (targetTable || "").toLowerCase();
  if (table.startsWith("raw_biying.")) return "biying";
  return "tushare";
}

function formatLagDuration(lagSeconds: number | null | undefined): string {
  if (!lagSeconds) return "—";
  return `${Math.floor(lagSeconds / 3600)}h ${Math.floor((lagSeconds % 3600) / 60)}m`;
}

function formatDetailStatusLabel(value: string | null | undefined): string {
  const normalized = (value || "unknown").toLowerCase();
  if (normalized === "healthy") return "正常";
  return formatStatusLabel(value);
}

export function OpsV21DatasetDetailPage({ datasetKey }: { datasetKey: string }) {
  const freshnessQuery = useQuery({
    queryKey: ["ops", "freshness", "v21-dataset-detail", datasetKey],
    queryFn: () => apiRequest<OpsFreshnessResponse>("/api/v1/ops/freshness"),
  });
  const latestQuery = useQuery({
    queryKey: ["ops", "layer-snapshot", "latest", "v21-dataset-detail", datasetKey],
    queryFn: () => apiRequest<LayerSnapshotLatestResponse>(`/api/v1/ops/layer-snapshots/latest?dataset_key=${encodeURIComponent(datasetKey)}&limit=200`),
  });
  const historyQuery = useQuery({
    queryKey: ["ops", "layer-snapshot", "history", "v21-dataset-detail", datasetKey],
    queryFn: () => apiRequest<LayerSnapshotHistoryResponse>(`/api/v1/ops/layer-snapshots/history?dataset_key=${encodeURIComponent(datasetKey)}&limit=50`),
  });
  const executionQuery = useQuery({
    queryKey: ["ops", "executions", "v21-dataset-detail", datasetKey],
    queryFn: () => apiRequest<ExecutionListResponse>(`/api/v1/ops/executions?dataset_key=${encodeURIComponent(datasetKey)}&limit=20`),
  });
  const probeQuery = useQuery({
    queryKey: ["ops", "probes", "v21-dataset-detail", datasetKey],
    queryFn: () => apiRequest<ProbeRuleListResponse>(`/api/v1/ops/probes?dataset_key=${encodeURIComponent(datasetKey)}&limit=20`),
  });
  const releaseQuery = useQuery({
    queryKey: ["ops", "releases", "v21-dataset-detail", datasetKey],
    queryFn: () => apiRequest<ResolutionReleaseListResponse>(`/api/v1/ops/releases?dataset_key=${encodeURIComponent(datasetKey)}&limit=20`),
  });
  const mappingQuery = useQuery({
    queryKey: ["ops", "mapping-rules", "v21-dataset-detail", datasetKey],
    queryFn: () => apiRequest<StdMappingRuleListResponse>(`/api/v1/ops/std-rules/mapping?dataset_key=${encodeURIComponent(datasetKey)}&limit=100`),
  });
  const cleansingQuery = useQuery({
    queryKey: ["ops", "cleansing-rules", "v21-dataset-detail", datasetKey],
    queryFn: () => apiRequest<StdCleansingRuleListResponse>(`/api/v1/ops/std-rules/cleansing?dataset_key=${encodeURIComponent(datasetKey)}&limit=100`),
  });

  const isLoading = [
    freshnessQuery,
    latestQuery,
    historyQuery,
    executionQuery,
    probeQuery,
    releaseQuery,
    mappingQuery,
    cleansingQuery,
  ].some((query) => query.isLoading);
  const error = freshnessQuery.error || latestQuery.error || historyQuery.error || executionQuery.error || probeQuery.error || releaseQuery.error || mappingQuery.error || cleansingQuery.error;

  const displayNameMap = buildFreshnessDisplayNameMap(freshnessQuery.data);
  const displayName = displayNameMap[datasetKey] || datasetKey;
  const freshnessItem = (freshnessQuery.data?.groups || [])
    .flatMap((group) => group.items || [])
    .find((item) => item.dataset_key === datasetKey);
  const latestItems = (latestQuery.data?.items?.length ? latestQuery.data.items : []) as LayerSnapshotLatestResponse["items"];
  if (latestItems.length === 0 && freshnessItem) {
    const fallbackStatus =
      freshnessItem.freshness_status === "stale"
        ? "failed"
        : freshnessItem.freshness_status === "lagging"
          ? "warning"
          : freshnessItem.freshness_status === "fresh"
            ? "healthy"
            : "unknown";
    const fallbackTs = freshnessItem.last_sync_date || freshnessItem.recent_failure_at || freshnessItem.expected_business_date || "1970-01-01T00:00:00Z";
    const sourceKey = inferSourceFromTargetTable(freshnessItem.target_table, datasetKey);
    latestItems.push({
      snapshot_date: (freshnessItem.state_business_date || freshnessItem.latest_business_date || "1970-01-01").slice(0, 10),
      dataset_key: datasetKey,
      source_key: sourceKey,
      stage: "raw",
      status: fallbackStatus,
      rows_in: null,
      rows_out: null,
      error_count: freshnessItem.recent_failure_at ? 1 : 0,
      lag_seconds: freshnessItem.lag_days != null ? freshnessItem.lag_days * 86400 : null,
      message: freshnessItem.freshness_note || freshnessItem.recent_failure_summary || null,
      calculated_at: fallbackTs,
      last_success_at: freshnessItem.last_sync_date || null,
      last_failure_at: freshnessItem.recent_failure_at || null,
    });
    latestItems.push({
      snapshot_date: (freshnessItem.state_business_date || freshnessItem.latest_business_date || "1970-01-01").slice(0, 10),
      dataset_key: datasetKey,
      source_key: sourceKey,
      stage: "serving",
      status: fallbackStatus,
      rows_in: null,
      rows_out: null,
      error_count: freshnessItem.recent_failure_at ? 1 : 0,
      lag_seconds: freshnessItem.lag_days != null ? freshnessItem.lag_days * 86400 : null,
      message: freshnessItem.freshness_note || freshnessItem.recent_failure_summary || null,
      calculated_at: fallbackTs,
      last_success_at: freshnessItem.last_sync_date || null,
      last_failure_at: freshnessItem.recent_failure_at || null,
    });
  }
  const stageMap = new Map(latestItems.map((item) => [item.stage, item]));
  const stageOrder = ["raw", "std", "resolution", "serving"];
  if (datasetKey === "daily" || stageMap.has("light")) {
    stageOrder.push("light");
  }
  const executionItems = executionQuery.data?.items || [];
  const executionRows = executionItems.slice(0, 10);
  const recentExecution = executionItems[0];
  const sourceGroups = new Map<string, typeof latestItems>();
  for (const item of latestItems) {
    const key = item.source_key || "unknown";
    const arr = sourceGroups.get(key) || [];
    arr.push(item);
    sourceGroups.set(key, arr);
  }
  const releaseItems = releaseQuery.data?.items || [];
  const latestRelease = releaseItems[0];
  const executionColumns: DataTableColumn<ExecutionRow>[] = [
    {
      key: "id",
      header: "执行ID",
      align: "left",
      width: "20%",
      render: (item) => (
        <Text ff="var(--mantine-font-family-monospace)" size="sm">
          {item.id}
        </Text>
      ),
    },
    {
      key: "trigger_source",
      header: "触发方式",
      width: "12%",
      render: (item) => <Text size="sm">{item.trigger_source}</Text>,
    },
    {
      key: "status",
      header: "状态",
      width: "12%",
      render: (item) => <StatusBadge value={item.status} />,
    },
    {
      key: "rows_in",
      header: "rows_in",
      width: "12%",
      render: (item) => <Text size="sm">{item.rows_fetched}</Text>,
    },
    {
      key: "rows_out",
      header: "rows_out",
      width: "12%",
      render: (item) => <Text size="sm">{item.rows_written}</Text>,
    },
    {
      key: "requested_at",
      header: "请求时间",
      align: "left",
      width: "20%",
      render: (item) => <Text size="sm">{formatDateTimeLabel(item.requested_at)}</Text>,
    },
    {
      key: "error_code",
      header: "错误",
      align: "left",
      width: "12%",
      render: (item) => (
        <Text size="sm" c={item.error_code ? "var(--mantine-color-error-6)" : "dimmed"}>
          {item.error_code || "—"}
        </Text>
      ),
    },
  ];

  return (
    <Stack gap="lg">
      <SectionCard title={`${datasetKey} · ${displayName}`} description="数据集详情页先按 V2.1 设计骨架接入已有能力，缺失部分用待补充占位。">
        <Group justify="space-between" align="center">
          <Group gap="sm">
            <Button component={Link} to="/ops/v21/overview" variant="light" color="gray">
              返回总览
            </Button>
            <StatusBadge value={recentExecution?.status || "unknown"} />
            {latestRelease ? <Badge variant="light" color="success">策略 v{latestRelease.target_policy_version}</Badge> : null}
          </Group>
          <Group gap="sm">
            <Button component="a" href={`/app/ops/manual-sync?spec_key=${encodeURIComponent(recentExecution?.spec_key || "")}&spec_type=job`} variant="light" color="brand">
              去处理
            </Button>
            <Button component="a" href={`/app/ops/manual-sync?spec_key=${encodeURIComponent(recentExecution?.spec_key || "")}&spec_type=job`} variant="light">
              手动执行
            </Button>
            <Button variant="light" disabled>
              分层重跑
            </Button>
          </Group>
        </Group>
      </SectionCard>

      {isLoading ? <Loader size="sm" /> : null}
      {error ? (
        <Alert color="error" title="读取数据集详情失败">
          {error instanceof Error ? error.message : "未知错误"}
        </Alert>
      ) : null}
      {!isLoading && !error && latestItems.length === 0 && executionItems.length === 0 ? (
        <Alert color="info" title="该数据集暂无可展示记录">
          还没有该数据集的层级快照与执行记录。先执行一次同步任务后再查看详情。
        </Alert>
      ) : null}

      <Grid>
        <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
          <MetricPanel label="serving 版本">
            <Text ff="var(--mantine-font-family-monospace)" fw={700} size="lg">
              {stageMap.get("serving") ? formatDateTimeLabel(stageMap.get("serving")?.calculated_at) : "—"}
            </Text>
          </MetricPanel>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
          <MetricPanel label="今日写入行数">
            <Text fw={700} size="xl">{recentExecution?.rows_written ?? 0}</Text>
          </MetricPanel>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
          <MetricPanel label="serving lag">
            <Text fw={700} size="xl">
              {formatLagDuration(stageMap.get("serving")?.lag_seconds)}
            </Text>
          </MetricPanel>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
          <MetricPanel label="今日执行次数">
            <Text fw={700} size="xl">{executionItems.length}</Text>
          </MetricPanel>
        </Grid.Col>
      </Grid>

      <SectionCard title="全链路层级状态" description="raw / std / resolution / serving / light 的最新状态。">
        <Grid>
          {stageOrder.map((stage) => {
            const item = stageMap.get(stage);
            return (
              <Grid.Col key={stage} span={{ base: 12, md: 6, xl: 3 }}>
                <MetricPanel label={stageTitle(stage)} align="start" minHeight={176}>
                  <Stack gap={6} w="100%">
                    <StatusBadge value={item?.status || "unknown"} label={formatDetailStatusLabel(item?.status)} />
                    <Text size="sm">最近成功：{item?.last_success_at ? formatDateTimeLabel(item.last_success_at) : "—"}</Text>
                    <Text size="sm">最近失败：{item?.last_failure_at ? formatDateTimeLabel(item.last_failure_at) : "—"}</Text>
                    <Text size="sm">rows_in：{item?.rows_in ?? "—"}</Text>
                    <Text size="sm">rows_out：{item?.rows_out ?? "—"}</Text>
                  </Stack>
                </MetricPanel>
              </Grid.Col>
            );
          })}
        </Grid>
      </SectionCard>

      <SectionCard title="数据来源状态" description="按来源展示该数据集最新状态。">
        <Grid>
          {Array.from(sourceGroups.entries()).map(([source, items]) => {
            const failedCount = items.filter((item) => item.status === "failed").length;
            return (
              <Grid.Col key={source} span={{ base: 12, xl: 6 }}>
                <MetricPanel label={source} align="start" minHeight={220}>
                  <Stack gap="sm" w="100%">
                    <Group justify="space-between" wrap="nowrap">
                      <StatusBadge
                        value={failedCount > 0 ? "failed" : "healthy"}
                        label={failedCount > 0 ? "存在失败" : "状态正常"}
                      />
                      <Text c="dimmed" size="sm">条目数：{items.length}</Text>
                    </Group>
                    <Stack gap={6}>
                      {items.map((item) => (
                        <Group key={`${source}-${item.stage}`} justify="space-between" wrap="nowrap">
                          <Text ff="var(--mantine-font-family-monospace)" size="sm">{item.stage}</Text>
                          <Group gap={8} wrap="nowrap">
                            <StatusBadge value={item.status} label={formatDetailStatusLabel(item.status)} />
                            <Text size="sm" c="dimmed">{formatDateTimeLabel(item.calculated_at)}</Text>
                          </Group>
                        </Group>
                      ))}
                    </Stack>
                  </Stack>
                </MetricPanel>
              </Grid.Col>
            );
          })}
        </Grid>
      </SectionCard>

      <SectionCard title="调度覆盖" description="先接入已存在的自动任务与探测规则。">
        <Stack gap="xs">
          {probeQuery.data?.items?.map((item) => (
            <Group key={item.id} justify="space-between">
              <Group gap={8}>
                <Badge variant="light" color="info">probe</Badge>
                <Text>{item.name}</Text>
              </Group>
              <Group gap={8}>
                <Text c="dimmed" size="sm">{item.window_start || "—"}~{item.window_end || "—"} / {item.probe_interval_seconds}s</Text>
                <StatusBadge value={item.status} />
              </Group>
            </Group>
          ))}
          {probeQuery.data?.items?.length === 0 ? <Text c="dimmed">暂无探测规则</Text> : null}
        </Stack>
      </SectionCard>

      <SectionCard title="近期执行记录" description="按 dataset_key 过滤出的最近执行。">
        <DataTable
          columns={executionColumns}
          rows={executionRows}
          getRowKey={(item) => item.id}
          emptyState={<EmptyState title="暂无执行记录" description="当前数据集还没有可展示的执行结果。" />}
          minWidth={920}
        />
      </SectionCard>

      <SectionCard title="当前生效融合策略" description="先展示发布版本与规则规模，策略细节后续补充独立页面。">
        <Grid>
          <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
            <MetricPanel label="生效版本" align="start">
              <Stack gap={2}>
                <Text fw={700} size="xl">{latestRelease ? `v${latestRelease.target_policy_version}` : "待补充"}</Text>
                <Text size="sm" c="dimmed">{latestRelease?.triggered_at ? formatDateLabel(latestRelease.triggered_at) : "—"}</Text>
              </Stack>
            </MetricPanel>
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
            <MetricPanel label="映射规则">
              <Text fw={700} size="xl">{mappingQuery.data?.total ?? 0}</Text>
            </MetricPanel>
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
            <MetricPanel label="清洗规则">
              <Text fw={700} size="xl">{cleansingQuery.data?.total ?? 0}</Text>
            </MetricPanel>
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
            <MetricPanel label="快照样本">
              <Text fw={700} size="xl">{historyQuery.data?.total ?? 0}</Text>
            </MetricPanel>
          </Grid.Col>
        </Grid>
      </SectionCard>
    </Stack>
  );
}
