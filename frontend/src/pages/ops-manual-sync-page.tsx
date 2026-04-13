import {
  Alert,
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
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useRef } from "react";

import { apiRequest } from "../shared/api/client";
import type {
  ExecutionDetailResponse,
  OpsCatalogResponse,
  ScheduleDetailResponse,
} from "../shared/api/types";
import { formatCategoryLabel, formatResourceLabel, formatSpecDisplayLabel } from "../shared/ops-display";
import { usePersistentState } from "../shared/hooks/use-persistent-state";
import {
  filterNonTimeParams,
  getTimeModeLabels,
  inferTimeCapability,
  type TimeCapability,
  type TimeMode,
} from "../shared/ops-time-capability";
import { DateField, type DateSelectionRule } from "../shared/ui/date-field";
import { EmptyState } from "../shared/ui/empty-state";
import { MonthField } from "../shared/ui/month-field";
import { SectionCard } from "../shared/ui/section-card";

type ManualSpecType = "job" | "workflow";

type CatalogJobSpec = OpsCatalogResponse["job_specs"][number];
type CatalogWorkflowSpec = OpsCatalogResponse["workflow_specs"][number];
type CatalogParamSpec = NonNullable<CatalogJobSpec["supported_params"]>[number];

type ManualAction = {
  id: string;
  type: "job" | "workflow";
  domainLabel: string;
  categoryLabel: string;
  displayName: string;
  description: string;
  syncDailySpecKey: string | null;
  backfillSpecKey: string | null;
  backfillNoDateSpecKey: string | null;
  directSpecKey: string | null;
  workflowKey: string | null;
  supportedParams: CatalogParamSpec[];
  timeCapability: TimeCapability;
};

type ActionGuidance = {
  title: string;
  lines: string[];
};

const INTERNAL_PARAM_KEYS = new Set(["offset", "limit"]);
const REFERENCE_RESOURCES = new Set(["stock_basic", "trade_cal", "etf_basic", "index_basic", "hk_basic", "us_basic"]);
const MARKET_REFERENCE_RESOURCES = new Set(["ths_index", "ths_member", "broker_recommend"]);
const EQUITY_RESOURCES = new Set([
  "daily",
  "equity_price_restore_factor",
  "equity_indicators",
  "adj_factor",
  "daily_basic",
  "moneyflow",
  "top_list",
  "block_trade",
  "limit_list_d",
  "stk_period_bar_week",
  "stk_period_bar_month",
  "stk_period_bar_adj_week",
  "stk_period_bar_adj_month",
]);
const FUND_RESOURCES = new Set(["fund_daily", "fund_adj"]);
const INDEX_RESOURCES = new Set(["index_daily", "index_weekly", "index_monthly", "index_daily_basic", "index_weight"]);
const BOARD_RESOURCES = new Set(["ths_daily", "dc_index", "dc_member", "dc_daily", "kpl_concept_cons"]);
const RANKING_RESOURCES = new Set(["ths_hot", "dc_hot", "kpl_list", "limit_list_ths", "limit_step", "limit_cpt_list"]);
const EVENT_RESOURCES = new Set(["dividend", "stk_holdernumber"]);
const WEEKLY_ANCHOR_RESOURCES = new Set(["stk_period_bar_week", "stk_period_bar_adj_week"]);
const MONTHLY_ANCHOR_RESOURCES = new Set(["stk_period_bar_month", "stk_period_bar_adj_month"]);

function buildEmptyDraft() {
  return {
    action_id: "",
    date_mode: "single_point" as TimeMode,
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

function matchesActionSpec(action: ManualAction, specType: string | null, specKey: string | null) {
  if (!specKey) {
    return false;
  }
  if (specType === "workflow") {
    return action.workflowKey === specKey;
  }
  return [action.syncDailySpecKey, action.backfillSpecKey, action.directSpecKey].includes(specKey);
}

function filterVisibleParams(params: CatalogParamSpec[]) {
  return filterNonTimeParams(params).filter((param) => !INTERNAL_PARAM_KEYS.has(param.key));
}

export function shouldAutoAlignDomain(selectedDomain: string, selectedAction: ManualAction | null) {
  return Boolean(selectedAction && !selectedDomain);
}

export function resolveDraftOnDomainChange(current: ManualDraft, nextDomain: string, manualActions: ManualAction[]) {
  if (!current.action_id) {
    return current;
  }
  const currentAction = manualActions.find((item) => item.id === current.action_id);
  if (!currentAction) {
    return buildEmptyDraft();
  }
  if (!nextDomain || currentAction.domainLabel === nextDomain) {
    return current;
  }
  return buildEmptyDraft();
}

function extractResourceKey(specKey: string) {
  const parts = specKey.split(".");
  return parts.length >= 2 ? parts[1] : specKey;
}

function isSinglePoint(resource: ManualAction, draft: ReturnType<typeof buildEmptyDraft>) {
  if (resource.timeCapability.supportsPoint && resource.timeCapability.supportsRange) {
    return draft.date_mode === "single_point";
  }
  if (resource.timeCapability.supportsPoint) {
    return true;
  }
  return false;
}

function inferSinglePointDateRule(action: ManualAction | null): DateSelectionRule {
  if (!action || action.type !== "job") {
    return "any";
  }
  if (action.timeCapability.pointGranularity !== "day") {
    return "any";
  }
  const resourceKey = action.id.startsWith("job:") ? action.id.slice(4) : "";
  if (WEEKLY_ANCHOR_RESOURCES.has(resourceKey)) {
    return "week_friday";
  }
  if (MONTHLY_ANCHOR_RESOURCES.has(resourceKey)) {
    return "month_end";
  }
  return "any";
}

function buildManualActions(catalog: OpsCatalogResponse | undefined) {
  if (!catalog) {
    return [];
  }

  const resourceMap = new Map<
    string,
    {
      resourceKey: string;
      category: string;
      description: string;
      syncDailySpec: CatalogJobSpec | null;
      backfillSpec: CatalogJobSpec | null;
      directSpec: CatalogJobSpec | null;
      supportedParams: CatalogParamSpec[];
    }
  >();

  for (const job of catalog.job_specs.filter((item) => item.supports_manual_run !== false)) {
    const prefix = job.key.split(".", 1)[0];
    const resourceKey = extractResourceKey(job.key);

    if (prefix === "maintenance") {
      continue;
    }

    if (prefix === "sync_history" && !REFERENCE_RESOURCES.has(resourceKey) && job.strategy_type !== "full_refresh") {
      continue;
    }

    const current = resourceMap.get(resourceKey) || {
      resourceKey,
      category: job.category,
      description: job.description,
      syncDailySpec: null,
      backfillSpec: null,
      directSpec: null,
      supportedParams: [],
    };

    const visibleParams = filterVisibleParams(job.supported_params || []);
    const dedupedParams = new Map(current.supportedParams.map((param) => [param.key, param]));
    for (const param of visibleParams) {
      if (!dedupedParams.has(param.key)) {
        dedupedParams.set(param.key, param);
      }
    }
    current.supportedParams = Array.from(dedupedParams.values());

    if (prefix === "sync_daily") {
      current.syncDailySpec = job;
    } else if (prefix.startsWith("backfill_")) {
      current.backfillSpec = job;
    } else {
      current.directSpec = job;
    }

    if (current.category === "sync_history" && job.category !== "sync_history") {
      current.category = job.category;
    }
    if (!current.description || current.description === current.directSpec?.description) {
      current.description = job.description;
    }
    resourceMap.set(resourceKey, current);
  }

  const actions: ManualAction[] = Array.from(resourceMap.values()).map((item) => {
    const timeCapability = inferTimeCapability([
      ...(item.syncDailySpec?.supported_params || []),
      ...(item.backfillSpec?.supported_params || []),
      ...(item.directSpec?.supported_params || []),
    ]);
    const backfillNoDateSpecKey = item.backfillSpec && !timeCapability.supportsRange ? item.backfillSpec.key : null;
    return {
      id: `job:${item.resourceKey}`,
      type: "job",
      domainLabel: inferActionDomain(item.resourceKey, item.category, "job"),
      categoryLabel: formatCategoryLabel(item.category),
      displayName: `维护${formatResourceLabel(item.resourceKey)}`,
      description: item.description,
      syncDailySpecKey: item.syncDailySpec?.key || null,
      backfillSpecKey: item.backfillSpec?.key || null,
      backfillNoDateSpecKey,
      directSpecKey: item.directSpec?.key || null,
      workflowKey: null,
      supportedParams: item.supportedParams,
      timeCapability,
    };
  });

  for (const workflow of catalog.workflow_specs.filter((item) => item.supports_manual_run !== false)) {
    const workflowVisibleParams = filterVisibleParams(workflow.supported_params || []);
    const timeCapability = inferTimeCapability(workflow.supported_params || []);
    actions.push({
      id: `workflow:${workflow.key}`,
      type: "workflow",
      domainLabel: inferActionDomain(workflow.key, "workflow", "workflow"),
      categoryLabel: "工作流",
      displayName: workflow.display_name,
      description: workflow.description,
      syncDailySpecKey: null,
      backfillSpecKey: null,
      backfillNoDateSpecKey: null,
      directSpecKey: null,
      workflowKey: workflow.key,
      supportedParams: workflowVisibleParams,
      timeCapability,
    });
  }

  return actions.sort((left, right) => left.displayName.localeCompare(right.displayName, "zh-CN"));
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

function buildDraftFromParams(
  current: ReturnType<typeof buildEmptyDraft>,
  actionId: string,
  paramsJson: Record<string, unknown> | undefined,
) {
  const fieldValues = buildFieldValues(paramsJson);
  const tradeDate = typeof paramsJson?.trade_date === "string" ? paramsJson.trade_date : "";
  const startDate = typeof paramsJson?.start_date === "string" ? paramsJson.start_date : "";
  const endDate = typeof paramsJson?.end_date === "string" ? paramsJson.end_date : "";
  const month = typeof paramsJson?.month === "string" ? paramsJson.month : "";
  const startMonth = typeof paramsJson?.start_month === "string" ? paramsJson.start_month : "";
  const endMonth = typeof paramsJson?.end_month === "string" ? paramsJson.end_month : "";
  const dateMode: TimeMode = (tradeDate || month) ? "single_point" : "time_range";
  return {
    ...current,
    action_id: actionId,
    date_mode: dateMode,
    selected_date: tradeDate || startDate || current.selected_date,
    start_date: startDate,
    end_date: endDate,
    selected_month: month || startMonth || current.selected_month,
    start_month: startMonth,
    end_month: endMonth,
    field_values: fieldValues,
  };
}

function buildDraftForActionSelection(actionId: string) {
  const draft = buildEmptyDraft();
  return {
    ...draft,
    action_id: actionId,
  };
}

function getActionGuidance(action: ManualAction | null): ActionGuidance | null {
  if (!action) {
    return null;
  }
  if (action.id === "job:ths_member") {
    return {
      title: "执行方式说明",
      lines: [
        "系统会先刷新“同花顺概念和行业指数”，再按板块代码逐个同步板块成分。",
        "如果你不填写板块代码，就会按全部板块依次处理。",
      ],
    };
  }
  if (action.id === "job:dc_member") {
    return {
      title: "执行方式说明",
      lines: [
        "系统会先刷新你所选日期的“东方财富概念板块”，再按板块代码逐个同步板块成分。",
        "如果你不填写板块代码，就会按该日期下全部板块依次处理。",
      ],
    };
  }
  return null;
}

function inferActionDomain(resourceKey: string, category: string, type: "job" | "workflow"): string {
  if (type === "workflow") {
    return "工作流";
  }
  if (category === "maintenance") {
    return "维护动作";
  }
  if (REFERENCE_RESOURCES.has(resourceKey) || MARKET_REFERENCE_RESOURCES.has(resourceKey)) {
    return "基础主数据";
  }
  if (EQUITY_RESOURCES.has(resourceKey)) {
    return "股票";
  }
  if (FUND_RESOURCES.has(resourceKey)) {
    return "ETF/Fund";
  }
  if (INDEX_RESOURCES.has(resourceKey)) {
    return "指数";
  }
  if (BOARD_RESOURCES.has(resourceKey)) {
    return "板块";
  }
  if (RANKING_RESOURCES.has(resourceKey)) {
    return "榜单";
  }
  if (EVENT_RESOURCES.has(resourceKey)) {
    return "低频事件";
  }
  return "其他";
}

export function resolveExecutionTarget(
  action: ManualAction,
  draft: ReturnType<typeof buildEmptyDraft>,
) {
  if (action.type === "workflow" && !action.workflowKey) {
    throw new Error("当前工作流缺少执行标识。");
  }
  const params: Record<string, unknown> = {};

  for (const param of action.supportedParams) {
    const rawValue = draft.field_values[param.key];
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

  if (action.timeCapability.supportsPoint && action.timeCapability.supportsRange) {
    if (draft.date_mode === "single_point") {
      const pointValue = action.timeCapability.pointGranularity === "month" ? draft.selected_month : draft.selected_date;
      if (!pointValue) {
        throw new Error(action.timeCapability.pointGranularity === "month" ? "请选择要处理的月份。" : "请选择要处理的日期。");
      }
      if (action.type === "workflow") {
        return {
          spec_type: "workflow" as ManualSpecType,
          spec_key: action.workflowKey!,
          params_json: { ...params, [action.timeCapability.pointKey!]: pointValue },
        };
      }
      if (!action.syncDailySpecKey) {
        throw new Error("当前任务暂不支持按单日直接执行。");
      }
      return {
        spec_type: "job" as ManualSpecType,
        spec_key: action.syncDailySpecKey,
        params_json: { ...params, [action.timeCapability.pointKey!]: pointValue },
      };
    }
    const rangeStart = action.timeCapability.rangeGranularity === "month" ? draft.start_month : draft.start_date;
    const rangeEnd = action.timeCapability.rangeGranularity === "month" ? draft.end_month : draft.end_date;
    if (!rangeStart || !rangeEnd) {
      throw new Error(action.timeCapability.rangeGranularity === "month" ? "请选择开始月份和结束月份。" : "请选择开始日期和结束日期。");
    }
    if (action.type === "workflow") {
      return {
        spec_type: "workflow" as ManualSpecType,
        spec_key: action.workflowKey!,
        params_json: { ...params, [action.timeCapability.rangeStartKey!]: rangeStart, [action.timeCapability.rangeEndKey!]: rangeEnd },
      };
    }
    const rangeSpecKey = action.backfillSpecKey || action.directSpecKey;
    if (!rangeSpecKey) {
      throw new Error("当前任务暂不支持按日期区间执行。");
    }
    return {
      spec_type: "job" as ManualSpecType,
      spec_key: rangeSpecKey,
      params_json: { ...params, [action.timeCapability.rangeStartKey!]: rangeStart, [action.timeCapability.rangeEndKey!]: rangeEnd },
    };
  }

  if (action.timeCapability.supportsPoint) {
    const pointValue = action.timeCapability.pointGranularity === "month" ? draft.selected_month : draft.selected_date;
    if (!pointValue) {
      throw new Error(action.timeCapability.pointGranularity === "month" ? "请选择要处理的月份。" : "请选择要处理的日期。");
    }
    if (action.type === "workflow") {
      return {
        spec_type: "workflow" as ManualSpecType,
        spec_key: action.workflowKey!,
        params_json: { ...params, [action.timeCapability.pointKey!]: pointValue },
      };
    }
    if (!action.syncDailySpecKey) {
      throw new Error("当前任务暂不支持按单日直接执行。");
    }
    return {
      spec_type: "job" as ManualSpecType,
      spec_key: action.syncDailySpecKey,
      params_json: { ...params, [action.timeCapability.pointKey!]: pointValue },
    };
  }

  if (action.timeCapability.supportsRange) {
    const rangeStart = action.timeCapability.rangeGranularity === "month"
      ? (draft.start_month || draft.selected_month)
      : (draft.start_date || draft.selected_date);
    const rangeEnd = action.timeCapability.rangeGranularity === "month"
      ? (draft.end_month || draft.selected_month)
      : (draft.end_date || draft.selected_date);
    if (!rangeStart || !rangeEnd) {
      throw new Error(action.timeCapability.rangeGranularity === "month" ? "请选择开始月份和结束月份。" : "请选择开始日期和结束日期。");
    }
    if (action.type === "workflow") {
      return {
        spec_type: "workflow" as ManualSpecType,
        spec_key: action.workflowKey!,
        params_json: { ...params, [action.timeCapability.rangeStartKey!]: rangeStart, [action.timeCapability.rangeEndKey!]: rangeEnd },
      };
    }
    const rangeSpecKey = action.backfillSpecKey || action.directSpecKey;
    if (!rangeSpecKey) {
      throw new Error("当前任务暂不支持按日期区间执行。");
    }
    return {
      spec_type: "job" as ManualSpecType,
      spec_key: rangeSpecKey,
      params_json: { ...params, [action.timeCapability.rangeStartKey!]: rangeStart, [action.timeCapability.rangeEndKey!]: rangeEnd },
    };
  }

  if (action.type === "workflow") {
    return {
      spec_type: "workflow" as ManualSpecType,
      spec_key: action.workflowKey!,
      params_json: params,
    };
  }

  if (action.backfillNoDateSpecKey) {
    return {
      spec_type: "job" as ManualSpecType,
      spec_key: action.backfillNoDateSpecKey,
      params_json: params,
    };
  }

  if (!action.directSpecKey) {
    throw new Error("当前任务还没有绑定可执行能力。");
  }

  return {
    spec_type: "job" as ManualSpecType,
    spec_key: action.directSpecKey,
    params_json: params,
  };
}

export function OpsManualSyncPage() {
  const navigate = useNavigate();
  const [draft, setDraft] = usePersistentState("goldenshare.frontend.ops.manual-sync.draft", buildEmptyDraft());
  const [selectedDomain, setSelectedDomain] = usePersistentState<string>("goldenshare.frontend.ops.manual-sync.domain", "");
  const [recentActionIds, setRecentActionIds] = usePersistentState<string[]>("goldenshare.frontend.ops.manual-sync.recent-actions", []);

  const search = new URLSearchParams(window.location.search);
  const prefillExecutionId = search.get("from_execution_id");
  const prefillScheduleId = search.get("from_schedule_id");
  const prefillSpecKey = search.get("spec_key");
  const prefillSpecType = search.get("spec_type");

  const catalogQuery = useQuery({
    queryKey: ["ops", "catalog"],
    queryFn: () => apiRequest<OpsCatalogResponse>("/api/v1/ops/catalog"),
  });

  const prefillExecutionQuery = useQuery({
    queryKey: ["ops", "prefill-execution", prefillExecutionId],
    queryFn: () => apiRequest<ExecutionDetailResponse>(`/api/v1/ops/executions/${prefillExecutionId}`),
    enabled: Boolean(prefillExecutionId),
  });

  const prefillScheduleQuery = useQuery({
    queryKey: ["ops", "prefill-schedule", prefillScheduleId],
    queryFn: () => apiRequest<ScheduleDetailResponse>(`/api/v1/ops/schedules/${prefillScheduleId}`),
    enabled: Boolean(prefillScheduleId),
  });

  const manualActions = useMemo(() => buildManualActions(catalogQuery.data), [catalogQuery.data]);

  const domainOptions = useMemo(() => {
    const domains = Array.from(new Set(manualActions.map((action) => action.domainLabel))).sort((a, b) => a.localeCompare(b, "zh-CN"));
    return domains.map((domain) => ({ value: domain, label: domain }));
  }, [manualActions]);

  const actionOptions = useMemo(
    () =>
      manualActions
        .filter((action) => !selectedDomain || action.domainLabel === selectedDomain)
        .map((action) => ({
          value: action.id,
          label: `${action.displayName}（${action.categoryLabel}）`,
        })),
    [manualActions, selectedDomain],
  );

  const recentActions = useMemo(
    () =>
      recentActionIds
        .map((id) => manualActions.find((action) => action.id === id))
        .filter((item): item is ManualAction => Boolean(item))
        .slice(0, 5),
    [manualActions, recentActionIds],
  );

  const selectedAction = useMemo(
    () => manualActions.find((item) => item.id === draft.action_id) || null,
    [draft.action_id, manualActions],
  );
  const selectedActionDateRule = useMemo(() => inferSinglePointDateRule(selectedAction), [selectedAction]);
  const actionGuidance = useMemo(() => getActionGuidance(selectedAction), [selectedAction]);
  const prefillSpecAppliedRef = useRef(false);
  const prefillExecutionAppliedRef = useRef(false);
  const prefillScheduleAppliedRef = useRef(false);

  useEffect(() => {
    if (selectedAction && shouldAutoAlignDomain(selectedDomain, selectedAction)) {
      setSelectedDomain(selectedAction.domainLabel);
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
      if (draft.action_id && manualActions.some((item) => item.id === draft.action_id)) {
        return;
      }
      return;
    }
    const prefilledAction = manualActions.find((item) => matchesActionSpec(item, prefillSpecType, prefillSpecKey));
    if (prefilledAction) {
      setSelectedDomain(prefilledAction.domainLabel);
      if (draft.action_id !== prefilledAction.id) {
        setDraft(() => buildDraftForActionSelection(prefilledAction.id));
      }
      prefillSpecAppliedRef.current = true;
      return;
    }
    prefillSpecAppliedRef.current = true;
  }, [draft.action_id, manualActions, prefillSpecKey, prefillSpecType, setDraft, setSelectedDomain]);

  useEffect(() => {
    if (prefillExecutionAppliedRef.current) {
      return;
    }
    if (!manualActions.length || !prefillExecutionQuery.data) {
      return;
    }
    const action = manualActions.find(
      (item) =>
        item.type === prefillExecutionQuery.data.spec_type &&
        (
          item.workflowKey === prefillExecutionQuery.data.spec_key ||
          item.syncDailySpecKey === prefillExecutionQuery.data.spec_key ||
          item.backfillSpecKey === prefillExecutionQuery.data.spec_key ||
          item.directSpecKey === prefillExecutionQuery.data.spec_key
        ),
    );
    if (!action) {
      prefillExecutionAppliedRef.current = true;
      return;
    }
    prefillExecutionAppliedRef.current = true;
    setSelectedDomain(action.domainLabel);
    setDraft((current) => buildDraftFromParams(current, action.id, prefillExecutionQuery.data.params_json));
  }, [manualActions, prefillExecutionQuery.data, setDraft, setSelectedDomain]);

  useEffect(() => {
    if (prefillScheduleAppliedRef.current) {
      return;
    }
    if (!manualActions.length || !prefillScheduleQuery.data) {
      return;
    }
    const action = manualActions.find(
      (item) =>
        item.type === prefillScheduleQuery.data.spec_type &&
        (
          item.workflowKey === prefillScheduleQuery.data.spec_key ||
          item.syncDailySpecKey === prefillScheduleQuery.data.spec_key ||
          item.backfillSpecKey === prefillScheduleQuery.data.spec_key ||
          item.directSpecKey === prefillScheduleQuery.data.spec_key
        ),
    );
    if (!action) {
      prefillScheduleAppliedRef.current = true;
      return;
    }
    prefillScheduleAppliedRef.current = true;
    setSelectedDomain(action.domainLabel);
    setDraft((current) => buildDraftFromParams(current, action.id, prefillScheduleQuery.data.params_json));
  }, [manualActions, prefillScheduleQuery.data, setDraft, setSelectedDomain]);

  const createExecutionMutation = useMutation({
    mutationFn: () => {
      if (!selectedAction) {
        throw new Error("请先选择要维护的数据。");
      }
      return apiRequest<ExecutionDetailResponse>("/api/v1/ops/executions", {
        method: "POST",
        body: resolveExecutionTarget(selectedAction, draft),
      });
    },
    onSuccess: async (data) => {
      notifications.show({
        color: "green",
        title: "任务已提交",
        message: "系统已经收到这次同步请求，正在为你打开任务详情页。",
      });
      await navigate({ to: "/ops/tasks/$executionId", params: { executionId: String(data.id) } });
    },
    onError: (error) => {
      notifications.show({
        color: "red",
        title: "启动任务失败",
        message: error instanceof Error ? error.message : "未知错误",
      });
    },
  });

  return (
    <Stack gap="lg">
      <Text c="dimmed" size="sm">
        这里只做一件事：维护你选中的数据。至于是补一天、补一段时间，还是直接刷新一次，由系统根据你的输入自动决定。
      </Text>

      {(catalogQuery.isLoading || prefillExecutionQuery.isLoading || prefillScheduleQuery.isLoading) ? <Loader size="sm" /> : null}
      {catalogQuery.error || prefillExecutionQuery.error || prefillScheduleQuery.error ? (
        <Alert color="red" title="无法打开手动同步">
          {(catalogQuery.error || prefillExecutionQuery.error || prefillScheduleQuery.error) instanceof Error
            ? ((catalogQuery.error || prefillExecutionQuery.error || prefillScheduleQuery.error) as Error).message
            : "未知错误"}
        </Alert>
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
                    label="先选数据分组"
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
                    label="再选维护对象"
                    placeholder="例如：股票日线、分红送转、指数周线、交易日历"
                    data={actionOptions}
                    value={draft.action_id || null}
                    nothingFoundMessage="没有找到匹配任务"
                    onChange={(value) => {
                      if (!value) {
                        setDraft(() => buildEmptyDraft());
                        return;
                      }
                      const nextAction = manualActions.find((item) => item.id === value);
                      if (nextAction) {
                        setSelectedDomain(nextAction.domainLabel);
                      }
                      setRecentActionIds((current) => [value, ...current.filter((item) => item !== value)].slice(0, 10));
                      setDraft(() => buildDraftForActionSelection(value));
                    }}
                  />
                </SimpleGrid>
                {recentActions.length ? (
                  <Stack gap={6}>
                    <Text size="sm" c="dimmed">最近使用</Text>
                    <Group gap="xs">
                      {recentActions.map((action) => (
                        <Button
                          key={action.id}
                          size="xs"
                          variant={draft.action_id === action.id ? "filled" : "light"}
                          onClick={() => {
                            setSelectedDomain(action.domainLabel);
                            setDraft(() => buildDraftForActionSelection(action.id));
                          }}
                        >
                          {action.displayName}
                        </Button>
                      ))}
                    </Group>
                  </Stack>
                ) : null}
              </Stack>

              {selectedAction ? (
                <>
                  <Alert color="blue" variant="light" title={selectedAction.displayName}>
                    <Stack gap={4}>
                      <Text size="sm">所属类型：{selectedAction.categoryLabel}</Text>
                      {selectedAction.description ? <Text size="sm">{selectedAction.description}</Text> : null}
                    </Stack>
                  </Alert>

                  {actionGuidance ? (
                    <Alert color="teal" variant="light" title={actionGuidance.title}>
                      <Stack gap={4}>
                        {actionGuidance.lines.map((line) => (
                          <Text size="sm" key={line}>
                            {line}
                          </Text>
                        ))}
                      </Stack>
                    </Alert>
                  ) : null}

                  {selectedAction.timeCapability.hasTimeInput ? (
                    <Stack gap="xs">
                      <Text fw={700}>第二步：选择时间范围</Text>

                      {(selectedAction.timeCapability.supportsPoint && selectedAction.timeCapability.supportsRange) ? (
                        <SimpleGrid cols={{ base: 1, md: 2 }}>
                          <Button
                            variant={draft.date_mode === "single_point" ? "filled" : "light"}
                            onClick={() => setDraft((current) => ({ ...current, date_mode: "single_point" }))}
                          >
                            {getTimeModeLabels(selectedAction.timeCapability).point}
                          </Button>
                          <Button
                            variant={draft.date_mode === "time_range" ? "filled" : "light"}
                            onClick={() => setDraft((current) => ({ ...current, date_mode: "time_range" }))}
                          >
                            {getTimeModeLabels(selectedAction.timeCapability).range}
                          </Button>
                        </SimpleGrid>
                      ) : null}

                      {isSinglePoint(selectedAction, draft) ? (
                        selectedAction.timeCapability.pointGranularity === "month" ? (
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
                        ) : (
                          <DateField
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
                          {selectedAction.timeCapability.rangeGranularity === "month" ? (
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
                          ) : (
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
                          )}
                        </SimpleGrid>
                      )}
                    </Stack>
                  ) : null}

                  {selectedAction.supportedParams.length ? (
                    <Stack gap="xs">
                      <Text fw={700}>{selectedAction.timeCapability.hasTimeInput ? "第三步：其他输入条件" : "第二步：其他输入条件"}</Text>
                      <Grid>
                        {selectedAction.supportedParams.map((param) => (
                          <Grid.Col key={param.key} span={{ base: 12, md: 6 }}>
                            {(param.param_type === "enum" && param.multi_value) ? (
                              <Checkbox.Group
                                label={param.display_name}
                                description={param.description}
                                value={
                                  Array.isArray(draft.field_values[param.key])
                                    ? (draft.field_values[param.key] as string[])
                                    : String(draft.field_values[param.key] || "")
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
                                  Array.isArray(draft.field_values[param.key])
                                    ? ((draft.field_values[param.key] as string[])[0] || "")
                                    : (draft.field_values[param.key] as string) || ""
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
                                  Array.isArray(draft.field_values[param.key])
                                    ? ((draft.field_values[param.key] as string[])[0] || null)
                                    : (draft.field_values[param.key] as string) || null
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
                                value={Array.isArray(draft.field_values[param.key]) ? "" : (draft.field_values[param.key] as string) || ""}
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
                                value={Array.isArray(draft.field_values[param.key]) ? "" : (draft.field_values[param.key] as string) || ""}
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
                        loading={createExecutionMutation.isPending}
                        onClick={() => createExecutionMutation.mutate()}
                      >
                        开始同步
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
            <SectionCard title="常见用途" description="把最常见的手动维护动作固定下来，减少你去猜系统内部流程。">
              <Stack gap="sm">
                <Badge variant="light" size="lg" color="brand">补今天没跑出来的数据</Badge>
                <Badge variant="light" size="lg" color="brand">补一段时间的历史数据</Badge>
                <Badge variant="light" size="lg" color="brand">重新维护刚才失败的数据</Badge>
                <Badge variant="light" size="lg" color="brand">按自动任务配置手动跑一次</Badge>
              </Stack>
            </SectionCard>

            <SectionCard title="已带入条件" description="如果你是从任务记录或自动运行页跳过来的，这里会自动带入原来的条件。">
              <Stack gap="sm">
                <Text size="sm">来自任务记录：{prefillExecutionId || "无"}</Text>
                <Text size="sm">来自自动任务：{prefillScheduleId || "无"}</Text>
                <Text size="sm">当前已选数据：{selectedAction ? selectedAction.displayName : "未选择"}</Text>
              </Stack>
            </SectionCard>
          </Stack>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
