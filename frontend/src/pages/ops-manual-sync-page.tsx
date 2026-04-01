import {
  Accordion,
  Alert,
  Badge,
  Button,
  Grid,
  Group,
  JsonInput,
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
import { useEffect, useMemo } from "react";

import { apiRequest } from "../shared/api/client";
import type {
  ExecutionDetailResponse,
  OpsCatalogResponse,
  ScheduleDetailResponse,
} from "../shared/api/types";
import { formatCategoryLabel, formatResourceLabel, formatSpecDisplayLabel } from "../shared/ops-display";
import { usePersistentState } from "../shared/hooks/use-persistent-state";
import { DateField } from "../shared/ui/date-field";
import { EmptyState } from "../shared/ui/empty-state";
import { SectionCard } from "../shared/ui/section-card";

type ManualSpecType = "job" | "workflow";
type DateMode = "single_day" | "date_range";

type CatalogJobSpec = OpsCatalogResponse["job_specs"][number];
type CatalogWorkflowSpec = OpsCatalogResponse["workflow_specs"][number];
type CatalogParamSpec = NonNullable<CatalogJobSpec["supported_params"]>[number];

type ManualAction = {
  id: string;
  type: "job" | "workflow";
  categoryLabel: string;
  displayName: string;
  description: string;
  syncDailySpecKey: string | null;
  backfillSpecKey: string | null;
  directSpecKey: string | null;
  workflowKey: string | null;
  supportedParams: CatalogParamSpec[];
  supportsSingleDay: boolean;
  supportsDateRange: boolean;
};

type ActionGuidance = {
  title: string;
  lines: string[];
};

const INTERNAL_PARAM_KEYS = new Set(["offset", "limit"]);
const DATE_PARAM_KEYS = new Set(["trade_date", "start_date", "end_date"]);
const REFERENCE_RESOURCES = new Set(["stock_basic", "trade_cal", "etf_basic", "index_basic"]);

function parseJsonOrThrow(label: string, raw: string) {
  const normalized = raw.trim() || "{}";
  try {
    return JSON.parse(normalized);
  } catch {
    throw new Error(`${label} 格式不正确，请检查大括号、引号和逗号。`);
  }
}

function buildEmptyDraft() {
  return {
    action_id: "",
    date_mode: "single_day" as DateMode,
    selected_date: "",
    start_date: "",
    end_date: "",
    field_values: {} as Record<string, string>,
    extra_params_json: "{}",
  };
}

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
  return params.filter((param) => !INTERNAL_PARAM_KEYS.has(param.key) && !DATE_PARAM_KEYS.has(param.key));
}

function extractResourceKey(specKey: string) {
  const parts = specKey.split(".");
  return parts.length >= 2 ? parts[1] : specKey;
}

function isSingleDay(resource: ManualAction, draft: ReturnType<typeof buildEmptyDraft>) {
  if (resource.supportsSingleDay && resource.supportsDateRange) {
    return draft.date_mode === "single_day";
  }
  if (resource.supportsSingleDay) {
    return true;
  }
  return false;
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

  const actions: ManualAction[] = Array.from(resourceMap.values()).map((item) => ({
    id: `job:${item.resourceKey}`,
    type: "job",
    categoryLabel: formatCategoryLabel(item.category),
    displayName: `维护${formatResourceLabel(item.resourceKey)}`,
    description: item.description,
    syncDailySpecKey: item.syncDailySpec?.key || null,
    backfillSpecKey: item.backfillSpec?.key || null,
    directSpecKey: item.directSpec?.key || null,
    workflowKey: null,
    supportedParams: item.supportedParams,
    supportsSingleDay: Boolean(item.syncDailySpec),
    supportsDateRange: Boolean(item.backfillSpec),
  }));

  for (const workflow of catalog.workflow_specs.filter((item) => item.supports_manual_run !== false)) {
    actions.push({
      id: `workflow:${workflow.key}`,
      type: "workflow",
      categoryLabel: "工作流",
      displayName: workflow.display_name,
      description: workflow.description,
      syncDailySpecKey: null,
      backfillSpecKey: null,
      directSpecKey: null,
      workflowKey: workflow.key,
      supportedParams: [],
      supportsSingleDay: false,
      supportsDateRange: false,
    });
  }

  return actions.sort((left, right) => left.displayName.localeCompare(right.displayName, "zh-CN"));
}

function buildFieldValues(paramsJson: Record<string, unknown> | undefined) {
  if (!paramsJson) {
    return {};
  }
  return Object.fromEntries(Object.entries(paramsJson).map(([key, value]) => [key, String(value ?? "")]));
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
  const dateMode: DateMode = tradeDate || (startDate && endDate && startDate === endDate) ? "single_day" : "date_range";
  return {
    ...current,
    action_id: actionId,
    date_mode: dateMode,
    selected_date: tradeDate || startDate || current.selected_date,
    start_date: startDate,
    end_date: endDate,
    field_values: fieldValues,
    extra_params_json: JSON.stringify(paramsJson || {}, null, 2),
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

function resolveExecutionTarget(
  action: ManualAction,
  draft: ReturnType<typeof buildEmptyDraft>,
  extraJson: string,
) {
  const params = parseJsonOrThrow("高级参数", extraJson);

  for (const param of action.supportedParams) {
    const rawValue = draft.field_values[param.key];
    if (rawValue === undefined || rawValue === null || rawValue === "") {
      continue;
    }
    params[param.key] = param.param_type === "integer" ? Number(rawValue) : rawValue;
  }

  if (action.type === "workflow" && action.workflowKey) {
    return {
      spec_type: "workflow" as ManualSpecType,
      spec_key: action.workflowKey,
      params_json: params,
    };
  }

  if (action.supportsSingleDay && action.supportsDateRange) {
    if (draft.date_mode === "single_day") {
      if (!draft.selected_date) {
        throw new Error("请选择要处理的日期。");
      }
      if (!action.syncDailySpecKey) {
        throw new Error("当前任务暂不支持按单日直接执行。");
      }
      return {
        spec_type: "job" as ManualSpecType,
        spec_key: action.syncDailySpecKey,
        params_json: { ...params, trade_date: draft.selected_date },
      };
    }
    if (!draft.start_date || !draft.end_date) {
      throw new Error("请选择开始日期和结束日期。");
    }
    if (!action.backfillSpecKey) {
      throw new Error("当前任务暂不支持按日期区间补数据。");
    }
    return {
      spec_type: "job" as ManualSpecType,
      spec_key: action.backfillSpecKey,
      params_json: { ...params, start_date: draft.start_date, end_date: draft.end_date },
    };
  }

  if (action.supportsSingleDay) {
    if (!draft.selected_date) {
      throw new Error("请选择要处理的日期。");
    }
    if (!action.syncDailySpecKey) {
      throw new Error("当前任务暂不支持按单日直接执行。");
    }
    return {
      spec_type: "job" as ManualSpecType,
      spec_key: action.syncDailySpecKey,
      params_json: { ...params, trade_date: draft.selected_date },
    };
  }

  if (action.supportsDateRange) {
    const startDate = draft.start_date || draft.selected_date;
    const endDate = draft.end_date || draft.selected_date;
    if (!startDate || !endDate) {
      throw new Error("请选择开始日期和结束日期。");
    }
    if (!action.backfillSpecKey) {
      throw new Error("当前任务暂不支持按日期区间补数据。");
    }
    return {
      spec_type: "job" as ManualSpecType,
      spec_key: action.backfillSpecKey,
      params_json: { ...params, start_date: startDate, end_date: endDate },
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

  const actionOptions = useMemo(
    () =>
      manualActions.map((action) => ({
        value: action.id,
        label: `${action.displayName}（${action.categoryLabel}）`,
      })),
    [manualActions],
  );

  const selectedAction = useMemo(
    () => manualActions.find((item) => item.id === draft.action_id) || null,
    [draft.action_id, manualActions],
  );
  const actionGuidance = useMemo(() => getActionGuidance(selectedAction), [selectedAction]);

  useEffect(() => {
    if (!manualActions.length) {
      return;
    }
    if (!prefillSpecKey) {
      if (draft.action_id && manualActions.some((item) => item.id === draft.action_id)) {
        return;
      }
      return;
    }
    const prefilledAction = manualActions.find((item) => matchesActionSpec(item, prefillSpecType, prefillSpecKey));
    if (prefilledAction) {
      if (draft.action_id !== prefilledAction.id) {
        setDraft(() => buildDraftForActionSelection(prefilledAction.id));
      }
      return;
    }
  }, [draft.action_id, manualActions, prefillSpecKey, prefillSpecType, setDraft]);

  useEffect(() => {
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
      return;
    }
    setDraft((current) => buildDraftFromParams(current, action.id, prefillExecutionQuery.data.params_json));
  }, [manualActions, prefillExecutionQuery.data, setDraft]);

  useEffect(() => {
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
      return;
    }
    setDraft((current) => buildDraftFromParams(current, action.id, prefillScheduleQuery.data.params_json));
  }, [manualActions, prefillScheduleQuery.data, setDraft]);

  const createExecutionMutation = useMutation({
    mutationFn: () => {
      if (!selectedAction) {
        throw new Error("请先选择要维护的数据。");
      }
      return apiRequest<ExecutionDetailResponse>("/api/v1/ops/executions", {
        method: "POST",
        body: resolveExecutionTarget(selectedAction, draft, draft.extra_params_json),
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
                <Select
                  searchable
                  placeholder="例如：股票日线、分红送转、指数周线、交易日历"
                  data={actionOptions}
                  value={draft.action_id || null}
                  onChange={(value) =>
                    setDraft(() => (value ? buildDraftForActionSelection(value) : buildEmptyDraft()))
                  }
                />
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

                  {(selectedAction.supportsSingleDay || selectedAction.supportsDateRange) ? (
                    <Stack gap="xs">
                      <Text fw={700}>第二步：选择时间范围</Text>

                      {(selectedAction.supportsSingleDay && selectedAction.supportsDateRange) ? (
                        <SimpleGrid cols={{ base: 1, md: 2 }}>
                          <Button
                            variant={draft.date_mode === "single_day" ? "filled" : "light"}
                            onClick={() => setDraft((current) => ({ ...current, date_mode: "single_day" }))}
                          >
                            只处理一天
                          </Button>
                          <Button
                            variant={draft.date_mode === "date_range" ? "filled" : "light"}
                            onClick={() => setDraft((current) => ({ ...current, date_mode: "date_range" }))}
                          >
                            处理一个时间区间
                          </Button>
                        </SimpleGrid>
                      ) : null}

                      {isSingleDay(selectedAction, draft) ? (
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
                        <SimpleGrid cols={{ base: 1, md: 2 }}>
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
                        </SimpleGrid>
                      )}
                    </Stack>
                  ) : null}

                  <Stack gap="xs">
                    <Text fw={700}>第三步：补充范围条件</Text>
                    {selectedAction.supportedParams.length ? (
                      <Grid>
                        {selectedAction.supportedParams.map((param) => (
                          <Grid.Col key={param.key} span={{ base: 12, md: 6 }}>
                            {param.param_type === "enum" ? (
                              <Select
                                label={param.display_name}
                                placeholder={param.description}
                                data={normalizeParamOptions(param.options).map((option) => ({
                                  value: option,
                                  label: option,
                                }))}
                                value={draft.field_values[param.key] || null}
                                onChange={(value) =>
                                  setDraft((current) => ({
                                    ...current,
                                    field_values: { ...current.field_values, [param.key]: value || "" },
                                  }))
                                }
                              />
                            ) : (
                              <TextInput
                                label={param.display_name}
                                placeholder={param.description}
                                value={draft.field_values[param.key] || ""}
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
                    ) : (
                      <Alert color="gray" variant="light" title="这个任务没有额外筛选条件">
                        直接点击“开始同步”就可以了。
                      </Alert>
                    )}
                  </Stack>

                  <Accordion variant="separated" radius="md">
                    <Accordion.Item value="advanced">
                      <Accordion.Control>高级设置</Accordion.Control>
                      <Accordion.Panel>
                        <JsonInput
                          label="高级参数"
                          description="只有在常用条件不够用时才需要填写。与上面的条件重复时，以这里为准。"
                          autosize
                          minRows={8}
                          value={draft.extra_params_json}
                          onChange={(value) => setDraft((current) => ({ ...current, extra_params_json: value }))}
                        />
                      </Accordion.Panel>
                    </Accordion.Item>
                  </Accordion>

                  <Group justify="space-between" align="center">
                    <Text c="dimmed" size="sm">
                      提交后会直接跳到任务详情页，后续进度会自动刷新。
                    </Text>
                    <Button
                      variant="light"
                      onClick={() => setDraft(buildEmptyDraft())}
                    >
                      清空当前表单
                    </Button>
                    <Button
                      loading={createExecutionMutation.isPending}
                      onClick={() => createExecutionMutation.mutate()}
                    >
                      开始同步
                    </Button>
                  </Group>
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
