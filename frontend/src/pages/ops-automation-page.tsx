import {
  Accordion,
  Alert,
  Anchor,
  Badge,
  Button,
  Drawer,
  Grid,
  Group,
  JsonInput,
  Loader,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useDisclosure } from "@mantine/hooks";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { apiRequest } from "../shared/api/client";
import type {
  OpsCatalogResponse,
  ScheduleDetailResponse,
  ScheduleListResponse,
  SchedulePreviewResponse,
  ScheduleRevisionListResponse,
} from "../shared/api/types";
import { formatDateTimeLabel } from "../shared/date-format";
import {
  formatRevisionActionLabel,
  formatScheduleTypeLabel,
  formatSpecDisplayLabel,
  formatTimezoneLabel,
} from "../shared/ops-display";
import { usePersistentState } from "../shared/hooks/use-persistent-state";
import { ActionSummaryCard } from "../shared/ui/action-summary-card";
import { EmptyState } from "../shared/ui/empty-state";
import { PageHeader } from "../shared/ui/page-header";
import { SectionCard } from "../shared/ui/section-card";
import { StatCard } from "../shared/ui/stat-card";
import { StatusBadge } from "../shared/ui/status-badge";


const emptyForm = {
  id: null as number | null,
  spec_type: "job",
  spec_key: "",
  display_name: "",
  schedule_type: "once",
  cron_expr: "",
  timezone: "Asia/Shanghai",
  calendar_policy: "",
  next_run_at: "",
  params_json: "{}",
  retry_policy_json: "{}",
  concurrency_policy_json: "{}",
};

function parseJsonOrThrow(label: string, raw: string) {
  const normalized = raw.trim() || "{}";
  try {
    return JSON.parse(normalized);
  } catch {
    throw new Error(`${label} 格式不正确，请检查大括号、引号和逗号。`);
  }
}

export function OpsAutomationPage() {
  const queryClient = useQueryClient();
  const [opened, { open, close }] = useDisclosure(false);
  const [selectedScheduleId, setSelectedScheduleId] = usePersistentState<number | null>(
    "goldenshare.frontend.ops.automation.selected-id",
    null,
  );
  const [form, setForm] = usePersistentState("goldenshare.frontend.ops.automation.form", emptyForm);
  const [lastAction, setLastAction] = useState<ScheduleDetailResponse | null>(null);

  const catalogQuery = useQuery({
    queryKey: ["ops", "catalog"],
    queryFn: () => apiRequest<OpsCatalogResponse>("/api/v1/ops/catalog"),
  });

  const schedulesQuery = useQuery({
    queryKey: ["ops", "schedules"],
    queryFn: () => apiRequest<ScheduleListResponse>("/api/v1/ops/schedules?limit=100"),
  });

  useEffect(() => {
    if (!selectedScheduleId && schedulesQuery.data?.items?.length) {
      setSelectedScheduleId(schedulesQuery.data.items[0].id);
    }
  }, [selectedScheduleId, schedulesQuery.data, setSelectedScheduleId]);

  const detailQuery = useQuery({
    queryKey: ["ops", "schedule", selectedScheduleId],
    queryFn: () => apiRequest<ScheduleDetailResponse>(`/api/v1/ops/schedules/${selectedScheduleId}`),
    enabled: Boolean(selectedScheduleId),
  });

  const revisionsQuery = useQuery({
    queryKey: ["ops", "schedule-revisions", selectedScheduleId],
    queryFn: () => apiRequest<ScheduleRevisionListResponse>(`/api/v1/ops/schedules/${selectedScheduleId}/revisions`),
    enabled: Boolean(selectedScheduleId),
  });

  const specOptions = useMemo(() => {
    if (!catalogQuery.data) return [];
    return [
      ...catalogQuery.data.job_specs
        .filter((item) => item.supports_schedule !== false)
        .map((item) => ({
          value: `job:${item.key}`,
          label: `【任务】${formatSpecDisplayLabel(item.key, item.display_name)}`,
        })),
      ...catalogQuery.data.workflow_specs
        .filter((item) => item.supports_schedule !== false)
        .map((item) => ({
          value: `workflow:${item.key}`,
          label: `【流程】${formatSpecDisplayLabel(item.key, item.display_name)}`,
        })),
    ];
  }, [catalogQuery.data]);

  const summary = useMemo(() => {
    const items = schedulesQuery.data?.items || [];
    return {
      total: items.length,
      active: items.filter((item) => item.status === "active").length,
      paused: items.filter((item) => item.status === "paused").length,
      once: items.filter((item) => item.schedule_type === "once").length,
      cron: items.filter((item) => item.schedule_type === "cron").length,
    };
  }, [schedulesQuery.data?.items]);

  const previewMutation = useMutation({
    mutationFn: () =>
      apiRequest<SchedulePreviewResponse>("/api/v1/ops/schedules/preview", {
        method: "POST",
        body: {
          schedule_type: form.schedule_type,
          cron_expr: form.cron_expr || null,
          timezone: form.timezone,
          next_run_at: form.next_run_at || null,
          count: 5,
        },
      }),
  });

  const saveMutation = useMutation({
    mutationFn: async () => {
      const body = {
        spec_type: form.spec_type,
        spec_key: form.spec_key,
        display_name: form.display_name,
        schedule_type: form.schedule_type,
        cron_expr: form.cron_expr || null,
        timezone: form.timezone,
        calendar_policy: form.calendar_policy || null,
        next_run_at: form.next_run_at || null,
        params_json: parseJsonOrThrow("自动运行参数", form.params_json),
        retry_policy_json: parseJsonOrThrow("失败后重试设置", form.retry_policy_json),
        concurrency_policy_json: parseJsonOrThrow("并发处理设置", form.concurrency_policy_json),
      };
      if (form.id) {
        return apiRequest<ScheduleDetailResponse>(`/api/v1/ops/schedules/${form.id}`, {
          method: "PATCH",
          body,
        });
      }
      return apiRequest<ScheduleDetailResponse>("/api/v1/ops/schedules", {
        method: "POST",
        body,
      });
    },
    onSuccess: async (data) => {
      setLastAction(data);
      notifications.show({
        color: "green",
        title: form.id ? "自动任务已更新" : "自动任务已创建",
        message: data.display_name,
      });
      close();
      setSelectedScheduleId(data.id);
      setForm(emptyForm);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ops", "schedules"] }),
        queryClient.invalidateQueries({ queryKey: ["ops", "schedule", data.id] }),
        queryClient.invalidateQueries({ queryKey: ["ops", "schedule-revisions", data.id] }),
        queryClient.invalidateQueries({ queryKey: ["ops", "catalog"] }),
      ]);
    },
    onError: (error) => {
      notifications.show({
        color: "red",
        title: "保存自动任务失败",
        message: error instanceof Error ? error.message : "未知错误",
      });
    },
  });

  const toggleMutation = useMutation({
    mutationFn: async (mode: "pause" | "resume") =>
      apiRequest<ScheduleDetailResponse>(`/api/v1/ops/schedules/${selectedScheduleId}/${mode}`, {
        method: "POST",
      }),
    onSuccess: async (data) => {
      setLastAction(data);
      notifications.show({
        color: "green",
        title: data.status === "active" ? "自动任务已恢复" : "自动任务已暂停",
        message: data.display_name,
      });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ops", "schedules"] }),
        queryClient.invalidateQueries({ queryKey: ["ops", "schedule", data.id] }),
        queryClient.invalidateQueries({ queryKey: ["ops", "schedule-revisions", data.id] }),
        queryClient.invalidateQueries({ queryKey: ["ops", "catalog"] }),
      ]);
    },
  });

  const openCreate = () => {
    setForm(emptyForm);
    open();
  };

  const openEdit = () => {
    const detail = detailQuery.data;
    if (!detail) return;
    setForm({
      id: detail.id,
      spec_type: detail.spec_type,
      spec_key: detail.spec_key,
      display_name: detail.display_name,
      schedule_type: detail.schedule_type,
      cron_expr: detail.cron_expr || "",
      timezone: detail.timezone,
      calendar_policy: detail.calendar_policy || "",
      next_run_at: detail.next_run_at || "",
      params_json: JSON.stringify(detail.params_json || {}, null, 2),
      retry_policy_json: JSON.stringify(detail.retry_policy_json || {}, null, 2),
      concurrency_policy_json: JSON.stringify(detail.concurrency_policy_json || {}, null, 2),
    });
    open();
  };

  return (
    <Stack gap="lg">
      <PageHeader
        title="自动运行"
        description="把系统要自动执行的任务安排好，平时只需要看结果，不需要手动盯着跑。"
        action={<Button onClick={openCreate}>新建自动任务</Button>}
      />

      {(catalogQuery.isLoading || schedulesQuery.isLoading) ? <Loader size="sm" /> : null}
      {catalogQuery.error || schedulesQuery.error ? (
        <Alert color="red" title="无法读取自动运行配置">
          {(catalogQuery.error || schedulesQuery.error) instanceof Error
            ? ((catalogQuery.error || schedulesQuery.error) as Error).message
            : "未知错误"}
        </Alert>
      ) : null}

      <Grid>
        <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
          <StatCard label="自动任务总数" value={summary.total} />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
          <StatCard label="启用中" value={summary.active} />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
          <StatCard label="已暂停" value={summary.paused} />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
          <StatCard label="单次执行" value={summary.once} />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
          <StatCard label="按周期执行" value={summary.cron} hint="按周期执行需要填写周期规则。" />
        </Grid.Col>
      </Grid>

      <Grid align="stretch">
        <Grid.Col span={{ base: 12, xl: 7 }}>
          <SectionCard
            title="自动任务列表"
            description="这里列出系统会自动运行的任务。点中一条后，可以在右侧查看详情和修改。"
          >
            {(schedulesQuery.data?.items?.length ?? 0) > 0 ? (
              <Table highlightOnHover striped>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>任务名称</Table.Th>
                    <Table.Th>执行对象</Table.Th>
                    <Table.Th>当前状态</Table.Th>
                    <Table.Th>执行方式</Table.Th>
                    <Table.Th>下次运行</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {(schedulesQuery.data?.items || []).map((item) => (
                    <Table.Tr
                      key={item.id}
                      onClick={() => setSelectedScheduleId(item.id)}
                      style={{
                        cursor: "pointer",
                        background: selectedScheduleId === item.id ? "rgba(0, 169, 187, 0.08)" : undefined,
                      }}
                    >
                      <Table.Td>{item.display_name}</Table.Td>
                      <Table.Td>{formatSpecDisplayLabel(item.spec_key, item.spec_display_name)}</Table.Td>
                      <Table.Td>
                        <StatusBadge value={item.status} />
                      </Table.Td>
                      <Table.Td>{formatScheduleTypeLabel(item.schedule_type)}</Table.Td>
                      <Table.Td>{formatDateTimeLabel(item.next_run_at)}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            ) : (
              <EmptyState
                title="还没有自动任务"
                description="你可以先新建一个自动任务，让系统在固定时间自动同步数据。"
                action={<Button onClick={openCreate}>立即新建</Button>}
              />
            )}
          </SectionCard>
        </Grid.Col>

        <Grid.Col span={{ base: 12, xl: 5 }}>
          <Stack gap="lg">
            <SectionCard
              title="任务详情"
              description="这里展示当前自动任务的执行对象、运行时间和最近结果。"
              action={
                detailQuery.data ? (
                  <Group gap="xs">
                    <Button variant="light" onClick={openEdit}>
                      修改
                    </Button>
                    <Button
                      color={detailQuery.data.status === "active" ? "orange" : "green"}
                      onClick={() =>
                        toggleMutation.mutate(detailQuery.data?.status === "active" ? "pause" : "resume")
                      }
                    >
                      {detailQuery.data.status === "active" ? "暂停自动运行" : "恢复自动运行"}
                    </Button>
                  </Group>
                ) : undefined
              }
            >
              {detailQuery.isLoading ? <Loader size="sm" /> : null}
              {detailQuery.data ? (
                <Stack gap="sm">
                  <Text fw={700}>{detailQuery.data.display_name}</Text>
                  <Group gap="xs">
                    <StatusBadge value={detailQuery.data.status} />
                    <Badge variant="light">{formatScheduleTypeLabel(detailQuery.data.schedule_type)}</Badge>
                    <Badge variant="light">{formatTimezoneLabel(detailQuery.data.timezone)}</Badge>
                  </Group>
                  <Text size="sm">执行对象：{formatSpecDisplayLabel(detailQuery.data.spec_key, detailQuery.data.spec_display_name)}</Text>
                  <Text size="sm">下次运行：{formatDateTimeLabel(detailQuery.data.next_run_at)}</Text>
                  <Text size="sm">上次触发：{formatDateTimeLabel(detailQuery.data.last_triggered_at)}</Text>
                  <Text size="sm">周期规则：{detailQuery.data.cron_expr || "未设置"}</Text>
                  <Anchor component="a" href={`/app/ops/manual-sync?from_schedule_id=${detailQuery.data.id}`} size="sm">
                    按当前配置手动执行一次
                  </Anchor>
                </Stack>
              ) : (
                <EmptyState title="请先选择一条自动任务" description="点左侧列表中的任务后，这里会显示它的详细设置。" />
              )}
            </SectionCard>

            {lastAction ? (
              <ActionSummaryCard
                title="最近一次自动任务操作"
                rows={[
                  { label: "任务名称", value: lastAction.display_name },
                  { label: "执行对象", value: formatSpecDisplayLabel(lastAction.spec_key, lastAction.spec_display_name) },
                  { label: "当前状态", value: lastAction.status },
                  { label: "下次运行", value: formatDateTimeLabel(lastAction.next_run_at) },
                ]}
              />
            ) : null}

            <SectionCard title="最近变更" description="这里只记录自动任务配置的变更历史，方便回看是谁改了什么。">
              {revisionsQuery.data?.items?.length ? (
                <Stack gap="sm">
                  {revisionsQuery.data.items.slice(0, 5).map((item) => (
                    <Stack key={item.id} gap={2}>
                      <Text fw={600}>{formatRevisionActionLabel(item.action)}</Text>
                      <Text c="dimmed" size="sm">
                        {item.changed_by_username || "系统"} · {formatDateTimeLabel(item.changed_at)}
                      </Text>
                    </Stack>
                  ))}
                </Stack>
              ) : (
                <Text c="dimmed" size="sm">
                  当前还没有变更记录。
                </Text>
              )}
            </SectionCard>
          </Stack>
        </Grid.Col>
      </Grid>

      <Drawer
        opened={opened}
        onClose={close}
        position="right"
        size="lg"
        title={form.id ? "修改自动任务" : "新建自动任务"}
      >
        <Stack gap="md">
          <TextInput
            label="任务名称"
            value={form.display_name}
            onChange={(event) => setForm((current) => ({ ...current, display_name: event.currentTarget.value }))}
          />
          <Select
            label="执行对象"
            searchable
            data={specOptions}
            value={form.spec_key ? `${form.spec_type}:${form.spec_key}` : null}
            onChange={(value) => {
              const [specType, specKey] = (value || "job:").split(":");
              setForm((current) => ({ ...current, spec_type: specType, spec_key: specKey || "" }));
            }}
          />
          <Select
            label="执行方式"
            data={[
              { value: "once", label: "单次执行" },
              { value: "cron", label: "按周期执行" },
            ]}
            value={form.schedule_type}
            onChange={(value) => setForm((current) => ({ ...current, schedule_type: value || "once" }))}
          />
          {form.schedule_type === "once" ? (
            <TextInput
              label="开始执行时间"
              placeholder="例如：2026-04-01T19:00:00+08:00"
              value={form.next_run_at}
              onChange={(event) => setForm((current) => ({ ...current, next_run_at: event.currentTarget.value }))}
            />
          ) : (
            <TextInput
              label="周期规则"
              placeholder="例如：0 19 * * 1-5"
              value={form.cron_expr}
              onChange={(event) => setForm((current) => ({ ...current, cron_expr: event.currentTarget.value }))}
            />
          )}
          <Select
            label="时区"
            data={[{ value: "Asia/Shanghai", label: "北京时间（默认）" }]}
            value={form.timezone}
            onChange={(value) => setForm((current) => ({ ...current, timezone: value || "Asia/Shanghai" }))}
          />

          <Accordion variant="separated" radius="md">
            <Accordion.Item value="params">
              <Accordion.Control>高级设置</Accordion.Control>
              <Accordion.Panel>
                <Stack gap="md">
                  <JsonInput
                    label="自动运行参数"
                    autosize
                    minRows={6}
                    value={form.params_json}
                    onChange={(value) => setForm((current) => ({ ...current, params_json: value }))}
                  />
                  <JsonInput
                    label="失败后重试设置"
                    autosize
                    minRows={4}
                    value={form.retry_policy_json}
                    onChange={(value) => setForm((current) => ({ ...current, retry_policy_json: value }))}
                  />
                  <JsonInput
                    label="并发处理设置"
                    autosize
                    minRows={4}
                    value={form.concurrency_policy_json}
                    onChange={(value) => setForm((current) => ({ ...current, concurrency_policy_json: value }))}
                  />
                </Stack>
              </Accordion.Panel>
            </Accordion.Item>
          </Accordion>

          <Group justify="space-between">
            <Button variant="light" onClick={() => previewMutation.mutate()}>
              预览未来 5 次运行时间
            </Button>
            <Button loading={saveMutation.isPending} onClick={() => saveMutation.mutate()}>
              {form.id ? "保存修改" : "创建自动任务"}
            </Button>
          </Group>

          {previewMutation.data ? (
            <Alert color="blue" variant="light" title="预览结果">
              <Stack gap={4}>
                {previewMutation.data.preview_times.map((item) => (
                  <Text key={item} size="sm">
                    {formatDateTimeLabel(item)}
                  </Text>
                ))}
              </Stack>
            </Alert>
          ) : null}
        </Stack>
      </Drawer>
    </Stack>
  );
}
