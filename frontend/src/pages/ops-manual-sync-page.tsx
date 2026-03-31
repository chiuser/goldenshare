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
import { formatCategoryLabel, formatSpecDisplayLabel } from "../shared/ops-display";
import { usePersistentState } from "../shared/hooks/use-persistent-state";
import { EmptyState } from "../shared/ui/empty-state";
import { PageHeader } from "../shared/ui/page-header";
import { SectionCard } from "../shared/ui/section-card";


type ManualSpecType = "job" | "workflow";
type RunMode = "now" | "queue";

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
    spec_type: "job" as ManualSpecType,
    spec_key: "",
    category_key: "all",
    run_mode: "now" as RunMode,
    field_values: {} as Record<string, string>,
    extra_params_json: "{}",
  };
}

function mergeParams(
  fieldValues: Record<string, string>,
  supportedParams: NonNullable<OpsCatalogResponse["job_specs"][number]["supported_params"]>,
  extraJson: string,
) {
  const params = parseJsonOrThrow("高级参数", extraJson);
  for (const param of supportedParams) {
    const rawValue = fieldValues[param.key];
    if (rawValue === undefined || rawValue === null || rawValue === "") {
      continue;
    }
    if (param.param_type === "integer") {
      params[param.key] = Number(rawValue);
      continue;
    }
    params[param.key] = rawValue;
  }
  return params;
}

function normalizeParamOptions(options: string[] | undefined) {
  return Array.isArray(options) ? options : [];
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

  const groupedJobSpecs = useMemo(() => {
    const catalog = catalogQuery.data;
    if (!catalog) return [];
    const groups = new Map<string, Array<{ value: string; label: string }>>();
    for (const item of catalog.job_specs.filter((job) => job.supports_manual_run !== false)) {
      const key = item.category || "other";
      const group = groups.get(key) || [];
      group.push({
        value: `job:${item.key}`,
        label: formatSpecDisplayLabel(item.key, item.display_name),
      });
      groups.set(key, group);
    }
    for (const item of catalog.workflow_specs.filter((workflow) => workflow.supports_manual_run !== false)) {
      const key = "workflow";
      const group = groups.get(key) || [];
      group.push({
        value: `workflow:${item.key}`,
        label: formatSpecDisplayLabel(item.key, item.display_name),
      });
      groups.set(key, group);
    }
    return Array.from(groups.entries()).map(([group, items]) => ({
      group,
      title: group === "workflow" ? "工作流" : formatCategoryLabel(group),
      items,
    }));
  }, [catalogQuery.data]);

  const flatSpecOptions = useMemo(
    () =>
      groupedJobSpecs.flatMap((group) =>
        group.items.map((item) => ({
          value: item.value,
          label: `【${group.title}】${item.label}`,
        })),
      ),
    [groupedJobSpecs],
  );

  const selectedSpec = useMemo(() => {
    const catalog = catalogQuery.data;
    if (!catalog || !draft.spec_key) return null;
    if (draft.spec_type === "job") {
      const job = catalog.job_specs.find((item) => item.key === draft.spec_key);
      if (!job) return null;
      return {
        type: "job" as const,
        key: job.key,
        display_name: formatSpecDisplayLabel(job.key, job.display_name),
        description: job.description,
        supported_params: job.supported_params || [],
        category: formatCategoryLabel(job.category),
      };
    }
    const workflow = catalog.workflow_specs.find((item) => item.key === draft.spec_key);
    if (!workflow) return null;
    return {
      type: "workflow" as const,
      key: workflow.key,
      display_name: formatSpecDisplayLabel(workflow.key, workflow.display_name),
      description: workflow.description,
      supported_params: [],
      category: "工作流",
    };
  }, [catalogQuery.data, draft.spec_key, draft.spec_type]);

  useEffect(() => {
    if (prefillExecutionQuery.data) {
      setDraft((current) => ({
        ...current,
        spec_type: prefillExecutionQuery.data.spec_type as ManualSpecType,
        spec_key: prefillExecutionQuery.data.spec_key,
        field_values: Object.fromEntries(
          Object.entries(prefillExecutionQuery.data.params_json || {}).map(([key, value]) => [key, String(value ?? "")]),
        ),
        extra_params_json: JSON.stringify(prefillExecutionQuery.data.params_json || {}, null, 2),
      }));
      return;
    }
    if (prefillScheduleQuery.data) {
      setDraft((current) => ({
        ...current,
        spec_type: prefillScheduleQuery.data.spec_type as ManualSpecType,
        spec_key: prefillScheduleQuery.data.spec_key,
        field_values: Object.fromEntries(
          Object.entries(prefillScheduleQuery.data.params_json || {}).map(([key, value]) => [key, String(value ?? "")]),
        ),
        extra_params_json: JSON.stringify(prefillScheduleQuery.data.params_json || {}, null, 2),
      }));
      return;
    }
    if (prefillSpecKey) {
      setDraft((current) => ({
        ...current,
        spec_type: (prefillSpecType as ManualSpecType) || current.spec_type,
        spec_key: prefillSpecKey,
      }));
    }
  }, [
    prefillExecutionQuery.data,
    prefillScheduleQuery.data,
    prefillSpecKey,
    prefillSpecType,
    setDraft,
  ]);

  const createQueuedMutation = useMutation({
    mutationFn: () =>
      apiRequest<ExecutionDetailResponse>("/api/v1/ops/executions", {
        method: "POST",
        body: {
          spec_type: draft.spec_type,
          spec_key: draft.spec_key,
          params_json: mergeParams(
            draft.field_values,
            selectedSpec?.type === "job" ? selectedSpec.supported_params : [],
            draft.extra_params_json,
          ),
        },
      }),
    onSuccess: async (data) => {
      notifications.show({
        color: "green",
        title: "任务已加入等待列表",
        message: `${formatSpecDisplayLabel(data.spec_key, data.spec_display_name)} #${data.id}`,
      });
      await navigate({ to: "/ops/tasks/$executionId", params: { executionId: String(data.id) } });
    },
    onError: (error) => {
      notifications.show({
        color: "red",
        title: "创建任务失败",
        message: error instanceof Error ? error.message : "未知错误",
      });
    },
  });

  const createAndRunMutation = useMutation({
    mutationFn: () =>
      apiRequest<ExecutionDetailResponse>("/api/v1/ops/executions/run-now", {
        method: "POST",
        body: {
          spec_type: draft.spec_type,
          spec_key: draft.spec_key,
          params_json: mergeParams(
            draft.field_values,
            selectedSpec?.type === "job" ? selectedSpec.supported_params : [],
            draft.extra_params_json,
          ),
        },
      }),
    onSuccess: async (data) => {
      notifications.show({
        color: "green",
        title: "任务已经开始处理",
        message: `${formatSpecDisplayLabel(data.spec_key, data.spec_display_name)} #${data.id}`,
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
      <PageHeader
        title="手动同步"
        description="当你需要补数据、重跑失败任务或立即执行一次时，从这里发起最直接。"
      />

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
            title="发起一次手动同步"
            description="先选要处理的数据，再填处理范围。默认会立即开始，不需要再去别的页面点第二次。"
          >
            <Stack gap="lg">
              <Stack gap="xs">
                <Text fw={700}>第一步：选择要处理的数据</Text>
                <Select
                  searchable
                  placeholder="搜索任务模板，例如：股票日线、分红送转、指数周线"
                  data={flatSpecOptions}
                  value={draft.spec_key ? `${draft.spec_type}:${draft.spec_key}` : null}
                  onChange={(value) => {
                    const [specType, specKey] = (value || "job:").split(":");
                    setDraft((current) => ({
                      ...current,
                      spec_type: specType as ManualSpecType,
                      spec_key: specKey || "",
                    }));
                  }}
                />
              </Stack>

              {selectedSpec ? (
                <>
                  <Alert color="blue" variant="light" title={selectedSpec.display_name}>
                    <Stack gap={4}>
                      <Text size="sm">所属类型：{selectedSpec.category}</Text>
                      {selectedSpec.description ? <Text size="sm">{selectedSpec.description}</Text> : null}
                    </Stack>
                  </Alert>

                  <Stack gap="xs">
                    <Text fw={700}>第二步：选择处理方式</Text>
                    <SimpleGrid cols={{ base: 1, md: 2 }}>
                      <Button
                        variant={draft.run_mode === "now" ? "filled" : "light"}
                        onClick={() => setDraft((current) => ({ ...current, run_mode: "now" }))}
                      >
                        立即开始
                      </Button>
                      <Button
                        variant={draft.run_mode === "queue" ? "filled" : "light"}
                        onClick={() => setDraft((current) => ({ ...current, run_mode: "queue" }))}
                      >
                        加入等待列表
                      </Button>
                    </SimpleGrid>
                  </Stack>

                  <Stack gap="xs">
                    <Text fw={700}>第三步：填写处理范围</Text>
                    {selectedSpec.type === "job" && selectedSpec.supported_params.length ? (
                      <Grid>
                        {selectedSpec.supported_params.map((param) => (
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
                      <Alert color="gray" variant="light" title="这个任务没有固定的常用参数">
                        你可以直接使用默认参数，或者在“高级设置”里填写完整参数。
                      </Alert>
                    )}
                  </Stack>

                  <Accordion variant="separated" radius="md">
                    <Accordion.Item value="advanced">
                      <Accordion.Control>高级设置</Accordion.Control>
                      <Accordion.Panel>
                        <JsonInput
                          label="高级参数"
                          description="如果这个任务需要更复杂的参数，可以直接在这里填写。与上面的常用参数重复时，以这里为准。"
                          autosize
                          minRows={8}
                          value={draft.extra_params_json}
                          onChange={(value) => setDraft((current) => ({ ...current, extra_params_json: value }))}
                        />
                      </Accordion.Panel>
                    </Accordion.Item>
                  </Accordion>

                  <Group justify="flex-end">
                    <Button
                      variant="light"
                      onClick={() => setDraft(buildEmptyDraft())}
                    >
                      清空当前表单
                    </Button>
                    <Button
                      loading={createQueuedMutation.isPending || createAndRunMutation.isPending}
                      onClick={() =>
                        draft.run_mode === "now"
                          ? createAndRunMutation.mutate()
                          : createQueuedMutation.mutate()
                      }
                    >
                      {draft.run_mode === "now" ? "开始同步" : "加入等待列表"}
                    </Button>
                  </Group>
                </>
              ) : (
                <EmptyState title="先选择一个要处理的任务" description="选中之后，我会显示这个任务常用的处理参数，尽量不用你直接写 JSON。" />
              )}
            </Stack>
          </SectionCard>
        </Grid.Col>

        <Grid.Col span={{ base: 12, xl: 4 }}>
          <Stack gap="lg">
            <SectionCard title="这页适合做什么" description="先把最常见的几类手动操作固定下来，避免每次都从任务记录里猜下一步。">
              <Stack gap="sm">
                <Badge variant="light" size="lg">补今天没跑出来的数据</Badge>
                <Badge variant="light" size="lg">重新执行刚才失败的任务</Badge>
                <Badge variant="light" size="lg">按日期范围补历史数据</Badge>
                <Badge variant="light" size="lg">按当前自动任务配置手动跑一次</Badge>
              </Stack>
            </SectionCard>

            <SectionCard title="最近带入的上下文" description="如果你是从任务记录或自动运行页跳过来的，这里会自动带入原来的参数。">
              <Stack gap="sm">
                <Text size="sm">来自任务记录：{prefillExecutionId ? `#${prefillExecutionId}` : "无"}</Text>
                <Text size="sm">来自自动任务：{prefillScheduleId ? `#${prefillScheduleId}` : "无"}</Text>
                <Text size="sm">当前执行方式：{draft.run_mode === "now" ? "立即开始" : "加入等待列表"}</Text>
              </Stack>
            </SectionCard>
          </Stack>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
