import { Alert, Badge, Button, Divider, Grid, Group, Loader, Paper, Stack, Table, Text } from "@mantine/core";
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
import { OpsTable, OpsTableCell, OpsTableCellText, OpsTableHeaderCell } from "../shared/ui/ops-table";
import { SectionCard } from "../shared/ui/section-card";
import { StatusBadge } from "../shared/ui/status-badge";
import { buildFreshnessDisplayNameMap } from "./ops-v21-shared";


function stageTitle(stage: string) {
  if (stage === "raw") return "raw";
  if (stage === "std") return "std";
  if (stage === "resolution") return "resolution";
  if (stage === "serving") return "serving";
  return stage;
}

function inferSourceFromTargetTable(targetTable: string | null | undefined): string | null {
  const table = (targetTable || "").toLowerCase();
  if (table.startsWith("raw_biying.")) return "biying";
  if (table.startsWith("raw_tushare.")) return "tushare";
  if (table.startsWith("raw.")) return "tushare";
  return null;
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
    const sourceKey = inferSourceFromTargetTable(freshnessItem.target_table);
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
  const executionItems = executionQuery.data?.items || [];
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

  return (
    <Stack gap="lg">
      <SectionCard title={`${datasetKey} · ${displayName}`} description="数据集详情页先按 V2.1 设计骨架接入已有能力，缺失部分用待补充占位。">
        <Group justify="space-between" align="center">
          <Group gap="sm">
            <Button component={Link} to="/ops/v21/overview" variant="light" color="gray">
              返回总览
            </Button>
            <StatusBadge value={recentExecution?.status || "unknown"} />
            {latestRelease ? <Badge variant="light" color="green">策略 v{latestRelease.target_policy_version}</Badge> : null}
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
        <Alert color="red" title="读取数据集详情失败">
          {error instanceof Error ? error.message : "未知错误"}
        </Alert>
      ) : null}
      {!isLoading && !error && latestItems.length === 0 && executionItems.length === 0 ? (
        <Alert color="blue" title="该数据集暂无可展示记录">
          还没有该数据集的层级快照与执行记录。先执行一次同步任务后再查看详情。
        </Alert>
      ) : null}

      <Grid>
        <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
          <Paper p="md" radius="md" withBorder>
            <Text c="dimmed" size="sm">serving 版本</Text>
            <Text fw={800} size="xl">{stageMap.get("serving") ? formatDateTimeLabel(stageMap.get("serving")?.calculated_at) : "—"}</Text>
          </Paper>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
          <Paper p="md" radius="md" withBorder>
            <Text c="dimmed" size="sm">今日写入行数</Text>
            <Text fw={800} size="xl">{recentExecution?.rows_written ?? 0}</Text>
          </Paper>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
          <Paper p="md" radius="md" withBorder>
            <Text c="dimmed" size="sm">serving lag</Text>
            <Text fw={800} size="xl">
              {stageMap.get("serving")?.lag_seconds ? `${Math.floor((stageMap.get("serving")?.lag_seconds || 0) / 3600)}h ${Math.floor(((stageMap.get("serving")?.lag_seconds || 0) % 3600) / 60)}m` : "—"}
            </Text>
          </Paper>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
          <Paper p="md" radius="md" withBorder>
            <Text c="dimmed" size="sm">今日执行次数</Text>
            <Text fw={800} size="xl">{executionItems.length}</Text>
          </Paper>
        </Grid.Col>
      </Grid>

      <SectionCard title="全链路层级状态" description="raw / std / resolution / serving 的最新状态。">
        <Grid>
          {(["raw", "std", "resolution", "serving"] as const).map((stage) => {
            const item = stageMap.get(stage);
            return (
              <Grid.Col key={stage} span={{ base: 12, md: 6, xl: 3 }}>
                <Paper withBorder radius="md" p="md">
                  <Text ff="IBM Plex Mono, SFMono-Regular, monospace" c="dimmed">{stageTitle(stage)}</Text>
                  <Group gap={8} mt={4}>
                    <StatusBadge value={item?.status || "unknown"} />
                  </Group>
                  <Text size="sm" mt={10}>最近成功：{item?.last_success_at ? formatDateTimeLabel(item.last_success_at) : "—"}</Text>
                  <Text size="sm">最近失败：{item?.last_failure_at ? formatDateTimeLabel(item.last_failure_at) : "—"}</Text>
                  <Text size="sm">rows_in：{item?.rows_in ?? "—"}</Text>
                  <Text size="sm">rows_out：{item?.rows_out ?? "—"}</Text>
                </Paper>
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
                <Paper withBorder radius="md" p="md">
                  <Group justify="space-between">
                    <Group gap={8}>
                      <Text fw={800} size="xl">{source}</Text>
                      <Badge color={failedCount > 0 ? "red" : "green"} variant="light">{failedCount > 0 ? "失败" : "正常"}</Badge>
                    </Group>
                    <Text c="dimmed" size="sm">条目数：{items.length}</Text>
                  </Group>
                  <Divider my="sm" />
                  {items.map((item) => (
                    <Group key={`${source}-${item.stage}`} justify="space-between" mb={6}>
                      <Text ff="IBM Plex Mono, SFMono-Regular, monospace">{item.stage}</Text>
                      <Group gap={8}>
                        <StatusBadge value={item.status} />
                        <Text size="sm" c="dimmed">{formatDateTimeLabel(item.calculated_at)}</Text>
                      </Group>
                    </Group>
                  ))}
                </Paper>
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
                <Badge variant="light" color="violet">probe</Badge>
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
        <OpsTable>
          <Table.Thead>
            <Table.Tr>
              <OpsTableHeaderCell align="left" width="20%">执行ID</OpsTableHeaderCell>
              <OpsTableHeaderCell width="12%">触发方式</OpsTableHeaderCell>
              <OpsTableHeaderCell width="12%">状态</OpsTableHeaderCell>
              <OpsTableHeaderCell width="12%">rows_in</OpsTableHeaderCell>
              <OpsTableHeaderCell width="12%">rows_out</OpsTableHeaderCell>
              <OpsTableHeaderCell align="left" width="20%">请求时间</OpsTableHeaderCell>
              <OpsTableHeaderCell align="left" width="12%">错误</OpsTableHeaderCell>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {executionItems.slice(0, 10).map((item) => (
              <Table.Tr key={item.id}>
                <OpsTableCell align="left"><OpsTableCellText ff="IBM Plex Mono, SFMono-Regular, monospace">{item.id}</OpsTableCellText></OpsTableCell>
                <OpsTableCell><OpsTableCellText>{item.trigger_source}</OpsTableCellText></OpsTableCell>
                <OpsTableCell><StatusBadge value={item.status} /></OpsTableCell>
                <OpsTableCell><OpsTableCellText>{item.rows_fetched}</OpsTableCellText></OpsTableCell>
                <OpsTableCell><OpsTableCellText>{item.rows_written}</OpsTableCellText></OpsTableCell>
                <OpsTableCell align="left"><OpsTableCellText>{formatDateTimeLabel(item.requested_at)}</OpsTableCellText></OpsTableCell>
                <OpsTableCell align="left"><OpsTableCellText c={item.error_code ? "var(--gs-magenta)" : "dimmed"}>{item.error_code || "—"}</OpsTableCellText></OpsTableCell>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </OpsTable>
      </SectionCard>

      <SectionCard title="当前生效融合策略" description="先展示发布版本与规则规模，策略细节后续补充独立页面。">
        <Grid>
          <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
            <Paper withBorder radius="md" p="md">
              <Text c="dimmed" size="sm">生效版本</Text>
              <Text fw={800} size="xl">{latestRelease ? `v${latestRelease.target_policy_version}` : "待补充"}</Text>
              <Text size="sm" c="dimmed">{latestRelease?.triggered_at ? formatDateLabel(latestRelease.triggered_at) : "—"}</Text>
            </Paper>
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
            <Paper withBorder radius="md" p="md">
              <Text c="dimmed" size="sm">映射规则</Text>
              <Text fw={800} size="xl">{mappingQuery.data?.total ?? 0}</Text>
            </Paper>
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
            <Paper withBorder radius="md" p="md">
              <Text c="dimmed" size="sm">清洗规则</Text>
              <Text fw={800} size="xl">{cleansingQuery.data?.total ?? 0}</Text>
            </Paper>
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
            <Paper withBorder radius="md" p="md">
              <Text c="dimmed" size="sm">快照样本</Text>
              <Text fw={800} size="xl">{historyQuery.data?.total ?? 0}</Text>
            </Paper>
          </Grid.Col>
        </Grid>
      </SectionCard>
    </Stack>
  );
}
