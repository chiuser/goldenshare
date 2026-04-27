import {
  Button,
  Grid,
  Group,
  Loader,
  Pagination,
  Select,
  Stack,
  Text,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";

import { apiRequest } from "../shared/api/client";
import type {
  OpsCatalogResponse,
  TaskRunCreateResponse,
  TaskRunListResponse,
  TaskRunSummaryResponse,
} from "../shared/api/types";
import { formatDateTimeLabel } from "../shared/date-format";
import {
  formatTaskRunResourceLabel,
  formatStatusLabel,
  formatTriggerSourceLabel,
} from "../shared/ops-display";
import { ActionSummaryCard } from "../shared/ui/action-summary-card";
import { AlertBar } from "../shared/ui/alert-bar";
import { DataTable, type DataTableColumn } from "../shared/ui/data-table";
import { EmptyState } from "../shared/ui/empty-state";
import { FilterBar, FilterBarItem } from "../shared/ui/filter-bar";
import { OpsTableActionGroup, OpsTableCellText } from "../shared/ui/ops-table";
import { SectionCard } from "../shared/ui/section-card";
import { StatCard } from "../shared/ui/stat-card";
import { StatusBadge } from "../shared/ui/status-badge";

const ALL_FILTER_VALUE = "all";
const PAGE_SIZE = 20;

type TaskFilters = {
  status: string;
  trigger_source: string;
  resource_key: string;
};
type CatalogAction = OpsCatalogResponse["actions"][number];
type DatasetCatalogAction = CatalogAction & {
  action_type: "dataset_action";
  target_key: string;
  target_display_name: string;
};

function buildTaskRunsRefetchInterval(data: TaskRunListResponse | undefined) {
  if (!data?.items?.length) {
    return false;
  }
  return data.items.some((item) => item.status === "queued" || item.status === "running" || item.status === "canceling") ? 3000 : false;
}

function buildTaskRunSummaryRefetchInterval(data: TaskRunSummaryResponse | undefined) {
  if (!data) {
    return false;
  }
  return data.queued > 0 || data.running > 0 ? 3000 : false;
}

function createDefaultFilters(): TaskFilters {
  return {
    status: ALL_FILTER_VALUE,
    trigger_source: ALL_FILTER_VALUE,
    resource_key: ALL_FILTER_VALUE,
  };
}

function parsePageValue(raw: string | null): number {
  const value = Number(raw);
  if (!Number.isFinite(value) || value < 1) {
    return 1;
  }
  return Math.floor(value);
}

function buildFilterParams(filters: TaskFilters) {
  const params = new URLSearchParams();
  if (filters.status !== ALL_FILTER_VALUE) params.set("status", filters.status);
  if (filters.trigger_source !== ALL_FILTER_VALUE) params.set("trigger_source", filters.trigger_source);
  if (filters.resource_key !== ALL_FILTER_VALUE) params.set("resource_key", filters.resource_key);
  return params;
}

function buildListParams(filters: TaskFilters, page: number) {
  const params = buildFilterParams(filters);
  params.set("page", String(page));
  params.set("limit", String(PAGE_SIZE));
  params.set("offset", String((page - 1) * PAGE_SIZE));
  return params;
}

function isDatasetCatalogAction(item: CatalogAction): item is DatasetCatalogAction {
  return (
    item.action_type === "dataset_action"
    && typeof item.target_key === "string"
    && item.target_key.trim().length > 0
    && typeof item.target_display_name === "string"
    && item.target_display_name.trim().length > 0
  );
}

function formatCatalogTaskOption(item: DatasetCatalogAction) {
  return item.target_display_name;
}

function formatExecutionTimeScopeLabel(item: { time_scope_label?: string | null }) {
  return item.time_scope_label || "无时间维度";
}

function getCatalogActions(catalog: OpsCatalogResponse | undefined) {
  return Array.isArray(catalog?.actions) ? catalog.actions : [];
}

export function OpsTasksPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchReady, setSearchReady] = useState(false);
  const [filters, setFilters] = useState<TaskFilters>(createDefaultFilters);
  const [page, setPage] = useState(1);
  const [lastAction, setLastAction] = useState<TaskRunCreateResponse | null>(null);

  useEffect(() => {
    const search = new URLSearchParams(window.location.search);
    const status = search.get("status");
    const triggerSource = search.get("trigger_source");
    const resourceKey = search.get("resource_key");
    const pageValue = parsePageValue(search.get("page"));
    setFilters({
      status: status || ALL_FILTER_VALUE,
      trigger_source: triggerSource || ALL_FILTER_VALUE,
      resource_key: resourceKey || ALL_FILTER_VALUE,
    });
    setPage(pageValue);
    setSearchReady(true);
  }, []);

  useEffect(() => {
    if (!searchReady) {
      return;
    }
    const params = buildFilterParams(filters);
    params.set("page", String(page));
    const query = params.toString();
    const nextUrl = query ? `${window.location.pathname}?${query}` : window.location.pathname;
    window.history.replaceState({}, "", nextUrl);
  }, [filters, page, searchReady]);

  const filterQueryString = useMemo(() => buildFilterParams(filters).toString(), [filters]);
  const taskRunListQueryString = useMemo(() => buildListParams(filters, page).toString(), [filters, page]);

  const catalogQuery = useQuery({
    queryKey: ["ops", "catalog"],
    queryFn: () => apiRequest<OpsCatalogResponse>("/api/v1/ops/catalog"),
  });

  const taskRunsQuery = useQuery({
    queryKey: ["ops", "task-runs", taskRunListQueryString],
    queryFn: () => apiRequest<TaskRunListResponse>(`/api/v1/ops/task-runs?${taskRunListQueryString}`),
    enabled: searchReady,
    placeholderData: keepPreviousData,
    refetchInterval: (query) => buildTaskRunsRefetchInterval(query.state.data),
  });

  const taskRunSummaryQuery = useQuery({
    queryKey: ["ops", "task-run-summary", filterQueryString],
    queryFn: () =>
      apiRequest<TaskRunSummaryResponse>(`/api/v1/ops/task-runs/summary${filterQueryString ? `?${filterQueryString}` : ""}`),
    enabled: searchReady,
    placeholderData: keepPreviousData,
    refetchInterval: (query) => buildTaskRunSummaryRefetchInterval(query.state.data),
  });

  const resourceOptions = useMemo(() => {
    const items = [
      ...getCatalogActions(catalogQuery.data)
        .filter(isDatasetCatalogAction)
        .map((item) => ({
          value: item.target_key,
          label: formatCatalogTaskOption(item),
        })),
    ];
    return [{ value: ALL_FILTER_VALUE, label: "全选" }, ...items];
  }, [catalogQuery.data]);

  const statusOptions = useMemo(
    () => [
      { value: ALL_FILTER_VALUE, label: "全选" },
      { value: "queued", label: "等待处理" },
      { value: "running", label: "正在处理" },
      { value: "canceling", label: "停止中" },
      { value: "success", label: "执行成功" },
      { value: "failed", label: "执行失败" },
      { value: "canceled", label: "已取消" },
      { value: "partial_success", label: "部分成功" },
    ],
    [],
  );

  const triggerSourceOptions = useMemo(
    () => [
      { value: ALL_FILTER_VALUE, label: "全选" },
      { value: "manual", label: "手动" },
      { value: "scheduled", label: "自动" },
      { value: "retry", label: "重新提交" },
      { value: "system", label: "系统触发" },
    ],
    [],
  );

  const totalPages = useMemo(() => {
    const total = taskRunsQuery.data?.total ?? 0;
    return total > 0 ? Math.ceil(total / PAGE_SIZE) : 1;
  }, [taskRunsQuery.data?.total]);
  const isInitialTaskRunsLoading = taskRunsQuery.isLoading && !taskRunsQuery.data;
  const isRefreshing =
    !isInitialTaskRunsLoading && (taskRunsQuery.isFetching || taskRunSummaryQuery.isFetching);

  const retryMutation = useMutation({
    mutationFn: (taskRunId: number) =>
      apiRequest<TaskRunCreateResponse>(`/api/v1/ops/task-runs/${taskRunId}/retry`, {
        method: "POST",
      }),
    onSuccess: async (data) => {
      setLastAction(data);
      notifications.show({
        color: "success",
        title: "任务已重新提交",
        message: "系统已经收到新的任务请求。",
      });
      await queryClient.invalidateQueries({ queryKey: ["ops", "task-runs"] });
      await queryClient.invalidateQueries({ queryKey: ["ops", "task-run-summary"] });
      await navigate({ to: "/ops/tasks/$taskRunId", params: { taskRunId: String(data.id) } });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (taskRunId: number) =>
      apiRequest<TaskRunCreateResponse>(`/api/v1/ops/task-runs/${taskRunId}/cancel`, {
        method: "POST",
      }),
    onSuccess: async (data) => {
      setLastAction(data);
      notifications.show({
        color: "success",
        title: "已请求停止当前任务",
        message: `任务 #${data.id}`,
      });
      await queryClient.invalidateQueries({ queryKey: ["ops", "task-runs"] });
      await queryClient.invalidateQueries({ queryKey: ["ops", "task-run-summary"] });
    },
  });

  function updateFilters(next: TaskFilters) {
    setFilters(next);
    setPage(1);
  }

  function buildResultSummary(item: TaskRunListResponse["items"][number] | TaskRunCreateResponse) {
    if ("unit_total" in item && item.unit_total > 0) {
      return `当前进展 ${item.unit_done}/${item.unit_total}（${item.progress_percent ?? 0}%）`;
    }
    if ("primary_issue_title" in item && item.primary_issue_title) {
      return item.primary_issue_title;
    }
    if (item.status === "queued") {
      return "系统已经收到这次任务，正在等待开始处理。";
    }
    if (item.status === "running") {
      return "任务正在处理中，新的进展会陆续更新。";
    }
    if (item.status === "canceling") {
      return "已收到停止请求，正在结束当前处理。";
    }
    return `当前状态：${formatStatusLabel(item.status)}`;
  }

  const taskRunColumns = useMemo<DataTableColumn<TaskRunListResponse["items"][number]>[]>(() => [
    {
      key: "task",
      header: "任务名称",
      align: "left",
      width: "24%",
      render: (item) => (
        <Stack gap={2}>
          <OpsTableCellText fw={600} size="sm">
            {formatTaskRunResourceLabel(item)}
          </OpsTableCellText>
        </Stack>
      ),
    },
    {
      key: "time_scope",
      header: "处理范围",
      align: "left",
      width: "18%",
      render: (item) => (
        <OpsTableCellText size="xs">
          {formatExecutionTimeScopeLabel(item)}
        </OpsTableCellText>
      ),
    },
    {
      key: "trigger",
      header: "发起方式",
      width: "12%",
      render: (item) => <OpsTableCellText size="xs">{formatTriggerSourceLabel(item.trigger_source)}</OpsTableCellText>,
    },
    {
      key: "requested_at",
      header: "提交时间",
      align: "left",
      width: "22%",
      render: (item) => (
        <OpsTableCellText ff="var(--mantine-font-family-monospace)" fw={500} size="xs">
          {formatDateTimeLabel(item.requested_at)}
        </OpsTableCellText>
      ),
    },
    {
      key: "status",
      header: "当前状态",
      width: "10%",
      render: (item) => <StatusBadge value={item.status} />,
    },
    {
      key: "actions",
      header: "操作",
      width: "14%",
      render: (item) => (
        <OpsTableActionGroup>
          <Button
            component="a"
            href={`/app/ops/tasks/${item.id}`}
            size="xs"
            variant="light"
            color="brand"
          >
            查看详情
          </Button>
          {item.status === "failed" ? (
            <Button
              type="button"
              onClick={() => retryMutation.mutate(item.id)}
              size="xs"
              variant="light"
              color="brand"
            >
              重新提交
            </Button>
          ) : null}
          {item.status === "queued" || item.status === "running" ? (
            <Button
              type="button"
              onClick={() => cancelMutation.mutate(item.id)}
              size="xs"
              variant="light"
              color="error"
            >
              停止处理
            </Button>
          ) : null}
        </OpsTableActionGroup>
      ),
    },
  ], [cancelMutation, retryMutation]);

  return (
    <Stack gap="lg">
      {isInitialTaskRunsLoading ? <Loader size="sm" /> : null}
      {taskRunsQuery.error ? (
        <AlertBar tone="error" title="无法读取任务记录">
          {taskRunsQuery.error instanceof Error
            ? taskRunsQuery.error.message
            : "未知错误"}
        </AlertBar>
      ) : null}

      <SectionCard title="任务统计" description="按当前筛选条件统计任务分布，不受当前分页影响。">
        <Grid>
          <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
            <StatCard label="当前筛选任务" value={taskRunSummaryQuery.data?.total ?? "—"} />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
            <StatCard label="等待处理" value={taskRunSummaryQuery.data?.queued ?? "—"} />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
            <StatCard label="正在处理" value={taskRunSummaryQuery.data?.running ?? "—"} />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
            <StatCard label="执行成功" value={taskRunSummaryQuery.data?.success ?? "—"} />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
            <StatCard label="执行失败" value={taskRunSummaryQuery.data?.failed ?? "—"} hint="含部分成功任务；失败任务可以重新提交。" />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
            <StatCard label="已取消" value={taskRunSummaryQuery.data?.canceled ?? "—"} />
          </Grid.Col>
        </Grid>
      </SectionCard>

      <SectionCard title="任务记录" description="先筛选，再查看详情、停止处理，或重新提交失败任务。页面只负责发起和查看，不会把长任务绑在当前页面里执行。">
        <DataTable
          columns={taskRunColumns}
          getRowKey={(item) => item.id}
          rows={taskRunsQuery.data?.items || []}
          toolbar={(
            <FilterBar
              actions={(
                <Group gap="sm">
                  {isRefreshing ? (
                    <Group gap={6}>
                      <Loader size="xs" />
                      <Text size="sm" c="dimmed">
                        正在刷新...
                      </Text>
                    </Group>
                  ) : null}
                  <Button
                    variant="light"
                    color="brand"
                    onClick={() => updateFilters(createDefaultFilters())}
                  >
                    清空筛选
                  </Button>
                </Group>
              )}
            >
              <FilterBarItem>
                <Select
                  label="当前状态"
                  data={statusOptions}
                  value={filters.status}
                  onChange={(value) => updateFilters({ ...filters, status: value || ALL_FILTER_VALUE })}
                />
              </FilterBarItem>
              <FilterBarItem>
                <Select
                  label="发起方式"
                  data={triggerSourceOptions}
                  value={filters.trigger_source}
                  onChange={(value) => updateFilters({ ...filters, trigger_source: value || ALL_FILTER_VALUE })}
                />
              </FilterBarItem>
              <FilterBarItem>
                <Select
                  label="任务名称"
                  searchable
                  data={resourceOptions}
                  value={filters.resource_key}
                  onChange={(value) => updateFilters({ ...filters, resource_key: value || ALL_FILTER_VALUE })}
                />
              </FilterBarItem>
            </FilterBar>
          )}
          summary={lastAction ? (
            <ActionSummaryCard
              title="最近一次任务操作"
              rows={[
                { label: "任务名称", value: lastAction.title },
                { label: "当前状态", value: formatStatusLabel(lastAction.status) },
                { label: "处理结果", value: buildResultSummary(lastAction) },
              ]}
            />
          ) : null}
          emptyState={(
            <EmptyState
              title="当前筛选下没有任务记录"
              description="可以清空筛选后再看，或调整筛选条件重新查看。"
              action={(
                <Button
                  variant="light"
                  onClick={() => updateFilters(createDefaultFilters())}
                >
                  清空筛选
                </Button>
              )}
            />
          )}
        />
        {taskRunsQuery.data && taskRunsQuery.data.total > PAGE_SIZE ? (
          <Group justify="flex-end" mt="md">
            <Pagination
              aria-label="任务记录分页"
              total={totalPages}
              value={page}
              onChange={setPage}
            />
          </Group>
        ) : null}
      </SectionCard>
    </Stack>
  );
}
