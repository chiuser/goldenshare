import {
  Alert,
  Anchor,
  Button,
  Grid,
  Group,
  Loader,
  Paper,
  Select,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useRef } from "react";

import { apiRequest } from "../shared/api/client";
import type { ExecutionDetailResponse, ExecutionListResponse, OpsCatalogResponse } from "../shared/api/types";
import { formatDateTimeLabel } from "../shared/date-format";
import { formatSpecDisplayLabel, formatTriggerSourceLabel } from "../shared/ops-display";
import { usePersistentState } from "../shared/hooks/use-persistent-state";
import { ActionSummaryCard } from "../shared/ui/action-summary-card";
import { EmptyState } from "../shared/ui/empty-state";
import { PageHeader } from "../shared/ui/page-header";
import { SectionCard } from "../shared/ui/section-card";
import { StatCard } from "../shared/ui/stat-card";
import { StatusBadge } from "../shared/ui/status-badge";


const FILTERS_KEY = "goldenshare.frontend.ops.tasks.filters";

export function OpsTasksPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const appliedSearchRef = useRef(false);
  const [filters, setFilters] = usePersistentState<{
    status: string | null;
    trigger_source: string | null;
    spec_key: string | null;
  }>(FILTERS_KEY, {
    status: null,
    trigger_source: null,
    spec_key: null,
  });
  const [lastAction, setLastAction] = usePersistentState<ExecutionDetailResponse | null>(
    "goldenshare.frontend.ops.tasks.last-action",
    null,
  );

  useEffect(() => {
    if (appliedSearchRef.current) return;
    appliedSearchRef.current = true;
    const search = new URLSearchParams(window.location.search);
    const status = search.get("status");
    const triggerSource = search.get("trigger_source");
    const specKey = search.get("spec_key");
    if (!status && !triggerSource && !specKey) return;
    setFilters((current) => ({
      status: status ?? current.status,
      trigger_source: triggerSource ?? current.trigger_source,
      spec_key: specKey ?? current.spec_key,
    }));
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
      running: items.filter((item) => item.status === "running").length,
      success: items.filter((item) => item.status === "success").length,
      failed: items.filter((item) => item.status === "failed").length,
    };
  }, [executionsQuery.data?.items]);

  const retryNowMutation = useMutation({
    mutationFn: (executionId: number) =>
      apiRequest<ExecutionDetailResponse>(`/api/v1/ops/executions/${executionId}/retry-now`, {
        method: "POST",
      }),
    onSuccess: async (data) => {
      setLastAction(data);
      notifications.show({
        color: "green",
        title: "任务已经重新开始",
        message: `${formatSpecDisplayLabel(data.spec_key, data.spec_display_name)} #${data.id}`,
      });
      await queryClient.invalidateQueries({ queryKey: ["ops", "executions"] });
      await navigate({ to: "/ops/tasks/$executionId", params: { executionId: String(data.id) } });
    },
  });

  const runNowMutation = useMutation({
    mutationFn: (executionId: number) =>
      apiRequest<ExecutionDetailResponse>(`/api/v1/ops/executions/${executionId}/run-now`, {
        method: "POST",
      }),
    onSuccess: async (data) => {
      setLastAction(data);
      notifications.show({
        color: "green",
        title: "任务已经开始处理",
        message: `${formatSpecDisplayLabel(data.spec_key, data.spec_display_name)} #${data.id}`,
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
        color: "green",
        title: "已请求停止当前任务",
        message: `任务 #${data.id}`,
      });
      await queryClient.invalidateQueries({ queryKey: ["ops", "executions"] });
    },
  });

  return (
    <Stack gap="lg">
      <PageHeader
        title="任务记录"
        description="在这里看最近跑了什么、结果怎么样，以及失败后应该怎么继续处理。"
        action={
          <Button component={Link} to="/ops/manual-sync">
            去手动同步
          </Button>
        }
      />

      {(catalogQuery.isLoading || executionsQuery.isLoading) ? <Loader size="sm" /> : null}
      {catalogQuery.error || executionsQuery.error ? (
        <Alert color="red" title="无法读取任务记录">
          {(catalogQuery.error || executionsQuery.error) instanceof Error
            ? ((catalogQuery.error || executionsQuery.error) as Error).message
            : "未知错误"}
        </Alert>
      ) : null}

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
          <StatCard label="执行失败" value={stats.failed} hint="失败任务通常优先使用“重新执行”，这样会立刻开始，不需要再去别的页面点第二次。" />
        </Grid.Col>
      </Grid>

      <SectionCard title="筛选任务" description="先按状态、发起方式或任务名称筛一遍，再进入详情处理。">
        <Grid align="end">
          <Grid.Col span={{ base: 12, md: 4 }}>
            <Select
              label="当前状态"
              clearable
              data={[
                { value: "queued", label: "等待处理" },
                { value: "running", label: "正在处理" },
                { value: "success", label: "执行成功" },
                { value: "failed", label: "执行失败" },
                { value: "canceled", label: "已取消" },
                { value: "partial_success", label: "部分成功" },
              ]}
              value={filters.status}
              onChange={(value) => setFilters((current) => ({ ...current, status: value }))}
            />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 4 }}>
            <Select
              label="发起方式"
              clearable
              data={[
                { value: "manual", label: "手动发起" },
                { value: "scheduled", label: "自动运行" },
                { value: "retry", label: "重新执行" },
                { value: "system", label: "系统内部触发" },
              ]}
              value={filters.trigger_source}
              onChange={(value) => setFilters((current) => ({ ...current, trigger_source: value }))}
            />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 4 }}>
            <Select
              label="任务名称"
              searchable
              clearable
              data={specOptions}
              value={filters.spec_key}
              onChange={(value) => setFilters((current) => ({ ...current, spec_key: value }))}
            />
          </Grid.Col>
        </Grid>
      </SectionCard>

      <Grid align="stretch">
        <Grid.Col span={{ base: 12, xl: 8 }}>
          <SectionCard title="任务列表" description="默认动作尽量闭环：失败任务优先“重新执行”，等待中的任务优先“立即开始”。">
            {(executionsQuery.data?.items?.length ?? 0) > 0 ? (
              <Table highlightOnHover striped>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>任务名称</Table.Th>
                    <Table.Th>发起方式</Table.Th>
                    <Table.Th>提交时间</Table.Th>
                    <Table.Th>当前状态</Table.Th>
                    <Table.Th>结果摘要</Table.Th>
                    <Table.Th>操作</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {(executionsQuery.data?.items || []).map((item) => (
                    <Table.Tr key={item.id}>
                      <Table.Td>
                        <Stack gap={2}>
                          <Text fw={600}>{formatSpecDisplayLabel(item.spec_key, item.spec_display_name)}</Text>
                          <Text c="dimmed" size="xs">#{item.id}</Text>
                        </Stack>
                      </Table.Td>
                      <Table.Td>{formatTriggerSourceLabel(item.trigger_source)}</Table.Td>
                      <Table.Td>{formatDateTimeLabel(item.requested_at)}</Table.Td>
                      <Table.Td>
                        <StatusBadge value={item.status} />
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm" lineClamp={2}>{item.summary_message || "暂无结果摘要"}</Text>
                      </Table.Td>
                      <Table.Td>
                        <Stack gap={6}>
                          <Anchor component="a" href={`/app/ops/tasks/${item.id}`} size="sm">
                            查看详情
                          </Anchor>
                          {item.status === "failed" ? (
                            <Anchor component="button" type="button" onClick={() => retryNowMutation.mutate(item.id)} size="sm">
                              重新执行
                            </Anchor>
                          ) : null}
                          {item.status === "queued" ? (
                            <Anchor component="button" type="button" onClick={() => runNowMutation.mutate(item.id)} size="sm">
                              立即开始
                            </Anchor>
                          ) : null}
                          {item.status === "queued" || item.status === "running" ? (
                            <Anchor component="button" type="button" onClick={() => cancelMutation.mutate(item.id)} size="sm">
                              停止处理
                            </Anchor>
                          ) : null}
                          <Anchor component="a" href={`/app/ops/manual-sync?from_execution_id=${item.id}`} size="sm">
                            复制参数
                          </Anchor>
                        </Stack>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            ) : (
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
          </SectionCard>
        </Grid.Col>

        <Grid.Col span={{ base: 12, xl: 4 }}>
          <Stack gap="lg">
            <SectionCard title="使用提醒" description="这套页面按用户动作设计，不需要记住内部运行机制。">
              <Stack gap="sm">
                <Text size="sm">失败任务：直接点“重新执行”，会立刻开始。</Text>
                <Text size="sm">等待中的任务：直接点“立即开始”，不用再去别的页面。</Text>
                <Text size="sm">想改参数：点“复制参数”，会带着原参数跳到手动同步页。</Text>
              </Stack>
            </SectionCard>

            {lastAction ? (
              <ActionSummaryCard
                title="最近一次任务操作"
                rows={[
                  { label: "任务名称", value: formatSpecDisplayLabel(lastAction.spec_key, lastAction.spec_display_name) },
                  { label: "任务编号", value: `#${lastAction.id}` },
                  { label: "当前状态", value: lastAction.status },
                  { label: "处理结果", value: lastAction.summary_message || "暂无摘要" },
                ]}
              />
            ) : null}
          </Stack>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
