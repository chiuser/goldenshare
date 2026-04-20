import {
  Button,
  Grid,
  Group,
  Loader,
  Select,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";

import { apiRequest } from "../shared/api/client";
import type { ExecutionDetailResponse, ExecutionListResponse, OpsCatalogResponse } from "../shared/api/types";
import { formatDateTimeLabel } from "../shared/date-format";
import { formatSpecDisplayLabel, formatStatusLabel, formatTriggerSourceLabel } from "../shared/ops-display";
import { ActionSummaryCard } from "../shared/ui/action-summary-card";
import { AlertBar } from "../shared/ui/alert-bar";
import { DataTable, type DataTableColumn } from "../shared/ui/data-table";
import { EmptyState } from "../shared/ui/empty-state";
import { FilterBar, FilterBarItem } from "../shared/ui/filter-bar";
import { OpsTableActionGroup, OpsTableCellText } from "../shared/ui/ops-table";
import { SectionCard } from "../shared/ui/section-card";
import { StatCard } from "../shared/ui/stat-card";
import { StatusBadge } from "../shared/ui/status-badge";

function buildExecutionsRefetchInterval(data: ExecutionListResponse | undefined) {
  if (!data?.items?.length) {
    return false;
  }
  return data.items.some((item) => item.status === "queued" || item.status === "running" || item.status === "canceling") ? 3000 : false;
}

export function OpsTasksPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const appliedSearchRef = useRef(false);
  const [filters, setFilters] = useState<{
    status: string | null;
    trigger_source: string | null;
    spec_key: string | null;
  }>({
    status: null,
    trigger_source: null,
    spec_key: null,
  });
  const [lastAction, setLastAction] = useState<ExecutionDetailResponse | null>(null);

  useEffect(() => {
    if (appliedSearchRef.current) return;
    appliedSearchRef.current = true;
    const search = new URLSearchParams(window.location.search);
    const status = search.get("status");
    const triggerSource = search.get("trigger_source");
    const specKey = search.get("spec_key");
    setFilters({
      status,
      trigger_source: triggerSource,
      spec_key: specKey,
    });
  }, [setFilters]);

  const filterQueryString = useMemo(() => {
    const params = new URLSearchParams();
    if (filters.status) params.set("status", filters.status);
    if (filters.trigger_source) params.set("trigger_source", filters.trigger_source);
    if (filters.spec_key) params.set("spec_key", filters.spec_key);
    return params.toString();
  }, [filters]);

  const catalogQuery = useQuery({
    queryKey: ["ops", "catalog"],
    queryFn: () => apiRequest<OpsCatalogResponse>("/api/v1/ops/catalog"),
  });

  const executionsQuery = useQuery({
    queryKey: ["ops", "executions", filterQueryString],
    queryFn: () =>
      apiRequest<ExecutionListResponse>(`/api/v1/ops/executions${filterQueryString ? `?${filterQueryString}` : ""}`),
    refetchInterval: (query) => buildExecutionsRefetchInterval(query.state.data),
  });

  const specOptions = useMemo(() => {
    const catalog = catalogQuery.data;
    if (!catalog) return [];
    return [
      ...catalog.job_specs.map((item) => ({
        value: item.key,
        label: formatSpecDisplayLabel(item.key, item.display_name),
      })),
      ...catalog.workflow_specs.map((item) => ({
        value: item.key,
        label: formatSpecDisplayLabel(item.key, item.display_name),
      })),
    ];
  }, [catalogQuery.data]);

  const stats = useMemo(() => {
    const items = executionsQuery.data?.items || [];
    return {
      total: items.length,
      queued: items.filter((item) => item.status === "queued").length,
      running: items.filter((item) => item.status === "running" || item.status === "canceling").length,
      success: items.filter((item) => item.status === "success").length,
      failed: items.filter((item) => item.status === "failed").length,
    };
  }, [executionsQuery.data?.items]);

  const retryMutation = useMutation({
    mutationFn: (executionId: number) =>
      apiRequest<ExecutionDetailResponse>(`/api/v1/ops/executions/${executionId}/retry`, {
        method: "POST",
      }),
    onSuccess: async (data) => {
      setLastAction(data);
      notifications.show({
        color: "success",
        title: "任务已重新提交",
        message: "系统已经收到新的任务请求。",
      });
      await queryClient.invalidateQueries({ queryKey: ["ops", "executions"] });
      await navigate({ to: "/ops/tasks/$executionId", params: { executionId: String(data.id) } });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (executionId: number) =>
      apiRequest<ExecutionDetailResponse>(`/api/v1/ops/executions/${executionId}/cancel`, {
        method: "POST",
      }),
    onSuccess: async (data) => {
      setLastAction(data);
      notifications.show({
        color: "success",
        title: "已请求停止当前任务",
        message: `任务 #${data.id}`,
      });
      await queryClient.invalidateQueries({ queryKey: ["ops", "executions"] });
    },
  });

  function buildResultSummary(item: ExecutionListResponse["items"][number]) {
    if (
      item.progress_current !== null &&
      item.progress_current !== undefined &&
      item.progress_total !== null &&
      item.progress_total !== undefined &&
      item.progress_total > 0
    ) {
      return `当前进展 ${item.progress_current}/${item.progress_total}（${item.progress_percent ?? 0}%）`;
    }
    if (item.progress_message && (item.status === "queued" || item.status === "running" || item.status === "canceling")) {
      return item.progress_message;
    }
    if (item.summary_message) {
      return item.summary_message;
    }
    if (item.progress_message) {
      return item.progress_message;
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

  const executionColumns = useMemo<DataTableColumn<ExecutionListResponse["items"][number]>[]>(() => [
    {
      key: "spec",
      header: "任务名称",
      align: "left",
      width: "34%",
      render: (item) => (
        <Stack gap={2}>
          <OpsTableCellText fw={600} size="sm">
            {formatSpecDisplayLabel(item.spec_key, item.spec_display_name)}
          </OpsTableCellText>
        </Stack>
      ),
    },
    {
      key: "trigger",
      header: "发起方式",
      width: "14%",
      render: (item) => <OpsTableCellText size="xs">{formatTriggerSourceLabel(item.trigger_source)}</OpsTableCellText>,
    },
    {
      key: "requested_at",
      header: "提交时间",
      align: "left",
      width: "24%",
      render: (item) => (
        <OpsTableCellText ff="var(--mantine-font-family-monospace)" fw={500} size="xs">
          {formatDateTimeLabel(item.requested_at)}
        </OpsTableCellText>
      ),
    },
    {
      key: "status",
      header: "当前状态",
      width: "12%",
      render: (item) => <StatusBadge value={item.status} />,
    },
    {
      key: "actions",
      header: "操作",
      width: "16%",
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
      <Group justify="space-between" align="center">
        <Text c="dimmed" size="sm">
          在这里看最近跑了什么、结果怎么样，再决定是查看详情、停止处理，还是重新提交。
        </Text>
        <Group gap="xs">
          <Button component={Link} to="/ops/v21/overview" size="sm" variant="light" color="brand">
            查看数据状态
          </Button>
          <Button component={Link} to="/ops/manual-sync" size="sm">
            去手动同步
          </Button>
        </Group>
      </Group>

      {(catalogQuery.isLoading || executionsQuery.isLoading) ? <Loader size="sm" /> : null}
      {catalogQuery.error || executionsQuery.error ? (
        <AlertBar tone="error" title="无法读取任务记录">
          {(catalogQuery.error || executionsQuery.error) instanceof Error
            ? ((catalogQuery.error || executionsQuery.error) as Error).message
            : "未知错误"}
        </AlertBar>
      ) : null}

      <SectionCard title="任务概览" description="先看当前任务分布，再按状态筛选处理。">
        <Grid>
          <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
            <StatCard label="当前结果集" value={stats.total} />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
            <StatCard label="等待处理" value={stats.queued} />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
            <StatCard label="正在处理" value={stats.running} />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
            <StatCard label="已完成" value={stats.success} />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6, xl: 4 }}>
            <StatCard label="执行失败" value={stats.failed} hint="失败任务可以重新提交。" />
          </Grid.Col>
        </Grid>
      </SectionCard>

      <SectionCard title="筛选任务" description="先按状态、发起方式或任务名称筛一遍，再进入详情处理。">
        <FilterBar
          actions={(
            <Button
              variant="light"
              color="brand"
              onClick={() => setFilters({ status: null, trigger_source: null, spec_key: null })}
            >
              清空筛选
            </Button>
          )}
        >
          <FilterBarItem>
            <Select
              label="当前状态"
              clearable
              data={[
                { value: "queued", label: "等待处理" },
                { value: "running", label: "正在处理" },
                { value: "canceling", label: "停止中" },
                { value: "success", label: "执行成功" },
                { value: "failed", label: "执行失败" },
                { value: "canceled", label: "已取消" },
                { value: "partial_success", label: "部分成功" },
              ]}
              value={filters.status}
              onChange={(value) => setFilters((current) => ({ ...current, status: value }))}
            />
          </FilterBarItem>
          <FilterBarItem>
            <Select
              label="发起方式"
              clearable
              data={[
                { value: "manual", label: "手动" },
                { value: "scheduled", label: "自动" },
                { value: "retry", label: "重新提交" },
                { value: "system", label: "系统触发" },
              ]}
              value={filters.trigger_source}
              onChange={(value) => setFilters((current) => ({ ...current, trigger_source: value }))}
            />
          </FilterBarItem>
          <FilterBarItem>
            <Select
              label="任务名称"
              searchable
              clearable
              data={specOptions}
              value={filters.spec_key}
              onChange={(value) => setFilters((current) => ({ ...current, spec_key: value }))}
            />
          </FilterBarItem>
        </FilterBar>
      </SectionCard>

      <SectionCard title="任务记录" description="这里查看任务状态，或重新提交失败任务。页面只负责发起和查看，不会把长任务绑在当前页面里执行。">
        <DataTable
          columns={executionColumns}
          getRowKey={(item) => item.id}
          rows={executionsQuery.data?.items || []}
          summary={lastAction ? (
            <ActionSummaryCard
              title="最近一次任务操作"
              rows={[
                { label: "任务名称", value: formatSpecDisplayLabel(lastAction.spec_key, lastAction.spec_display_name) },
                { label: "当前状态", value: formatStatusLabel(lastAction.status) },
                { label: "处理结果", value: buildResultSummary(lastAction) },
              ]}
            />
          ) : null}
          emptyState={(
            <EmptyState
              title="当前筛选下没有任务记录"
              description="可以清空筛选后再看，或者直接去“手动同步”发起新的任务。"
              action={
                <Button variant="light" onClick={() => setFilters({ status: null, trigger_source: null, spec_key: null })}>
                  清空筛选
                </Button>
              }
            />
          )}
        />
      </SectionCard>
    </Stack>
  );
}
