import {
  Accordion,
  Alert,
  Badge,
  Button,
  Checkbox,
  Drawer,
  Grid,
  Group,
  Loader,
  MultiSelect,
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
  ExecutionListResponse,
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
import { DateField } from "../shared/ui/date-field";
import { useAuth } from "../features/auth/auth-context";
import { ActionSummaryCard } from "../shared/ui/action-summary-card";
import { EmptyState } from "../shared/ui/empty-state";
import { OpsTable, OpsTableCell, OpsTableCellText, OpsTableHeaderCell } from "../shared/ui/ops-table";
import { SectionCard } from "../shared/ui/section-card";
import { StatCard } from "../shared/ui/stat-card";
import { StatusBadge } from "../shared/ui/status-badge";

type DateMode = "single_day" | "date_range";
type CatalogParamSpec = NonNullable<OpsCatalogResponse["job_specs"][number]["supported_params"]>[number];
type RepeatMode = "daily" | "weekly" | "monthly";

const INTERNAL_PARAM_KEYS = new Set(["offset", "limit"]);
const DATE_PARAM_KEYS = new Set(["trade_date", "start_date", "end_date"]);

const emptyForm = {
  id: null as number | null,
  spec_type: "job",
  spec_key: "",
  display_name: "",
  schedule_type: "once",
  timezone: "Asia/Shanghai",
  calendar_policy: "",
  once_date: "",
  once_time: "19:00",
  repeat_mode: "daily" as RepeatMode,
  repeat_weekdays: ["1", "2", "3", "4", "5"] as string[],
  repeat_month_day: "1",
  repeat_time: "19:00",
  date_mode: "single_day" as DateMode,
  selected_date: "",
  start_date: "",
  end_date: "",
  field_values: {} as Record<string, string | string[]>,
};

function normalizeParamOptions(options: string[] | undefined) {
  return Array.isArray(options) ? options : [];
}

function buildFieldValues(paramsJson: Record<string, unknown> | undefined) {
  if (!paramsJson) {
    return {};
  }
  return Object.fromEntries(
    Object.entries(paramsJson).map(([key, value]) => {
      if (Array.isArray(value)) {
        return [key, value.map((item) => String(item ?? ""))];
      }
      return [key, String(value ?? "")];
    }),
  );
}

function parseCronExpression(cronExpr: string | null | undefined) {
  const raw = String(cronExpr || "").trim();
  const match = raw.match(/^(\d{1,2})\s+(\d{1,2})\s+(.+)\s+(.+)\s+(.+)$/);
  if (!match) {
    return null;
  }
  const minute = Number(match[1]);
  const hour = Number(match[2]);
  const dayOfMonth = match[3];
  const month = match[4];
  const dayOfWeek = match[5];
  if (!Number.isFinite(minute) || !Number.isFinite(hour)) {
    return null;
  }
  if (month !== "*") {
    return null;
  }
  const time = `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
  if (dayOfMonth === "*" && dayOfWeek === "*") {
    return { repeatMode: "daily" as RepeatMode, repeatTime: time, repeatWeekdays: ["1", "2", "3", "4", "5"], repeatMonthDay: "1" };
  }
  if (dayOfMonth === "*" && dayOfWeek !== "*") {
    const weekdays = dayOfWeek
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    return { repeatMode: "weekly" as RepeatMode, repeatTime: time, repeatWeekdays: weekdays.length ? weekdays : ["1"], repeatMonthDay: "1" };
  }
  if (dayOfWeek === "*" && /^\d{1,2}$/.test(dayOfMonth)) {
    return { repeatMode: "monthly" as RepeatMode, repeatTime: time, repeatWeekdays: ["1"], repeatMonthDay: dayOfMonth };
  }
  return null;
}

function buildCronExpression(repeatMode: RepeatMode, repeatTime: string, repeatWeekdays: string[], repeatMonthDay: string) {
  const [hourRaw, minuteRaw] = repeatTime.split(":");
  const hour = Number(hourRaw);
  const minute = Number(minuteRaw);
  if (!Number.isFinite(hour) || !Number.isFinite(minute) || hour < 0 || hour > 23 || minute < 0 || minute > 59) {
    throw new Error("请填写正确的执行时间，格式为 HH:mm。");
  }
  if (repeatMode === "daily") {
    return `${minute} ${hour} * * *`;
  }
  if (repeatMode === "weekly") {
    const weekdays = repeatWeekdays.filter(Boolean);
    if (!weekdays.length) {
      throw new Error("每周执行至少选择一天。");
    }
    return `${minute} ${hour} * * ${weekdays.join(",")}`;
  }
  const day = Number(repeatMonthDay);
  if (!Number.isFinite(day) || day < 1 || day > 28) {
    throw new Error("每月执行日期请填写 1 到 28 之间的数字。");
  }
  return `${minute} ${hour} ${day} * *`;
}

function buildOnceRunAt(onceDate: string, onceTime: string) {
  if (!onceDate) {
    throw new Error("请选择单次执行日期。");
  }
  if (!/^\d{2}:\d{2}$/.test(onceTime)) {
    throw new Error("请填写正确的执行时间，格式为 HH:mm。");
  }
  return `${onceDate}T${onceTime}:00+08:00`;
}

function formatScheduleRule(scheduleType: string, cronExpr: string | null, nextRunAt: string | null) {
  const weekdayLabel: Record<string, string> = {
    "1": "周一",
    "2": "周二",
    "3": "周三",
    "4": "周四",
    "5": "周五",
    "6": "周六",
    "0": "周日",
  };
  if (scheduleType === "once") {
    return nextRunAt ? `单次执行：${nextRunAt.replace("T", " ").slice(0, 16)}` : "单次执行";
  }
  const parsed = parseCronExpression(cronExpr);
  if (!parsed) {
    return cronExpr || "未设置";
  }
  if (parsed.repeatMode === "daily") {
    return `每天 ${parsed.repeatTime}`;
  }
  if (parsed.repeatMode === "weekly") {
    return `每周 ${parsed.repeatWeekdays.map((item) => weekdayLabel[item] || item).join("、")} ${parsed.repeatTime}`;
  }
  return `每月 ${parsed.repeatMonthDay} 日 ${parsed.repeatTime}`;
}

function formatParamLabel(key: string): string {
  const map: Record<string, string> = {
    trade_date: "交易日",
    start_date: "开始日期",
    end_date: "结束日期",
    ts_code: "证券代码",
    con_code: "板块代码",
    index_code: "指数代码",
    market: "市场",
    tag: "标签",
    type: "类型",
    hot_type: "热榜类型",
    is_new: "最新标记",
    exchange: "交易所",
  };
  return map[key] || key;
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

export function OpsAutomationPage() {
  const { token } = useAuth();
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

  useEffect(() => {
    if (!token) {
      return;
    }
    const source = new EventSource(`/api/v1/ops/schedules/stream?token=${encodeURIComponent(token)}`);
    const refresh = () => {
      void queryClient.invalidateQueries({ queryKey: ["ops", "schedules"] });
      if (selectedScheduleId) {
        void queryClient.invalidateQueries({ queryKey: ["ops", "schedule", selectedScheduleId] });
        void queryClient.invalidateQueries({ queryKey: ["ops", "schedule-revisions", selectedScheduleId] });
        void queryClient.invalidateQueries({ queryKey: ["ops", "schedule-latest-execution", selectedScheduleId] });
      }
    };
    source.addEventListener("schedules", refresh);
    source.onerror = () => {
      source.close();
    };
    return () => {
      source.removeEventListener("schedules", refresh);
      source.close();
    };
  }, [queryClient, selectedScheduleId, token]);

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

  const latestExecutionQuery = useQuery({
    queryKey: ["ops", "schedule-latest-execution", selectedScheduleId],
    queryFn: async () => {
      const response = await apiRequest<ExecutionListResponse>(
        `/api/v1/ops/executions?schedule_id=${selectedScheduleId}&limit=1`,
      );
      return response.items[0] || null;
    },
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

  const selectedJobSpec = useMemo(
    () =>
      (form.spec_type === "job" && catalogQuery.data && form.spec_key)
        ? (catalogQuery.data.job_specs.find((item) => item.key === form.spec_key) || null)
        : null,
    [catalogQuery.data, form.spec_key, form.spec_type],
  );

  const selectedJobParamSpecs = useMemo<CatalogParamSpec[]>(
    () =>
      form.spec_type === "job"
        ? (selectedJobSpec?.supported_params || []).filter(
          (param) => !INTERNAL_PARAM_KEYS.has(param.key) && !DATE_PARAM_KEYS.has(param.key),
        )
        : [],
    [form.spec_type, selectedJobSpec],
  );

  const supportsSingleDay = useMemo(
    () => form.spec_type === "job" && Boolean(selectedJobSpec?.supported_params?.some((param) => param.key === "trade_date")),
    [form.spec_type, selectedJobSpec],
  );
  const supportsDateRange = useMemo(
    () =>
      form.spec_type === "job"
      && Boolean(
        selectedJobSpec?.supported_params?.some((param) => param.key === "start_date")
        && selectedJobSpec?.supported_params?.some((param) => param.key === "end_date"),
      ),
    [form.spec_type, selectedJobSpec],
  );

  const resolvedParamsJson = useMemo(() => {
    const params: Record<string, unknown> = {};
    for (const param of selectedJobParamSpecs) {
      const rawValue = form.field_values[param.key];
      if (rawValue === undefined || rawValue === null) {
        continue;
      }
      if (param.multi_value) {
        const values =
          Array.isArray(rawValue)
            ? rawValue.filter((item) => item !== "")
            : String(rawValue)
              .split(",")
              .map((item) => item.trim())
              .filter(Boolean);
        if (!values.length) {
          continue;
        }
        params[param.key] = values;
        continue;
      }
      const singleValue = Array.isArray(rawValue) ? rawValue[0] : rawValue;
      if (singleValue === "") {
        continue;
      }
      params[param.key] = param.param_type === "integer" ? Number(singleValue) : singleValue;
    }

    if (supportsSingleDay && supportsDateRange) {
      if (form.date_mode === "single_day") {
        if (form.selected_date) {
          params.trade_date = form.selected_date;
        }
      } else if (form.start_date && form.end_date) {
        params.start_date = form.start_date;
        params.end_date = form.end_date;
      }
    } else if (supportsSingleDay) {
      if (form.selected_date) {
        params.trade_date = form.selected_date;
      }
    } else if (supportsDateRange && form.start_date && form.end_date) {
      params.start_date = form.start_date;
      params.end_date = form.end_date;
    }
    return params;
  }, [
    form.date_mode,
    form.end_date,
    form.field_values,
    form.selected_date,
    form.start_date,
    selectedJobParamSpecs,
    supportsDateRange,
    supportsSingleDay,
  ]);

  const resolvedScheduleSummary = useMemo(() => {
    if (form.schedule_type === "once") {
      return {
        title: "单次执行",
        detail: form.once_date ? `${form.once_date} ${form.once_time}` : "未选择日期",
        cronExpr: null as string | null,
      };
    }
    try {
      const cronExpr = buildCronExpression(form.repeat_mode, form.repeat_time, form.repeat_weekdays, form.repeat_month_day);
      const detail =
        form.repeat_mode === "daily"
          ? `每天 ${form.repeat_time}`
          : form.repeat_mode === "weekly"
            ? `每周 ${form.repeat_weekdays.join("、")} ${form.repeat_time}`
            : `每月 ${form.repeat_month_day} 日 ${form.repeat_time}`;
      return {
        title: "重复执行",
        detail,
        cronExpr,
      };
    } catch {
      return {
        title: "重复执行",
        detail: "当前时间配置无效",
        cronExpr: null as string | null,
      };
    }
  }, [form.once_date, form.once_time, form.repeat_mode, form.repeat_month_day, form.repeat_time, form.repeat_weekdays, form.schedule_type]);

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

  const previewPayload = useMemo(() => {
    try {
      const scheduleType = form.schedule_type;
      const cronExpr = scheduleType === "cron"
        ? buildCronExpression(form.repeat_mode, form.repeat_time, form.repeat_weekdays, form.repeat_month_day)
        : null;
      const nextRunAt = scheduleType === "once" ? buildOnceRunAt(form.once_date, form.once_time) : null;
      return {
        schedule_type: scheduleType,
        cron_expr: cronExpr,
        timezone: form.timezone,
        next_run_at: nextRunAt,
        count: 5,
      };
    } catch {
      return null;
    }
  }, [
    form.once_date,
    form.once_time,
    form.repeat_mode,
    form.repeat_month_day,
    form.repeat_time,
    form.repeat_weekdays,
    form.schedule_type,
    form.timezone,
  ]);

  const previewTriggerKey = useMemo(() => {
    if (!previewPayload) {
      return null;
    }
    return JSON.stringify({
      schedule_type: previewPayload.schedule_type,
      cron_expr: previewPayload.cron_expr,
      next_run_at: previewPayload.next_run_at,
      timezone: previewPayload.timezone,
    });
  }, [previewPayload]);

  const previewQuery = useQuery({
    queryKey: ["ops", "schedule-preview", previewTriggerKey],
    queryFn: () =>
      apiRequest<SchedulePreviewResponse>("/api/v1/ops/schedules/preview", {
        method: "POST",
        body: previewPayload as {
          schedule_type: string;
          cron_expr: string | null;
          timezone: string;
          next_run_at: string | null;
          count: number;
        },
      }),
    enabled: opened && Boolean(previewPayload && previewTriggerKey),
    refetchOnWindowFocus: false,
    retry: false,
  });

  const saveMutation = useMutation({
    mutationFn: async () => {
      const scheduleType = form.schedule_type;
      const cronExpr = scheduleType === "cron"
        ? buildCronExpression(form.repeat_mode, form.repeat_time, form.repeat_weekdays, form.repeat_month_day)
        : null;
      const nextRunAt = scheduleType === "once" ? buildOnceRunAt(form.once_date, form.once_time) : null;
      const body = {
        spec_type: form.spec_type,
        spec_key: form.spec_key,
        display_name: form.display_name,
        schedule_type: scheduleType,
        cron_expr: cronExpr,
        timezone: form.timezone,
        calendar_policy: form.calendar_policy || null,
        next_run_at: nextRunAt,
        params_json: resolvedParamsJson,
        retry_policy_json: {},
        concurrency_policy_json: {},
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
    const parsedCron = parseCronExpression(detail.cron_expr);
    const nextRunAt = detail.next_run_at ? String(detail.next_run_at) : "";
    const paramsJson = detail.params_json || {};
    const tradeDate = typeof paramsJson.trade_date === "string" ? paramsJson.trade_date : "";
    const startDate = typeof paramsJson.start_date === "string" ? paramsJson.start_date : "";
    const endDate = typeof paramsJson.end_date === "string" ? paramsJson.end_date : "";
    const dateMode: DateMode = tradeDate || (startDate && endDate && startDate === endDate) ? "single_day" : "date_range";
    setForm({
      id: detail.id,
      spec_type: detail.spec_type,
      spec_key: detail.spec_key,
      display_name: detail.display_name,
      schedule_type: detail.schedule_type,
      timezone: detail.timezone,
      calendar_policy: detail.calendar_policy || "",
      once_date: nextRunAt ? nextRunAt.slice(0, 10) : "",
      once_time: nextRunAt ? nextRunAt.slice(11, 16) : "19:00",
      repeat_mode: parsedCron?.repeatMode || "daily",
      repeat_weekdays: parsedCron?.repeatWeekdays || ["1", "2", "3", "4", "5"],
      repeat_month_day: parsedCron?.repeatMonthDay || "1",
      repeat_time: parsedCron?.repeatTime || "19:00",
      date_mode: dateMode,
      selected_date: tradeDate || startDate || "",
      start_date: startDate,
      end_date: endDate,
      field_values: buildFieldValues(paramsJson),
    });
    open();
  };

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="center">
        <Text c="dimmed" size="sm">
          把系统要自动执行的任务安排好，平时只需要看结果，不需要手动盯着跑。
        </Text>
        <Button onClick={openCreate}>新建自动任务</Button>
      </Group>

      {(catalogQuery.isLoading || schedulesQuery.isLoading) ? <Loader size="sm" /> : null}
      {catalogQuery.error || schedulesQuery.error ? (
        <Alert color="red" title="无法读取自动运行配置">
          {(catalogQuery.error || schedulesQuery.error) instanceof Error
            ? ((catalogQuery.error || schedulesQuery.error) as Error).message
            : "未知错误"}
        </Alert>
      ) : null}

      <SectionCard title="自动运行概览" description="先看自动任务的整体分布，再选择左侧具体任务继续处理。">
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
      </SectionCard>

      <Grid align="stretch">
        <Grid.Col span={{ base: 12, xl: 7 }}>
          <SectionCard
            title="自动任务列表"
            description="这里列出系统会自动运行的任务。点中一条后，可以在右侧查看详情和修改。"
          >
            {(schedulesQuery.data?.items?.length ?? 0) > 0 ? (
              <OpsTable>
                <Table.Thead>
                  <Table.Tr>
                    <OpsTableHeaderCell align="left" width="26%">任务名称</OpsTableHeaderCell>
                    <OpsTableHeaderCell align="left" width="28%">执行对象</OpsTableHeaderCell>
                    <OpsTableHeaderCell width="14%">当前状态</OpsTableHeaderCell>
                    <OpsTableHeaderCell width="12%">执行方式</OpsTableHeaderCell>
                    <OpsTableHeaderCell align="left" width="20%">下次运行</OpsTableHeaderCell>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {(schedulesQuery.data?.items || []).map((item) => (
                    <Table.Tr
                      key={item.id}
                      onClick={() => setSelectedScheduleId(item.id)}
                      style={{
                        cursor: "pointer",
                        background: selectedScheduleId === item.id ? "rgba(72, 149, 239, 0.10)" : undefined,
                      }}
                    >
                      <OpsTableCell align="left" width="26%">
                        <OpsTableCellText fw={600} size="sm">{item.display_name}</OpsTableCellText>
                      </OpsTableCell>
                      <OpsTableCell align="left" width="28%">
                        <OpsTableCellText size="xs">{formatSpecDisplayLabel(item.spec_key, item.spec_display_name)}</OpsTableCellText>
                      </OpsTableCell>
                      <OpsTableCell width="14%">
                        <StatusBadge value={item.status} />
                      </OpsTableCell>
                      <OpsTableCell width="12%">
                        <OpsTableCellText size="xs">{formatScheduleTypeLabel(item.schedule_type)}</OpsTableCellText>
                      </OpsTableCell>
                      <OpsTableCell align="left" width="20%">
                        <OpsTableCellText ff="IBM Plex Mono, SFMono-Regular, monospace" fw={500} size="xs">
                          {formatDateTimeLabel(item.next_run_at)}
                        </OpsTableCellText>
                      </OpsTableCell>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </OpsTable>
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
              description="先看当前状态和运行时间，再决定是修改、暂停，还是恢复自动运行。"
              action={
                detailQuery.data ? (
                  <Group gap="xs">
                    <Button variant="light" color="brand" onClick={openEdit}>
                      修改
                    </Button>
                    <Button
                      color={detailQuery.data.status === "active" ? "orange" : "brand"}
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
                <Stack gap="md">
                  <Text fw={800} size="lg">{detailQuery.data.display_name}</Text>
                  <Group gap="xs">
                    <StatusBadge value={detailQuery.data.status} />
                    <Badge variant="light">{formatScheduleTypeLabel(detailQuery.data.schedule_type)}</Badge>
                    <Badge variant="light">{formatTimezoneLabel(detailQuery.data.timezone)}</Badge>
                  </Group>
                  <Grid gutter="sm">
                    <Grid.Col span={{ base: 12, sm: 6 }}>
                      <Stack
                        gap={4}
                        p="sm"
                        bg="var(--mantine-color-gray-0)"
                        bd="1px solid var(--mantine-color-gray-2)"
                        style={{ borderRadius: "var(--mantine-radius-md)" }}
                      >
                        <Text c="dimmed" size="xs">执行对象</Text>
                        <Text size="sm">{formatSpecDisplayLabel(detailQuery.data.spec_key, detailQuery.data.spec_display_name)}</Text>
                      </Stack>
                    </Grid.Col>
                    <Grid.Col span={{ base: 12, sm: 6 }}>
                      <Stack
                        gap={4}
                        p="sm"
                        bg="var(--mantine-color-gray-0)"
                        bd="1px solid var(--mantine-color-gray-2)"
                        style={{ borderRadius: "var(--mantine-radius-md)" }}
                      >
                        <Text c="dimmed" size="xs">下次运行</Text>
                        <Text ff="IBM Plex Mono, SFMono-Regular, monospace" size="sm">
                          {formatDateTimeLabel(detailQuery.data.next_run_at)}
                        </Text>
                      </Stack>
                    </Grid.Col>
                    <Grid.Col span={{ base: 12, sm: 6 }}>
                      <Stack
                        gap={4}
                        p="sm"
                        bg="var(--mantine-color-gray-0)"
                        bd="1px solid var(--mantine-color-gray-2)"
                        style={{ borderRadius: "var(--mantine-radius-md)" }}
                      >
                        <Text c="dimmed" size="xs">上次触发</Text>
                        <Text ff="IBM Plex Mono, SFMono-Regular, monospace" size="sm">
                          {formatDateTimeLabel(detailQuery.data.last_triggered_at)}
                        </Text>
                      </Stack>
                    </Grid.Col>
                    <Grid.Col span={{ base: 12, sm: 6 }}>
                      <Stack
                        gap={4}
                        p="sm"
                        bg="var(--mantine-color-gray-0)"
                        bd="1px solid var(--mantine-color-gray-2)"
                        style={{ borderRadius: "var(--mantine-radius-md)" }}
                      >
                        <Text c="dimmed" size="xs">调度策略</Text>
                        <Text size="sm">
                          {formatScheduleRule(detailQuery.data.schedule_type, detailQuery.data.cron_expr, detailQuery.data.next_run_at)}
                        </Text>
                      </Stack>
                    </Grid.Col>
                  </Grid>
                  <Stack
                    gap={6}
                    p="sm"
                    bg="var(--mantine-color-gray-0)"
                    bd="1px solid var(--mantine-color-gray-2)"
                    style={{ borderRadius: "var(--mantine-radius-md)" }}
                  >
                    <Text c="dimmed" size="xs">任务参数</Text>
                    {Object.keys(detailQuery.data.params_json || {}).length ? (
                      Object.entries(detailQuery.data.params_json || {}).map(([key, value]) => (
                        <Group key={key} justify="space-between" align="flex-start" gap="md" wrap="nowrap">
                          <Text size="sm" c="dimmed">{formatParamLabel(key)}</Text>
                          <Text size="sm" ta="right">{formatParamValue(value)}</Text>
                        </Group>
                      ))
                    ) : (
                      <Text size="sm">无额外参数（系统使用默认策略）</Text>
                    )}
                  </Stack>
                  {detailQuery.data.last_triggered_at ? (
                    <Stack
                      gap={6}
                      p="sm"
                      bg="var(--mantine-color-gray-0)"
                      bd="1px solid var(--mantine-color-gray-2)"
                      style={{ borderRadius: "var(--mantine-radius-md)" }}
                    >
                      <Text c="dimmed" size="xs">上次执行结果</Text>
                      {latestExecutionQuery.isLoading ? (
                        <Text size="sm" c="dimmed">正在读取上次执行结果…</Text>
                      ) : latestExecutionQuery.data ? (
                        <>
                          <Group justify="space-between" align="center">
                            <Text size="sm" c="dimmed">执行状态</Text>
                            <StatusBadge value={latestExecutionQuery.data.status} />
                          </Group>
                          <Group justify="space-between" align="center">
                            <Text size="sm" c="dimmed">触发时间</Text>
                            <Text size="sm" ff="IBM Plex Mono, SFMono-Regular, monospace">
                              {formatDateTimeLabel(latestExecutionQuery.data.requested_at)}
                            </Text>
                          </Group>
                          <Group justify="space-between" align="center">
                            <Text size="sm" c="dimmed">读取/写入</Text>
                            <Text size="sm">
                              {latestExecutionQuery.data.rows_fetched}/{latestExecutionQuery.data.rows_written}
                            </Text>
                          </Group>
                          {latestExecutionQuery.data.summary_message ? (
                            <Text size="sm">{latestExecutionQuery.data.summary_message}</Text>
                          ) : null}
                          <Button
                            component="a"
                            href={`/app/ops/tasks/${latestExecutionQuery.data.id}`}
                            size="xs"
                            variant="light"
                            color="brand"
                          >
                            查看上次任务详情
                          </Button>
                        </>
                      ) : (
                        <Text size="sm" c="dimmed">该任务已有触发记录，但暂未查到执行明细。</Text>
                      )}
                    </Stack>
                  ) : null}
                  <Button
                    component="a"
                    href={`/app/ops/manual-sync?from_schedule_id=${detailQuery.data.id}`}
                    size="sm"
                    variant="light"
                    color="brand"
                  >
                    按当前配置手动执行一次
                  </Button>
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

            <SectionCard title="最近变更" description="记录自动任务配置最近几次调整，方便快速回看。">
              {revisionsQuery.data?.items?.length ? (
                <OpsTable>
                  <Table.Thead>
                    <Table.Tr>
                      <OpsTableHeaderCell align="left" width="34%">变更动作</OpsTableHeaderCell>
                      <OpsTableHeaderCell align="left" width="26%">操作人</OpsTableHeaderCell>
                      <OpsTableHeaderCell align="left" width="40%">变更时间</OpsTableHeaderCell>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {revisionsQuery.data.items.slice(0, 5).map((item) => (
                      <Table.Tr key={item.id}>
                        <OpsTableCell align="left" width="34%">
                          <OpsTableCellText fw={600} size="sm">
                            {formatRevisionActionLabel(item.action)}
                          </OpsTableCellText>
                        </OpsTableCell>
                        <OpsTableCell align="left" width="26%">
                          <OpsTableCellText size="xs">{item.changed_by_username || "系统"}</OpsTableCellText>
                        </OpsTableCell>
                        <OpsTableCell align="left" width="40%">
                          <OpsTableCellText ff="IBM Plex Mono, SFMono-Regular, monospace" size="xs">
                            {formatDateTimeLabel(item.changed_at)}
                          </OpsTableCellText>
                        </OpsTableCell>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </OpsTable>
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
              setForm((current) => ({
                ...current,
                spec_type: specType,
                spec_key: specKey || "",
                date_mode: "single_day",
                selected_date: "",
                start_date: "",
                end_date: "",
                field_values: {},
              }));
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
            <Grid>
              <Grid.Col span={{ base: 12, sm: 7 }}>
                <DateField
                  label="执行日期"
                  placeholder="请选择日期"
                  value={form.once_date}
                  onChange={(value) => setForm((current) => ({ ...current, once_date: value }))}
                />
              </Grid.Col>
              <Grid.Col span={{ base: 12, sm: 5 }}>
                <TextInput
                  label="执行时间"
                  placeholder="HH:mm"
                  type="time"
                  value={form.once_time}
                  onChange={(event) => setForm((current) => ({ ...current, once_time: event.currentTarget.value }))}
                />
              </Grid.Col>
            </Grid>
          ) : (
            <Stack gap="sm">
              <Select
                label="重复方式"
                data={[
                  { value: "daily", label: "每天" },
                  { value: "weekly", label: "每周" },
                  { value: "monthly", label: "每月" },
                ]}
                value={form.repeat_mode}
                onChange={(value) => setForm((current) => ({ ...current, repeat_mode: (value as RepeatMode) || "daily" }))}
              />
              {form.repeat_mode === "weekly" ? (
                <MultiSelect
                  label="每周执行日"
                  data={[
                    { value: "1", label: "周一" },
                    { value: "2", label: "周二" },
                    { value: "3", label: "周三" },
                    { value: "4", label: "周四" },
                    { value: "5", label: "周五" },
                    { value: "6", label: "周六" },
                    { value: "0", label: "周日" },
                  ]}
                  value={form.repeat_weekdays}
                  onChange={(values) => setForm((current) => ({ ...current, repeat_weekdays: values }))}
                  clearable={false}
                />
              ) : null}
              {form.repeat_mode === "monthly" ? (
                <TextInput
                  label="每月几号"
                  placeholder="1-28"
                  value={form.repeat_month_day}
                  onChange={(event) => setForm((current) => ({ ...current, repeat_month_day: event.currentTarget.value }))}
                />
              ) : null}
              <TextInput
                label="执行时间"
                placeholder="HH:mm"
                type="time"
                value={form.repeat_time}
                onChange={(event) => setForm((current) => ({ ...current, repeat_time: event.currentTarget.value }))}
              />
            </Stack>
          )}
          <Select
            label="时区"
            data={[{ value: "Asia/Shanghai", label: "北京时间（默认）" }]}
            value={form.timezone}
            onChange={(value) => setForm((current) => ({ ...current, timezone: value || "Asia/Shanghai" }))}
          />

          <Accordion variant="separated" radius="md">
            <Accordion.Item value="params">
              <Accordion.Control>同步参数</Accordion.Control>
              <Accordion.Panel>
                <Stack gap="md">
                  {(supportsSingleDay || supportsDateRange) ? (
                    <Stack gap="xs">
                      <Text fw={700} size="sm">可选：固定同步日期</Text>
                      {(supportsSingleDay && supportsDateRange) ? (
                        <Group grow>
                          <Button
                            variant={form.date_mode === "single_day" ? "filled" : "light"}
                            onClick={() => setForm((current) => ({ ...current, date_mode: "single_day" }))}
                          >
                            单日
                          </Button>
                          <Button
                            variant={form.date_mode === "date_range" ? "filled" : "light"}
                            onClick={() => setForm((current) => ({ ...current, date_mode: "date_range" }))}
                          >
                            日期区间
                          </Button>
                        </Group>
                      ) : null}
                      {(supportsSingleDay && (!supportsDateRange || form.date_mode === "single_day")) ? (
                        <DateField
                          label="同步日期（可留空）"
                          placeholder="留空表示按系统自动判断业务日期"
                          value={form.selected_date}
                          onChange={(value) =>
                            setForm((current) => ({
                              ...current,
                              selected_date: value,
                              start_date: value,
                              end_date: value,
                            }))
                          }
                        />
                      ) : null}
                      {(supportsDateRange && (!supportsSingleDay || form.date_mode === "date_range")) ? (
                        <Grid>
                          <Grid.Col span={{ base: 12, sm: 6 }}>
                            <DateField
                              label="开始日期（可留空）"
                              placeholder="留空表示按系统自动判断业务日期"
                              value={form.start_date}
                              onChange={(value) => setForm((current) => ({ ...current, start_date: value }))}
                            />
                          </Grid.Col>
                          <Grid.Col span={{ base: 12, sm: 6 }}>
                            <DateField
                              label="结束日期（可留空）"
                              placeholder="留空表示按系统自动判断业务日期"
                              value={form.end_date}
                              onChange={(value) => setForm((current) => ({ ...current, end_date: value }))}
                            />
                          </Grid.Col>
                        </Grid>
                      ) : null}
                    </Stack>
                  ) : null}

                  {selectedJobParamSpecs.length ? (
                    <Stack gap="xs">
                      <Text fw={700} size="sm">可选：附加筛选条件</Text>
                      <Grid>
                        {selectedJobParamSpecs.map((param) => (
                          <Grid.Col key={param.key} span={{ base: 12, md: 6 }}>
                            {(param.param_type === "enum" && param.multi_value) ? (
                              <Checkbox.Group
                                label={param.display_name}
                                description={param.description}
                                value={
                                  Array.isArray(form.field_values[param.key])
                                    ? (form.field_values[param.key] as string[])
                                    : String(form.field_values[param.key] || "")
                                      .split(",")
                                      .map((item) => item.trim())
                                      .filter(Boolean)
                                }
                                onChange={(values) =>
                                  setForm((current) => ({
                                    ...current,
                                    field_values: { ...current.field_values, [param.key]: values },
                                  }))
                                }
                              >
                                <Stack gap={6} mt="xs">
                                  {normalizeParamOptions(param.options).map((option) => (
                                    <Checkbox key={option} value={option} label={option} />
                                  ))}
                                </Stack>
                              </Checkbox.Group>
                            ) : param.param_type === "enum" ? (
                              <Select
                                label={param.display_name}
                                placeholder={param.description}
                                data={normalizeParamOptions(param.options).map((option) => ({
                                  value: option,
                                  label: option,
                                }))}
                                value={
                                  Array.isArray(form.field_values[param.key])
                                    ? ((form.field_values[param.key] as string[])[0] || null)
                                    : (form.field_values[param.key] as string) || null
                                }
                                onChange={(value) =>
                                  setForm((current) => ({
                                    ...current,
                                    field_values: { ...current.field_values, [param.key]: value || "" },
                                  }))
                                }
                              />
                            ) : (
                              <TextInput
                                label={param.display_name}
                                placeholder={param.description}
                                value={Array.isArray(form.field_values[param.key]) ? "" : (form.field_values[param.key] as string) || ""}
                                onChange={(event) =>
                                  setForm((current) => ({
                                    ...current,
                                    field_values: { ...current.field_values, [param.key]: event.currentTarget.value },
                                  }))
                                }
                              />
                            )}
                          </Grid.Col>
                        ))}
                      </Grid>
                    </Stack>
                  ) : null}
                  <Alert color="indigo" variant="light" title="系统将按以下参数执行（只读）">
                    <Stack gap={6}>
                      <Text size="sm">调度策略：{resolvedScheduleSummary.title}，{resolvedScheduleSummary.detail}</Text>
                      {resolvedScheduleSummary.cronExpr ? (
                        <Text size="xs" c="dimmed">内部规则：{resolvedScheduleSummary.cronExpr}</Text>
                      ) : null}
                      <Text size="sm">同步参数：</Text>
                      <Text component="pre" ff="monospace" fz={12} style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                        {JSON.stringify(resolvedParamsJson, null, 2)}
                      </Text>
                    </Stack>
                  </Alert>
                </Stack>
              </Accordion.Panel>
            </Accordion.Item>
          </Accordion>

          <Group justify="flex-end">
            <Button loading={saveMutation.isPending} onClick={() => saveMutation.mutate()}>
              {form.id ? "保存修改" : "创建自动任务"}
            </Button>
          </Group>

          {previewQuery.data ? (
            <Alert color="blue" variant="light" title="预览未来 5 次运行时间（自动更新）">
              <Stack gap={4}>
                {previewQuery.data.preview_times.map((item) => (
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
