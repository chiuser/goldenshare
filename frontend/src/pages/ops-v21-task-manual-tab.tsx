import {
  Badge,
  Button,
  Checkbox,
  Radio,
  Grid,
  Group,
  Loader,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";

import { useTradeCalendarField } from "../features/trade-calendar/use-trade-calendar";
import { apiRequest } from "../shared/api/client";
import type {
  OpsManualActionsResponse,
  OpsManualActionTaskRunRequest,
  ScheduleDetailResponse,
  TaskRunListResponse,
  TaskRunViewResponse,
} from "../shared/api/types";
import { usePersistentState } from "../shared/hooks/use-persistent-state";
import { AlertBar } from "../shared/ui/alert-bar";
import { DateField, type DateSelectionRule } from "../shared/ui/date-field";
import { EmptyState } from "../shared/ui/empty-state";
import { MonthField } from "../shared/ui/month-field";
import { SectionCard } from "../shared/ui/section-card";
import { TradeDateField } from "../shared/ui/trade-date-field";

type ManualActionGroup = OpsManualActionsResponse["groups"][number];
type ManualActionApiItem = ManualActionGroup["actions"][number];
type ManualActionFilter = ManualActionApiItem["filters"][number];
type ManualAction = ManualActionApiItem & {
  groupKey: string;
  groupLabel: string;
};
type ManualDateMode = "single_point" | "time_range";

type ActionGuidance = {
  title: string;
  lines: string[];
};

type CreateRecoveryState = {
  actionName: string;
  resourceKey: string | null;
  submittedAtMs: number;
};

const MANUAL_DRAFT_STORAGE_KEY = "goldenshare.frontend.ops.task-center.manual.draft";
const MANUAL_DOMAIN_STORAGE_KEY = "goldenshare.frontend.ops.task-center.manual.domain";
const MANUAL_RECENT_ACTIONS_STORAGE_KEY = "goldenshare.frontend.ops.task-center.manual.recent-actions";

function buildEmptyDraft() {
  return {
    action_id: "",
    date_mode: "single_point" as ManualDateMode,
    selected_date: "",
    start_date: "",
    end_date: "",
    selected_month: "",
    start_month: "",
    end_month: "",
    field_values: {} as Record<string, string | string[]>,
  };
}

type ManualDraft = ReturnType<typeof buildEmptyDraft>;

function normalizeParamOptions(options: string[] | undefined) {
  return Array.isArray(options) ? options : [];
}

function isEmptyFieldValue(value: string | string[] | undefined) {
  if (value === undefined || value === null) {
    return true;
  }
  if (Array.isArray(value)) {
    return value.filter(Boolean).length === 0;
  }
  return String(value).trim() === "";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function getDefaultFieldValue(action: ManualAction, param: ManualActionFilter): string | string[] | undefined {
  if (action.action_key !== "dc_hot") {
    return undefined;
  }
  const options = normalizeParamOptions(param.options);
  if (param.key === "market" || param.key === "hot_type") {
    return options;
  }
  if (param.key === "is_new") {
    return options.includes("Y") ? "Y" : options[0] || undefined;
  }
  return undefined;
}

function buildDefaultFieldValues(action: ManualAction) {
  const defaults: Record<string, string | string[]> = {};
  for (const param of action.filters) {
    const value = getDefaultFieldValue(action, param);
    if (value !== undefined && !isEmptyFieldValue(value)) {
      defaults[param.key] = value;
    }
  }
  return defaults;
}

function mergeDefaultFieldValues(action: ManualAction, fieldValues: Record<string, string | string[]>) {
  const merged = { ...fieldValues };
  for (const [key, value] of Object.entries(buildDefaultFieldValues(action))) {
    if (isEmptyFieldValue(merged[key])) {
      merged[key] = value;
    }
  }
  return merged;
}

function flattenManualActions(response: OpsManualActionsResponse | undefined): ManualAction[] {
  if (!response) {
    return [];
  }
  return response.groups.flatMap((group) =>
    group.actions.map((action) => ({
      ...action,
      groupKey: group.group_key,
      groupLabel: group.group_label,
    })),
  );
}

function getActionDomain(action: Pick<ManualAction, "groupLabel"> | { domainLabel?: string } | null) {
  if (!action) {
    return "";
  }
  return "groupLabel" in action ? action.groupLabel : action.domainLabel || "";
}

function normalizeDraftActionId(actionId: string) {
  if (actionId.startsWith("job:")) {
    return actionId.slice(4);
  }
  return actionId;
}

function findManualAction(actions: ManualAction[], actionId: string) {
  const normalized = normalizeDraftActionId(actionId);
  return actions.find((action) => action.action_key === normalized) || null;
}

function matchesActionSpec(action: ManualAction, specType: string | null, specKey: string | null) {
  if (!specKey) {
    return false;
  }
  if (specType && action.action_type !== specType) {
    return false;
  }
  return action.route_spec_keys.includes(specKey);
}

export function shouldAutoAlignDomain(selectedDomain: string, selectedAction: ManualAction | { domainLabel?: string } | null) {
  return Boolean(selectedAction && !selectedDomain);
}

export function resolveDraftOnDomainChange(current: ManualDraft, nextDomain: string, manualActions: ManualAction[]) {
  if (!current.action_id) {
    return current;
  }
  const currentAction = findManualAction(manualActions, current.action_id);
  if (!currentAction) {
    return buildEmptyDraft();
  }
  if (!nextDomain || getActionDomain(currentAction) === nextDomain) {
    return current;
  }
  return buildEmptyDraft();
}

function hasTimeInput(action: ManualAction) {
  return action.time_form.control !== "none" && !action.time_form.allowed_modes.includes("none");
}

function supportsPoint(action: ManualAction) {
  return action.time_form.allowed_modes.includes("point");
}

function supportsRange(action: ManualAction) {
  return action.time_form.allowed_modes.includes("range");
}

function isSinglePoint(action: ManualAction, draft: ManualDraft) {
  if (supportsPoint(action) && supportsRange(action)) {
    return draft.date_mode === "single_point";
  }
  return supportsPoint(action);
}

function inferSinglePointDateRule(action: ManualAction | null): DateSelectionRule {
  if (!action) {
    return "any";
  }
  if (action.time_form.selection_rule === "week_last_trading_day") {
    return "week_last_trading_day";
  }
  if (action.time_form.selection_rule === "month_last_trading_day") {
    return "month_end";
  }
  return "any";
}

function isCalendarDateAction(action: ManualAction) {
  return action.time_form.control === "calendar_date_or_range";
}

function isMonthAction(action: ManualAction) {
  return action.time_form.control === "month_or_range" || action.time_form.control === "month_window_range";
}

function buildFieldValues(paramsJson: unknown) {
  if (!isRecord(paramsJson)) {
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

function buildDraftFromParams(
  current: ManualDraft,
  action: ManualAction,
  paramsJson: unknown,
) {
  const params = isRecord(paramsJson) ? paramsJson : {};
  const fieldValues = buildFieldValues(paramsJson);
  const tradeDate = typeof params.trade_date === "string" ? params.trade_date : "";
  const annDate = typeof params.ann_date === "string" ? params.ann_date : "";
  const startDate = typeof params.start_date === "string" ? params.start_date : "";
  const endDate = typeof params.end_date === "string" ? params.end_date : "";
  const month = typeof params.month === "string" ? params.month : "";
  const startMonth = typeof params.start_month === "string" ? params.start_month : "";
  const endMonth = typeof params.end_month === "string" ? params.end_month : "";
  const dateMode: ManualDateMode = (tradeDate || annDate || month) ? "single_point" : "time_range";
  return {
    ...current,
    action_id: action.action_key,
    date_mode: dateMode,
    selected_date: tradeDate || annDate || startDate || current.selected_date,
    start_date: startDate,
    end_date: endDate,
    selected_month: month || startMonth || current.selected_month,
    start_month: startMonth,
    end_month: endMonth,
    field_values: mergeDefaultFieldValues(action, fieldValues),
  };
}

function buildPrefillParamsFromTaskRun(view: TaskRunViewResponse): Record<string, unknown> {
  const filters = isRecord(view.run.filters) ? view.run.filters : {};
  const timeInput = isRecord(view.run.time_input) ? view.run.time_input : {};
  return {
    ...filters,
    ...timeInput,
    dataset_key: view.run.resource_key,
    action: view.run.action,
    time_input: timeInput,
    filters,
  };
}

function getCreatedTaskRunId(data: TaskRunViewResponse | null | undefined): number | null {
  const id = data?.run?.id;
  return typeof id === "number" && Number.isFinite(id) ? id : null;
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function recoverCreatedTaskRunId(input: CreateRecoveryState): Promise<number | null> {
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    try {
      const params = new URLSearchParams({
        trigger_source: "manual",
        limit: "10",
      });
      if (input.resourceKey) {
        params.set("resource_key", input.resourceKey);
      }
      const response = await apiRequest<TaskRunListResponse>(`/api/v1/ops/task-runs?${params.toString()}`);
      const candidate = response.items.find((item) => {
        const requestedAtMs = Date.parse(item.requested_at);
        return Number.isFinite(requestedAtMs) && requestedAtMs >= input.submittedAtMs - 5_000;
      });
      if (candidate) {
        return candidate.id;
      }
    } catch {
      // 任务请求已经发出；确认编号失败不能让业务提交链路反向崩掉。
    }
    await sleep(1_000);
  }
  return null;
}

function buildDraftForActionSelection(action: ManualAction | string): ManualDraft {
  const actionId = typeof action === "string" ? action : action.action_key;
  const defaultMode = typeof action === "string" ? "point" : action.time_form.default_mode;
  const draft = buildEmptyDraft();
  const dateMode: ManualDateMode = defaultMode === "range" ? "time_range" : "single_point";
  return {
    ...draft,
    action_id: actionId,
    date_mode: dateMode,
    field_values: typeof action === "string" ? {} : buildDefaultFieldValues(action),
  };
}

function getActionGuidance(action: ManualAction | null): ActionGuidance | null {
  if (!action) {
    return null;
  }
  if (action.action_key === "ths_member") {
    return {
      title: "执行方式说明",
      lines: [
        "系统会先刷新“同花顺概念和行业指数”，再按板块代码逐个同步板块成分。",
        "如果你不填写板块代码，就会按全部板块依次处理。",
      ],
    };
  }
  if (action.action_key === "dc_member") {
    return {
      title: "执行方式说明",
      lines: [
        "系统会先刷新你所选日期的“东方财富概念板块”，再按板块代码逐个同步板块成分。",
        "如果你不填写板块代码，就会按该日期下全部板块依次处理。",
      ],
    };
  }
  if (action.action_key === "stk_mins") {
    return {
      title: "执行方式说明",
      lines: [
        "系统会按固定交易时段 09:30~11:30、13:00~15:00 请求分钟行情，不支持手动输入具体时分秒。",
        "未填写股票代码时，系统会按当前股票列表全市场扇开请求。",
      ],
    };
  }
  return null;
}

function normalizeFilterValue(param: ManualActionFilter, rawValue: string | string[] | undefined) {
  if (rawValue === undefined || rawValue === null) {
    return undefined;
  }
  if (param.multi_value) {
    const values =
      Array.isArray(rawValue)
        ? rawValue.filter((item) => item !== "")
        : String(rawValue)
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean);
    return values.length ? values : undefined;
  }
  const singleValue = Array.isArray(rawValue) ? rawValue[0] : rawValue;
  if (singleValue === "") {
    return undefined;
  }
  return param.param_type === "integer" ? Number(singleValue) : singleValue;
}

function buildManualActionRequest(action: ManualAction, draft: ManualDraft): OpsManualActionTaskRunRequest {
  const filters: Record<string, unknown> = {};
  const fieldValues = mergeDefaultFieldValues(action, draft.field_values);
  for (const param of action.filters) {
    const normalized = normalizeFilterValue(param, fieldValues[param.key]);
    if (normalized !== undefined) {
      filters[param.key] = normalized;
    }
  }

  if (!hasTimeInput(action)) {
    return { time_input: { mode: "none" }, filters };
  }

  if (isSinglePoint(action, draft)) {
    if (isMonthAction(action)) {
      if (!draft.selected_month) {
        throw new Error("请选择要处理的月份。");
      }
      return { time_input: { mode: "point", month: draft.selected_month }, filters };
    }
    if (!draft.selected_date) {
      throw new Error("请选择要处理的日期。");
    }
    if (action.date_model?.input_shape === "ann_date_or_start_end") {
      return { time_input: { mode: "point", ann_date: draft.selected_date }, filters };
    }
    return { time_input: { mode: "point", trade_date: draft.selected_date }, filters };
  }

  if (isMonthAction(action)) {
    const startMonth = draft.start_month || draft.selected_month;
    const endMonth = draft.end_month || draft.selected_month;
    if (!startMonth || !endMonth) {
      throw new Error("请选择开始月份和结束月份。");
    }
    return { time_input: { mode: "range", start_month: startMonth, end_month: endMonth }, filters };
  }

  const startDate = draft.start_date || draft.selected_date;
  const endDate = draft.end_date || draft.selected_date;
  if (!startDate || !endDate) {
    throw new Error("请选择开始日期和结束日期。");
  }
  return {
    time_input: {
      mode: "range",
      start_date: startDate,
      end_date: endDate,
      date_field: action.date_model?.input_shape === "ann_date_or_start_end" ? "ann_date" : undefined,
    },
    filters,
  };
}

function getPointLabel(action: ManualAction) {
  return action.time_form.point_label || "只处理一天";
}

function getRangeLabel(action: ManualAction) {
  return action.time_form.range_label || "处理一个时间区间";
}

function readSearchString(search: Record<string, unknown>, key: string): string | null {
  const value = search[key];
  if (typeof value === "string") {
    return value || null;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  if (typeof window !== "undefined") {
    return new URLSearchParams(window.location.search).get(key);
  }
  return null;
}

export function OpsManualTaskTab() {
  const navigate = useNavigate();
  const routerSearch = useSearch({ strict: false }) as Record<string, unknown>;
  const [draft, setDraft] = usePersistentState(MANUAL_DRAFT_STORAGE_KEY, buildEmptyDraft());
  const [selectedDomain, setSelectedDomain] = usePersistentState<string>(MANUAL_DOMAIN_STORAGE_KEY, "");
  const [recentActionIds, setRecentActionIds] = usePersistentState<string[]>(MANUAL_RECENT_ACTIONS_STORAGE_KEY, []);
  const [createRecovery, setCreateRecovery] = useState<CreateRecoveryState | null>(null);

  const prefillTaskRunId = readSearchString(routerSearch, "from_task_run_id");
  const prefillScheduleId = readSearchString(routerSearch, "from_schedule_id");
  const prefillSpecKey = readSearchString(routerSearch, "spec_key");
  const prefillSpecType = readSearchString(routerSearch, "spec_type");
  const prefillTradeDate = readSearchString(routerSearch, "trade_date");

  const manualActionsQuery = useQuery({
    queryKey: ["ops", "manual-actions"],
    queryFn: () => apiRequest<OpsManualActionsResponse>("/api/v1/ops/manual-actions"),
  });

  const prefillTaskRunQuery = useQuery({
    queryKey: ["ops", "prefill-task-run", prefillTaskRunId],
    queryFn: () => apiRequest<TaskRunViewResponse>(`/api/v1/ops/task-runs/${prefillTaskRunId}/view`),
    enabled: Boolean(prefillTaskRunId),
  });

  const prefillScheduleQuery = useQuery({
    queryKey: ["ops", "prefill-schedule", prefillScheduleId],
    queryFn: () => apiRequest<ScheduleDetailResponse>(`/api/v1/ops/schedules/${prefillScheduleId}`),
    enabled: Boolean(prefillScheduleId),
  });

  const manualActions = useMemo(() => flattenManualActions(manualActionsQuery.data), [manualActionsQuery.data]);

  const domainOptions = useMemo(
    () =>
      (manualActionsQuery.data?.groups || [])
        .map((group) => ({
          value: group.group_label,
          label: group.group_label,
        })),
    [manualActionsQuery.data],
  );

  const actionOptions = useMemo(
    () =>
      manualActions
        .filter((action) => !selectedDomain || action.groupLabel === selectedDomain)
        .map((action) => ({
          value: action.action_key,
          label: action.display_name,
        })),
    [manualActions, selectedDomain],
  );

  const recentActions = useMemo(
    () =>
      recentActionIds
        .map((id) => findManualAction(manualActions, id))
        .filter((item): item is ManualAction => Boolean(item))
        .slice(0, 5),
    [manualActions, recentActionIds],
  );

  const selectedAction = useMemo(
    () => findManualAction(manualActions, draft.action_id),
    [draft.action_id, manualActions],
  );
  const effectiveFieldValues = useMemo(
    () => selectedAction ? mergeDefaultFieldValues(selectedAction, draft.field_values) : draft.field_values,
    [draft.field_values, selectedAction],
  );
  const selectedActionDateRule = useMemo(() => inferSinglePointDateRule(selectedAction), [selectedAction]);
  const singleTradeCalendar = useTradeCalendarField({ value: draft.selected_date });
  const rangeStartTradeCalendar = useTradeCalendarField({ value: draft.start_date });
  const rangeEndTradeCalendar = useTradeCalendarField({ value: draft.end_date });
  const actionGuidance = useMemo(() => getActionGuidance(selectedAction), [selectedAction]);
  const prefillSpecAppliedRef = useRef(false);
  const prefillTaskRunAppliedRef = useRef(false);
  const prefillScheduleAppliedRef = useRef(false);

  useEffect(() => {
    if (selectedAction && shouldAutoAlignDomain(selectedDomain, selectedAction)) {
      setSelectedDomain(selectedAction.groupLabel);
    }
  }, [selectedAction, selectedDomain, setSelectedDomain]);

  useEffect(() => {
    if (prefillSpecAppliedRef.current) {
      return;
    }
    if (!manualActions.length) {
      return;
    }
    if (!prefillSpecKey) {
      prefillSpecAppliedRef.current = true;
      return;
    }
    const prefilledAction = manualActions.find((item) => matchesActionSpec(item, prefillSpecType, prefillSpecKey));
    if (prefilledAction) {
      setSelectedDomain(prefilledAction.groupLabel);
      setDraft((current) => {
        const base = normalizeDraftActionId(current.action_id) === prefilledAction.action_key
          ? current
          : buildDraftForActionSelection(prefilledAction);
        if (!prefillTradeDate) {
          return base;
        }
        return {
          ...base,
          date_mode: "single_point",
          selected_date: prefillTradeDate,
          start_date: prefillTradeDate,
          end_date: prefillTradeDate,
        };
      });
    }
    prefillSpecAppliedRef.current = true;
  }, [manualActions, prefillSpecKey, prefillSpecType, prefillTradeDate, setDraft, setSelectedDomain]);

  useEffect(() => {
    if (prefillTaskRunAppliedRef.current) {
      return;
    }
    if (!manualActions.length || !prefillTaskRunQuery.data) {
      return;
    }
    const specKey = prefillTaskRunQuery.data.run.resource_key ? `${prefillTaskRunQuery.data.run.resource_key}.maintain` : null;
    const action = manualActions.find((item) => matchesActionSpec(item, prefillTaskRunQuery.data?.run.task_type || null, specKey));
    if (!action) {
      prefillTaskRunAppliedRef.current = true;
      return;
    }
    prefillTaskRunAppliedRef.current = true;
    setSelectedDomain(action.groupLabel);
    setDraft((current) => buildDraftFromParams(current, action, buildPrefillParamsFromTaskRun(prefillTaskRunQuery.data)));
  }, [manualActions, prefillTaskRunQuery.data, setDraft, setSelectedDomain]);

  useEffect(() => {
    if (prefillScheduleAppliedRef.current) {
      return;
    }
    if (!manualActions.length || !prefillScheduleQuery.data) {
      return;
    }
    const action = manualActions.find((item) => matchesActionSpec(item, prefillScheduleQuery.data.spec_type, prefillScheduleQuery.data.spec_key));
    if (!action) {
      prefillScheduleAppliedRef.current = true;
      return;
    }
    prefillScheduleAppliedRef.current = true;
    setSelectedDomain(action.groupLabel);
    setDraft((current) => buildDraftFromParams(current, action, prefillScheduleQuery.data.params_json));
  }, [manualActions, prefillScheduleQuery.data, setDraft, setSelectedDomain]);

  const createTaskRunMutation = useMutation({
    mutationFn: () => {
      if (!selectedAction) {
        throw new Error("请先选择要维护的数据。");
      }
      return apiRequest<TaskRunViewResponse>(`/api/v1/ops/manual-actions/${encodeURIComponent(selectedAction.action_key)}/task-runs`, {
        method: "POST",
        body: buildManualActionRequest(selectedAction, draft),
      });
    },
    onSuccess: async (data) => {
      const taskRunId = getCreatedTaskRunId(data);
      if (taskRunId === null) {
        const recovery = {
          actionName: selectedAction?.display_name || "维护任务",
          resourceKey: selectedAction?.resource_key || null,
          submittedAtMs: Date.now(),
        };
        setCreateRecovery(recovery);
        const recoveredTaskRunId = await recoverCreatedTaskRunId(recovery);
        setCreateRecovery(null);
        if (recoveredTaskRunId !== null) {
          await navigate({ to: "/ops/tasks/$taskRunId", params: { taskRunId: String(recoveredTaskRunId) } });
          return;
        }
        notifications.show({
          color: "warning",
          title: "还在确认任务编号",
          message: "任务请求已经发出，但暂时没有确认到编号。请到任务记录查看最新任务。",
        });
        return;
      }
      notifications.show({
        color: "success",
        title: "任务已提交",
        message: "系统已经收到这次维护请求，正在为你打开任务详情页。",
      });
      await navigate({ to: "/ops/tasks/$taskRunId", params: { taskRunId: String(taskRunId) } });
    },
    onError: (error) => {
      notifications.show({
        color: "error",
        title: "启动任务失败",
        message: error instanceof Error ? error.message : "未知错误",
      });
    },
  });

  const isLoading = manualActionsQuery.isLoading || prefillTaskRunQuery.isLoading || prefillScheduleQuery.isLoading;
  const pageError = manualActionsQuery.error || prefillTaskRunQuery.error || prefillScheduleQuery.error;

  return (
    <Stack gap="lg">
      {isLoading ? <Loader size="sm" /> : null}
      {pageError ? (
        <AlertBar tone="error" title="无法打开手动任务">
          {pageError instanceof Error ? pageError.message : "未知错误"}
        </AlertBar>
      ) : null}
      {createRecovery ? (
        <SectionCard title="正在确认任务编号" description="任务提交请求已经发出，我正在从任务记录中确认刚创建的任务。">
          <Group justify="center" gap="sm">
            <Loader size="sm" />
            <Text size="sm">{`${createRecovery.actionName} 正在确认中，最多等待 10 秒。`}</Text>
          </Group>
        </SectionCard>
      ) : null}

      <Grid align="stretch">
        <Grid.Col span={{ base: 12, xl: 8 }}>
          <SectionCard
            title="发起一次手动维护"
            description="选中要维护的数据后，只需要给出时间范围和必要条件，系统会自动挑选合适的底层执行方式。"
          >
            <Stack gap="lg">
              <Stack gap="xs">
                <Text fw={700}>第一步：选择要维护的数据</Text>
                <SimpleGrid cols={{ base: 1, md: 2 }}>
                  <Select
                    label="选择数据分组"
                    placeholder="请选择分组"
                    data={domainOptions}
                    value={selectedDomain || null}
                    onChange={(value) => {
                      const nextDomain = value || "";
                      setSelectedDomain(nextDomain);
                      setDraft((current) => resolveDraftOnDomainChange(current, nextDomain, manualActions));
                    }}
                    clearable
                  />
                  <Select
                    searchable
                    label="选择维护对象"
                    placeholder="例如：股票日线、分红送转、指数周线、交易日历"
                    data={actionOptions}
                    value={normalizeDraftActionId(draft.action_id) || null}
                    nothingFoundMessage="没有找到匹配任务"
                    onChange={(value) => {
                      if (!value) {
                        setDraft(() => buildEmptyDraft());
                        return;
                      }
                      const nextAction = findManualAction(manualActions, value);
                      if (nextAction) {
                        setSelectedDomain(nextAction.groupLabel);
                        setRecentActionIds((current) => [nextAction.action_key, ...current.filter((item) => normalizeDraftActionId(item) !== nextAction.action_key)].slice(0, 10));
                        setDraft(() => buildDraftForActionSelection(nextAction));
                      }
                    }}
                  />
                </SimpleGrid>
                {recentActions.length ? (
                  <Stack gap={6}>
                    <Text size="sm" c="dimmed">最近使用</Text>
                    <Group gap="xs">
                      {recentActions.map((action) => (
                        <Button
                          key={action.action_key}
                          size="xs"
                          variant={normalizeDraftActionId(draft.action_id) === action.action_key ? "filled" : "light"}
                          onClick={() => {
                            setSelectedDomain(action.groupLabel);
                            setDraft(() => buildDraftForActionSelection(action));
                          }}
                        >
                          {action.display_name}
                        </Button>
                      ))}
                    </Group>
                  </Stack>
                ) : null}
              </Stack>

              {selectedAction ? (
                <>
                  <AlertBar title={selectedAction.display_name}>
                    <Stack gap={4}>
                      <Text size="sm">数据分组：{selectedAction.groupLabel}</Text>
                      {selectedAction.description ? <Text size="sm">{selectedAction.description}</Text> : null}
                    </Stack>
                  </AlertBar>

                  {actionGuidance ? (
                    <AlertBar title={actionGuidance.title}>
                      <Stack gap={4}>
                        {actionGuidance.lines.map((line) => (
                          <Text size="sm" key={line}>
                            {line}
                          </Text>
                        ))}
                      </Stack>
                    </AlertBar>
                  ) : null}

                  {hasTimeInput(selectedAction) ? (
                    <Stack gap="xs">
                      <Text fw={700}>第二步：选择时间范围</Text>

                      {(supportsPoint(selectedAction) && supportsRange(selectedAction)) ? (
                        <SimpleGrid cols={{ base: 1, md: 2 }}>
                          <Button
                            variant={draft.date_mode === "single_point" ? "filled" : "light"}
                            onClick={() => setDraft((current) => ({ ...current, date_mode: "single_point" }))}
                          >
                            {getPointLabel(selectedAction)}
                          </Button>
                          <Button
                            variant={draft.date_mode === "time_range" ? "filled" : "light"}
                            onClick={() => setDraft((current) => ({ ...current, date_mode: "time_range" }))}
                          >
                            {getRangeLabel(selectedAction)}
                          </Button>
                        </SimpleGrid>
                      ) : null}

                      {isSinglePoint(selectedAction, draft) ? (
                        isMonthAction(selectedAction) ? (
                          <MonthField
                            label="选择月份"
                            placeholder="请选择月份"
                            value={draft.selected_month}
                            onChange={(value) =>
                              setDraft((current) => ({
                                ...current,
                                selected_month: value,
                                start_month: value,
                                end_month: value,
                              }))
                            }
                          />
                        ) : isCalendarDateAction(selectedAction) ? (
                          <DateField
                            label="选择日期"
                            placeholder="请选择日期"
                            value={draft.selected_date}
                            onChange={(value) =>
                              setDraft((current) => ({
                                ...current,
                                selected_date: value,
                                start_date: value,
                                end_date: value,
                              }))
                            }
                          />
                        ) : (
                          <TradeDateField
                            {...singleTradeCalendar.calendarProps}
                            isTradingDay={singleTradeCalendar.isTradingDay}
                            label="选择日期"
                            placeholder="请选择日期"
                            value={draft.selected_date}
                            selectionRule={selectedActionDateRule}
                            onChange={(value) =>
                              setDraft((current) => ({
                                ...current,
                                selected_date: value,
                                start_date: value,
                                end_date: value,
                              }))
                            }
                          />
                        )
                      ) : (
                        <SimpleGrid cols={{ base: 1, md: 2 }}>
                          {isMonthAction(selectedAction) ? (
                            <>
                              <MonthField
                                label="开始月份"
                                placeholder="请选择开始月份"
                                value={draft.start_month}
                                onChange={(value) =>
                                  setDraft((current) => ({
                                    ...current,
                                    start_month: value,
                                  }))
                                }
                              />
                              <MonthField
                                label="结束月份"
                                placeholder="请选择结束月份"
                                value={draft.end_month}
                                onChange={(value) =>
                                  setDraft((current) => ({
                                    ...current,
                                    end_month: value,
                                  }))
                                }
                              />
                            </>
                          ) : isCalendarDateAction(selectedAction) ? (
                            <>
                              <DateField
                                label="开始日期"
                                placeholder="请选择开始日期"
                                value={draft.start_date}
                                onChange={(value) =>
                                  setDraft((current) => ({
                                    ...current,
                                    start_date: value,
                                  }))
                                }
                              />
                              <DateField
                                label="结束日期"
                                placeholder="请选择结束日期"
                                value={draft.end_date}
                                onChange={(value) =>
                                  setDraft((current) => ({
                                    ...current,
                                    end_date: value,
                                  }))
                                }
                              />
                            </>
                          ) : (
                            <>
                              <TradeDateField
                                {...rangeStartTradeCalendar.calendarProps}
                                isTradingDay={rangeStartTradeCalendar.isTradingDay}
                                label="开始日期"
                                placeholder="请选择开始日期"
                                value={draft.start_date}
                                onChange={(value) =>
                                  setDraft((current) => ({
                                    ...current,
                                    start_date: value,
                                  }))
                                }
                              />
                              <TradeDateField
                                {...rangeEndTradeCalendar.calendarProps}
                                isTradingDay={rangeEndTradeCalendar.isTradingDay}
                                label="结束日期"
                                placeholder="请选择结束日期"
                                value={draft.end_date}
                                onChange={(value) =>
                                  setDraft((current) => ({
                                    ...current,
                                    end_date: value,
                                  }))
                                }
                              />
                            </>
                          )}
                        </SimpleGrid>
                      )}
                    </Stack>
                  ) : null}

                  {selectedAction.filters.length ? (
                    <Stack gap="xs">
                      <Text fw={700}>{hasTimeInput(selectedAction) ? "第三步：其他输入条件" : "第二步：其他输入条件"}</Text>
                      <Grid>
                        {selectedAction.filters.map((param) => (
                          <Grid.Col key={param.key} span={{ base: 12, md: 6 }}>
                            {(param.param_type === "enum" && param.multi_value) ? (
                              <Checkbox.Group
                                label={param.display_name}
                                description={param.description}
                                value={
                                  Array.isArray(effectiveFieldValues[param.key])
                                    ? (effectiveFieldValues[param.key] as string[])
                                    : String(effectiveFieldValues[param.key] || "")
                                      .split(",")
                                      .map((item) => item.trim())
                                      .filter(Boolean)
                                }
                                onChange={(values) =>
                                  setDraft((current) => ({
                                    ...current,
                                    field_values: { ...current.field_values, [param.key]: values },
                                  }))
                                }
                              >
                                <Group gap="lg" mt="xs">
                                  {normalizeParamOptions(param.options).map((option) => (
                                    <Checkbox key={option} value={option} label={option} />
                                  ))}
                                </Group>
                              </Checkbox.Group>
                            ) : (param.param_type === "enum" && param.key === "is_new") ? (
                              <Radio.Group
                                label={param.display_name}
                                description={param.description}
                                value={
                                  Array.isArray(effectiveFieldValues[param.key])
                                    ? ((effectiveFieldValues[param.key] as string[])[0] || "")
                                    : (effectiveFieldValues[param.key] as string) || ""
                                }
                                onChange={(value) =>
                                  setDraft((current) => ({
                                    ...current,
                                    field_values: { ...current.field_values, [param.key]: value },
                                  }))
                                }
                              >
                                <Group gap="lg" mt="xs">
                                  {normalizeParamOptions(param.options).map((option) => (
                                    <Radio key={option} value={option} label={option} />
                                  ))}
                                </Group>
                              </Radio.Group>
                            ) : param.param_type === "enum" ? (
                              <Select
                                label={param.display_name}
                                placeholder={param.description}
                                data={normalizeParamOptions(param.options).map((option) => ({
                                  value: option,
                                  label: option,
                                }))}
                                value={
                                  Array.isArray(effectiveFieldValues[param.key])
                                    ? ((effectiveFieldValues[param.key] as string[])[0] || null)
                                    : (effectiveFieldValues[param.key] as string) || null
                                }
                                onChange={(value) =>
                                  setDraft((current) => ({
                                    ...current,
                                    field_values: { ...current.field_values, [param.key]: value || "" },
                                  }))
                                }
                              />
                            ) : param.param_type === "month" ? (
                              <MonthField
                                label={param.display_name}
                                placeholder={param.description}
                                value={Array.isArray(effectiveFieldValues[param.key]) ? "" : (effectiveFieldValues[param.key] as string) || ""}
                                onChange={(value) =>
                                  setDraft((current) => ({
                                    ...current,
                                    field_values: { ...current.field_values, [param.key]: value },
                                  }))
                                }
                              />
                            ) : (
                              <TextInput
                                label={param.display_name}
                                placeholder={param.description}
                                value={Array.isArray(effectiveFieldValues[param.key]) ? "" : (effectiveFieldValues[param.key] as string) || ""}
                                onChange={(event) =>
                                  setDraft((current) => ({
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

                  <Stack gap="md">
                    <Group justify="flex-end" align="center">
                      <Button
                        loading={createTaskRunMutation.isPending || Boolean(createRecovery)}
                        disabled={Boolean(createRecovery)}
                        onClick={() => createTaskRunMutation.mutate()}
                      >
                        提交维护任务
                      </Button>
                    </Group>
                    <Group justify="center">
                      <Button
                        variant="light"
                        onClick={() => setDraft(buildEmptyDraft())}
                      >
                        清空当前表单
                      </Button>
                    </Group>
                  </Stack>
                </>
              ) : (
                <EmptyState
                  title="先选择一类要维护的数据"
                  description="选中之后，我会自动显示合适的日期控件和常用筛选条件，不会把底层执行方式直接丢给你。"
                />
              )}
            </Stack>
          </SectionCard>
        </Grid.Col>

        <Grid.Col span={{ base: 12, xl: 4 }}>
          <Stack gap="lg">
            <SectionCard title="已带入条件" description="如果你是从任务记录或自动运行页跳过来的，这里会自动带入原来的条件。">
              <Stack gap="sm">
                <Text size="sm">来自任务记录：{prefillTaskRunId || "无"}</Text>
                <Text size="sm">来自自动任务：{prefillScheduleId || "无"}</Text>
                <Text size="sm">当前已选数据：{selectedAction ? selectedAction.display_name : "未选择"}</Text>
              </Stack>
            </SectionCard>
          </Stack>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
