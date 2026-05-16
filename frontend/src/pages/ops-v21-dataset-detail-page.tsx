import { Alert, Badge, Button, Grid, Group, Loader, Stack, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { apiRequest } from "../shared/api/client";
import type {
  DatasetCardListResponse,
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

function formatDetailStatusLabel(value: string | null | undefined): string {
  const normalized = (value || "unknown").toLowerCase();
  if (normalized === "healthy") return "正常";
  return formatStatusLabel(value);
}

function formatApiObservedValue(value: string | null | undefined): string {
  if (!value) return "—";
  return value.includes("T") ? formatDateTimeLabel(value) : formatDateLabel(value);
}

export function OpsV21DatasetDetailPage({ datasetKey }: { datasetKey: string }) {
  const cardQuery = useQuery({
    queryKey: ["ops", "dataset-cards", "v21-dataset-detail", datasetKey],
    queryFn: () => apiRequest<DatasetCardListResponse>("/api/v1/ops/dataset-cards?limit=2000"),
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
    taskRunQuery,
    probeQuery,
    releaseQuery,
    mappingQuery,
    cleansingQuery,
  ].some((query) => query.isLoading);
  const error = cardQuery.error || taskRunQuery.error || probeQuery.error || releaseQuery.error || mappingQuery.error || cleansingQuery.error;

  const datasetCard = (cardQuery.data?.groups || [])
    .flatMap((group) => group.items || [])
    .find((item) => item.detail_dataset_key === datasetKey || item.dataset_key === datasetKey);
  const displayName = datasetCard?.display_name || "数据集未找到";
  const taskRunItems = taskRunQuery.data?.items || [];
  const taskRunRows = taskRunItems.slice(0, 10);
  const recentTaskRun = taskRunItems[0];
  const manualActionKey = datasetCard?.primary_action_key || null;
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
      header: "读取行数",
      width: "12%",
      render: (item) => <Text size="sm">{item.rows_fetched}</Text>,
    },
    {
      key: "rows_out",
      header: "保存行数",
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
      <SectionCard title={displayName} description="查看该数据集的健康度、近期任务、调度覆盖与规则配置。">
        <Group justify="space-between" align="center">
          <Group gap="sm">
            <Button component={Link} to="/ops/v21/overview" variant="light" color="gray">
              返回总览
            </Button>
            <StatusBadge value={datasetCard?.status || recentTaskRun?.status || "unknown"} />
            {latestRelease ? <Badge variant="light" color="success">策略 v{latestRelease.target_policy_version}</Badge> : null}
          </Group>
          <Group gap="sm">
            <Button component="a" href={buildManualTaskHref({ actionKey: manualActionKey, actionType: "dataset_action" })} variant="light" color="brand">
              去处理
            </Button>
            <Button component="a" href={buildManualTaskHref({ actionKey: manualActionKey, actionType: "dataset_action" })} variant="light">
              手动执行
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
      {!isLoading && !error && !datasetCard && taskRunItems.length === 0 ? (
        <Alert color="info" title="该数据集暂无可展示记录">
          还没有该数据集的状态与执行记录。先执行一次维护任务后再查看详情。
        </Alert>
      ) : null}

      <Grid>
        <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
          <MetricPanel label="当前状态">
            <StatusBadge
              value={datasetCard?.freshness_status || datasetCard?.status || recentTaskRun?.status || "unknown"}
              label={formatDetailStatusLabel(datasetCard?.freshness_status || datasetCard?.status || recentTaskRun?.status)}
            />
          </MetricPanel>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
          <MetricPanel label={datasetCard?.latest_observed_date_label || "最新观测"}>
            <Text fw={700} size="xl">
              {formatApiObservedValue(datasetCard?.latest_observed_date || datasetCard?.latest_business_date)}
            </Text>
          </MetricPanel>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
          <MetricPanel label="滞后天数">
            <Text fw={700} size="xl">
              {datasetCard?.lag_days != null ? `${datasetCard.lag_days} 天` : "—"}
            </Text>
          </MetricPanel>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
          <MetricPanel label="近期任务数">
            <Text fw={700} size="xl">{taskRunItems.length}</Text>
          </MetricPanel>
        </Grid.Col>
      </Grid>

      <SectionCard title="调度覆盖" description="先接入已存在的自动任务与探测规则。">
        <Stack gap="xs">
          {probeQuery.data?.items?.map((item) => (
            <Group key={item.id} justify="space-between">
              <Group gap={8}>
                <Badge variant="light" color="info">探测</Badge>
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

      <SectionCard title="当前生效融合策略" description="展示当前发布版本与规则规模。">
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
            <MetricPanel label={datasetCard?.last_success_label || "最近维护成功时间"}>
              <Text fw={700} size="xl">{datasetCard?.latest_success_at ? formatDateTimeLabel(datasetCard.latest_success_at) : "—"}</Text>
            </MetricPanel>
          </Grid.Col>
        </Grid>
      </SectionCard>
    </Stack>
  );
}
