import {
  Badge,
  Button,
  Grid,
  Group,
  Loader,
  Progress,
  SimpleGrid,
  Stack,
  Text,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { apiRequest } from "../shared/api/client";
import type { TaskRunCreateResponse, TaskRunIssueDetailResponse, TaskRunViewResponse } from "../shared/api/types";
import { formatDateTimeLabel } from "../shared/date-format";
import { buildManualTaskHref } from "../shared/ops-links";
import { formatStatusLabel, formatTriggerSourceLabel } from "../shared/ops-display";
import { AlertBar, AlertBarNote } from "../shared/ui/alert-bar";
import { DataTable, type DataTableColumn } from "../shared/ui/data-table";
import { DetailDrawer } from "../shared/ui/detail-drawer";
import { MetricPanel } from "../shared/ui/metric-panel";
import { OpsTableCellText } from "../shared/ui/ops-table";
import { SectionCard } from "../shared/ui/section-card";
import { StatusBadge } from "../shared/ui/status-badge";

function buildRefetchInterval(status: string | undefined) {
  return status === "queued" || status === "running" || status === "canceling" ? 3000 : false;
}

function buildStatusHeadline(view: TaskRunViewResponse) {
  const status = view.run.status;
  if (status === "failed" || status === "partial_success") {
    return {
      color: "error" as const,
      title: "任务处理失败",
      description: view.primary_issue?.operator_message || "系统已经记录失败原因，请先查看问题摘要。",
    };
  }
  if (status === "success") {
    return { color: "success" as const, title: "任务处理完成", description: "本次任务已经结束，结果已保存到数据库。" };
  }
  if (status === "canceled") {
    return { color: "warning" as const, title: "任务已取消", description: "本次任务已经停止处理。" };
  }
  if (status === "canceling") {
    return { color: "warning" as const, title: "正在停止", description: "系统已收到停止请求，正在结束当前处理边界。" };
  }
  if (status === "running") {
    return { color: "info" as const, title: "任务正在处理", description: "进度会自动刷新，页面不会阻塞任务执行。" };
  }
  return { color: "info" as const, title: "任务等待处理", description: "任务已经入队，等待 worker 接收。" };
}

function buildActionSuggestion(view: TaskRunViewResponse) {
  if (view.primary_issue?.suggested_action) {
    return view.primary_issue.suggested_action;
  }
  if (view.run.status === "failed" || view.run.status === "partial_success") {
    return "先查看问题摘要和技术诊断，确认是否需要缩小范围重新提交。";
  }
  if (view.run.status === "running" || view.run.status === "queued") {
    return "继续观察当前进度；如果任务明显卡住，再考虑停止处理。";
  }
  return "任务已经结束，可返回任务记录或复制参数发起新的任务。";
}

function formatContext(context: Record<string, unknown>) {
  const entries = Object.entries(context).filter(([, value]) => value !== null && value !== undefined && value !== "");
  if (!entries.length) {
    return "暂无当前对象";
  }
  return entries.map(([key, value]) => `${key}=${String(value)}`).join("，");
}

function formatDuration(ms: number | null) {
  if (ms === null || ms === undefined) {
    return "—";
  }
  if (ms < 1000) {
    return `${ms}ms`;
  }
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) {
    return `${seconds}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const remainSeconds = seconds % 60;
  return remainSeconds ? `${minutes}m ${remainSeconds}s` : `${minutes}m`;
}

export function OpsTaskDetailPage({ taskRunId }: { taskRunId: number }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [diagnosticOpened, setDiagnosticOpened] = useState(false);

  const viewQuery = useQuery({
    queryKey: ["ops", "task-run-view", taskRunId],
    queryFn: () => apiRequest<TaskRunViewResponse>(`/api/v1/ops/task-runs/${taskRunId}/view`),
    refetchInterval: (query) => buildRefetchInterval(query.state.data?.run.status),
  });

  const primaryIssueId = viewQuery.data?.primary_issue?.id ?? null;
  const issueQuery = useQuery({
    queryKey: ["ops", "task-run-issue", taskRunId, primaryIssueId],
    queryFn: () => apiRequest<TaskRunIssueDetailResponse>(`/api/v1/ops/task-runs/${taskRunId}/issues/${primaryIssueId}`),
    enabled: diagnosticOpened && primaryIssueId !== null,
  });

  const retryMutation = useMutation({
    mutationFn: () =>
      apiRequest<TaskRunCreateResponse>(`/api/v1/ops/task-runs/${taskRunId}/retry`, {
        method: "POST",
      }),
    onSuccess: async (data) => {
      notifications.show({
        color: "success",
        title: "任务已重新提交",
        message: "系统已经收到新的任务请求。",
      });
      await queryClient.invalidateQueries({ queryKey: ["ops"] });
      await navigate({ to: "/ops/tasks/$taskRunId", params: { taskRunId: String(data.id) } });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () =>
      apiRequest<TaskRunCreateResponse>(`/api/v1/ops/task-runs/${taskRunId}/cancel`, {
        method: "POST",
      }),
    onSuccess: async () => {
      notifications.show({
        color: "success",
        title: "已经请求停止当前任务",
        message: `任务 #${taskRunId}`,
      });
      await queryClient.invalidateQueries({ queryKey: ["ops"] });
    },
  });

  const view = viewQuery.data;
  const headline = view ? buildStatusHeadline(view) : null;
  const nodeColumns: DataTableColumn<TaskRunViewResponse["nodes"][number]>[] = [
    {
      key: "sequence",
      header: "序号",
      width: "8%",
      render: (item) => <OpsTableCellText size="xs">{item.sequence_no}</OpsTableCellText>,
    },
    {
      key: "node",
      header: "执行节点",
      align: "left",
      width: "32%",
      render: (item) => (
        <Stack gap={2}>
          <OpsTableCellText fw={600} size="sm">{item.title}</OpsTableCellText>
          <Text size="xs" c="dimmed">{item.node_key}</Text>
        </Stack>
      ),
    },
    {
      key: "status",
      header: "状态",
      width: "12%",
      render: (item) => <StatusBadge value={item.status} />,
    },
    {
      key: "rows",
      header: "结果",
      align: "left",
      width: "22%",
      render: (item) => (
        <Text size="sm">
          {`读取 ${item.rows_fetched}，保存 ${item.rows_saved}，拒绝 ${item.rows_rejected}`}
        </Text>
      ),
    },
    {
      key: "time",
      header: "时间",
      align: "left",
      width: "18%",
      render: (item) => <Text size="sm">{item.started_at ? formatDateTimeLabel(item.started_at) : "—"}</Text>,
    },
    {
      key: "duration",
      header: "耗时",
      width: "8%",
      render: (item) => <Text size="sm">{formatDuration(item.duration_ms)}</Text>,
    },
  ];

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-start">
        <Text c="dimmed" size="sm">
          当前详情页只读取 TaskRun view API，主页面只展示一处失败原因。
        </Text>
        <Button variant="light" component="a" href="/app/ops/tasks">
          返回任务记录
        </Button>
      </Group>

      {viewQuery.isLoading ? <Loader size="sm" /> : null}
      {viewQuery.error ? (
        <AlertBar tone="error" title="无法读取任务详情">
          {viewQuery.error instanceof Error ? viewQuery.error.message : "未知错误"}
        </AlertBar>
      ) : null}

      {view && headline ? (
        <>
          <SectionCard
            title={view.run.title}
            description="这里先告诉你这次任务现在是什么状态，以及你最常用的处理动作。"
            action={
              <Group gap="xs">
                <Button component="a" href={buildManualTaskHref({ fromTaskRunId: view.run.id })} variant="light">
                  复制参数
                </Button>
                {view.actions.can_retry ? (
                  <Button onClick={() => retryMutation.mutate()} loading={retryMutation.isPending}>
                    重新提交
                  </Button>
                ) : null}
                {view.actions.can_cancel ? (
                  <Button color="warning" variant="light" onClick={() => cancelMutation.mutate()} loading={cancelMutation.isPending}>
                    停止处理
                  </Button>
                ) : null}
              </Group>
            }
          >
            <AlertBar tone={headline.color} title={headline.title}>
              {headline.description}
            </AlertBar>
            <SimpleGrid cols={{ base: 1, sm: 2, xl: view.run.time_scope_label ? 5 : 4 }} spacing="md" verticalSpacing="md">
              <MetricPanel label="当前状态">
                <StatusBadge value={view.run.status} size="lg" />
              </MetricPanel>
              <MetricPanel label="发起方式">
                <Text fw={700} size="xl">{formatTriggerSourceLabel(view.run.trigger_source)}</Text>
              </MetricPanel>
              {view.run.time_scope_label ? (
                <MetricPanel label="处理范围">
                  <Text fw={700} size="xl">{view.run.time_scope_label}</Text>
                </MetricPanel>
              ) : null}
              <MetricPanel label="提交时间">
                <Text ff="monospace" fw={700} size="xl">{formatDateTimeLabel(view.run.requested_at)}</Text>
              </MetricPanel>
              <MetricPanel label="已保存">
                <Text fw={700} size="xl">{view.progress.rows_saved.toLocaleString()}</Text>
              </MetricPanel>
            </SimpleGrid>
          </SectionCard>

          {view.primary_issue ? (
            <SectionCard title="失败原因" description="失败摘要只在这里展示一次；完整技术信息按需打开。">
              <AlertBar tone={view.primary_issue.severity === "warning" ? "warning" : "error"} title={view.primary_issue.title}>
                <Stack gap={8}>
                  <Text size="sm">{view.primary_issue.operator_message || "系统记录到问题，但还没有生成运营摘要。"}</Text>
                  {view.primary_issue.suggested_action ? (
                    <Text size="sm" c="dimmed">{`建议：${view.primary_issue.suggested_action}`}</Text>
                  ) : null}
                  {view.primary_issue.has_technical_detail ? (
                    <Button size="xs" variant="light" onClick={() => setDiagnosticOpened(true)}>
                      查看技术诊断
                    </Button>
                  ) : null}
                  <AlertBarNote>{`发生时间：${formatDateTimeLabel(view.primary_issue.occurred_at)}`}</AlertBarNote>
                </Stack>
              </AlertBar>
            </SectionCard>
          ) : null}

          <Grid gutter="lg">
            <Grid.Col span={{ base: 12, lg: 7 }}>
              <SectionCard title="当前进度" description="这里展示覆盖式快照，不再追加重复日志。">
                <Stack gap="md">
                  <Group justify="space-between" align="end">
                    <Stack gap={2}>
                      <Text c="dimmed" size="sm">处理单元</Text>
                      <Text fw={700} size="xl">
                        {view.progress.unit_done} / {view.progress.unit_total || "—"}
                      </Text>
                    </Stack>
                    <Text fw={700} size="lg" c="var(--mantine-color-brand-6)">
                      {view.progress.progress_percent ?? 0}%
                    </Text>
                  </Group>
                  <Progress value={view.progress.progress_percent ?? 0} radius="md" size="lg" color="brand" />
                  <Text size="sm">{`当前对象：${formatContext(view.progress.current_context)}`}</Text>
                  <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="md">
                    <MetricPanel label="读取">
                      <Text fw={700}>{view.progress.rows_fetched.toLocaleString()}</Text>
                    </MetricPanel>
                    <MetricPanel label="保存">
                      <Text fw={700}>{view.progress.rows_saved.toLocaleString()}</Text>
                    </MetricPanel>
                    <MetricPanel label="拒绝">
                      <Text fw={700}>{view.progress.rows_rejected.toLocaleString()}</Text>
                    </MetricPanel>
                  </SimpleGrid>
                </Stack>
              </SectionCard>
            </Grid.Col>

            <Grid.Col span={{ base: 12, lg: 5 }}>
              <SectionCard title="建议下一步" description="先看建议，再决定是否重提或继续排查。">
                <Text>{buildActionSuggestion(view)}</Text>
              </SectionCard>
            </Grid.Col>
          </Grid>

          <SectionCard
            title="执行过程"
            description={view.nodes_truncated ? `当前展示前 ${view.nodes.length} 个节点，共 ${view.node_total} 个。` : "节点状态来自 task_run_node，不再展示重复错误全文。"}
          >
            <DataTable
              columns={nodeColumns}
              emptyState={<Text c="dimmed" size="sm">暂时还没有执行节点。</Text>}
              getRowKey={(item) => item.id}
              minWidth={820}
              rows={view.nodes}
            />
          </SectionCard>

          <DetailDrawer
            opened={diagnosticOpened}
            onClose={() => setDiagnosticOpened(false)}
            title="技术诊断"
            description="完整技术错误只在这里按需读取和展示。"
            size="lg"
          >
            <Stack gap="md">
              {issueQuery.isLoading ? <Loader size="sm" /> : null}
              {issueQuery.error ? (
                <AlertBar tone="error" title="技术诊断加载失败">
                  {issueQuery.error instanceof Error ? issueQuery.error.message : "未知错误"}
                </AlertBar>
              ) : null}
              {issueQuery.data ? (
                <>
                  <AlertBar tone="error" title={issueQuery.data.title}>
                    <Stack gap={6}>
                      <Text size="sm">{issueQuery.data.operator_message}</Text>
                      {issueQuery.data.suggested_action ? (
                        <Text size="sm" c="dimmed">{`建议：${issueQuery.data.suggested_action}`}</Text>
                      ) : null}
                    </Stack>
                  </AlertBar>
                  <Stack gap={6}>
                    <Group gap="xs">
                      <Badge variant="light">{issueQuery.data.code}</Badge>
                      {issueQuery.data.source_phase ? <Badge variant="light">{issueQuery.data.source_phase}</Badge> : null}
                    </Group>
                    <Text fw={700}>完整技术错误</Text>
                    <Text component="pre" size="xs" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                      {issueQuery.data.technical_message || "无技术详情"}
                    </Text>
                    <Text fw={700}>结构化信息</Text>
                    <Text component="pre" size="xs" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                      {JSON.stringify(issueQuery.data.technical_payload, null, 2)}
                    </Text>
                  </Stack>
                </>
              ) : null}
            </Stack>
          </DetailDrawer>
        </>
      ) : null}
    </Stack>
  );
}
