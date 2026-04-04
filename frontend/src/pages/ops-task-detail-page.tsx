import {
  Alert,
  Badge,
  Button,
  Grid,
  Group,
  Loader,
  Progress,
  ScrollArea,
  SimpleGrid,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useMemo } from "react";

import { apiRequest } from "../shared/api/client";
import type {
  ExecutionDetailResponse,
  ExecutionEventsResponse,
  ScheduleDetailResponse,
  ExecutionStepsResponse,
} from "../shared/api/types";
import { formatDateTimeLabel } from "../shared/date-format";
import {
  formatEventTypeLabel,
  formatRunTypeLabel,
  formatSpecDisplayLabel,
  formatTriggerSourceLabel,
  formatUnitKindLabel,
} from "../shared/ops-display";
import { SectionCard } from "../shared/ui/section-card";
import { StatusBadge } from "../shared/ui/status-badge";

function buildRefetchInterval(status: string | undefined) {
  return status === "queued" || status === "running" || status === "canceling" ? 3000 : false;
}

function sortByTimeDesc<T extends { occurred_at?: string; started_at?: string }>(items: T[]) {
  return [...items].sort((left, right) => {
    const leftTime = new Date(left.occurred_at || left.started_at || 0).getTime();
    const rightTime = new Date(right.occurred_at || right.started_at || 0).getTime();
    return rightTime - leftTime;
  });
}

function formatParamLabel(key: string): string {
  const labelMap: Record<string, string> = {
    start_date: "开始日期",
    end_date: "结束日期",
    trade_date: "处理日期",
    ts_code: "证券代码",
    index_code: "指数代码",
    exchange: "交易所",
    resource: "数据类型",
  };
  return labelMap[key] || key;
}

function formatParamValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "未填写";
  }
  if (Array.isArray(value)) {
    return value.join("、");
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function parseProgressDetails(message: string | null | undefined) {
  const raw = String(message || "").trim();
  if (!raw) {
    return null;
  }
  const ratioMatch = raw.match(/(\d+)\s*\/\s*(\d+)/);
  const kvMatches = [...raw.matchAll(/([a-zA-Z_]+)=([^\s]+)/g)];
  const kv = Object.fromEntries(kvMatches.map((item) => [item[1], item[2]]));
  const cursorValue = kv.trade_date || kv.ts_code || kv.con_code || kv.index_code || kv.code || kv.idx_type || null;
  const cursorLabel = kv.trade_date
    ? `当前日期：${kv.trade_date}`
    : kv.ts_code
      ? `当前代码：${kv.ts_code}`
      : kv.con_code
        ? `当前板块：${kv.con_code}`
        : kv.index_code
          ? `当前指数：${kv.index_code}`
          : kv.code
            ? `当前代码：${kv.code}`
            : kv.idx_type
              ? `当前类型：${kv.idx_type}`
              : null;
  const fetched = kv.fetched ? Number(kv.fetched) : null;
  const written = kv.written ? Number(kv.written) : null;
  return {
    raw,
    current: ratioMatch ? Number(ratioMatch[1]) : null,
    total: ratioMatch ? Number(ratioMatch[2]) : null,
    cursorLabel,
    fetched: Number.isFinite(fetched) ? fetched : null,
    written: Number.isFinite(written) ? written : null,
  };
}

function buildScopeItems(params: Record<string, unknown>) {
  const preferredOrder = ["trade_date", "start_date", "end_date", "ts_code", "index_code", "exchange"];
  const keys = preferredOrder.filter((key) => key in params);
  const extras = Object.keys(params).filter((key) => !preferredOrder.includes(key));
  const orderedKeys = [...keys, ...extras];
  if (!orderedKeys.length) {
    return [
      {
        label: "处理范围",
        value: "这次任务没有额外参数，系统会按默认方式处理。",
      },
    ];
  }
  return orderedKeys.map((key) => ({
    label: formatParamLabel(key),
    value: formatParamValue(params[key]),
  }));
}

function buildStatusHeadline(detail: ExecutionDetailResponse) {
  if (detail.status === "queued") {
    return {
      title: "任务已经提交",
      description: "系统已经收到你的请求，正在准备开始处理。页面会自动刷新。",
      color: "blue" as const,
    };
  }
  if (detail.status === "running") {
    return {
      title: "任务正在处理中",
      description: "系统正在处理你这次同步请求。你可以留在这里等待，也可以稍后回来查看结果。",
      color: "blue" as const,
    };
  }
  if (detail.status === "canceling") {
    return {
      title: "任务正在停止中",
      description: detail.progress_message || "系统已收到停止请求，正在结束当前处理。",
      color: "violet" as const,
    };
  }
  if (detail.status === "success") {
    return {
      title: "任务已经处理完成",
      description: detail.summary_message || "这次处理已经顺利完成。",
      color: "teal" as const,
    };
  }
  if (detail.status === "failed") {
    return {
      title: "任务处理失败",
      description: detail.summary_message || detail.error_message || "请先查看问题摘要，再决定是否重新提交。",
      color: "red" as const,
    };
  }
  if (detail.status === "canceled") {
    return {
      title: "任务已经停止",
      description: "这次处理已经被停止。如果还需要继续，可以重新提交。",
      color: "yellow" as const,
    };
  }
  return {
    title: "任务已结束",
    description: detail.summary_message || "可以查看下方结果和处理记录。",
    color: "gray" as const,
  };
}

function buildActionSuggestion(detail: ExecutionDetailResponse) {
  if (detail.status === "queued") {
    return "系统正在安排开始处理。现在不用重复提交，等待几秒后页面会自动刷新。";
  }
  if (detail.status === "running") {
    return "先观察当前进展。如果长时间没有变化，再查看实时处理记录定位卡点。";
  }
  if (detail.status === "canceling") {
    return "系统正在按停止请求收尾。通常会在当前处理单元结束后更新为“已取消”。";
  }
  if (detail.status === "success") {
    return "这次处理已经完成。如果还要处理别的日期范围，可以返回手动同步页继续发起。";
  }
  if (detail.status === "failed") {
    return "先看问题摘要和最近更新，再决定是重新提交，还是复制原参数后调整再发起。";
  }
  if (detail.status === "canceled") {
    return "如果还需要继续处理，建议复制原参数重新发起，避免遗漏处理范围。";
  }
  return "可以继续查看详细过程，确认这次任务的实际结果。";
}

function buildLatestUpdate(
  detail: ExecutionDetailResponse,
  events: ExecutionEventsResponse["items"],
  steps: ExecutionStepsResponse["items"],
) {
  if (detail.status === "success" || detail.status === "failed" || detail.status === "canceled" || detail.status === "partial_success") {
    return {
      time: formatDateTimeLabel(detail.ended_at || detail.last_progress_at || detail.requested_at),
      label: "任务结果",
      message: detail.summary_message || detail.error_message || "任务已结束。",
    };
  }

  if (detail.last_progress_at || detail.progress_message) {
    const parsed = parseProgressDetails(detail.progress_message);
    return {
      time: detail.last_progress_at ? formatDateTimeLabel(detail.last_progress_at) : "刚刚",
      label: "最近进展",
      message: parsed?.raw || detail.progress_message || "系统刚刚写入了新的处理进展。",
    };
  }

  const latestEvent = sortByTimeDesc(events)[0];
  if (latestEvent) {
    return {
      time: formatDateTimeLabel(latestEvent.occurred_at),
      label: formatEventTypeLabel(latestEvent.event_type),
      message: latestEvent.message || "系统已经记录了新的处理进展。",
    };
  }

  const latestStep = [...steps].sort((left, right) => right.sequence_no - left.sequence_no)[0];
  if (latestStep) {
    return {
      time: latestStep.started_at ? formatDateTimeLabel(latestStep.started_at) : "刚刚",
      label: "当前步骤",
      message: latestStep.message || `${latestStep.display_name} ${latestStep.status === "running" ? "正在执行" : "已经更新状态"}`,
    };
  }

  return {
    time: formatDateTimeLabel(detail.requested_at),
    label: "任务创建",
    message: detail.status === "queued" ? "系统已经收到请求，正在准备开始。" : "系统正在等待新的处理进展。",
  };
}

function extractProgressSnapshot(events: ExecutionEventsResponse["items"]) {
  const progressEvent = [...events]
    .reverse()
    .find((item) => item.event_type === "step_progress" && (item.payload_json?.progress_message || item.message));
  if (!progressEvent) {
    return null;
  }

  const progressMessage = String(progressEvent.payload_json?.progress_message || progressEvent.message || "");
  const match = progressMessage.match(/(\d+)\s*\/\s*(\d+)/);
  if (!match) {
    return null;
  }

  const current = Number(match[1]);
  const total = Number(match[2]);
  if (!Number.isFinite(current) || !Number.isFinite(total) || total <= 0) {
    return null;
  }

  return {
    current,
    total,
    percent: Math.max(0, Math.min(100, Math.round((current / total) * 100))),
    message: progressMessage,
    occurredAt: progressEvent.occurred_at,
  };
}

function buildStructuredProgressSnapshot(
  detail: ExecutionDetailResponse,
  events: ExecutionEventsResponse["items"],
) {
  const detailProgress = parseProgressDetails(detail.progress_message);
  if (
    detail.progress_current !== null &&
    detail.progress_current !== undefined &&
    detail.progress_total !== null &&
    detail.progress_total !== undefined &&
    detail.progress_total > 0
  ) {
    const current = detail.progress_current;
    const total = detail.progress_total;
    return {
      current,
      total,
      percent: detail.progress_percent ?? Math.round((current / total) * 100),
      message: detailProgress?.raw || detail.progress_message || "系统正在持续更新当前进展。",
      cursorLabel: detailProgress?.cursorLabel || null,
      fetched: detailProgress?.fetched ?? null,
      written: detailProgress?.written ?? null,
      occurredAt: detail.last_progress_at,
    };
  }
  const fromEvent = extractProgressSnapshot(events);
  if (fromEvent) {
    const parsed = parseProgressDetails(fromEvent.message);
    return {
      ...fromEvent,
      cursorLabel: parsed?.cursorLabel || null,
      fetched: parsed?.fetched ?? null,
      written: parsed?.written ?? null,
    };
  }
  return null;
}

function buildLiveResult(detail: ExecutionDetailResponse) {
  if (detail.rows_fetched > 0 || detail.rows_written > 0) {
    return {
      value: `${detail.rows_fetched}/${detail.rows_written}`,
      hint: "读取数量 / 写入数量",
    };
  }

  if (detail.status === "queued") {
    return {
      value: "等待开始",
      hint: "任务已经提交，但还没进入实际处理阶段。",
    };
  }

  if (detail.status === "running") {
    return {
      value: "处理中",
      hint: "任务正在运行，进展写回后会自动显示。",
    };
  }
  if (detail.status === "canceling") {
    return {
      value: "停止中",
      hint: "系统已收到停止请求，正在结束当前处理单元。",
    };
  }

  return {
    value: "暂无结果",
    hint: detail.status === "success" ? "任务执行完成，但没有可汇总的读取/写入数字。" : "这次任务还没有留下可汇总的处理结果。",
  };
}

export function OpsTaskDetailPage({ executionId }: { executionId: number }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const detailQuery = useQuery({
    queryKey: ["ops", "execution", executionId],
    queryFn: () => apiRequest<ExecutionDetailResponse>(`/api/v1/ops/executions/${executionId}`),
    refetchInterval: (query) => buildRefetchInterval(query.state.data?.status),
  });

  const activeStatus = detailQuery.data?.status;

  const stepsQuery = useQuery({
    queryKey: ["ops", "execution", executionId, "steps"],
    queryFn: () => apiRequest<ExecutionStepsResponse>(`/api/v1/ops/executions/${executionId}/steps`),
    refetchInterval: buildRefetchInterval(activeStatus),
  });

  const eventsQuery = useQuery({
    queryKey: ["ops", "execution", executionId, "events"],
    queryFn: () => apiRequest<ExecutionEventsResponse>(`/api/v1/ops/executions/${executionId}/events`),
    refetchInterval: buildRefetchInterval(activeStatus),
  });

  const scheduleQuery = useQuery({
    queryKey: ["ops", "schedule", detailQuery.data?.schedule_id],
    queryFn: () => apiRequest<ScheduleDetailResponse>(`/api/v1/ops/schedules/${detailQuery.data?.schedule_id}`),
    enabled: Boolean(detailQuery.data?.schedule_id),
  });

  const retryMutation = useMutation({
    mutationFn: () =>
      apiRequest<ExecutionDetailResponse>(`/api/v1/ops/executions/${executionId}/retry`, {
        method: "POST",
      }),
    onSuccess: async (data) => {
      notifications.show({
        color: "green",
        title: "任务已重新提交",
        message: "系统已经收到新的任务请求。",
      });
      await queryClient.invalidateQueries({ queryKey: ["ops"] });
      await navigate({ to: "/ops/tasks/$executionId", params: { executionId: String(data.id) } });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () =>
      apiRequest<ExecutionDetailResponse>(`/api/v1/ops/executions/${executionId}/cancel`, {
        method: "POST",
      }),
    onSuccess: async () => {
      notifications.show({
        color: "green",
        title: "已经请求停止当前任务",
        message: `任务 #${executionId}`,
      });
      await queryClient.invalidateQueries({ queryKey: ["ops", "execution", executionId] });
      await queryClient.invalidateQueries({ queryKey: ["ops", "executions"] });
    },
  });

  const detail = detailQuery.data;
  const steps = stepsQuery.data?.items || [];
  const events = eventsQuery.data?.items || [];
  const progressSnapshot = detail ? buildStructuredProgressSnapshot(detail, events) : null;
  const liveResult = detail ? buildLiveResult(detail) : null;
  const latestUpdate = detail ? buildLatestUpdate(detail, events, steps) : null;
  const userConfiguredParams = useMemo(
    () => (scheduleQuery.data?.params_json || detail?.params_json || {}) as Record<string, unknown>,
    [detail?.params_json, scheduleQuery.data?.params_json],
  );
  const finalExecutionParams = useMemo(
    () => (detail?.params_json || {}) as Record<string, unknown>,
    [detail?.params_json],
  );

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-start">
        <Stack gap={4}>
          <Text c="dimmed" size="sm">
            先看当前状态和进展，再决定是继续等待、重新提交，还是展开技术细节排查。
          </Text>
        </Stack>
        <Button variant="light" component="a" href="/app/ops/tasks">
          返回任务记录
        </Button>
      </Group>

      {(detailQuery.isLoading || stepsQuery.isLoading || eventsQuery.isLoading) ? <Loader size="sm" /> : null}
      {detailQuery.error ? (
        <Alert color="red" title="无法读取任务详情">
          {detailQuery.error instanceof Error ? detailQuery.error.message : "未知错误"}
        </Alert>
      ) : null}

      {detail ? (
        <>
          <SectionCard
            title={formatSpecDisplayLabel(detail.spec_key, detail.spec_display_name)}
            description="这里先告诉你这次任务现在是什么状态，以及你最常用的处理动作。"
            action={
              <Group gap="xs">
                <Button component="a" href={`/app/ops/manual-sync?from_execution_id=${detail.id}`} variant="light">
                  复制参数
                </Button>
                {detail.status === "failed" ? (
                  <Button onClick={() => retryMutation.mutate()} loading={retryMutation.isPending}>
                    重新提交
                  </Button>
                ) : null}
                {(detail.status === "queued" || detail.status === "running") ? (
                  <Button color="orange" variant="light" onClick={() => cancelMutation.mutate()} loading={cancelMutation.isPending}>
                    停止处理
                  </Button>
                ) : null}
              </Group>
            }
          >
            <Alert color={buildStatusHeadline(detail).color} title={buildStatusHeadline(detail).title}>
              {buildStatusHeadline(detail).description}
            </Alert>
            <SimpleGrid cols={{ base: 1, sm: 2, xl: 4 }} spacing="md" verticalSpacing="md">
              <Stack
                gap={8}
                p="md"
                bg="var(--mantine-color-gray-0)"
                bd="1px solid var(--mantine-color-gray-2)"
                style={{ borderRadius: "var(--mantine-radius-lg)", minHeight: 132, justifyContent: "space-between" }}
              >
                <Text c="dimmed" size="xl" fw={600}>当前状态</Text>
                <Group justify="flex-end" align="flex-end">
                  <StatusBadge value={detail.status} size="lg" />
                </Group>
              </Stack>
              <Stack
                gap={8}
                p="md"
                bg="var(--mantine-color-gray-0)"
                bd="1px solid var(--mantine-color-gray-2)"
                style={{ borderRadius: "var(--mantine-radius-lg)", minHeight: 132, justifyContent: "space-between" }}
              >
                <Text c="dimmed" size="xl" fw={600}>发起方式</Text>
                <Group justify="flex-end" align="flex-end">
                  <Text fw={700} size="xl">{formatTriggerSourceLabel(detail.trigger_source)}</Text>
                </Group>
              </Stack>
              <Stack
                gap={8}
                p="md"
                bg="var(--mantine-color-gray-0)"
                bd="1px solid var(--mantine-color-gray-2)"
                style={{ borderRadius: "var(--mantine-radius-lg)", minHeight: 132, justifyContent: "space-between" }}
              >
                <Text c="dimmed" size="xl" fw={600}>提交时间</Text>
                <Group justify="flex-end" align="flex-end">
                  <Text ff="monospace" fw={700} size="xl">{formatDateTimeLabel(detail.requested_at)}</Text>
                </Group>
              </Stack>
              <Stack
                gap={8}
                p="md"
                bg="var(--mantine-color-gray-0)"
                bd="1px solid var(--mantine-color-gray-2)"
                style={{ borderRadius: "var(--mantine-radius-lg)", minHeight: 132, justifyContent: "space-between" }}
              >
                <Text c="dimmed" size="xl" fw={600}>当前结果</Text>
                <Group justify="flex-end" align="flex-end">
                  <Text fw={700} size="xl">{liveResult?.value || "暂无结果"}</Text>
                </Group>
              </Stack>
            </SimpleGrid>
          </SectionCard>

          <Grid gutter="lg">
            <Grid.Col span={{ base: 12, lg: 7 }}>
              <SectionCard title="当前进展" description="这里只保留最关键的进展信息，帮助你快速判断任务是不是在正常推进。">
                <Stack gap="md">
                  {latestUpdate ? (
                    <Alert color={detail.status === "failed" ? "red" : "blue"} title={`最近更新：${latestUpdate.label}`}>
                      <Text size="sm">{latestUpdate.message}</Text>
                      <Text size="xs" c="dimmed" mt={6}>{latestUpdate.time}</Text>
                    </Alert>
                  ) : null}
                  {progressSnapshot ? (
                    <Stack
                      gap={8}
                      p="md"
                      bg="var(--mantine-color-gray-0)"
                      bd="1px solid var(--mantine-color-gray-2)"
                      style={{ borderRadius: "var(--mantine-radius-lg)" }}
                    >
                      <Group justify="space-between" align="end">
                        <Stack gap={2}>
                          <Text c="dimmed" size="sm">阶段性进度</Text>
                          <Text fw={700} size="xl">{progressSnapshot.current} / {progressSnapshot.total}</Text>
                        </Stack>
                        <Text fw={700} size="lg" c="var(--mantine-color-brand-6)">{progressSnapshot.percent}%</Text>
                      </Group>
                      <Progress value={progressSnapshot.percent} radius="xl" size="lg" />
                      <Text size="sm">{progressSnapshot.message}</Text>
                      {progressSnapshot.cursorLabel ? (
                        <Text size="sm">{progressSnapshot.cursorLabel}</Text>
                      ) : null}
                      {(progressSnapshot.fetched !== null || progressSnapshot.written !== null) ? (
                        <Text size="sm">
                          当前接口结果：读取 {progressSnapshot.fetched ?? 0} 条，写入 {progressSnapshot.written ?? 0} 条
                        </Text>
                      ) : null}
                      <Text size="sm" c="dimmed">
                        最近一次进度更新：{formatDateTimeLabel(progressSnapshot.occurredAt)}
                      </Text>
                    </Stack>
                  ) : (
                    (detail.status === "queued" || detail.status === "running" || detail.status === "canceling") ? (
                      <Alert color="blue" title="处理中，等待进展写回">
                        任务正在执行。进度与当前处理对象写回后，这里会自动更新。
                      </Alert>
                    ) : (
                      <Alert color={detail.status === "failed" ? "red" : "teal"} title="任务已结束">
                        {detail.summary_message || detail.error_message || "任务已结束。"}
                      </Alert>
                    )
                  )}
                  <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
                    <Stack
                      gap={4}
                      p="md"
                      bg="var(--mantine-color-gray-0)"
                      bd="1px solid var(--mantine-color-gray-2)"
                      style={{ borderRadius: "var(--mantine-radius-lg)" }}
                    >
                      <Text c="dimmed" size="sm">当前结果</Text>
                      <Text fw={700}>{liveResult?.value || "暂无结果"}</Text>
                      <Text size="sm" c="dimmed">{liveResult?.hint}</Text>
                    </Stack>
                    <Stack
                      gap={4}
                      p="md"
                      bg="var(--mantine-color-gray-0)"
                      bd="1px solid var(--mantine-color-gray-2)"
                      style={{ borderRadius: "var(--mantine-radius-lg)" }}
                    >
                      <Text c="dimmed" size="sm">最近更新</Text>
                      <Text fw={700}>{latestUpdate?.time || "刚刚"}</Text>
                      <Text size="sm" c="dimmed">{latestUpdate?.message || "系统正在等待新的处理进展。"}</Text>
                    </Stack>
                  </SimpleGrid>
                </Stack>
              </SectionCard>
            </Grid.Col>

            <Grid.Col span={{ base: 12, lg: 5 }}>
              <Stack gap="md">
                <SectionCard title="本次处理范围" description="这里展示这次任务实际会处理哪些日期、代码或交易所。">
                  <Grid gutter="md">
                    <Grid.Col span={{ base: 12, md: 6 }}>
                      <Stack gap="sm">
                        <Text fw={700} size="sm">用户配置</Text>
                        {buildScopeItems(userConfiguredParams).map((item) => (
                          <Stack gap={2} key={`user-${item.label}`}>
                            <Text c="dimmed" size="sm">{item.label}</Text>
                            <Text>{item.value}</Text>
                          </Stack>
                        ))}
                      </Stack>
                    </Grid.Col>
                    <Grid.Col span={{ base: 12, md: 6 }}>
                      <Stack gap="sm">
                        <Text fw={700} size="sm">最终执行参数</Text>
                        {buildScopeItems(finalExecutionParams).map((item) => (
                          <Stack gap={2} key={`final-${item.label}`}>
                            <Text c="dimmed" size="sm">{item.label}</Text>
                            <Text>{item.value}</Text>
                          </Stack>
                        ))}
                      </Stack>
                    </Grid.Col>
                  </Grid>
                </SectionCard>

                <SectionCard title="建议下一步" description="不要先钻进原始日志。先看这里给出的下一步建议，再决定要不要继续排查。">
                  <Stack gap="sm">
                    <Text>{buildActionSuggestion(detail)}</Text>
                    {detail.status === "failed" ? (
                      <Alert color="red" title="问题摘要">
                        {detail.summary_message || detail.error_message || "系统已经记录到失败，但还没有生成更具体的摘要。你可以查看实时处理记录继续排查。"}
                      </Alert>
                    ) : null}
                  </Stack>
                </SectionCard>
              </Stack>
            </Grid.Col>
          </Grid>

          <SectionCard
            title="实时处理记录"
            description="系统更新和步骤明细会直接显示在这里，方便你实时判断处理情况。"
          >
            <Stack gap="md">
              <Alert color={activeStatus === "queued" || activeStatus === "running" || activeStatus === "canceling" ? "blue" : "gray"} title="实时处理记录">
                {activeStatus === "queued" || activeStatus === "running" || activeStatus === "canceling"
                  ? "如果这里内容还不多，通常只是任务刚开始。页面会自动刷新，不需要手动反复点。"
                  : "这里保留了完整的过程记录，方便复盘。"}
              </Alert>
              <Text fw={600}>系统更新</Text>
              <ScrollArea h={260} type="auto" offsetScrollbars>
                {events.length ? (
                  <Table highlightOnHover striped>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>时间</Table.Th>
                        <Table.Th>更新内容</Table.Th>
                        <Table.Th>说明</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {sortByTimeDesc(events).map((item) => (
                        <Table.Tr key={item.id}>
                          <Table.Td>{formatDateTimeLabel(item.occurred_at)}</Table.Td>
                          <Table.Td>
                            <Group gap="xs">
                              <Badge variant="light">{formatEventTypeLabel(item.event_type)}</Badge>
                              <StatusBadge value={item.level} />
                            </Group>
                          </Table.Td>
                          <Table.Td>{item.message || "系统记录了一次新的处理更新。"}</Table.Td>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                ) : (
                  <Text c="dimmed" size="sm">暂时还没有更细的系统更新记录。</Text>
                )}
              </ScrollArea>

              <Text fw={600}>步骤明细</Text>
              <ScrollArea h={260} type="auto" offsetScrollbars>
                {steps.length ? (
                  <Table highlightOnHover striped>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>步骤名称</Table.Th>
                        <Table.Th>当前状态</Table.Th>
                        <Table.Th>处理对象</Table.Th>
                        <Table.Th>最近说明</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {steps.map((item) => (
                        <Table.Tr key={item.id}>
                          <Table.Td>{item.display_name}</Table.Td>
                          <Table.Td><StatusBadge value={item.status} /></Table.Td>
                          <Table.Td>
                            {item.unit_kind
                              ? `${formatUnitKindLabel(item.unit_kind)}：${item.unit_value || "未提供"}`
                              : "当前没有拆到更细的处理对象"}
                          </Table.Td>
                          <Table.Td>{item.message || "系统还没有写入更细的步骤说明。"}</Table.Td>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                ) : (
                  <Text c="dimmed" size="sm">暂时还没有步骤明细。通常说明任务刚开始，或者这类任务本身不会拆成更多步骤。</Text>
                )}
              </ScrollArea>
            </Stack>
          </SectionCard>
        </>
      ) : null}
    </Stack>
  );
}
