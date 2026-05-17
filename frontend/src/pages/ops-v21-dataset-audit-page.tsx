import {
  Alert,
  Badge,
  Button,
  Drawer,
  Group,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Tabs,
  Text,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconCalendarStats, IconListCheck, IconPlayerPlay, IconSearch } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { apiRequest } from "../shared/api/client";
import type {
  DateCompletenessExclusionListResponse,
  DateCompletenessGapListResponse,
  DateCompletenessRuleItem,
  DateCompletenessRuleListResponse,
  DateCompletenessRunCreateResponse,
  DateCompletenessRunItem,
  DateCompletenessRunListResponse,
  DateSubjectCompletenessGapDetailListResponse,
  DateSubjectCompletenessGapListResponse,
} from "../shared/api/date-completeness-types";
import { formatDateLabel, formatDateTimeLabel } from "../shared/date-format";
import { DateField } from "../shared/ui/date-field";
import { EmptyState } from "../shared/ui/empty-state";
import { FilterBar, FilterBarItem } from "../shared/ui/filter-bar";
import { OpsTable, OpsTableCell, OpsTableHeaderCell } from "../shared/ui/ops-table";
import { PageHeader } from "../shared/ui/page-header";
import { SectionCard } from "../shared/ui/section-card";
import { StatCard } from "../shared/ui/stat-card";
import { StatusBadge } from "../shared/ui/status-badge";
import { TableShell } from "../shared/ui/table-shell";
import { OpsV21DatasetAuditSchedulesPanel } from "./ops-v21-dataset-audit-schedules-panel";

type AuditTab = "datasets" | "runs" | "schedules";

const DEFAULT_RANGE = {
  start_date: "2026-04-20",
  end_date: "2026-04-24",
};

function byGroup(response: DateCompletenessRuleListResponse | undefined, groupKey: "supported" | "unsupported") {
  return response?.groups.find((group) => group.group_key === groupKey)?.items || [];
}

function resultLabel(value: DateCompletenessRunItem["result_status"]): string {
  if (value === "passed") return "通过";
  if (value === "failed") return "不通过";
  if (value === "error") return "执行错误";
  return "未完成";
}

function resultBadgeValue(value: DateCompletenessRunItem["result_status"]): string {
  if (value === "passed") return "success";
  if (value === "failed") return "failed";
  if (value === "error") return "error";
  return "queued";
}

function runModeLabel(value: string): string {
  return value === "scheduled" ? "自动" : "手动";
}

function unexpectedBucketCount(item: Pick<DateCompletenessRunItem, "actual_bucket_count" | "expected_bucket_count">): number {
  return Math.max(item.actual_bucket_count - item.expected_bucket_count, 0);
}

function auditScopeLabel(value: DateCompletenessRunItem["audit_scope"] | DateCompletenessRuleItem["audit_scope"]): string {
  return value === "date_subject_matrix" ? "日期 × 对象矩阵" : "日期桶";
}

function isSubjectMatrixRun(item: DateCompletenessRunItem | null): boolean {
  return item?.audit_scope === "date_subject_matrix";
}

function subjectSampleLabel(sample: Record<string, unknown>): string {
  const key = sample.subject_key || sample.ts_code || sample.code || Object.values(sample)[0] || "—";
  const name = sample.subject_name || sample.name;
  return name ? `${String(key)} ${String(name)}` : String(key);
}

function subjectKeyLabel(value: Record<string, unknown>): string {
  const entries = Object.entries(value);
  if (!entries.length) return "—";
  return entries.map(([key, item]) => `${key}=${String(item)}`).join("，");
}

function lifecycleLabel(start: string | null, end: string | null): string {
  if (start && end) return `${formatDateLabel(start)} 至 ${formatDateLabel(end)}`;
  if (start) return `${formatDateLabel(start)} 至今`;
  if (end) return `截至 ${formatDateLabel(end)}`;
  return "—";
}

function progressLabel(item: DateCompletenessRunItem): string {
  if (item.run_status === "queued") return "等待审计 worker 执行";
  if (item.expected_bucket_count > 0) {
    const current = item.current_bucket_value ? `，当前 ${formatDateLabel(item.current_bucket_value)}` : "";
    return `已处理 ${item.processed_bucket_count} / ${item.expected_bucket_count} 个日期桶${current}`;
  }
  return item.progress_message || "尚未生成日期桶进度";
}

function heartbeatLabel(value: string | null): string {
  return value ? formatDateTimeLabel(value) : "暂无心跳";
}

function heartbeatIsStale(item: DateCompletenessRunItem): boolean {
  if (item.run_status !== "running" || !item.heartbeat_at) return false;
  const timestamp = new Date(item.heartbeat_at).getTime();
  if (!Number.isFinite(timestamp)) return false;
  return Date.now() - timestamp > 5 * 60 * 1000;
}

export function OpsV21DatasetAuditPage() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<AuditTab>("datasets");
  const [group, setGroup] = useState<"supported" | "unsupported">("supported");
  const [domain, setDomain] = useState<string | null>(null);
  const [selectedRule, setSelectedRule] = useState<DateCompletenessRuleItem | null>(null);
  const [range, setRange] = useState(DEFAULT_RANGE);
  const [selectedRun, setSelectedRun] = useState<DateCompletenessRunItem | null>(null);

  const rulesQuery = useQuery({
    queryKey: ["ops", "date-completeness", "rules"],
    queryFn: () => apiRequest<DateCompletenessRuleListResponse>("/api/v1/ops/review/date-completeness/rules"),
  });

  const runsQuery = useQuery({
    queryKey: ["ops", "date-completeness", "runs"],
    queryFn: () => apiRequest<DateCompletenessRunListResponse>("/api/v1/ops/review/date-completeness/runs?limit=50&offset=0"),
    refetchInterval: (query) => {
      const hasOpenRun = query.state.data?.items.some((item) => item.run_status === "queued" || item.run_status === "running");
      return hasOpenRun ? 3000 : false;
    },
  });

  const gapsQuery = useQuery({
    queryKey: ["ops", "date-completeness", "run-gaps", selectedRun?.id],
    queryFn: () => apiRequest<DateCompletenessGapListResponse>(`/api/v1/ops/review/date-completeness/runs/${selectedRun?.id}/gaps`),
    enabled: Boolean(selectedRun && !isSubjectMatrixRun(selectedRun)),
  });

  const exclusionsQuery = useQuery({
    queryKey: ["ops", "date-completeness", "run-exclusions", selectedRun?.id],
    queryFn: () => apiRequest<DateCompletenessExclusionListResponse>(`/api/v1/ops/review/date-completeness/runs/${selectedRun?.id}/exclusions`),
    enabled: Boolean(selectedRun && selectedRun.excluded_bucket_count > 0),
  });

  const subjectGapsQuery = useQuery({
    queryKey: ["ops", "date-completeness", "run-subject-gaps", selectedRun?.id],
    queryFn: () =>
      apiRequest<DateSubjectCompletenessGapListResponse>(`/api/v1/ops/review/date-completeness/runs/${selectedRun?.id}/subject-gaps`),
    enabled: Boolean(selectedRun && isSubjectMatrixRun(selectedRun)),
  });

  const subjectGapDetailsQuery = useQuery({
    queryKey: ["ops", "date-completeness", "run-subject-gap-details", selectedRun?.id],
    queryFn: () =>
      apiRequest<DateSubjectCompletenessGapDetailListResponse>(
        `/api/v1/ops/review/date-completeness/runs/${selectedRun?.id}/subject-gap-details`,
      ),
    enabled: Boolean(selectedRun && isSubjectMatrixRun(selectedRun)),
  });

  const createRunMutation = useMutation({
    mutationFn: (payload: { dataset_key: string; start_date: string; end_date: string }) =>
      apiRequest<DateCompletenessRunCreateResponse>("/api/v1/ops/review/date-completeness/runs", {
        method: "POST",
        body: payload,
      }),
    onSuccess: async (created) => {
      notifications.show({
        color: "brand",
        title: "审计任务已创建",
        message: `${created.display_name} 已进入独立审计队列。`,
      });
      setSelectedRule(null);
      setTab("runs");
      await queryClient.invalidateQueries({ queryKey: ["ops", "date-completeness", "runs"] });
    },
    onError: (error) => {
      notifications.show({
        color: "red",
        title: "创建审计失败",
        message: error instanceof Error ? error.message : "请稍后重试。",
      });
    },
  });

  const supportedRules = byGroup(rulesQuery.data, "supported");
  const unsupportedRules = byGroup(rulesQuery.data, "unsupported");
  const groupOptions = useMemo(() => {
    const groups = new Map<string, string>();
    for (const item of [...supportedRules, ...unsupportedRules]) {
      groups.set(item.group_key, item.group_label);
    }
    return [...groups.entries()].map(([value, label]) => ({ value, label }));
  }, [supportedRules, unsupportedRules]);

  const visibleRules = useMemo(() => {
    const source = group === "supported" ? supportedRules : unsupportedRules;
    return domain ? source.filter((item) => item.group_key === domain) : source;
  }, [domain, group, supportedRules, unsupportedRules]);

  const failedRuns = runsQuery.data?.items.filter((item) => item.result_status === "failed").length ?? 0;
  const openRuns = runsQuery.data?.items.filter((item) => item.run_status === "queued" || item.run_status === "running").length ?? 0;

  const submitRun = () => {
    if (!selectedRule) return;
    createRunMutation.mutate({
      dataset_key: selectedRule.dataset_key,
      start_date: range.start_date,
      end_date: range.end_date,
    });
  };

  return (
    <Stack gap="lg">
      <PageHeader
        title="数据集审计"
        description="检查数据集在指定日期范围内是否存在缺失日期桶；支持对象矩阵的数据集会进一步检查日期 × 对象是否缺行。"
      />

      <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
        <StatCard label="支持审计数据集" value={rulesQuery.data?.summary.supported ?? "—"} />
        <StatCard label="不支持审计数据集" value={rulesQuery.data?.summary.unsupported ?? "—"} />
        <StatCard label="最近不通过" value={failedRuns} hint="只统计最近 50 条审计记录。" />
        <StatCard label="等待或运行中" value={openRuns} />
      </SimpleGrid>

      {rulesQuery.error ? (
        <Alert color="error" title="读取审计规则失败">
          {rulesQuery.error instanceof Error ? rulesQuery.error.message : "未知错误"}
        </Alert>
      ) : null}

      <Tabs value={tab} onChange={(value) => setTab((value as AuditTab) || "datasets")}>
        <Tabs.List>
          <Tabs.Tab value="datasets" leftSection={<IconCalendarStats size={16} />}>审计数据集</Tabs.Tab>
          <Tabs.Tab value="runs" leftSection={<IconListCheck size={16} />}>审计记录</Tabs.Tab>
          <Tabs.Tab value="schedules" leftSection={<IconPlayerPlay size={16} />}>自动审计</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="datasets" pt="lg">
          <SectionCard title="审计数据集" description="规则来自 DatasetDefinition.date_model；前端不复制日期规则。">
            <Stack gap="md">
              <FilterBar>
                <FilterBarItem span={{ base: 12, md: 4 }}>
                  <Select
                    label="审计能力"
                    value={group}
                    data={[
                      { value: "supported", label: "支持审计" },
                      { value: "unsupported", label: "不支持审计" },
                    ]}
                    allowDeselect={false}
                    onChange={(value) => setGroup((value as "supported" | "unsupported") || "supported")}
                  />
                </FilterBarItem>
                <FilterBarItem span={{ base: 12, md: 4 }}>
                  <Select
                    label="目录分组"
                    placeholder="全选"
                    value={domain}
                    data={groupOptions}
                    clearable
                    leftSection={<IconSearch size={14} />}
                    onChange={setDomain}
                  />
                </FilterBarItem>
              </FilterBar>

              <TableShell
                loading={rulesQuery.isLoading}
                hasData={visibleRules.length > 0}
                emptyState={<EmptyState title="暂无数据集" description="请调整筛选条件后重试。" />}
                minWidth={1120}
              >
                <OpsTable>
                  <Table.Thead>
                    <Table.Tr>
                      <OpsTableHeaderCell>数据集</OpsTableHeaderCell>
                      <OpsTableHeaderCell>目录分组</OpsTableHeaderCell>
                    <OpsTableHeaderCell>日期规则 / 审计粒度</OpsTableHeaderCell>
                      <OpsTableHeaderCell>数据时间范围</OpsTableHeaderCell>
                      <OpsTableHeaderCell>目标表</OpsTableHeaderCell>
                      <OpsTableHeaderCell>操作</OpsTableHeaderCell>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {visibleRules.map((item) => (
                      <Table.Tr key={item.dataset_key}>
                        <OpsTableCell>
                          <Stack gap={2}>
                            <Text fw={600}>{item.display_name}</Text>
                          </Stack>
                        </OpsTableCell>
                        <OpsTableCell>{item.group_label}</OpsTableCell>
                        <OpsTableCell>
                          <Badge variant="light" color={item.audit_applicable ? "brand" : "gray"}>
                            {item.rule_label}
                          </Badge>
                          <Badge variant="outline" color="gray" ml={6}>
                            {auditScopeLabel(item.audit_scope)}
                          </Badge>
                          {!item.audit_applicable ? (
                            <Text size="xs" c="dimmed" mt={4}>{item.not_applicable_reason || "未配置可审计规则"}</Text>
                          ) : null}
                        </OpsTableCell>
                        <OpsTableCell>
                          <Text size="sm">{item.data_range.label}</Text>
                        </OpsTableCell>
                        <OpsTableCell>
                          <Text size="sm" c="dimmed">{item.target_table}</Text>
                        </OpsTableCell>
                        <OpsTableCell>
                          {item.audit_applicable ? (
                            <Button
                              size="xs"
                              variant="light"
                              onClick={() => {
                                setRange(DEFAULT_RANGE);
                                setSelectedRule(item);
                              }}
                            >
                              创建审计
                            </Button>
                          ) : (
                            <Text size="sm" c="dimmed">不可创建</Text>
                          )}
                        </OpsTableCell>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </OpsTable>
              </TableShell>
            </Stack>
          </SectionCard>
        </Tabs.Panel>

        <Tabs.Panel value="runs" pt="lg">
          <SectionCard title="审计记录" description="只读取独立日期桶完整性审计表，不混用任务中心记录。">
            <TableShell
              loading={runsQuery.isLoading}
              hasData={(runsQuery.data?.items || []).length > 0}
              emptyState={<EmptyState title="暂无审计记录" description="在审计数据集页创建一次手动审计后，这里会显示记录。" />}
              minWidth={980}
            >
              <OpsTable>
                <Table.Thead>
                  <Table.Tr>
                    <OpsTableHeaderCell>审计对象</OpsTableHeaderCell>
                    <OpsTableHeaderCell>范围</OpsTableHeaderCell>
                    <OpsTableHeaderCell>运行状态</OpsTableHeaderCell>
                    <OpsTableHeaderCell>结论</OpsTableHeaderCell>
                    <OpsTableHeaderCell>应检查 / 实际 / 缺失 / 规则排除</OpsTableHeaderCell>
                    <OpsTableHeaderCell>发起方式</OpsTableHeaderCell>
                    <OpsTableHeaderCell>操作</OpsTableHeaderCell>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {(runsQuery.data?.items || []).map((item) => {
                    const isMatrix = item.audit_scope === "date_subject_matrix";
                    const unexpectedCount = isMatrix ? 0 : unexpectedBucketCount(item);
                    return (
                      <Table.Tr key={item.id}>
                        <OpsTableCell>
                          <Stack gap={2}>
                            <Text fw={600}>{item.display_name}</Text>
                          </Stack>
                        </OpsTableCell>
                        <OpsTableCell>{formatDateLabel(item.start_date)} 至 {formatDateLabel(item.end_date)}</OpsTableCell>
                        <OpsTableCell><StatusBadge value={item.run_status} /></OpsTableCell>
                        <OpsTableCell><StatusBadge value={resultBadgeValue(item.result_status)} label={resultLabel(item.result_status)} /></OpsTableCell>
                        <OpsTableCell>
                          <Stack gap={2}>
                            <Text size="sm">
                              {isMatrix
                                ? `${item.expected_cell_count} / ${item.actual_cell_count} / ${item.missing_cell_count} / ${item.excluded_bucket_count}`
                                : `${item.expected_bucket_count} / ${item.actual_bucket_count} / ${item.missing_bucket_count} / ${item.excluded_bucket_count}`}
                            </Text>
                            <Text size="xs" c="dimmed">
                              {isMatrix
                                ? `矩阵：缺失日期 ${item.affected_bucket_count}，缺失对象 ${item.affected_subject_count}`
                                : auditScopeLabel(item.audit_scope)}
                            </Text>
                            {unexpectedCount > 0 ? (
                              <Text size="xs" c="warning">
                                存在 {unexpectedCount} 个非预期日期桶
                              </Text>
                            ) : null}
                            {item.run_status === "queued" || item.run_status === "running" ? (
                              <Text size="xs" c={heartbeatIsStale(item) ? "warning" : "dimmed"}>
                                {progressLabel(item)}；最后心跳：{heartbeatLabel(item.heartbeat_at)}
                              </Text>
                            ) : null}
                          </Stack>
                        </OpsTableCell>
                        <OpsTableCell>{runModeLabel(item.run_mode)}</OpsTableCell>
                        <OpsTableCell>
                          <Button size="xs" variant="light" onClick={() => setSelectedRun(item)}>查看详情</Button>
                        </OpsTableCell>
                      </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </OpsTable>
            </TableShell>
          </SectionCard>
        </Tabs.Panel>

        <Tabs.Panel value="schedules" pt="lg">
          <OpsV21DatasetAuditSchedulesPanel supportedRules={supportedRules} />
        </Tabs.Panel>
      </Tabs>

      <Drawer
        opened={Boolean(selectedRule)}
        onClose={() => setSelectedRule(null)}
        title={selectedRule ? `创建审计 · ${selectedRule.display_name}` : "创建审计"}
        position="right"
        size="md"
      >
        {selectedRule ? (
          <Stack gap="md">
            <Alert color="blue" title="审计说明">
              本审计只读取已提交的业务数据，不影响同步任务，也不刷新数据新鲜度。
            </Alert>
            <Text size="sm">日期规则：{selectedRule.rule_label}</Text>
            <DateField
              label="开始日期"
              value={range.start_date}
              onChange={(value) => setRange((current) => ({ ...current, start_date: value }))}
            />
            <DateField
              label="结束日期"
              value={range.end_date}
              onChange={(value) => setRange((current) => ({ ...current, end_date: value }))}
            />
            <Group justify="flex-end">
              <Button variant="subtle" onClick={() => setSelectedRule(null)}>取消</Button>
              <Button loading={createRunMutation.isPending} onClick={submitRun}>创建审计</Button>
            </Group>
          </Stack>
        ) : null}
      </Drawer>

      <Drawer
        opened={Boolean(selectedRun)}
        onClose={() => setSelectedRun(null)}
        title={selectedRun ? `审计详情 · ${selectedRun.display_name}` : "审计详情"}
        position="right"
        size="lg"
      >
        {selectedRun ? (
          <Stack gap="md">
            <SimpleGrid cols={{ base: 1, sm: 4 }}>
              <StatCard label="结论" value={resultLabel(selectedRun.result_status)} />
              {isSubjectMatrixRun(selectedRun) ? (
                <>
                  <StatCard label="缺失单元" value={selectedRun.missing_cell_count} />
                  <StatCard label="缺失日期" value={selectedRun.affected_bucket_count} />
                  <StatCard label="缺失对象" value={selectedRun.affected_subject_count} />
                </>
              ) : (
                <>
                  <StatCard label="缺失日期桶" value={selectedRun.missing_bucket_count} />
                  <StatCard label="缺口区间" value={selectedRun.gap_range_count} />
                  <StatCard label="规则排除" value={selectedRun.excluded_bucket_count} />
                </>
              )}
            </SimpleGrid>
            {!isSubjectMatrixRun(selectedRun) && unexpectedBucketCount(selectedRun) > 0 ? (
              <Alert color="warning" title="发现非预期日期桶">
                目标表中的实际日期桶数量大于应检查日期桶数量。当前结论只表示应检查日期桶未缺失，不代表不存在额外日期或证券级缺行。
              </Alert>
            ) : null}
            {isSubjectMatrixRun(selectedRun) && selectedRun.detail_truncated ? (
              <Alert color="warning" title="对象缺失明细已截断">
                本次审计缺失对象明细超过安全上限，页面只展示前一部分样例；汇总数字仍以完整 SQL 结果为准。
              </Alert>
            ) : null}
            <SectionCard title="审计进度">
              <Stack gap={4}>
                <Text size="sm">{progressLabel(selectedRun)}</Text>
                <Text size="sm">阶段：{selectedRun.current_stage || "—"}</Text>
                <Text size="sm">最后心跳：{heartbeatLabel(selectedRun.heartbeat_at)}</Text>
                {heartbeatIsStale(selectedRun) ? (
                  <Text size="sm" c="warning">
                    运行中但心跳超过 5 分钟没有更新，请检查审计 worker 或数据库查询。
                  </Text>
                ) : null}
                {selectedRun.progress_message ? <Text size="sm">说明：{selectedRun.progress_message}</Text> : null}
              </Stack>
            </SectionCard>
            <SectionCard title="规则快照">
              <Stack gap={4}>
                <Text size="sm">范围：{formatDateLabel(selectedRun.start_date)} 至 {formatDateLabel(selectedRun.end_date)}</Text>
                <Text size="sm">规则：{selectedRun.date_axis} / {selectedRun.bucket_rule}</Text>
                <Text size="sm">审计粒度：{auditScopeLabel(selectedRun.audit_scope)}</Text>
                {selectedRun.subject_kind ? <Text size="sm">对象类型：{selectedRun.subject_kind}</Text> : null}
                {selectedRun.bucket_applicability_rule !== "always" ? (
                  <Text size="sm">可产出规则：{selectedRun.bucket_window_rule} / {selectedRun.bucket_applicability_rule}</Text>
                ) : null}
                <Text size="sm">观测字段：{selectedRun.observed_field}</Text>
                <Text size="sm">创建时间：{formatDateTimeLabel(selectedRun.requested_at)}</Text>
                {selectedRun.operator_message ? <Text size="sm">说明：{selectedRun.operator_message}</Text> : null}
              </Stack>
            </SectionCard>
            {selectedRun.technical_message ? (
              <Alert color="error" title="技术诊断">
                {selectedRun.technical_message}
              </Alert>
            ) : null}
            {!isSubjectMatrixRun(selectedRun) ? (
              <SectionCard title="缺失日期桶区间">
              <TableShell
                loading={gapsQuery.isLoading}
                hasData={(gapsQuery.data?.items || []).length > 0}
                emptyState={<EmptyState title="未发现日期桶缺口" description="当前审计范围内没有缺失日期桶。" />}
                minWidth={640}
              >
                <OpsTable>
                  <Table.Thead>
                    <Table.Tr>
                      <OpsTableHeaderCell>起点</OpsTableHeaderCell>
                      <OpsTableHeaderCell>终点</OpsTableHeaderCell>
                      <OpsTableHeaderCell>缺失数量</OpsTableHeaderCell>
                      <OpsTableHeaderCell>样例</OpsTableHeaderCell>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {(gapsQuery.data?.items || []).map((gap) => (
                      <Table.Tr key={gap.id}>
                        <OpsTableCell>{formatDateLabel(gap.range_start)}</OpsTableCell>
                        <OpsTableCell>{formatDateLabel(gap.range_end)}</OpsTableCell>
                        <OpsTableCell>{gap.missing_count}</OpsTableCell>
                        <OpsTableCell>{gap.sample_values.join("、") || "—"}</OpsTableCell>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </OpsTable>
              </TableShell>
            </SectionCard>
            ) : (
              <>
                <SectionCard title="对象缺失摘要">
                  <TableShell
                    loading={subjectGapsQuery.isLoading}
                    hasData={(subjectGapsQuery.data?.items || []).length > 0}
                    emptyState={<EmptyState title="未发现对象缺失" description="当前审计范围内没有日期 × 对象矩阵缺口。" />}
                    minWidth={720}
                  >
                    <OpsTable>
                      <Table.Thead>
                        <Table.Tr>
                          <OpsTableHeaderCell>日期桶</OpsTableHeaderCell>
                          <OpsTableHeaderCell>缺失单元</OpsTableHeaderCell>
                          <OpsTableHeaderCell>影响对象</OpsTableHeaderCell>
                          <OpsTableHeaderCell>样例对象</OpsTableHeaderCell>
                        </Table.Tr>
                      </Table.Thead>
                      <Table.Tbody>
                        {(subjectGapsQuery.data?.items || []).map((gap) => (
                          <Table.Tr key={gap.id}>
                            <OpsTableCell>{formatDateLabel(gap.bucket_value)}</OpsTableCell>
                            <OpsTableCell>{gap.missing_cell_count}</OpsTableCell>
                            <OpsTableCell>{gap.affected_subject_count}</OpsTableCell>
                            <OpsTableCell>{gap.sample_subjects.map(subjectSampleLabel).join("、") || "—"}</OpsTableCell>
                          </Table.Tr>
                        ))}
                      </Table.Tbody>
                    </OpsTable>
                  </TableShell>
                </SectionCard>
                <SectionCard title="对象缺失样例明细">
                  <TableShell
                    loading={subjectGapDetailsQuery.isLoading}
                    hasData={(subjectGapDetailsQuery.data?.items || []).length > 0}
                    emptyState={<EmptyState title="暂无对象缺失明细" description="当前审计记录没有可展示的对象缺失样例。" />}
                    minWidth={920}
                  >
                    <OpsTable>
                      <Table.Thead>
                        <Table.Tr>
                          <OpsTableHeaderCell>日期桶</OpsTableHeaderCell>
                          <OpsTableHeaderCell>对象</OpsTableHeaderCell>
                          <OpsTableHeaderCell>实际业务键</OpsTableHeaderCell>
                          <OpsTableHeaderCell>生命周期</OpsTableHeaderCell>
                          <OpsTableHeaderCell>原因</OpsTableHeaderCell>
                        </Table.Tr>
                      </Table.Thead>
                      <Table.Tbody>
                        {(subjectGapDetailsQuery.data?.items || []).map((detail) => (
                          <Table.Tr key={detail.id}>
                            <OpsTableCell>{formatDateLabel(detail.bucket_value)}</OpsTableCell>
                            <OpsTableCell>{detail.subject_name ? `${detail.subject_key} ${detail.subject_name}` : detail.subject_key}</OpsTableCell>
                            <OpsTableCell>{subjectKeyLabel(detail.actual_key_json)}</OpsTableCell>
                            <OpsTableCell>{lifecycleLabel(detail.lifecycle_start, detail.lifecycle_end)}</OpsTableCell>
                            <OpsTableCell>{detail.reason_message}</OpsTableCell>
                          </Table.Tr>
                        ))}
                      </Table.Tbody>
                    </OpsTable>
                  </TableShell>
                </SectionCard>
              </>
            )}
            {selectedRun.excluded_bucket_count > 0 ? (
              <SectionCard title="规则排除">
                <TableShell
                  loading={exclusionsQuery.isLoading}
                  hasData={(exclusionsQuery.data?.items || []).length > 0}
                  emptyState={<EmptyState title="暂无排除明细" description="当前审计记录没有可展示的规则排除桶。" />}
                  minWidth={720}
                >
                  <OpsTable>
                    <Table.Thead>
                      <Table.Tr>
                        <OpsTableHeaderCell>候选日期</OpsTableHeaderCell>
                        <OpsTableHeaderCell>窗口</OpsTableHeaderCell>
                        <OpsTableHeaderCell>排除原因</OpsTableHeaderCell>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {(exclusionsQuery.data?.items || []).map((item) => (
                        <Table.Tr key={item.id}>
                          <OpsTableCell>{formatDateLabel(item.bucket_value)}</OpsTableCell>
                          <OpsTableCell>{formatDateLabel(item.window_start)} 至 {formatDateLabel(item.window_end)}</OpsTableCell>
                          <OpsTableCell>{item.reason_message}</OpsTableCell>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </OpsTable>
                </TableShell>
              </SectionCard>
            ) : null}
          </Stack>
        ) : null}
      </Drawer>
    </Stack>
  );
}
