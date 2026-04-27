import { Alert, Badge, Button, Grid, Group, Loader, Stack, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { apiRequest } from "../shared/api/client";
import type {
  DatasetCardListResponse,
  LayerSnapshotHistoryResponse,
  LayerSnapshotLatestResponse,
  ProbeRuleListResponse,
  ResolutionReleaseListResponse,
  StdCleansingRuleListResponse,
  StdMappingRuleListResponse,
  TaskRunListResponse,
} from "../shared/api/types";
import { formatDateLabel, formatDateTimeLabel } from "../shared/date-format";
import { buildManualTaskHref } from "../shared/ops-links";
import { formatStatusLabel } from "../shared/ops-display";
import { DataTable, type DataTableColumn } from "../shared/ui/data-table";
import { EmptyState } from "../shared/ui/empty-state";
import { MetricPanel } from "../shared/ui/metric-panel";
import { SectionCard } from "../shared/ui/section-card";
import { StatusBadge } from "../shared/ui/status-badge";


type TaskRunRow = TaskRunListResponse["items"][number];
type DatasetCard = DatasetCardListResponse["groups"][number]["items"][number];
type DatasetCardStage = DatasetCard["stage_statuses"][number];
type LayerLatestItem = LayerSnapshotLatestResponse["items"][number];
type StageCard = {
  stage: string;
  stageLabel: string;
  status: string;
  rowsIn: number | null;
  rowsOut: number | null;
  lagSeconds: number | null;
  calculatedAt: string | null;
  lastSuccessAt: string | null;
  lastFailureAt: string | null;
};

function formatLagDuration(lagSeconds: number | null | undefined): string {
  if (!lagSeconds) return "—";
  return `${Math.floor(lagSeconds / 3600)}h ${Math.floor((lagSeconds % 3600) / 60)}m`;
}

function formatDetailStatusLabel(value: string | null | undefined): string {
  const normalized = (value || "unknown").toLowerCase();
  if (normalized === "healthy") return "正常";
  return formatStatusLabel(value);
}

function stageCardFromDatasetCard(item: DatasetCardStage): StageCard {
  return {
    stage: item.stage,
    stageLabel: item.stage_label,
    status: item.status,
    rowsIn: item.rows_in,
    rowsOut: item.rows_out,
    lagSeconds: item.lag_seconds,
    calculatedAt: item.calculated_at,
    lastSuccessAt: item.last_success_at,
    lastFailureAt: item.last_failure_at,
  };
}

function stageCardFromLatestItem(item: LayerLatestItem): StageCard {
  return {
    stage: item.stage,
    stageLabel: item.stage_display_name,
    status: item.status,
    rowsIn: item.rows_in,
    rowsOut: item.rows_out,
    lagSeconds: item.lag_seconds,
    calculatedAt: item.calculated_at,
    lastSuccessAt: item.last_success_at,
    lastFailureAt: item.last_failure_at,
  };
}

export function OpsV21DatasetDetailPage({ datasetKey }: { datasetKey: string }) {
  const cardQuery = useQuery({
    queryKey: ["ops", "dataset-cards", "v21-dataset-detail", datasetKey],
    queryFn: () => apiRequest<DatasetCardListResponse>("/api/v1/ops/dataset-cards?limit=2000"),
  });
  const latestQuery = useQuery({
    queryKey: ["ops", "layer-snapshot", "latest", "v21-dataset-detail", datasetKey],
    queryFn: () => apiRequest<LayerSnapshotLatestResponse>(`/api/v1/ops/layer-snapshots/latest?dataset_key=${encodeURIComponent(datasetKey)}&limit=200`),
  });
  const historyQuery = useQuery({
    queryKey: ["ops", "layer-snapshot", "history", "v21-dataset-detail", datasetKey],
    queryFn: () => apiRequest<LayerSnapshotHistoryResponse>(`/api/v1/ops/layer-snapshots/history?dataset_key=${encodeURIComponent(datasetKey)}&limit=50`),
  });
  const taskRunQuery = useQuery({
    queryKey: ["ops", "task-runs", "v21-dataset-detail", datasetKey],
    queryFn: () => apiRequest<TaskRunListResponse>(`/api/v1/ops/task-runs?resource_key=${encodeURIComponent(datasetKey)}&limit=20`),
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
    cardQuery,
    latestQuery,
    historyQuery,
    taskRunQuery,
    probeQuery,
    releaseQuery,
    mappingQuery,
    cleansingQuery,
  ].some((query) => query.isLoading);
  const error = cardQuery.error || latestQuery.error || historyQuery.error || taskRunQuery.error || probeQuery.error || releaseQuery.error || mappingQuery.error || cleansingQuery.error;

  const datasetCard = (cardQuery.data?.groups || [])
    .flatMap((group) => group.items || [])
    .find((item) => item.detail_dataset_key === datasetKey || item.dataset_key === datasetKey);
  const displayName = datasetCard?.display_name || "数据集未找到";
  const latestItems = (latestQuery.data?.items?.length ? latestQuery.data.items : []) as LayerSnapshotLatestResponse["items"];
  const stageMap = new Map(latestItems.map((item) => [item.stage, item]));
  const stageCards: StageCard[] = datasetCard?.stage_statuses?.length
    ? datasetCard.stage_statuses.map(stageCardFromDatasetCard)
    : latestItems.map(stageCardFromLatestItem);
  const taskRunItems = taskRunQuery.data?.items || [];
  const taskRunRows = taskRunItems.slice(0, 10);
  const recentTaskRun = taskRunItems[0];
  const manualActionKey = datasetCard?.primary_action_key || null;
  const sourceGroups = new Map<string, { label: string; items: typeof latestItems }>();
  for (const item of latestItems) {
    const key = item.source_key || "unknown";
    const group = sourceGroups.get(key) || { label: item.source_display_name, items: [] };
    group.items.push(item);
    sourceGroups.set(key, group);
  }
  const releaseItems = releaseQuery.data?.items || [];
  const latestRelease = releaseItems[0];
  const taskRunColumns: DataTableColumn<TaskRunRow>[] = [
    {
      key: "id",
      header: "任务ID",
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
      render: (item) => <Text size="sm">{item.rows_saved}</Text>,
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
        <Text size="sm" c={item.primary_issue_title ? "var(--mantine-color-error-6)" : "dimmed"}>
          {item.primary_issue_title || "—"}
        </Text>
      ),
    },
  ];

  return (
    <Stack gap="lg">
      <SectionCard title={displayName} description="数据集详情页先按 V2.1 设计骨架接入已有能力，缺失部分用待补充占位。">
        <Group justify="space-between" align="center">
          <Group gap="sm">
            <Button component={Link} to="/ops/v21/overview" variant="light" color="gray">
              返回总览
            </Button>
            <StatusBadge value={recentTaskRun?.status || "unknown"} />
            {latestRelease ? <Badge variant="light" color="success">策略 v{latestRelease.target_policy_version}</Badge> : null}
          </Group>
          <Group gap="sm">
            <Button component="a" href={buildManualTaskHref({ actionKey: manualActionKey, actionType: "dataset_action" })} variant="light" color="brand">
              去处理
            </Button>
            <Button component="a" href={buildManualTaskHref({ actionKey: manualActionKey, actionType: "dataset_action" })} variant="light">
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
      {!isLoading && !error && latestItems.length === 0 && taskRunItems.length === 0 ? (
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
            <Text fw={700} size="xl">{recentTaskRun?.rows_saved ?? 0}</Text>
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
            <Text fw={700} size="xl">{taskRunItems.length}</Text>
          </MetricPanel>
        </Grid.Col>
      </Grid>

      <SectionCard title="全链路层级状态" description="按服务端返回的层级计划展示最新状态。">
        <Grid>
          {stageCards.map((item) => {
            return (
              <Grid.Col key={item.stage} span={{ base: 12, md: 6, xl: 3 }}>
                <MetricPanel label={item.stageLabel} align="start" minHeight={176}>
                  <Stack gap={6} w="100%">
                    <StatusBadge value={item.status || "unknown"} label={formatDetailStatusLabel(item.status)} />
                    <Text size="sm">最近成功：{item.lastSuccessAt ? formatDateTimeLabel(item.lastSuccessAt) : "—"}</Text>
                    <Text size="sm">最近失败：{item.lastFailureAt ? formatDateTimeLabel(item.lastFailureAt) : "—"}</Text>
                    <Text size="sm">rows_in：{item.rowsIn ?? "—"}</Text>
                    <Text size="sm">rows_out：{item.rowsOut ?? "—"}</Text>
                  </Stack>
                </MetricPanel>
              </Grid.Col>
            );
          })}
        </Grid>
      </SectionCard>

      <SectionCard title="数据来源状态" description="按来源展示该数据集最新状态。">
        <Grid>
          {Array.from(sourceGroups.entries()).map(([source, group]) => {
            const items = group.items;
            const failedCount = items.filter((item) => item.status === "failed").length;
            return (
              <Grid.Col key={source} span={{ base: 12, xl: 6 }}>
                <MetricPanel label={group.label} align="start" minHeight={220}>
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
                          <Text size="sm">{item.stage_display_name}</Text>
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

      <SectionCard title="近期任务记录" description="按维护对象过滤出的最近任务。">
        <DataTable
          columns={taskRunColumns}
          rows={taskRunRows}
          getRowKey={(item) => item.id}
          emptyState={<EmptyState title="暂无任务记录" description="当前数据集还没有可展示的任务结果。" />}
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
