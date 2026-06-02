import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Divider,
  Grid,
  Group,
  Loader,
  NumberInput,
  Paper,
  ScrollArea,
  Stack,
  Switch,
  Table,
  Text,
  Title,
  UnstyledButton,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";

import { apiRequest } from "../shared/api/client";
import { ApiError } from "../shared/api/errors";
import type {
  RealtimeConfigDiffItem,
  RealtimeConfigField,
  RealtimeConfigApplyState,
  RealtimeConfigObjectDetailResponse,
  RealtimeConfigObjectListResponse,
  RealtimeConfigObjectSummary,
  RealtimeCollectorRestartResponse,
  RealtimeConfigRevisionItem,
  RealtimeConfigRevisionListResponse,
  RealtimeConfigValidateResponse,
  RealtimeConfigValue,
} from "../shared/api/realtime-config-types";
import { formatDateTimeLabel } from "../shared/date-format";
import { AlertBar } from "../shared/ui/alert-bar";
import { OpsTable, OpsTableCell, OpsTableCellText, OpsTableHeaderCell } from "../shared/ui/ops-table";
import { SectionCard } from "../shared/ui/section-card";
import { StatCard } from "../shared/ui/stat-card";
import { StatusBadge } from "../shared/ui/status-badge";

const CONFIG_OBJECTS_API_PATH = "/api/v1/ops/realtime/config/objects";
const CONFIG_COLLECTOR_RESTART_API_PATH = "/api/v1/ops/realtime/config/collector/restart";

type PageMode = "view" | "edit";
type DraftConfig = Record<string, RealtimeConfigValue>;

function objectDetailPath(objectKey: string): string {
  return `${CONFIG_OBJECTS_API_PATH}/${encodeURIComponent(objectKey)}`;
}

function objectValidatePath(objectKey: string): string {
  return `${objectDetailPath(objectKey)}/validate`;
}

function objectRevisionsPath(objectKey: string): string {
  return `${objectDetailPath(objectKey)}/revisions`;
}

export function OpsRealtimeConfigCenterPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [selectedObjectKey, setSelectedObjectKey] = useState<string | null>(null);
  const [mode, setMode] = useState<PageMode>("view");
  const [draftConfig, setDraftConfig] = useState<DraftConfig>({});
  const [validation, setValidation] = useState<RealtimeConfigValidateResponse | null>(null);
  const [validatedDraftSignature, setValidatedDraftSignature] = useState<string | null>(null);
  const [publishConflictMessage, setPublishConflictMessage] = useState<string | null>(null);

  const objectsQuery = useQuery({
    queryKey: ["ops", "realtime-config", "objects"],
    queryFn: () => apiRequest<RealtimeConfigObjectListResponse>(CONFIG_OBJECTS_API_PATH),
  });

  const objects = objectsQuery.data?.items ?? [];

  useEffect(() => {
    if (!selectedObjectKey && objects.length > 0) {
      setSelectedObjectKey(objects[0].object_key);
    }
  }, [objects, selectedObjectKey]);

  const detailQuery = useQuery({
    queryKey: ["ops", "realtime-config", "detail", selectedObjectKey],
    enabled: Boolean(selectedObjectKey),
    queryFn: () => apiRequest<RealtimeConfigObjectDetailResponse>(objectDetailPath(selectedObjectKey ?? "")),
  });

  const revisionsQuery = useQuery({
    queryKey: ["ops", "realtime-config", "revisions", selectedObjectKey],
    enabled: Boolean(selectedObjectKey),
    queryFn: () => apiRequest<RealtimeConfigRevisionListResponse>(objectRevisionsPath(selectedObjectKey ?? "")),
  });

  const detail = detailQuery.data;
  const draftSignature = useMemo(() => stableStringify(draftConfig), [draftConfig]);
  const canPublish = Boolean(validation?.valid && validatedDraftSignature === draftSignature);

  const validateMutation = useMutation({
    mutationFn: async () => {
      if (!selectedObjectKey) {
        throw new Error("请先选择实时流对象");
      }
      return apiRequest<RealtimeConfigValidateResponse>(objectValidatePath(selectedObjectKey), {
        method: "POST",
        body: { runtime_config: draftConfig },
      });
    },
    onSuccess: (result) => {
      setValidation(result);
      setValidatedDraftSignature(stableStringify(draftConfig));
      setPublishConflictMessage(null);
    },
  });

  const publishMutation = useMutation({
    mutationFn: async () => {
      if (!selectedObjectKey || !detail) {
        throw new Error("请先选择实时流对象");
      }
      return apiRequest(objectDetailPath(selectedObjectKey), {
        method: "PUT",
        body: {
          version: detail.version,
          runtime_config: draftConfig,
        },
      });
    },
    onSuccess: async () => {
      notifications.show({
        color: "green",
        title: "发布成功",
        message: "发布成功，需要重启 collector 生效。",
      });
      setMode("view");
      setValidation(null);
      setValidatedDraftSignature(null);
      setPublishConflictMessage(null);
      await refreshCurrentObject(queryClient, selectedObjectKey);
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        setPublishConflictMessage("配置已被更新，请刷新后重试");
        return;
      }
      notifications.show({
        color: "red",
        title: "发布失败",
        message: error instanceof Error ? error.message : "未知错误",
      });
    },
  });

  const restartCollectorMutation = useMutation({
    mutationFn: () => apiRequest<RealtimeCollectorRestartResponse>(CONFIG_COLLECTOR_RESTART_API_PATH, { method: "POST" }),
    onSuccess: async (result) => {
      notifications.show({
        color: result.status === "ok" ? "green" : "red",
        title: result.status === "ok" ? "重启命令已执行" : "重启失败",
        message: result.message,
      });
      await refreshObjectState(queryClient, selectedObjectKey);
      if (result.status === "ok" && selectedObjectKey) {
        await pollApplyStateUntilApplied(queryClient, selectedObjectKey);
      }
    },
    onError: (error) => {
      notifications.show({
        color: "red",
        title: "重启失败",
        message: error instanceof Error ? error.message : "未知错误",
      });
    },
  });

  function selectObject(objectKey: string): void {
    if (objectKey === selectedObjectKey) return;
    setSelectedObjectKey(objectKey);
    resetEditor();
  }

  function enterEditMode(): void {
    if (!detail) return;
    setDraftConfig(buildDraftFromDetail(detail));
    setValidation(null);
    setValidatedDraftSignature(null);
    setPublishConflictMessage(null);
    setMode("edit");
  }

  function resetEditor(): void {
    setMode("view");
    setDraftConfig({});
    setValidation(null);
    setValidatedDraftSignature(null);
    setPublishConflictMessage(null);
  }

  async function refreshConfig(): Promise<void> {
    resetEditor();
    await refreshCurrentObject(queryClient, selectedObjectKey);
  }

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-start" gap="md">
        <Stack gap={4}>
          <Text c="dimmed" size="sm">
            运行管理 / 实时流配置中心
          </Text>
          <Title order={2}>实时流配置中心</Title>
          <Text c="dimmed" size="sm">
            先选择实时流对象，再查看或编辑它的运行配置。查看态只解释事实；编辑态才展示草稿、校验和发布影响。
          </Text>
        </Stack>
        <Group gap="xs">
          <Button variant="light" onClick={() => void refreshConfig()} loading={objectsQuery.isFetching || detailQuery.isFetching}>
            刷新配置
          </Button>
          {mode === "view" ? (
            <Button onClick={enterEditMode} disabled={!detail}>
              进入编辑模式
            </Button>
          ) : (
            <Button variant="light" color="gray" onClick={resetEditor}>
              退出编辑模式
            </Button>
          )}
          <Button variant="outline" onClick={() => void navigate({ to: "/ops/v21/realtime" })}>
            查看实时流监控
          </Button>
        </Group>
      </Group>

      {objectsQuery.error ? (
        <Alert color="error" title="读取实时流配置对象失败">
          {objectsQuery.error instanceof Error ? objectsQuery.error.message : "未知错误"}
        </Alert>
      ) : null}

      <Grid>
        <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
          <StatCard label="配置对象" value={`${objects.length} 个`} hint="来自配置中心 objects API" hintDisplay="inline" />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
          <StatCard label="已启用" value={`${objects.filter((item) => item.enabled).length} 个`} hint="按后端当前配置事实统计" hintDisplay="inline" />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
          <StatCard label="当前版本" value={detail ? `v${detail.version}` : "—"} hint={detail?.display_name ?? "尚未选择对象"} hintDisplay="inline" />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6, xl: 3 }}>
          <StatCard label="当前模式" value={mode === "edit" ? "编辑态" : "查看态"} hint={mode === "edit" ? "草稿仅保存在页面内存" : "只展示后端配置事实"} hintDisplay="inline" />
        </Grid.Col>
      </Grid>

      <Grid align="stretch">
        <Grid.Col span={{ base: 12, lg: 4 }}>
          <SectionCard title="实时流对象" description="对象列表完全来自配置中心 API，前端不额外硬塞对象。">
            {objectsQuery.isLoading ? <Loader size="sm" /> : null}
            <Stack gap="sm">
              {objects.map((item) => (
                <RealtimeConfigObjectItem
                  key={item.object_key}
                  item={item}
                  active={item.object_key === selectedObjectKey}
                  onClick={() => selectObject(item.object_key)}
                />
              ))}
              {!objectsQuery.isLoading && objects.length === 0 ? (
                <AlertBar tone="warning" title="没有可配置对象">
                  当前后端没有返回实时流配置对象。
                </AlertBar>
              ) : null}
            </Stack>
          </SectionCard>
        </Grid.Col>

        <Grid.Col span={{ base: 12, lg: 8 }}>
          <SectionCard
            title={detail?.display_name ?? "配置详情"}
            description="右侧详情完全来自所选对象 detail API。"
            action={detail ? (
              <Group gap="xs">
                <StatusBadge value={detail.effective_config.enabled === true ? "active" : "disabled"} />
                <Badge variant="light" color="neutral">v{detail.version}</Badge>
                <ApplyStateBadge applyState={detail.apply_state} />
              </Group>
            ) : null}
          >
            {detailQuery.isLoading ? <Loader size="sm" /> : null}
            {detailQuery.error ? (
              <Alert color="error" title="读取配置详情失败">
                {detailQuery.error instanceof Error ? detailQuery.error.message : "未知错误"}
              </Alert>
            ) : null}
            {detail ? (
              mode === "edit" ? (
                <EditModePanel
                  detail={detail}
                  draftConfig={draftConfig}
                  setDraftConfig={(nextDraft) => {
                    setDraftConfig(nextDraft);
                    setValidation(null);
                    setValidatedDraftSignature(null);
                    setPublishConflictMessage(null);
                  }}
                  validation={validation}
                  validationError={validateMutation.error}
                  publishConflictMessage={publishConflictMessage}
                  canPublish={canPublish}
                  validateLoading={validateMutation.isPending}
                  publishLoading={publishMutation.isPending}
                  onValidate={() => validateMutation.mutate()}
                  onPublish={() => publishMutation.mutate()}
                />
              ) : (
                <ViewModePanel
                  detail={detail}
                  restartLoading={restartCollectorMutation.isPending}
                  restartError={restartCollectorMutation.error}
                  onRestart={() => restartCollectorMutation.mutate()}
                />
              )
            ) : null}
          </SectionCard>
        </Grid.Col>
      </Grid>

      <RevisionHistorySection revisions={revisionsQuery.data?.items ?? []} loading={revisionsQuery.isLoading} error={revisionsQuery.error} />
    </Stack>
  );
}

async function refreshCurrentObject(queryClient: ReturnType<typeof useQueryClient>, objectKey: string | null): Promise<void> {
  await refreshObjectState(queryClient, objectKey);
  if (objectKey) {
    await queryClient.invalidateQueries({ queryKey: ["ops", "realtime-config", "revisions", objectKey] });
  }
}

async function refreshObjectState(queryClient: ReturnType<typeof useQueryClient>, objectKey: string | null): Promise<void> {
  await queryClient.invalidateQueries({ queryKey: ["ops", "realtime-config", "objects"] });
  if (objectKey) {
    await queryClient.invalidateQueries({ queryKey: ["ops", "realtime-config", "detail", objectKey] });
  }
}

function RealtimeConfigObjectItem({
  item,
  active,
  onClick,
}: {
  item: RealtimeConfigObjectSummary;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <UnstyledButton onClick={onClick} style={{ width: "100%" }}>
      <Paper
        p="md"
        radius="md"
        withBorder
        styles={(theme) => ({
          root: {
            borderColor: active ? theme.colors.brand[4] : theme.colors.neutral[3],
            backgroundColor: active ? theme.colors.brand[0] : theme.white,
          },
        })}
      >
        <Stack gap="xs">
          <Group justify="space-between" gap="xs">
            <Text fw={700}>{item.display_name}</Text>
            <Badge variant="light" color={item.enabled ? "success" : "neutral"}>
              {item.enabled ? "启用" : "停用"}
            </Badge>
          </Group>
          <Text c="dimmed" ff="var(--mantine-font-family-monospace)" size="xs">
            {item.object_key}
          </Text>
          <Group gap="xs">
            <Badge variant="light" color="info">{item.object_kind}</Badge>
            <Badge variant="light" color="neutral">v{item.version}</Badge>
            <ApplyStateBadge applyState={item.apply_state} />
          </Group>
        </Stack>
      </Paper>
    </UnstyledButton>
  );
}

function ApplyStateBadge({ applyState }: { applyState: RealtimeConfigApplyState }) {
  return (
    <Badge variant="light" color={applyStateColor(applyState.status)}>
      {applyStateLabel(applyState.status)}
    </Badge>
  );
}

function ApplyStatePanel({
  detail,
  restartLoading,
  restartError,
  onRestart,
}: {
  detail: RealtimeConfigObjectDetailResponse;
  restartLoading: boolean;
  restartError: unknown;
  onRestart: () => void;
}) {
  const applyState = detail.apply_state;
  const showRestartButton = applyState.status !== "applied";
  return (
    <SectionCard title="发布生效状态" description="当前状态只来自 collector 上报的已应用版本，不再用发布策略字段推断。">
      <Stack gap="md">
        <Group gap="xs">
          <ApplyStateBadge applyState={applyState} />
          <Badge variant="light" color="neutral">发布版本 v{applyState.published_version}</Badge>
          {applyState.applied_version === null ? (
            <Badge variant="light" color="warning">未确认已应用版本</Badge>
          ) : (
            <Badge variant="light" color="info">已应用 v{applyState.applied_version}</Badge>
          )}
        </Group>
        <Text c="dimmed" size="sm">
          {applyState.message}
        </Text>
        <Grid>
          <Grid.Col span={{ base: 12, md: 4 }}>
            <Stack gap={2}>
              <Text fw={600} size="sm">Collector</Text>
              <Text c="dimmed" size="sm">{applyState.collector_id ?? "—"}</Text>
            </Stack>
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 4 }}>
            <Stack gap={2}>
              <Text fw={600} size="sm">进程启动</Text>
              <Text c="dimmed" size="sm">{formatDateTimeOrDash(applyState.process_started_at)}</Text>
            </Stack>
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 4 }}>
            <Stack gap={2}>
              <Text fw={600} size="sm">上报时间</Text>
              <Text c="dimmed" size="sm">{formatDateTimeOrDash(applyState.applied_at)}</Text>
            </Stack>
          </Grid.Col>
        </Grid>
        {restartError ? (
          <Alert color="error" title="重启请求失败">
            {restartError instanceof Error ? restartError.message : "未知错误"}
          </Alert>
        ) : null}
        {showRestartButton ? (
          <Group justify="flex-start">
            <Button onClick={onRestart} loading={restartLoading}>
              重启 collector
            </Button>
            <Text c="dimmed" size="sm">
              操作只重启固定 collector 服务；页面会等待 collector 上报已应用版本。
            </Text>
          </Group>
        ) : null}
      </Stack>
    </SectionCard>
  );
}

function applyStateLabel(status: RealtimeConfigApplyState["status"]): string {
  if (status === "applied") return "已应用";
  if (status === "pending_restart") return "待重启生效";
  return "应用状态未知";
}

function applyStateColor(status: RealtimeConfigApplyState["status"]): string {
  if (status === "applied") return "success";
  if (status === "pending_restart") return "warning";
  return "neutral";
}

function ViewModePanel({
  detail,
  restartLoading,
  restartError,
  onRestart,
}: {
  detail: RealtimeConfigObjectDetailResponse;
  restartLoading: boolean;
  restartError: unknown;
  onRestart: () => void;
}) {
  return (
    <Stack gap="lg">
      <AlertBar tone="info" title="当前为查看态">
        这里仅展示后端已经发布生效的配置事实；校验结果、发布影响和草稿差异只会在编辑态展示。
      </AlertBar>
      <ApplyStatePanel
        detail={detail}
        restartLoading={restartLoading}
        restartError={restartError}
        onRestart={onRestart}
      />
      <Grid>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <ConfigValueList title="有效配置" values={detail.effective_config} fields={detail.fields} />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <ConfigValueList title="锁定配置" values={detail.locked_config} fields={detail.fields} locked />
        </Grid.Col>
      </Grid>
      <FieldDetailTable detail={detail} />
    </Stack>
  );
}

function EditModePanel({
  detail,
  draftConfig,
  setDraftConfig,
  validation,
  validationError,
  publishConflictMessage,
  canPublish,
  validateLoading,
  publishLoading,
  onValidate,
  onPublish,
}: {
  detail: RealtimeConfigObjectDetailResponse;
  draftConfig: DraftConfig;
  setDraftConfig: (draftConfig: DraftConfig) => void;
  validation: RealtimeConfigValidateResponse | null;
  validationError: unknown;
  publishConflictMessage: string | null;
  canPublish: boolean;
  validateLoading: boolean;
  publishLoading: boolean;
  onValidate: () => void;
  onPublish: () => void;
}) {
  return (
    <Stack gap="lg">
      <AlertBar tone="warning" title="当前为编辑态">
        草稿只保存在当前页面。提交发布前必须先校验；发布成功后需要重启 collector 生效。
      </AlertBar>

      <Grid>
        <Grid.Col span={{ base: 12, xl: 7 }}>
          <SectionCard title="编辑草稿" description="控件类型由后端 fields 元信息决定。">
            <Stack gap="md">
              {detail.fields.map((field) => (
                <ConfigFieldInput
                  key={field.key}
                  field={field}
                  draftConfig={draftConfig}
                  lockedValue={detail.locked_config[field.key]}
                  onChange={(value) => setDraftConfig({ ...draftConfig, [field.key]: value })}
                />
              ))}
            </Stack>
          </SectionCard>
        </Grid.Col>
        <Grid.Col span={{ base: 12, xl: 5 }}>
          <SectionCard title="校验与发布" description="只有最近一次校验成功且草稿未再变化，才允许发布。">
            <Stack gap="md">
              <Group gap="xs">
                <Button onClick={onValidate} loading={validateLoading}>
                  校验草稿
                </Button>
                <Button onClick={onPublish} loading={publishLoading} disabled={!canPublish}>
                  提交发布
                </Button>
              </Group>

              {validationError ? (
                <Alert color="error" title="校验请求失败">
                  {validationError instanceof Error ? validationError.message : "未知错误"}
                </Alert>
              ) : null}
              {publishConflictMessage ? (
                <Alert color="warning" title="版本冲突">
                  {publishConflictMessage}
                </Alert>
              ) : null}
              {validation ? <ValidationResult validation={validation} fields={detail.fields} /> : (
                <Text c="dimmed" size="sm">
                  尚未校验草稿。校验通过后，发布按钮才会解锁。
                </Text>
              )}
            </Stack>
          </SectionCard>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}

function ConfigFieldInput({
  field,
  draftConfig,
  lockedValue,
  onChange,
}: {
  field: RealtimeConfigField;
  draftConfig: DraftConfig;
  lockedValue: RealtimeConfigValue | undefined;
  onChange: (value: RealtimeConfigValue) => void;
}) {
  if (!field.editable || field.control === "locked_text") {
    return (
      <Stack gap={4}>
        <Text fw={600} size="sm">{field.label}</Text>
        <ValueDisplay value={lockedValue ?? draftConfig[field.key]} />
        <Text c="dimmed" ff="var(--mantine-font-family-monospace)" size="xs">{field.key}</Text>
      </Stack>
    );
  }

  if (field.control === "switch") {
    return (
      <Switch
        label={field.label}
        description={field.key}
        checked={draftConfig[field.key] === true}
        onChange={(event) => onChange(event.currentTarget.checked)}
      />
    );
  }

  if (field.control === "number_input") {
    return (
      <NumberInput
        label={field.label}
        description={field.key}
        value={typeof draftConfig[field.key] === "number" ? draftConfig[field.key] as number : undefined}
        onChange={(value) => onChange(value === "" ? null : Number(value))}
        min={0}
        allowDecimal={false}
      />
    );
  }

  if (field.control === "checkbox_group") {
    return (
      <Checkbox.Group
        label={field.label}
        description={field.key}
        value={Array.isArray(draftConfig[field.key]) ? draftConfig[field.key] as string[] : []}
        onChange={(value) => onChange(value)}
      >
        <Group gap="sm" mt="xs">
          {field.options.map((option) => (
            <Checkbox key={option.value} value={option.value} label={option.label} />
          ))}
        </Group>
      </Checkbox.Group>
    );
  }

  return (
    <Stack gap={4}>
      <Text fw={600} size="sm">{field.label}</Text>
      <ValueDisplay value={draftConfig[field.key]} />
      <Text c="dimmed" size="xs">暂不支持编辑控件：{field.control}</Text>
    </Stack>
  );
}

function ConfigValueList({
  title,
  values,
  fields,
  locked = false,
}: {
  title: string;
  values: Record<string, RealtimeConfigValue>;
  fields: RealtimeConfigField[];
  locked?: boolean;
}) {
  const entries = Object.entries(values);
  const fieldLabelByKey = labelMapFromFields(fields);
  return (
    <SectionCard title={title} description={locked ? "锁定配置只展示，不进入发布草稿。" : "有效配置来自当前已发布配置。"}>
      <Stack gap="sm">
        {entries.length === 0 ? (
          <Text c="dimmed" size="sm">暂无配置项。</Text>
        ) : null}
        {entries.map(([key, value]) => (
          <Group key={key} justify="space-between" align="flex-start" gap="md">
            <Stack gap={2}>
              <Text fw={600} size="sm">{fieldLabelByKey[key] ?? key}</Text>
              <Text c="dimmed" ff="var(--mantine-font-family-monospace)" size="xs">{key}</Text>
            </Stack>
            <ValueDisplay value={value} />
          </Group>
        ))}
      </Stack>
    </SectionCard>
  );
}

function FieldDetailTable({ detail }: { detail: RealtimeConfigObjectDetailResponse }) {
  return (
    <SectionCard title="配置项明细" description="明细表只解释当前配置事实，不承载发布检查。">
      <ScrollArea>
        <OpsTable miw={760}>
          <Table.Thead>
            <Table.Tr>
              <OpsTableHeaderCell align="left" width="24%">配置项</OpsTableHeaderCell>
              <OpsTableHeaderCell align="left" width="24%">当前值</OpsTableHeaderCell>
              <OpsTableHeaderCell align="left" width="18%">控件</OpsTableHeaderCell>
              <OpsTableHeaderCell align="left" width="18%">编辑策略</OpsTableHeaderCell>
              <OpsTableHeaderCell align="left" width="16%">类型</OpsTableHeaderCell>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {detail.fields.map((field) => (
              <Table.Tr key={field.key}>
                <OpsTableCell align="left">
                  <Stack gap={2}>
                    <OpsTableCellText fw={600}>{field.label}</OpsTableCellText>
                    <OpsTableCellText c="dimmed" ff="var(--mantine-font-family-monospace)" size="xs">
                      {field.key}
                    </OpsTableCellText>
                  </Stack>
                </OpsTableCell>
                <OpsTableCell align="left">
                  <ValueDisplay value={detail.effective_config[field.key] ?? detail.locked_config[field.key]} />
                </OpsTableCell>
                <OpsTableCell align="left">
                  <OpsTableCellText>{formatControlLabel(field.control)}</OpsTableCellText>
                </OpsTableCell>
                <OpsTableCell align="left">
                  <Badge variant="light" color={field.editable ? "info" : "neutral"}>
                    {field.editable ? "可编辑" : "锁定"}
                  </Badge>
                </OpsTableCell>
                <OpsTableCell align="left">
                  <OpsTableCellText>{field.value_type}</OpsTableCellText>
                </OpsTableCell>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </OpsTable>
      </ScrollArea>
    </SectionCard>
  );
}

function ValidationResult({
  validation,
  fields,
}: {
  validation: RealtimeConfigValidateResponse;
  fields: RealtimeConfigField[];
}) {
  return (
    <Stack gap="md">
      {validation.valid ? (
        <AlertBar tone="success" title="校验通过">
          当前草稿可以提交发布。
        </AlertBar>
      ) : (
        <AlertBar tone="error" title="校验失败">
          草稿存在错误，修正后需要重新校验。
        </AlertBar>
      )}

      {validation.errors.length > 0 ? (
        <Stack gap="xs">
          <Text fw={700} size="sm">错误</Text>
          {validation.errors.map((error) => (
            <Alert key={`${error.field ?? "global"}-${error.code}-${error.message}`} color="error" title={formatFieldName(error.field, fields)}>
              {error.message}
            </Alert>
          ))}
        </Stack>
      ) : null}

      {validation.warnings.length > 0 ? (
        <Stack gap="xs">
          <Text fw={700} size="sm">提示</Text>
          {validation.warnings.map((warning) => (
            <Alert key={`${warning.field ?? "global"}-${warning.message}`} color="warning" title={formatFieldName(warning.field, fields)}>
              {warning.message}
            </Alert>
          ))}
        </Stack>
      ) : null}

      <Divider />
      <Stack gap="xs">
        <Text fw={700} size="sm">草稿差异</Text>
        {validation.diff.length > 0 ? <DiffTable diff={validation.diff} fields={fields} /> : (
          <Text c="dimmed" size="sm">本次草稿没有差异。</Text>
        )}
      </Stack>

      <Stack gap="xs">
        <Text fw={700} size="sm">发布影响</Text>
        <Group gap="xs">
          <Badge variant="light" color={validation.impact.requires_collector_restart ? "warning" : "neutral"}>
            {validation.impact.requires_collector_restart ? "需要重启 collector" : "无需重启"}
          </Badge>
          {validation.impact.affected_feeds.map((feed) => (
            <Badge key={feed} variant="light" color="info">{feed}</Badge>
          ))}
        </Group>
      </Stack>
    </Stack>
  );
}

function DiffTable({
  diff,
  fields,
}: {
  diff: RealtimeConfigDiffItem[];
  fields: RealtimeConfigField[];
}) {
  return (
    <OpsTable>
      <Table.Thead>
        <Table.Tr>
          <OpsTableHeaderCell align="left">配置项</OpsTableHeaderCell>
          <OpsTableHeaderCell align="left">发布前</OpsTableHeaderCell>
          <OpsTableHeaderCell align="left">发布后</OpsTableHeaderCell>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {diff.map((item) => (
          <Table.Tr key={item.field}>
            <OpsTableCell align="left">
              <OpsTableCellText fw={600}>{formatFieldName(item.field, fields)}</OpsTableCellText>
            </OpsTableCell>
            <OpsTableCell align="left">
              <ValueDisplay value={item.before as RealtimeConfigValue} />
            </OpsTableCell>
            <OpsTableCell align="left">
              <ValueDisplay value={item.after as RealtimeConfigValue} />
            </OpsTableCell>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </OpsTable>
  );
}

function RevisionHistorySection({
  revisions,
  loading,
  error,
}: {
  revisions: RealtimeConfigRevisionItem[];
  loading: boolean;
  error: unknown;
}) {
  return (
    <SectionCard title="修订历史" description="最近发布记录只做查看，不提供回滚。">
      {loading ? <Loader size="sm" /> : null}
      {error ? (
        <Alert color="error" title="读取修订历史失败">
          {error instanceof Error ? error.message : "未知错误"}
        </Alert>
      ) : null}
      {!loading && revisions.length === 0 ? (
        <Text c="dimmed" size="sm">暂无发布记录。</Text>
      ) : null}
      {revisions.length > 0 ? (
        <ScrollArea>
          <OpsTable miw={860}>
            <Table.Thead>
              <Table.Tr>
                <OpsTableHeaderCell align="left" width="18%">发布时间</OpsTableHeaderCell>
                <OpsTableHeaderCell align="left" width="16%">操作人</OpsTableHeaderCell>
                <OpsTableHeaderCell align="left" width="14%">动作</OpsTableHeaderCell>
                <OpsTableHeaderCell align="left" width="26%">发布前</OpsTableHeaderCell>
                <OpsTableHeaderCell align="left" width="26%">发布后</OpsTableHeaderCell>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {revisions.map((item) => (
                <Table.Tr key={item.id}>
                  <OpsTableCell align="left">
                    <OpsTableCellText>{formatDateTimeLabel(item.changed_at)}</OpsTableCellText>
                  </OpsTableCell>
                  <OpsTableCell align="left">
                    <OpsTableCellText>{item.changed_by_username || "—"}</OpsTableCellText>
                  </OpsTableCell>
                  <OpsTableCell align="left">
                    <Badge variant="light" color="info">{item.action}</Badge>
                  </OpsTableCell>
                  <OpsTableCell align="left">
                    <OpsTableCellText size="xs">{summarizeRevisionPayload(item.before_json)}</OpsTableCellText>
                  </OpsTableCell>
                  <OpsTableCell align="left">
                    <OpsTableCellText size="xs">{summarizeRevisionPayload(item.after_json)}</OpsTableCellText>
                  </OpsTableCell>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </OpsTable>
        </ScrollArea>
      ) : null}
    </SectionCard>
  );
}

function ValueDisplay({ value }: { value: RealtimeConfigValue | undefined }) {
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <Badge variant="light" color="neutral">空</Badge>;
    }
    return (
      <Group gap={6}>
        {value.map((item) => (
          <Badge key={item} variant="light" color="info">{item}</Badge>
        ))}
      </Group>
    );
  }
  if (typeof value === "boolean") {
    return (
      <Badge variant="light" color={value ? "success" : "neutral"}>
        {value ? "启用" : "停用"}
      </Badge>
    );
  }
  if (value === null || value === undefined) {
    return <Text c="dimmed" size="sm">—</Text>;
  }
  if (typeof value === "object") {
    return (
      <Text ff="var(--mantine-font-family-monospace)" size="xs">
        {JSON.stringify(value)}
      </Text>
    );
  }
  return (
    <Text ff={typeof value === "string" && value.includes("_") ? "var(--mantine-font-family-monospace)" : undefined} size="sm">
      {String(value)}
    </Text>
  );
}

function buildDraftFromDetail(detail: RealtimeConfigObjectDetailResponse): DraftConfig {
  const editableKeys = new Set(detail.fields.filter((field) => field.editable).map((field) => field.key));
  return Object.fromEntries(Object.entries(detail.effective_config).filter(([key]) => editableKeys.has(key)));
}

function labelMapFromFields(fields: RealtimeConfigField[]): Record<string, string> {
  return Object.fromEntries(fields.map((field) => [field.key, field.label]));
}

function formatFieldName(fieldKey: string | null, fields: RealtimeConfigField[]): string {
  if (!fieldKey) return "全局";
  return labelMapFromFields(fields)[fieldKey] ?? fieldKey;
}

function formatControlLabel(control: string): string {
  const labels: Record<string, string> = {
    switch: "开关",
    number_input: "数字输入",
    checkbox_group: "多选",
    locked_text: "锁定文本",
  };
  return labels[control] ?? control;
}

function stableStringify(value: unknown): string {
  return JSON.stringify(sortValue(value));
}

function sortValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, entryValue]) => [key, sortValue(entryValue)]),
    );
  }
  return value;
}

function summarizeRevisionPayload(payload: Record<string, unknown> | null): string {
  if (!payload) return "—";
  const keys = Object.keys(payload);
  if (keys.length === 0) return "空";
  return keys.slice(0, 4).join(" / ") + (keys.length > 4 ? ` 等 ${keys.length} 项` : "");
}

function formatDateTimeOrDash(value: string | null): string {
  return value ? formatDateTimeLabel(value) : "—";
}

async function pollApplyStateUntilApplied(
  queryClient: ReturnType<typeof useQueryClient>,
  objectKey: string,
): Promise<void> {
  for (let attempt = 0; attempt < 10; attempt += 1) {
    if (attempt > 0) {
      await delay(2000);
    }
    const detail = await queryClient.fetchQuery({
      queryKey: ["ops", "realtime-config", "detail", objectKey],
      queryFn: () => apiRequest<RealtimeConfigObjectDetailResponse>(objectDetailPath(objectKey)),
    });
    await queryClient.invalidateQueries({ queryKey: ["ops", "realtime-config", "objects"] });
    if (detail.apply_state.status === "applied") {
      return;
    }
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}
