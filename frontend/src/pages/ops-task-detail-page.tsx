import {
  Alert,
  Anchor,
  Badge,
  Button,
  Grid,
  Group,
  Loader,
  Select,
  Stack,
  Table,
  Tabs,
  Text,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useMemo, useState } from "react";

import { apiRequest } from "../shared/api/client";
import type {
  ExecutionDetailResponse,
  ExecutionEventsResponse,
  ExecutionLogsResponse,
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
import { PageHeader } from "../shared/ui/page-header";
import { SectionCard } from "../shared/ui/section-card";
import { StatusBadge } from "../shared/ui/status-badge";


function buildIssueSummary(detail: ExecutionDetailResponse) {
  if (detail.status === "success") {
    return {
      title: "这项任务已经处理完成",
      description: detail.summary_message || "当前没有发现需要继续处理的问题。",
      color: "teal" as const,
    };
  }
  if (detail.status === "queued") {
    return {
      title: "这项任务还在等待处理",
      description: "你可以直接点击“立即开始”，不需要再去别的页面。",
      color: "blue" as const,
    };
  }
  if (detail.status === "running") {
    return {
      title: "这项任务正在处理",
      description: "如果你怀疑卡住了，可以先看步骤进度和底层日志，再决定要不要停止。",
      color: "blue" as const,
    };
  }
  if (detail.status === "failed") {
    return {
      title: "这项任务执行失败",
      description: detail.summary_message || detail.error_message || "请先看下方的错误详情和底层日志，再决定是否重新执行。",
      color: "red" as const,
    };
  }
  if (detail.status === "canceled") {
    return {
      title: "这项任务已经停止",
      description: "如果还需要继续处理，可以重新执行，或者复制参数后调整再发起。",
      color: "yellow" as const,
    };
  }
  return {
    title: "这项任务已经结束",
    description: detail.summary_message || "可以查看下方过程记录了解更多细节。",
    color: "gray" as const,
  };
}

export function OpsTaskDetailPage({ executionId }: { executionId: number }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [eventLevel, setEventLevel] = useState<string | null>(null);
  const [logStatus, setLogStatus] = useState<string | null>(null);

  const detailQuery = useQuery({
    queryKey: ["ops", "execution", executionId],
    queryFn: () => apiRequest<ExecutionDetailResponse>(`/api/v1/ops/executions/${executionId}`),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? 3000 : false;
    },
  });

  const stepsQuery = useQuery({
    queryKey: ["ops", "execution", executionId, "steps"],
    queryFn: () => apiRequest<ExecutionStepsResponse>(`/api/v1/ops/executions/${executionId}/steps`),
  });

  const eventsQuery = useQuery({
    queryKey: ["ops", "execution", executionId, "events"],
    queryFn: () => apiRequest<ExecutionEventsResponse>(`/api/v1/ops/executions/${executionId}/events`),
  });

  const logsQuery = useQuery({
    queryKey: ["ops", "execution", executionId, "logs"],
    queryFn: () => apiRequest<ExecutionLogsResponse>(`/api/v1/ops/executions/${executionId}/logs`),
  });

  const retryNowMutation = useMutation({
    mutationFn: () =>
      apiRequest<ExecutionDetailResponse>(`/api/v1/ops/executions/${executionId}/retry-now`, {
        method: "POST",
      }),
    onSuccess: async (data) => {
      notifications.show({
        color: "green",
        title: "任务已经重新开始",
        message: `${formatSpecDisplayLabel(data.spec_key, data.spec_display_name)} #${data.id}`,
      });
      await queryClient.invalidateQueries({ queryKey: ["ops"] });
      await navigate({ to: "/ops/tasks/$executionId", params: { executionId: String(data.id) } });
    },
  });

  const runNowMutation = useMutation({
    mutationFn: () =>
      apiRequest<ExecutionDetailResponse>(`/api/v1/ops/executions/${executionId}/run-now`, {
        method: "POST",
      }),
    onSuccess: async (data) => {
      notifications.show({
        color: "green",
        title: "任务已经开始处理",
        message: `${formatSpecDisplayLabel(data.spec_key, data.spec_display_name)} #${data.id}`,
      });
      await queryClient.invalidateQueries({ queryKey: ["ops"] });
      await queryClient.invalidateQueries({ queryKey: ["ops", "execution", executionId] });
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
        title: "已请求停止当前任务",
        message: `任务 #${executionId}`,
      });
      await queryClient.invalidateQueries({ queryKey: ["ops", "execution", executionId] });
      await queryClient.invalidateQueries({ queryKey: ["ops", "executions"] });
    },
  });

  const filteredEvents = useMemo(() => {
    const items = eventsQuery.data?.items || [];
    return eventLevel ? items.filter((item) => item.level.toLowerCase() === eventLevel) : items;
  }, [eventLevel, eventsQuery.data?.items]);

  const filteredLogs = useMemo(() => {
    const items = logsQuery.data?.items || [];
    return logStatus ? items.filter((item) => item.status.toLowerCase() === logStatus) : items;
  }, [logStatus, logsQuery.data?.items]);

  const detail = detailQuery.data;
  const issueSummary = detail ? buildIssueSummary(detail) : null;

  return (
    <Stack gap="lg">
      <PageHeader
        title="任务详情"
        description="先看这项任务现在是什么状态，再决定是继续等待、重新执行，还是复制参数重新发起。"
        action={
          <Button variant="light" component="a" href="/app/ops/tasks">
            返回任务记录
          </Button>
        }
      />

      {(detailQuery.isLoading || stepsQuery.isLoading || eventsQuery.isLoading || logsQuery.isLoading) ? <Loader size="sm" /> : null}
      {detailQuery.error ? (
        <Alert color="red" title="无法读取任务详情">
          {detailQuery.error instanceof Error ? detailQuery.error.message : "未知错误"}
        </Alert>
      ) : null}

      {detail ? (
        <>
          {issueSummary ? (
            <Alert color={issueSummary.color} title={issueSummary.title}>
              {issueSummary.description}
            </Alert>
          ) : null}

          <SectionCard
            title={formatSpecDisplayLabel(detail.spec_key, detail.spec_display_name)}
            description="这里展示这项任务的基本信息和你现在最常用的几个处理动作。"
            action={
              <Group gap="xs">
                <Button component="a" href={`/app/ops/manual-sync?from_execution_id=${detail.id}`} variant="light">
                  复制参数
                </Button>
                {detail.status === "failed" ? (
                  <Button onClick={() => retryNowMutation.mutate()} loading={retryNowMutation.isPending}>
                    重新执行
                  </Button>
                ) : null}
                {detail.status === "queued" ? (
                  <Button onClick={() => runNowMutation.mutate()} loading={runNowMutation.isPending}>
                    立即开始
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
            <Grid>
              <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
                <Stack gap={4}>
                  <Text c="dimmed" size="sm">当前状态</Text>
                  <StatusBadge value={detail.status} />
                </Stack>
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
                <Stack gap={4}>
                  <Text c="dimmed" size="sm">发起方式</Text>
                  <Text>{formatTriggerSourceLabel(detail.trigger_source)}</Text>
                </Stack>
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
                <Stack gap={4}>
                  <Text c="dimmed" size="sm">提交时间</Text>
                  <Text>{formatDateTimeLabel(detail.requested_at)}</Text>
                </Stack>
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
                <Stack gap={4}>
                  <Text c="dimmed" size="sm">处理结果</Text>
                  <Text>{detail.rows_fetched}/{detail.rows_written}</Text>
                </Stack>
              </Grid.Col>
            </Grid>
            <Stack gap={4}>
              <Text c="dimmed" size="sm">结果摘要</Text>
              <Text>{detail.summary_message || "暂无结果摘要"}</Text>
            </Stack>
            <Stack gap={4}>
              <Text c="dimmed" size="sm">执行参数</Text>
              <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(detail.params_json || {}, null, 2)}</pre>
            </Stack>
          </SectionCard>

          <Tabs defaultValue="steps">
            <Tabs.List>
              <Tabs.Tab value="steps">处理过程</Tabs.Tab>
              <Tabs.Tab value="events">事件记录</Tabs.Tab>
              <Tabs.Tab value="logs">底层日志</Tabs.Tab>
            </Tabs.List>

            <Tabs.Panel value="steps" pt="md">
              <SectionCard title="处理过程" description="先看每一步做到哪儿了，再决定是否需要继续排查。">
                <Table highlightOnHover striped>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>步骤</Table.Th>
                      <Table.Th>执行单元</Table.Th>
                      <Table.Th>当前状态</Table.Th>
                      <Table.Th>处理结果</Table.Th>
                      <Table.Th>说明</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {(stepsQuery.data?.items || []).map((item) => (
                      <Table.Tr key={item.id}>
                        <Table.Td>{item.display_name}</Table.Td>
                        <Table.Td>{item.unit_kind ? `${formatUnitKindLabel(item.unit_kind)}：${item.unit_value || "—"}` : "—"}</Table.Td>
                        <Table.Td><StatusBadge value={item.status} /></Table.Td>
                        <Table.Td>{item.rows_fetched}/{item.rows_written}</Table.Td>
                        <Table.Td>{item.message || "—"}</Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </SectionCard>
            </Tabs.Panel>

            <Tabs.Panel value="events" pt="md">
              <SectionCard
                title="事件记录"
                description="这里保留结构化事件，方便判断任务是在哪个阶段开始出问题的。"
                action={
                  <Select
                    clearable
                    placeholder="筛选事件级别"
                    data={[
                      { value: "info", label: "提示" },
                      { value: "warning", label: "警告" },
                      { value: "error", label: "错误" },
                    ]}
                    value={eventLevel}
                    onChange={setEventLevel}
                    w={180}
                  />
                }
              >
                <Table highlightOnHover striped>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>时间</Table.Th>
                      <Table.Th>事件</Table.Th>
                      <Table.Th>说明</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {filteredEvents.map((item) => (
                      <Table.Tr key={item.id}>
                        <Table.Td>{formatDateTimeLabel(item.occurred_at)}</Table.Td>
                        <Table.Td>
                          <Group gap="xs">
                            <Badge variant="light">{formatEventTypeLabel(item.event_type)}</Badge>
                            <StatusBadge value={item.level} />
                          </Group>
                        </Table.Td>
                        <Table.Td>{item.message || JSON.stringify(item.payload_json || {})}</Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </SectionCard>
            </Tabs.Panel>

            <Tabs.Panel value="logs" pt="md">
              <SectionCard
                title="底层日志"
                description="当任务失败原因还不清楚时，可以在这里查看底层同步日志。"
                action={
                  <Select
                    clearable
                    placeholder="筛选日志状态"
                    data={[
                      { value: "success", label: "执行成功" },
                      { value: "failed", label: "执行失败" },
                    ]}
                    value={logStatus}
                    onChange={setLogStatus}
                    w={180}
                  />
                }
              >
                <Table highlightOnHover striped>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>开始时间</Table.Th>
                      <Table.Th>底层任务</Table.Th>
                      <Table.Th>运行方式</Table.Th>
                      <Table.Th>状态</Table.Th>
                      <Table.Th>说明</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {filteredLogs.map((item) => (
                      <Table.Tr key={item.id}>
                        <Table.Td>{formatDateTimeLabel(item.started_at)}</Table.Td>
                        <Table.Td>{item.job_name}</Table.Td>
                        <Table.Td>{formatRunTypeLabel(item.run_type)}</Table.Td>
                        <Table.Td><StatusBadge value={item.status} /></Table.Td>
                        <Table.Td>{item.message || "—"}</Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </SectionCard>
            </Tabs.Panel>
          </Tabs>
        </>
      ) : null}
    </Stack>
  );
}
