import {
  Alert,
  Button,
  Drawer,
  Group,
  NumberInput,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { apiRequest } from "../shared/api/client";
import type {
  DateCompletenessRuleItem,
  DateCompletenessScheduleCreateRequest,
  DateCompletenessScheduleItem,
  DateCompletenessScheduleListResponse,
} from "../shared/api/date-completeness-types";
import { formatDateLabel, formatDateTimeLabel } from "../shared/date-format";
import { DateField } from "../shared/ui/date-field";
import { EmptyState } from "../shared/ui/empty-state";
import { OpsTable, OpsTableActionGroup, OpsTableCell, OpsTableHeaderCell } from "../shared/ui/ops-table";
import { SectionCard } from "../shared/ui/section-card";
import { StatusBadge } from "../shared/ui/status-badge";
import { TableShell } from "../shared/ui/table-shell";

interface ScheduleFormState {
  dataset_key: string;
  display_name: string;
  window_mode: "fixed_range" | "rolling";
  start_date: string;
  end_date: string;
  lookback_count: number;
  lookback_unit: "calendar_day" | "open_day" | "month";
  cron_expr: string;
  timezone: string;
}

const DEFAULT_FORM: ScheduleFormState = {
  dataset_key: "",
  display_name: "",
  window_mode: "rolling",
  start_date: "2026-04-20",
  end_date: "2026-04-24",
  lookback_count: 10,
  lookback_unit: "open_day",
  cron_expr: "0 22 * * *",
  timezone: "Asia/Shanghai",
};

function resultLabel(value: DateCompletenessScheduleItem["last_result_status"]): string {
  if (value === "passed") return "通过";
  if (value === "failed") return "不通过";
  if (value === "error") return "执行错误";
  return "未运行";
}

function resultBadgeValue(value: DateCompletenessScheduleItem["last_result_status"]): string {
  if (value === "passed") return "success";
  if (value === "failed") return "failed";
  if (value === "error") return "error";
  return "unknown";
}

function lookbackUnitLabel(value: DateCompletenessScheduleItem["lookback_unit"]): string {
  if (value === "calendar_day") return "自然日";
  if (value === "open_day") return "开市日";
  if (value === "month") return "自然月";
  return "—";
}

function windowLabel(item: DateCompletenessScheduleItem): string {
  if (item.window_mode === "fixed_range") {
    return `${formatDateLabel(item.start_date)} 至 ${formatDateLabel(item.end_date)}`;
  }
  return `最近 ${item.lookback_count ?? "—"} 个${lookbackUnitLabel(item.lookback_unit)}`;
}

function buildSchedulePayload(
  form: ScheduleFormState,
  status: DateCompletenessScheduleCreateRequest["status"],
): DateCompletenessScheduleCreateRequest {
  return {
    dataset_key: form.dataset_key,
    display_name: form.display_name.trim() || null,
    status,
    window_mode: form.window_mode,
    start_date: form.window_mode === "fixed_range" ? form.start_date : null,
    end_date: form.window_mode === "fixed_range" ? form.end_date : null,
    lookback_count: form.window_mode === "rolling" ? form.lookback_count : null,
    lookback_unit: form.window_mode === "rolling" ? form.lookback_unit : null,
    calendar_scope: "default_cn_market",
    calendar_exchange: null,
    cron_expr: form.cron_expr,
    timezone: form.timezone,
  };
}

export function OpsV21DatasetAuditSchedulesPanel({ supportedRules }: { supportedRules: DateCompletenessRuleItem[] }) {
  const queryClient = useQueryClient();
  const [drawerOpened, setDrawerOpened] = useState(false);
  const [editingSchedule, setEditingSchedule] = useState<DateCompletenessScheduleItem | null>(null);
  const [form, setForm] = useState<ScheduleFormState>(DEFAULT_FORM);

  const datasetOptions = useMemo(
    () => supportedRules.map((item) => ({ value: item.dataset_key, label: item.display_name })),
    [supportedRules],
  );

  const schedulesQuery = useQuery({
    queryKey: ["ops", "date-completeness", "schedules"],
    queryFn: () =>
      apiRequest<DateCompletenessScheduleListResponse>("/api/v1/ops/review/date-completeness/schedules?limit=50&offset=0"),
  });

  const refreshSchedules = async () => {
    await queryClient.invalidateQueries({ queryKey: ["ops", "date-completeness", "schedules"] });
    await queryClient.invalidateQueries({ queryKey: ["ops", "date-completeness", "runs"] });
  };

  const createScheduleMutation = useMutation({
    mutationFn: (payload: DateCompletenessScheduleCreateRequest) =>
      apiRequest<DateCompletenessScheduleItem>("/api/v1/ops/review/date-completeness/schedules", {
        method: "POST",
        body: payload,
      }),
    onSuccess: async () => {
      notifications.show({ color: "brand", title: "自动审计已创建", message: "计划会按配置时间生成独立审计任务。" });
      setDrawerOpened(false);
      setForm(DEFAULT_FORM);
      await refreshSchedules();
    },
    onError: (error) => {
      notifications.show({ color: "red", title: "创建自动审计失败", message: error instanceof Error ? error.message : "请稍后重试。" });
    },
  });

  const updateScheduleMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: DateCompletenessScheduleCreateRequest }) =>
      apiRequest<DateCompletenessScheduleItem>(`/api/v1/ops/review/date-completeness/schedules/${id}`, {
        method: "PATCH",
        body: payload,
      }),
    onSuccess: async () => {
      notifications.show({ color: "brand", title: "自动审计已更新", message: "新的计划配置会从下一次调度开始生效。" });
      setDrawerOpened(false);
      setEditingSchedule(null);
      setForm(DEFAULT_FORM);
      await refreshSchedules();
    },
    onError: (error) => {
      notifications.show({ color: "red", title: "更新自动审计失败", message: error instanceof Error ? error.message : "请稍后重试。" });
    },
  });

  const scheduleActionMutation = useMutation({
    mutationFn: ({ path, method }: { path: string; method?: string }) => apiRequest(path, { method }),
    onSuccess: refreshSchedules,
    onError: (error) => {
      notifications.show({ color: "red", title: "操作失败", message: error instanceof Error ? error.message : "请稍后重试。" });
    },
  });

  const openCreateDrawer = () => {
    setEditingSchedule(null);
    setForm({ ...DEFAULT_FORM, dataset_key: supportedRules[0]?.dataset_key || "" });
    setDrawerOpened(true);
  };

  const openEditDrawer = (item: DateCompletenessScheduleItem) => {
    setEditingSchedule(item);
    setForm({
      dataset_key: item.dataset_key,
      display_name: item.display_name,
      window_mode: item.window_mode,
      start_date: item.start_date || DEFAULT_FORM.start_date,
      end_date: item.end_date || DEFAULT_FORM.end_date,
      lookback_count: item.lookback_count || DEFAULT_FORM.lookback_count,
      lookback_unit: item.lookback_unit || DEFAULT_FORM.lookback_unit,
      cron_expr: item.cron_expr,
      timezone: item.timezone,
    });
    setDrawerOpened(true);
  };

  const submitSchedule = () => {
    const payload = buildSchedulePayload(form, editingSchedule?.status || "active");
    if (editingSchedule) {
      updateScheduleMutation.mutate({ id: editingSchedule.id, payload });
      return;
    }
    createScheduleMutation.mutate(payload);
  };

  const items = schedulesQuery.data?.items || [];

  return (
    <>
      <SectionCard
        title="自动审计"
        description="自动审计只写入日期完整性审计表，不复用任务中心自动任务。"
        action={<Button onClick={openCreateDrawer} disabled={supportedRules.length === 0}>创建自动审计</Button>}
      >
        <Stack gap="md">
          <Alert color="blue" title="运行方式">
            系统按计划创建独立审计记录；真正检查由日期完整性审计 worker 执行。
          </Alert>
          <TableShell
            loading={schedulesQuery.isLoading}
            hasData={items.length > 0}
            emptyState={<EmptyState title="暂无自动审计" description="创建计划后，这里会显示下次运行时间和最近审计结论。" />}
            minWidth={1080}
          >
            <OpsTable>
              <Table.Thead>
                <Table.Tr>
                  <OpsTableHeaderCell>计划</OpsTableHeaderCell>
                  <OpsTableHeaderCell>审计窗口</OpsTableHeaderCell>
                  <OpsTableHeaderCell>周期</OpsTableHeaderCell>
                  <OpsTableHeaderCell>状态</OpsTableHeaderCell>
                  <OpsTableHeaderCell>最近结论</OpsTableHeaderCell>
                  <OpsTableHeaderCell>下次运行</OpsTableHeaderCell>
                  <OpsTableHeaderCell>操作</OpsTableHeaderCell>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {items.map((item) => (
                  <Table.Tr key={item.id}>
                    <OpsTableCell>
                      <Stack gap={2}>
                        <Text fw={600}>{item.display_name}</Text>
                      </Stack>
                    </OpsTableCell>
                    <OpsTableCell>{windowLabel(item)}</OpsTableCell>
                    <OpsTableCell>
                      <Stack gap={2}>
                        <Text size="sm">{item.cron_expr}</Text>
                        <Text size="xs" c="dimmed">{item.timezone}</Text>
                      </Stack>
                    </OpsTableCell>
                    <OpsTableCell><StatusBadge value={item.status} /></OpsTableCell>
                    <OpsTableCell>
                      <Stack gap={2} align="center">
                        <StatusBadge value={resultBadgeValue(item.last_result_status)} label={resultLabel(item.last_result_status)} />
                        {item.last_run_finished_at ? <Text size="xs" c="dimmed">{formatDateTimeLabel(item.last_run_finished_at)}</Text> : null}
                      </Stack>
                    </OpsTableCell>
                    <OpsTableCell>{formatDateTimeLabel(item.next_run_at)}</OpsTableCell>
                    <OpsTableCell>
                      <OpsTableActionGroup>
                        <Button size="xs" variant="subtle" onClick={() => openEditDrawer(item)}>
                          编辑
                        </Button>
                        {item.status === "active" ? (
                          <Button
                            size="xs"
                            variant="subtle"
                            onClick={() => scheduleActionMutation.mutate({ path: `/api/v1/ops/review/date-completeness/schedules/${item.id}/pause`, method: "POST" })}
                          >
                            暂停
                          </Button>
                        ) : (
                          <Button
                            size="xs"
                            variant="subtle"
                            onClick={() => scheduleActionMutation.mutate({ path: `/api/v1/ops/review/date-completeness/schedules/${item.id}/resume`, method: "POST" })}
                          >
                            恢复
                          </Button>
                        )}
                        <Button
                          size="xs"
                          variant="subtle"
                          color="red"
                          onClick={() => scheduleActionMutation.mutate({ path: `/api/v1/ops/review/date-completeness/schedules/${item.id}`, method: "DELETE" })}
                        >
                          删除
                        </Button>
                      </OpsTableActionGroup>
                    </OpsTableCell>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </OpsTable>
          </TableShell>
        </Stack>
      </SectionCard>

      <Drawer
        opened={drawerOpened}
        onClose={() => {
          setDrawerOpened(false);
          setEditingSchedule(null);
        }}
        title={editingSchedule ? "编辑自动审计" : "创建自动审计"}
        position="right"
        size="md"
      >
        <Stack gap="md">
          <Select
            label="审计数据集"
            data={datasetOptions}
            value={form.dataset_key}
            allowDeselect={false}
            searchable
            disabled={Boolean(editingSchedule)}
            onChange={(value) => setForm((current) => ({ ...current, dataset_key: value || "" }))}
          />
          <TextInput
            label="计划名称"
            placeholder="默认使用数据集名称"
            value={form.display_name}
            onChange={(event) => setForm((current) => ({ ...current, display_name: event.currentTarget.value }))}
          />
          <Select
            label="审计窗口"
            value={form.window_mode}
            allowDeselect={false}
            data={[
              { value: "rolling", label: "滚动窗口" },
              { value: "fixed_range", label: "固定范围" },
            ]}
            onChange={(value) => setForm((current) => ({ ...current, window_mode: (value as ScheduleFormState["window_mode"]) || "rolling" }))}
          />
          {form.window_mode === "fixed_range" ? (
            <Group grow align="flex-start">
              <DateField label="开始日期" value={form.start_date} onChange={(value) => setForm((current) => ({ ...current, start_date: value }))} />
              <DateField label="结束日期" value={form.end_date} onChange={(value) => setForm((current) => ({ ...current, end_date: value }))} />
            </Group>
          ) : (
            <Group grow align="flex-start">
              <NumberInput
                label="回看数量"
                min={1}
                value={form.lookback_count}
                onChange={(value) => setForm((current) => ({ ...current, lookback_count: Math.max(1, Number(value) || 1) }))}
              />
              <Select
                label="回看单位"
                value={form.lookback_unit}
                allowDeselect={false}
                data={[
                  { value: "calendar_day", label: "自然日" },
                  { value: "open_day", label: "开市日" },
                  { value: "month", label: "自然月" },
                ]}
                onChange={(value) => setForm((current) => ({ ...current, lookback_unit: (value as ScheduleFormState["lookback_unit"]) || "open_day" }))}
              />
            </Group>
          )}
          <TextInput
            label="周期表达式"
            description="5 段 cron 表达式，例如每天 22:00：0 22 * * *"
            value={form.cron_expr}
            onChange={(event) => setForm((current) => ({ ...current, cron_expr: event.currentTarget.value }))}
          />
          <TextInput
            label="时区"
            value={form.timezone}
            onChange={(event) => setForm((current) => ({ ...current, timezone: event.currentTarget.value }))}
          />
          <Text size="sm" c="dimmed">日历：默认 A 股交易日历。港股/自定义交易所入口已预留，后续按业务口径开启。</Text>
          <Group justify="flex-end">
            <Button
              variant="subtle"
              onClick={() => {
                setDrawerOpened(false);
                setEditingSchedule(null);
              }}
            >
              取消
            </Button>
            <Button
              loading={createScheduleMutation.isPending || updateScheduleMutation.isPending}
              onClick={submitSchedule}
            >
              {editingSchedule ? "保存自动审计" : "确认创建自动审计"}
            </Button>
          </Group>
        </Stack>
      </Drawer>
    </>
  );
}
