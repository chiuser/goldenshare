import {
  Accordion,
  Badge,
  Button,
  Checkbox,
  Grid,
  Group,
  Loader,
  MultiSelect,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useDisclosure } from "@mantine/hooks";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { useTradeCalendarField } from "../features/trade-calendar/use-trade-calendar";
import { apiRequest } from "../shared/api/client";
import type {
  OpsCatalogResponse,
  ProbeRuleListResponse,
  ScheduleDetailResponse,
  ScheduleListResponse,
  SchedulePreviewResponse,
  ScheduleRevisionListResponse,
  TaskRunListResponse,
} from "../shared/api/types";
import { formatDateTimeLabel } from "../shared/date-format";
import { buildManualTaskHref } from "../shared/ops-links";
import {
  formatRevisionActionLabel,
  formatScheduleTypeLabel,
  formatTimezoneLabel,
} from "../shared/ops-display";
import { usePersistentState } from "../shared/hooks/use-persistent-state";
import { DateField, type DateSelectionRule } from "../shared/ui/date-field";
import { useAuth } from "../features/auth/auth-context";
import { ActionSummaryCard } from "../shared/ui/action-summary-card";
import { ActivityTimeline } from "../shared/ui/activity-timeline";
import { AlertBar } from "../shared/ui/alert-bar";
import { DataTable, type DataTableColumn } from "../shared/ui/data-table";
import { DetailDrawer } from "../shared/ui/detail-drawer";
import { EmptyState } from "../shared/ui/empty-state";
import { MonthField } from "../shared/ui/month-field";
import { OpsTableCellText } from "../shared/ui/ops-table";
import { SectionCard } from "../shared/ui/section-card";
import { StatCard } from "../shared/ui/stat-card";
import { StatusBadge } from "../shared/ui/status-badge";
import { TradeDateField } from "../shared/ui/trade-date-field";

type DateMode = "single_day" | "date_range";
type CatalogAction = OpsCatalogResponse["actions"][number];
type DatasetCatalogAction = CatalogAction & {
  action_type: "dataset_action";
  target_key: string;
  target_display_name: string;
};
type CatalogWorkflow = OpsCatalogResponse["workflows"][number];
type CatalogSource = OpsCatalogResponse["sources"][number];
type CatalogActionParameter = NonNullable<OpsCatalogResponse["actions"][number]["parameters"]>[number];
type RepeatMode = "daily" | "weekly" | "monthly";
type TriggerMode = "schedule" | "probe" | "schedule_probe_fallback";

const INTERNAL_PARAM_KEYS = new Set(["offset", "limit"]);
const DATE_PARAM_KEYS = new Set(["trade_date", "start_date", "end_date"]);
const PARAM_RESERVED_KEYS = new Set(["dataset_key", "action", "time_input", "filters"]);
const DEFAULT_PARAM_LABELS = new Map([
  ["trade_date", "维护日期"],
  ["start_date", "开始日期"],
  ["end_date", "结束日期"],
  ["month", "月份"],
  ["start_month", "开始月份"],
  ["end_month", "结束月份"],
  ["ann_date", "公告日期"],
]);

const emptyForm = {
  id: null as number | null,
  action_type: "dataset_action",
  action_key: "",
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
  trigger_mode: "schedule" as TriggerMode,
  probe_source_key: "tushare",
  probe_window_start: "15:30",
  probe_window_end: "17:00",
  probe_interval_seconds: "300",
  probe_max_triggers_per_day: "1",
  probe_condition_kind: "freshness_latest_open",
  probe_min_rows_in: "",
  workflow_probe_dataset_keys: [] as string[],
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

function DetailInfoPanel({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <Paper withBorder radius="md" p="sm" style={{ minHeight: "100%" }}>
      <Stack gap={6}>
        <Text c="dimmed" size="xs">
          {label}
        </Text>
        {children}
      </Stack>
    </Paper>
  );
}

function formatTriggerModeLabel(triggerMode: string): string {
  if (triggerMode === "probe") return "探测触发";
  if (triggerMode === "schedule_probe_fallback") return "定时 + 探测兜底";
  return "定时触发";
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

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
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

function buildReadableParamRows(params: Record<string, unknown>, labelMap: Map<string, string>) {
  const rows: Array<{ key: string; label: string; value: string }> = [];
  const seen = new Set<string>();
  const pushRow = (key: string, value: unknown) => {
    if (seen.has(key) || key === "mode" || value === undefined || value === null || value === "") {
      return;
    }
    seen.add(key);
    rows.push({
      key,
      label: labelMap.get(key) || DEFAULT_PARAM_LABELS.get(key) || key,
      value: formatParamValue(value),
    });
  };

  for (const [key, value] of Object.entries(params)) {
    if (!PARAM_RESERVED_KEYS.has(key)) {
      pushRow(key, value);
    }
  }
  if (isPlainRecord(params.time_input)) {
    for (const [key, value] of Object.entries(params.time_input)) {
      pushRow(key, value);
    }
  }
  if (isPlainRecord(params.filters)) {
    for (const [key, value] of Object.entries(params.filters)) {
      pushRow(key, value);
    }
  }
  return rows;
}

function getCatalogActionLabel(item: CatalogAction): string {
  if (item.action_type === "dataset_action") {
    return item.target_display_name || "数据集名称缺失";
  }
  const targetDisplayName = item.target_display_name;
  return targetDisplayName ? targetDisplayName : item.display_name;
}

function getCatalogActions(catalog: OpsCatalogResponse | undefined): CatalogAction[] {
  return Array.isArray(catalog?.actions) ? catalog.actions : [];
}

function getCatalogWorkflows(catalog: OpsCatalogResponse | undefined): CatalogWorkflow[] {
  return Array.isArray(catalog?.workflows) ? catalog.workflows : [];
}

function getCatalogSources(catalog: OpsCatalogResponse | undefined): CatalogSource[] {
  return Array.isArray(catalog?.sources) ? catalog.sources : [];
}

function getScheduleTargetLabel(item: { target_display_name?: string | null }): string {
  return item.target_display_name || "执行对象名称缺失";
}

function getSourceLabelFromCatalog(catalog: OpsCatalogResponse | undefined, sourceKey: string | null | undefined): string {
  const normalized = String(sourceKey || "").trim();
  if (!normalized || normalized === "all") {
    return "全部来源";
  }
  const source = getCatalogSources(catalog).find((item) => item.source_key === normalized);
  return source?.display_name || "来源名称缺失";
}

function toDateSelectionRule(rule: string | null | undefined): DateSelectionRule {
  if (rule === "week_last_trading_day") {
    return "week_last_trading_day";
  }
  if (rule === "month_last_trading_day" || rule === "month_end") {
    return "month_end";
  }
  return "any";
}

function findCatalogAction(catalog: OpsCatalogResponse | undefined, actionType: string, actionKey: string): CatalogAction | null {
  if (!catalog || !(actionType === "maintenance_action" || actionType === "dataset_action")) {
    return null;
  }
  return getCatalogActions(catalog).find((item) => item.action_type === actionType && item.key === actionKey) || null;
}

function findCatalogWorkflow(catalog: OpsCatalogResponse | undefined, actionType: string, actionKey: string): CatalogWorkflow | null {
  if (!catalog || actionType !== "workflow") {
    return null;
  }
  return getCatalogWorkflows(catalog).find((item) => item.key === actionKey) || null;
}

function buildParamLabelMap(
  catalog: OpsCatalogResponse | undefined,
  actionType: string,
  actionKey: string,
): Map<string, string> {
  const action = findCatalogAction(catalog, actionType, actionKey);
  const workflow = findCatalogWorkflow(catalog, actionType, actionKey);
  const params = action?.parameters || workflow?.parameters || [];
  return new Map(params.map((param) => [param.key, param.display_name]));
}

export function OpsAutomationPage() {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  const [opened, { open, close }] = useDisclosure(false);
  const [selectedScheduleId, setSelectedScheduleId] = usePersistentState<number | null>(
    "goldenshare.frontend.ops.automation.selected-id",
    null,
  );
  const [selectedActionDomain, setSelectedActionDomain] = usePersistentState<string>(
    "goldenshare.frontend.ops.automation.selected-domain",
    "",
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
        void queryClient.invalidateQueries({ queryKey: ["ops", "schedule-latest-task-run", selectedScheduleId] });
        void queryClient.invalidateQueries({ queryKey: ["ops", "schedule-probes", selectedScheduleId] });
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

  const latestTaskRunQuery = useQuery({
    queryKey: ["ops", "schedule-latest-task-run", selectedScheduleId],
    queryFn: async () => {
      const response = await apiRequest<TaskRunListResponse>(
        `/api/v1/ops/task-runs?schedule_id=${selectedScheduleId}&limit=1`,
      );
      return response.items[0] || null;
    },
    enabled: Boolean(selectedScheduleId),
  });

  const probeRulesQuery = useQuery({
    queryKey: ["ops", "schedule-probes", selectedScheduleId],
    queryFn: () => apiRequest<ProbeRuleListResponse>(`/api/v1/ops/probes?schedule_id=${selectedScheduleId}&limit=50`),
    enabled: Boolean(selectedScheduleId),
  });

  const actionItems = useMemo(() => {
    if (!catalogQuery.data) return [];
    return [
      ...getCatalogActions(catalogQuery.data)
        .filter((item) => item.schedule_enabled !== false)
        .map((item) => ({
          value: `${item.action_type}:${item.key}`,
          label: `${item.action_type === "dataset_action" ? "【数据】" : "【维护】"}${getCatalogActionLabel(item)}`,
          domain: item.domain_display_name || "其他",
        })),
      ...getCatalogWorkflows(catalogQuery.data)
        .filter((item) => item.schedule_enabled !== false)
        .map((item) => ({
          value: `workflow:${item.key}`,
          label: `【流程】${item.display_name}`,
          domain: item.domain_display_name || "工作流",
        })),
    ];
  }, [catalogQuery.data]);

  const domainOptions = useMemo(() => {
    const domains = Array.from(new Set(actionItems.map((item) => item.domain))).sort((a, b) => a.localeCompare(b, "zh-CN"));
    return domains.map((domain) => ({ value: domain, label: domain }));
  }, [actionItems]);

  const actionOptions = useMemo(
    () => actionItems.filter((item) => !selectedActionDomain || item.domain === selectedActionDomain),
    [selectedActionDomain, actionItems],
  );

  useEffect(() => {
    if (!form.action_key) {
      return;
    }
    const value = `${form.action_type}:${form.action_key}`;
    const matched = actionItems.find((item) => item.value === value);
    if (!matched) {
      return;
    }
    if (selectedActionDomain !== matched.domain) {
      setSelectedActionDomain(matched.domain);
    }
  }, [form.action_key, form.action_type, selectedActionDomain, setSelectedActionDomain, actionItems]);

  const selectedAction = useMemo(
    () =>
      ((form.action_type === "maintenance_action" || form.action_type === "dataset_action") && catalogQuery.data && form.action_key)
        ? (getCatalogActions(catalogQuery.data).find((item) => item.action_type === form.action_type && item.key === form.action_key) || null)
        : null,
    [catalogQuery.data, form.action_key, form.action_type],
  );
  const detailParamLabelMap = useMemo(
    () =>
      buildParamLabelMap(
        catalogQuery.data,
        detailQuery.data?.target_type || "",
        detailQuery.data?.target_key || "",
      ),
    [catalogQuery.data, detailQuery.data?.target_key, detailQuery.data?.target_type],
  );
  const selectedActionDateRule = useMemo<DateSelectionRule>(() => {
    if (!selectedAction) {
      return "any";
    }
    return toDateSelectionRule(selectedAction.date_selection_rule);
  }, [selectedAction]);
  const singleTradeCalendar = useTradeCalendarField({ value: form.selected_date });
  const rangeStartTradeCalendar = useTradeCalendarField({ value: form.start_date });
  const rangeEndTradeCalendar = useTradeCalendarField({ value: form.end_date });

  const selectedActionParameters = useMemo<CatalogActionParameter[]>(
    () =>
      form.action_type === "maintenance_action"
      || form.action_type === "dataset_action"
        ? (selectedAction?.parameters || []).filter(
          (param) => !INTERNAL_PARAM_KEYS.has(param.key) && !DATE_PARAM_KEYS.has(param.key),
        )
        : [],
    [form.action_type, selectedAction],
  );

  const workflowProbeDatasetOptions = useMemo(
    () =>
      getCatalogActions(catalogQuery.data)
        .filter(isDatasetCatalogAction)
        .map((item) => ({
          value: item.target_key,
          label: getCatalogActionLabel(item),
        }))
        .sort((a, b) => a.label.localeCompare(b.label, "zh-CN")),
    [catalogQuery.data],
  );

  const probeSourceOptions = useMemo(
    () => [
      ...getCatalogSources(catalogQuery.data).map((item) => ({
        value: item.source_key,
        label: item.display_name,
      })),
      { value: "all", label: "全部来源" },
    ],
    [catalogQuery.data],
  );

  const supportsSingleDay = useMemo(
    () =>
      (form.action_type === "maintenance_action" || form.action_type === "dataset_action")
      && Boolean(selectedAction?.parameters?.some((param) => param.key === "trade_date")),
    [form.action_type, selectedAction],
  );
  const supportsDateRange = useMemo(
    () =>
        (form.action_type === "maintenance_action" || form.action_type === "dataset_action")
      && Boolean(
        selectedAction?.parameters?.some((param) => param.key === "start_date")
        && selectedAction?.parameters?.some((param) => param.key === "end_date"),
      ),
    [form.action_type, selectedAction],
  );

  const resolvedParamsJson = useMemo(() => {
    const params: Record<string, unknown> = {};
    for (const param of selectedActionParameters) {
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
    if (form.action_type === "dataset_action" && selectedAction) {
      if (!selectedAction.target_key) {
        return params;
      }
      const datasetKey = selectedAction.target_key;
      const timeKeys = new Set(["trade_date", "start_date", "end_date", "month", "start_month", "end_month", "ann_date"]);
      const filters = Object.fromEntries(Object.entries(params).filter(([key]) => !timeKeys.has(key)));
      const timeInput: Record<string, unknown> = {};
      if (params.trade_date) {
        timeInput.mode = "point";
        timeInput.trade_date = params.trade_date;
      } else if (params.month) {
        timeInput.mode = "point";
        timeInput.month = params.month;
      } else if (params.start_date || params.end_date) {
        timeInput.mode = "range";
        timeInput.start_date = params.start_date;
        timeInput.end_date = params.end_date;
      } else if (params.start_month || params.end_month) {
        timeInput.mode = "range";
        timeInput.start_month = params.start_month;
        timeInput.end_month = params.end_month;
      } else if (supportsSingleDay) {
        timeInput.mode = "point";
      } else {
        timeInput.mode = "none";
      }
      return {
        ...params,
        dataset_key: datasetKey,
        action: "maintain",
        time_input: timeInput,
        filters,
      };
    }
    return params;
  }, [
    form.date_mode,
    form.end_date,
    form.field_values,
    form.selected_date,
    form.action_type,
    form.start_date,
    selectedActionParameters,
    selectedAction,
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

  const resolvedParameterRows = useMemo(() => {
    const labelMap = new Map(selectedActionParameters.map((param) => [param.key, param.display_name]));
    return buildReadableParamRows(resolvedParamsJson, labelMap);
  }, [resolvedParamsJson, selectedActionParameters]);

  const detailParameterRows = useMemo(() => (
    buildReadableParamRows(detailQuery.data?.params_json || {}, detailParamLabelMap)
  ), [detailParamLabelMap, detailQuery.data?.params_json]);

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

  const scheduleColumns = useMemo<DataTableColumn<ScheduleListResponse["items"][number]>[]>(() => [
    {
      key: "display_name",
      header: "任务名称",
      align: "left",
      width: "26%",
      render: (item) => <OpsTableCellText fw={600} size="sm">{item.display_name}</OpsTableCellText>,
    },
    {
      key: "target",
      header: "执行对象",
      align: "left",
      width: "28%",
      render: (item) => <OpsTableCellText size="xs">{getScheduleTargetLabel(item)}</OpsTableCellText>,
    },
    {
      key: "status",
      header: "当前状态",
      width: "14%",
      render: (item) => <StatusBadge value={item.status} />,
    },
    {
      key: "schedule_type",
      header: "执行方式",
      width: "12%",
      render: (item) => <OpsTableCellText size="xs">{formatScheduleTypeLabel(item.schedule_type)}</OpsTableCellText>,
    },
    {
      key: "next_run_at",
      header: "下次运行",
      align: "left",
      width: "20%",
      render: (item) => (
        <OpsTableCellText ff="var(--mantine-font-family-monospace)" fw={500} size="xs">
          {formatDateTimeLabel(item.next_run_at)}
        </OpsTableCellText>
      ),
    },
  ], []);

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
      if (form.trigger_mode !== "schedule" && form.action_type === "workflow" && form.workflow_probe_dataset_keys.length === 0) {
        throw new Error("工作流使用探测触发时，请至少选择一个探测目标数据集。");
      }
      if (form.action_type === "dataset_action" && !selectedAction?.target_key) {
        throw new Error("当前数据集动作缺少维护对象，请刷新后重试。");
      }
      const scheduleType = form.schedule_type;
      const cronExpr = scheduleType === "cron"
        ? buildCronExpression(form.repeat_mode, form.repeat_time, form.repeat_weekdays, form.repeat_month_day)
        : null;
      const nextRunAt = scheduleType === "once" ? buildOnceRunAt(form.once_date, form.once_time) : null;
      const body = {
        target_type: form.action_type,
        target_key: form.action_key,
        display_name: form.display_name,
        schedule_type: scheduleType,
        trigger_mode: form.trigger_mode,
        cron_expr: cronExpr,
        timezone: form.timezone,
        calendar_policy: form.calendar_policy || null,
        next_run_at: nextRunAt,
        probe_config:
          form.trigger_mode === "schedule"
            ? null
            : {
              source_key: form.probe_source_key || null,
              window_start: form.probe_window_start || null,
              window_end: form.probe_window_end || null,
              probe_interval_seconds: Number(form.probe_interval_seconds || "300"),
              max_triggers_per_day: Number(form.probe_max_triggers_per_day || "1"),
              condition_kind: form.probe_condition_kind || "freshness_latest_open",
              min_rows_in: form.probe_min_rows_in ? Number(form.probe_min_rows_in) : null,
              workflow_dataset_keys:
                form.action_type === "workflow"
                  ? form.workflow_probe_dataset_keys
                  : [],
            },
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
        color: "success",
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
        queryClient.invalidateQueries({ queryKey: ["ops", "schedule-probes", data.id] }),
        queryClient.invalidateQueries({ queryKey: ["ops", "catalog"] }),
      ]);
    },
    onError: (error) => {
      notifications.show({
        color: "error",
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
        color: "success",
        title: data.status === "active" ? "自动任务已恢复" : "自动任务已暂停",
        message: data.display_name,
      });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ops", "schedules"] }),
        queryClient.invalidateQueries({ queryKey: ["ops", "schedule", data.id] }),
        queryClient.invalidateQueries({ queryKey: ["ops", "schedule-revisions", data.id] }),
        queryClient.invalidateQueries({ queryKey: ["ops", "schedule-probes", data.id] }),
        queryClient.invalidateQueries({ queryKey: ["ops", "catalog"] }),
      ]);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async () => apiRequest<{ id: number; status: string }>(`/api/v1/ops/schedules/${selectedScheduleId}`, {
      method: "DELETE",
    }),
    onSuccess: async (data) => {
      notifications.show({
        color: "success",
        title: "自动任务已删除",
        message: `任务 #${data.id}`,
      });
      setSelectedScheduleId(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ops", "schedules"] }),
        queryClient.invalidateQueries({ queryKey: ["ops", "schedule-probes"] }),
        queryClient.invalidateQueries({ queryKey: ["ops", "catalog"] }),
      ]);
    },
    onError: (error) => {
      notifications.show({
        color: "error",
        title: "删除自动任务失败",
        message: error instanceof Error ? error.message : "未知错误",
      });
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
    const probeConfig = detail.probe_config || null;
    setForm({
      id: detail.id,
      action_type: detail.target_type,
      action_key: detail.target_key,
      display_name: detail.display_name,
      schedule_type: detail.schedule_type,
      trigger_mode: (detail.trigger_mode as TriggerMode) || "schedule",
      timezone: detail.timezone,
      calendar_policy: detail.calendar_policy || "",
      once_date: nextRunAt ? nextRunAt.slice(0, 10) : "",
      once_time: nextRunAt ? nextRunAt.slice(11, 16) : "19:00",
      repeat_mode: parsedCron?.repeatMode || "daily",
      repeat_weekdays: parsedCron?.repeatWeekdays || ["1", "2", "3", "4", "5"],
      repeat_month_day: parsedCron?.repeatMonthDay || "1",
      repeat_time: parsedCron?.repeatTime || "19:00",
      probe_source_key: probeConfig?.source_key || "tushare",
      probe_window_start: probeConfig?.window_start || "15:30",
      probe_window_end: probeConfig?.window_end || "17:00",
      probe_interval_seconds: String(probeConfig?.probe_interval_seconds || 300),
      probe_max_triggers_per_day: String(probeConfig?.max_triggers_per_day || 1),
      probe_condition_kind: probeConfig?.condition_kind || "freshness_latest_open",
      probe_min_rows_in: probeConfig?.min_rows_in != null ? String(probeConfig.min_rows_in) : "",
      workflow_probe_dataset_keys: probeConfig?.workflow_dataset_keys || [],
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
      <Group justify="flex-end" align="center">
        <Button onClick={openCreate}>新建自动任务</Button>
      </Group>

      {(catalogQuery.isLoading || schedulesQuery.isLoading) ? <Loader size="sm" /> : null}
      {catalogQuery.error || schedulesQuery.error ? (
        <AlertBar tone="error" title="无法读取自动运行配置">
          {(catalogQuery.error || schedulesQuery.error) instanceof Error
            ? ((catalogQuery.error || schedulesQuery.error) as Error).message
            : "未知错误"}
        </AlertBar>
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
            <DataTable
              columns={scheduleColumns}
              emptyState={(
                <EmptyState
                  title="还没有自动任务"
                  description="你可以先新建一个自动任务，让系统在固定时间自动维护数据。"
                  action={<Button onClick={openCreate}>立即新建</Button>}
                />
              )}
              getRowKey={(item) => item.id}
              getRowProps={(item) => ({
                onClick: () => setSelectedScheduleId(item.id),
                style: {
                  cursor: "pointer",
                  background: selectedScheduleId === item.id ? "rgba(72, 149, 239, 0.10)" : undefined,
                },
              })}
              rows={schedulesQuery.data?.items || []}
            />
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
                      color={detailQuery.data.status === "active" ? "warning" : "brand"}
                      onClick={() =>
                        toggleMutation.mutate(detailQuery.data?.status === "active" ? "pause" : "resume")
                      }
                    >
                      {detailQuery.data.status === "active" ? "暂停自动运行" : "恢复自动运行"}
                    </Button>
                    <Button
                      color="error"
                      variant="light"
                      loading={deleteMutation.isPending}
                      onClick={() => {
                        if (!detailQuery.data) return;
                        const confirmed = window.confirm(`确认删除自动任务“${detailQuery.data.display_name}”？删除后无法恢复。`);
                        if (!confirmed) return;
                        deleteMutation.mutate();
                      }}
                    >
                      删除任务
                    </Button>
                  </Group>
                ) : undefined
              }
            >
              {detailQuery.isLoading ? <Loader size="sm" /> : null}
              {detailQuery.data ? (
                <Stack gap="md">
                  <Text fw={600} size="lg">{detailQuery.data.display_name}</Text>
                  <Group gap="xs">
                    <StatusBadge value={detailQuery.data.status} />
                    <Badge variant="light">{formatScheduleTypeLabel(detailQuery.data.schedule_type)}</Badge>
                    <Badge variant="light" color="info">{formatTriggerModeLabel(detailQuery.data.trigger_mode)}</Badge>
                    <Badge variant="light">{formatTimezoneLabel(detailQuery.data.timezone)}</Badge>
                  </Group>
                  <Grid gutter="sm">
                    <Grid.Col span={{ base: 12, sm: 6 }}>
                      <DetailInfoPanel label="执行对象">
                        <Text size="sm">{getScheduleTargetLabel(detailQuery.data)}</Text>
                      </DetailInfoPanel>
                    </Grid.Col>
                    <Grid.Col span={{ base: 12, sm: 6 }}>
                      <DetailInfoPanel label="下次运行">
                        <Text ff="var(--mantine-font-family-monospace)" size="sm">
                          {formatDateTimeLabel(detailQuery.data.next_run_at)}
                        </Text>
                      </DetailInfoPanel>
                    </Grid.Col>
                    <Grid.Col span={{ base: 12, sm: 6 }}>
                      <DetailInfoPanel label="上次触发">
                        <Text ff="var(--mantine-font-family-monospace)" size="sm">
                          {formatDateTimeLabel(detailQuery.data.last_triggered_at)}
                        </Text>
                      </DetailInfoPanel>
                    </Grid.Col>
                    <Grid.Col span={{ base: 12, sm: 6 }}>
                      <DetailInfoPanel label="调度策略">
                        <Text size="sm">
                          {formatScheduleRule(detailQuery.data.schedule_type, detailQuery.data.cron_expr, detailQuery.data.next_run_at)}
                        </Text>
                      </DetailInfoPanel>
                    </Grid.Col>
                    <Grid.Col span={{ base: 12, sm: 6 }}>
                      <DetailInfoPanel label="触发方式">
                        <Text size="sm">{formatTriggerModeLabel(detailQuery.data.trigger_mode)}</Text>
                      </DetailInfoPanel>
                    </Grid.Col>
                  </Grid>
                  {(detailQuery.data.trigger_mode !== "schedule" && detailQuery.data.probe_config) ? (
                    <DetailInfoPanel label="探测配置">
                      <Group justify="space-between"><Text size="sm" c="dimmed">探测窗口</Text><Text size="sm">{detailQuery.data.probe_config.window_start || "—"} ~ {detailQuery.data.probe_config.window_end || "—"}</Text></Group>
                      <Group justify="space-between"><Text size="sm" c="dimmed">探测频率</Text><Text size="sm">{detailQuery.data.probe_config.probe_interval_seconds} 秒</Text></Group>
                      <Group justify="space-between"><Text size="sm" c="dimmed">每日触发上限</Text><Text size="sm">{detailQuery.data.probe_config.max_triggers_per_day}</Text></Group>
                      <Group justify="space-between"><Text size="sm" c="dimmed">探测来源</Text><Text size="sm">{detailQuery.data.probe_config.source_display_name || "全部来源"}</Text></Group>
                      {detailQuery.data.target_type === "workflow" ? (
                        <Group justify="space-between" align="flex-start">
                          <Text size="sm" c="dimmed">工作流探测目标</Text>
                          <Text size="sm" ta="right">
                            {(detailQuery.data.probe_config.workflow_dataset_targets || []).length
                              ? (detailQuery.data.probe_config.workflow_dataset_targets || [])
                                .map((item) => item.dataset_display_name || "数据集名称缺失")
                                .join("、")
                              : "未配置"}
                          </Text>
                        </Group>
                      ) : null}
                    </DetailInfoPanel>
                  ) : null}
                  {(detailQuery.data.trigger_mode !== "schedule") ? (
                    <DetailInfoPanel label="探测规则运行状态">
                      {probeRulesQuery.isLoading ? <Text size="sm" c="dimmed">正在读取探测规则…</Text> : null}
                      {probeRulesQuery.data?.items?.length ? (
                        probeRulesQuery.data.items.map((rule) => (
                          <Group key={rule.id} justify="space-between" align="center">
                            <Text size="sm">{rule.dataset_display_name || "数据集名称缺失"}</Text>
                            <Group gap={6}>
                              <StatusBadge value={rule.status} />
                              <Text size="xs" c="dimmed">最近探测：{formatDateTimeLabel(rule.last_probed_at)}</Text>
                              <Text size="xs" c="dimmed">最近命中：{formatDateTimeLabel(rule.last_triggered_at)}</Text>
                            </Group>
                          </Group>
                        ))
                      ) : (
                        <Text size="sm" c="dimmed">当前还没有探测规则。</Text>
                      )}
                    </DetailInfoPanel>
                  ) : null}
                  <DetailInfoPanel label="任务参数">
                    {detailParameterRows.length ? (
                      detailParameterRows.map((row) => (
                        <Group key={row.key} justify="space-between" align="flex-start" gap="md" wrap="nowrap">
                          <Text size="sm" c="dimmed">{row.label}</Text>
                          <Text size="sm" ta="right">{row.value}</Text>
                        </Group>
                      ))
                    ) : (
                      <Text size="sm">无额外参数（系统使用默认策略）</Text>
                    )}
                  </DetailInfoPanel>
                  {detailQuery.data.last_triggered_at ? (
                    <DetailInfoPanel label="上次执行结果">
                      {latestTaskRunQuery.isLoading ? (
                        <Text size="sm" c="dimmed">正在读取上次执行结果…</Text>
                      ) : latestTaskRunQuery.data ? (
                        <>
                          <Group justify="space-between" align="center">
                            <Text size="sm" c="dimmed">执行状态</Text>
                            <StatusBadge value={latestTaskRunQuery.data.status} />
                          </Group>
                          <Group justify="space-between" align="center">
                            <Text size="sm" c="dimmed">触发时间</Text>
                            <Text size="sm" ff="var(--mantine-font-family-monospace)">
                              {formatDateTimeLabel(latestTaskRunQuery.data.requested_at)}
                            </Text>
                          </Group>
                          <Group justify="space-between" align="center">
                            <Text size="sm" c="dimmed">读取/保存</Text>
                            <Text size="sm">
                              {latestTaskRunQuery.data.rows_fetched}/{latestTaskRunQuery.data.rows_saved}
                            </Text>
                          </Group>
                          {latestTaskRunQuery.data.primary_issue_title ? (
                            <Text size="sm">{latestTaskRunQuery.data.primary_issue_title}</Text>
                          ) : null}
                          <Button
                            component="a"
                            href={`/app/ops/tasks/${latestTaskRunQuery.data.id}`}
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
                    </DetailInfoPanel>
                  ) : null}
                  <Button
                    component="a"
                    href={buildManualTaskHref({ fromScheduleId: detailQuery.data.id })}
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
                  { label: "执行对象", value: getScheduleTargetLabel(lastAction) },
                  { label: "当前状态", value: lastAction.status },
                  { label: "下次运行", value: formatDateTimeLabel(lastAction.next_run_at) },
                ]}
              />
            ) : null}

            <SectionCard title="最近变更" description="记录自动任务配置最近几次调整，方便快速回看。">
              {revisionsQuery.data?.items?.length ? (
                <ActivityTimeline
                  items={revisionsQuery.data.items.slice(0, 5).map((item) => ({
                    id: item.id,
                    title: formatRevisionActionLabel(item.action),
                    time: formatDateTimeLabel(item.changed_at),
                    body: (
                      <Text size="sm">
                        操作人：{item.changed_by_username || "系统"}
                      </Text>
                    ),
                  }))}
                />
              ) : (
                <Text c="dimmed" size="sm">
                  当前还没有变更记录。
                </Text>
              )}
            </SectionCard>
          </Stack>
        </Grid.Col>
      </Grid>

      <DetailDrawer
        description="统一维护调度规则、探测触发与维护参数。"
        footer={
          <>
            <Button variant="default" onClick={close}>
              取消
            </Button>
            <Button loading={saveMutation.isPending} onClick={() => saveMutation.mutate()}>
              {form.id ? "保存修改" : "创建自动任务"}
            </Button>
          </>
        }
        opened={opened}
        onClose={close}
        size="lg"
        title={form.id ? "修改自动任务" : "新建自动任务"}
      >
        <Stack gap="md">
          <TextInput
            label="任务名称"
            value={form.display_name}
            onChange={(event) => setForm((current) => ({ ...current, display_name: event.currentTarget.value }))}
          />
          <SimpleGrid cols={{ base: 1, md: 2 }}>
            <Select
              label="先选数据分组"
              placeholder="请选择分组"
              data={domainOptions}
              value={selectedActionDomain || null}
              clearable
              onChange={(value) => {
                const nextDomain = value || "";
                setSelectedActionDomain(nextDomain);
                if (!nextDomain) {
                  return;
                }
                const selectedValue = form.action_key ? `${form.action_type}:${form.action_key}` : "";
                const current = actionItems.find((item) => item.value === selectedValue);
                if (current && current.domain === nextDomain) {
                  return;
                }
                setForm((currentForm) => ({
                  ...currentForm,
                  action_type: "dataset_action",
                  action_key: "",
                  date_mode: "single_day",
                  selected_date: "",
                  start_date: "",
                  end_date: "",
                  field_values: {},
                }));
              }}
            />
            <Select
              label="再选执行对象"
              searchable
              placeholder="请选择执行对象"
              data={actionOptions}
              value={form.action_key ? `${form.action_type}:${form.action_key}` : null}
              nothingFoundMessage="没有找到匹配对象"
              onChange={(value) => {
                const [actionType, actionKey] = (value || "dataset_action:").split(":");
                const selected = actionItems.find((item) => item.value === value);
                if (selected) {
                  setSelectedActionDomain(selected.domain);
                }
                setForm((current) => ({
                  ...current,
                  action_type: actionType,
                  action_key: actionKey || "",
                  date_mode: "single_day",
                  selected_date: "",
                  start_date: "",
                  end_date: "",
                  field_values: {},
                }));
              }}
            />
          </SimpleGrid>
          <Select
            label="执行方式"
            data={form.trigger_mode === "probe"
              ? [{ value: "cron", label: "按周期执行（探测触发场景下仅用于兜底）" }]
              : [
                { value: "once", label: "单次执行" },
                { value: "cron", label: "按周期执行" },
              ]}
            value={form.schedule_type}
            onChange={(value) => setForm((current) => ({ ...current, schedule_type: value || "once" }))}
          />
          <Select
            label="触发方式"
            data={[
              { value: "schedule", label: "定时触发" },
              { value: "probe", label: "探测触发" },
              { value: "schedule_probe_fallback", label: "定时 + 探测兜底" },
            ]}
            value={form.trigger_mode}
            onChange={(value) =>
              setForm((current) => ({
                ...current,
                trigger_mode: (value as TriggerMode) || "schedule",
                schedule_type:
                  ((value as TriggerMode) === "probe" && current.schedule_type === "once")
                    ? "cron"
                    : current.schedule_type,
              }))
            }
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
          {form.trigger_mode !== "schedule" ? (
            <Stack gap="sm" p="sm" bg="var(--mantine-color-gray-0)" bd="1px solid var(--mantine-color-gray-2)" style={{ borderRadius: "var(--mantine-radius-md)" }}>
              <Text fw={700} size="sm">探测触发配置</Text>
              <SimpleGrid cols={{ base: 1, md: 2 }}>
                <Select
                  label="探测来源"
                  data={probeSourceOptions}
                  value={form.probe_source_key}
                  onChange={(value) => setForm((current) => ({ ...current, probe_source_key: value || "tushare" }))}
                />
                <Select
                  label="探测条件"
                  data={[
                    { value: "freshness_latest_open", label: "最新业务日命中最新交易日" },
                    { value: "raw_rows_min", label: "原始层写入行数达到阈值" },
                  ]}
                  value={form.probe_condition_kind}
                  onChange={(value) => setForm((current) => ({ ...current, probe_condition_kind: value || "freshness_latest_open" }))}
                />
              </SimpleGrid>
              <Grid>
                <Grid.Col span={{ base: 12, sm: 6 }}>
                  <TextInput
                    label="探测窗口开始"
                    placeholder="15:30"
                    type="time"
                    value={form.probe_window_start}
                    onChange={(event) => setForm((current) => ({ ...current, probe_window_start: event.currentTarget.value }))}
                  />
                </Grid.Col>
                <Grid.Col span={{ base: 12, sm: 6 }}>
                  <TextInput
                    label="探测窗口结束"
                    placeholder="17:00"
                    type="time"
                    value={form.probe_window_end}
                    onChange={(event) => setForm((current) => ({ ...current, probe_window_end: event.currentTarget.value }))}
                  />
                </Grid.Col>
                <Grid.Col span={{ base: 12, sm: 6 }}>
                  <TextInput
                    label="探测频率（秒）"
                    placeholder="300"
                    type="number"
                    value={form.probe_interval_seconds}
                    onChange={(event) => setForm((current) => ({ ...current, probe_interval_seconds: event.currentTarget.value }))}
                  />
                </Grid.Col>
                <Grid.Col span={{ base: 12, sm: 6 }}>
                  <TextInput
                    label="每日触发上限"
                    placeholder="1"
                    type="number"
                    value={form.probe_max_triggers_per_day}
                    onChange={(event) => setForm((current) => ({ ...current, probe_max_triggers_per_day: event.currentTarget.value }))}
                  />
                </Grid.Col>
                <Grid.Col span={12}>
                  <TextInput
                    label="最小写入行数（可选）"
                    placeholder="例如 1"
                    type="number"
                    value={form.probe_min_rows_in}
                    onChange={(event) => setForm((current) => ({ ...current, probe_min_rows_in: event.currentTarget.value }))}
                  />
                </Grid.Col>
              </Grid>
              {form.action_type === "workflow" ? (
                <MultiSelect
                  label="工作流探测目标数据集"
                  placeholder="请选择工作流探测目标（可多选）"
                  data={workflowProbeDatasetOptions}
                  value={form.workflow_probe_dataset_keys}
                  searchable
                  onChange={(values) => setForm((current) => ({ ...current, workflow_probe_dataset_keys: values }))}
                />
              ) : null}
            </Stack>
          ) : null}

          <Accordion variant="separated" radius="md">
            <Accordion.Item value="params">
              <Accordion.Control>维护参数</Accordion.Control>
              <Accordion.Panel>
                <Stack gap="md">
                  {(supportsSingleDay || supportsDateRange) ? (
                    <Stack gap="xs">
                      <Text fw={700} size="sm">可选：固定维护日期</Text>
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
                        <TradeDateField
                          {...singleTradeCalendar.calendarProps}
                          isTradingDay={singleTradeCalendar.isTradingDay}
                          label="维护日期（可留空）"
                          placeholder="留空表示按系统自动判断业务日期"
                          value={form.selected_date}
                          selectionRule={selectedActionDateRule}
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
                            <TradeDateField
                              {...rangeStartTradeCalendar.calendarProps}
                              isTradingDay={rangeStartTradeCalendar.isTradingDay}
                              label="开始日期（可留空）"
                              placeholder="留空表示按系统自动判断业务日期"
                              value={form.start_date}
                              onChange={(value) => setForm((current) => ({ ...current, start_date: value }))}
                            />
                          </Grid.Col>
                          <Grid.Col span={{ base: 12, sm: 6 }}>
                            <TradeDateField
                              {...rangeEndTradeCalendar.calendarProps}
                              isTradingDay={rangeEndTradeCalendar.isTradingDay}
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

                  {selectedActionParameters.length ? (
                    <Stack gap="xs">
                      <Text fw={700} size="sm">可选：附加筛选条件</Text>
                      <Grid>
                        {selectedActionParameters.map((param) => (
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
                            ) : param.param_type === "month" ? (
                              <MonthField
                                label={param.display_name}
                                placeholder={param.description}
                                value={Array.isArray(form.field_values[param.key]) ? "" : (form.field_values[param.key] as string) || ""}
                                onChange={(value) =>
                                  setForm((current) => ({
                                    ...current,
                                    field_values: { ...current.field_values, [param.key]: value },
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
                  <AlertBar title="系统将按以下参数执行（只读）">
                    <Stack gap={6}>
                      <Text size="sm">触发方式：{formatTriggerModeLabel(form.trigger_mode)}</Text>
                      <Text size="sm">调度策略：{resolvedScheduleSummary.title}，{resolvedScheduleSummary.detail}</Text>
                      {form.trigger_mode !== "schedule" ? (
                        <Text size="sm">
                          探测配置：{form.probe_window_start || "—"}~{form.probe_window_end || "—"}，每 {form.probe_interval_seconds || "300"} 秒探测，来源 {getSourceLabelFromCatalog(catalogQuery.data, form.probe_source_key)}
                        </Text>
                      ) : null}
                      <Text size="sm">维护参数：</Text>
                      {resolvedParameterRows.length ? (
                        <Stack gap={4}>
                          {resolvedParameterRows.map((row) => (
                            <Group key={row.key} justify="space-between" align="flex-start" gap="md" wrap="nowrap">
                              <Text size="sm" c="dimmed">{row.label}</Text>
                              <Text size="sm" ta="right">{row.value}</Text>
                            </Group>
                          ))}
                        </Stack>
                      ) : (
                        <Text size="sm" c="dimmed">未指定额外维护参数，系统将按数据集定义自动处理。</Text>
                      )}
                    </Stack>
                  </AlertBar>
                </Stack>
              </Accordion.Panel>
            </Accordion.Item>
          </Accordion>

          {previewQuery.data ? (
            <AlertBar title="预览未来 5 次运行时间（自动更新）">
              <Stack gap={4}>
                {previewQuery.data.preview_times.map((item) => (
                  <Text key={item} size="sm">
                    {formatDateTimeLabel(item)}
                  </Text>
                ))}
              </Stack>
            </AlertBar>
          ) : null}
        </Stack>
      </DetailDrawer>
    </Stack>
  );
}
