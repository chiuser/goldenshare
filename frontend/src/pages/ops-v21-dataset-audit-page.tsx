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
    enabled: Boolean(selectedRun),
  });

  const exclusionsQuery = useQuery({
    queryKey: ["ops", "date-completeness", "run-exclusions", selectedRun?.id],
    queryFn: () => apiRequest<DateCompletenessExclusionListResponse>(`/api/v1/ops/review/date-completeness/runs/${selectedRun?.id}/exclusions`),
    enabled: Boolean(selectedRun && selectedRun.excluded_bucket_count > 0),
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
        description="检查数据集在指定日期范围内是否存在缺失日期桶；审计结果独立于任务中心和数据新鲜度。"
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
                minWidth={980}
              >
                <OpsTable>
                  <Table.Thead>
                    <Table.Tr>
                      <OpsTableHeaderCell>数据集</OpsTableHeaderCell>
                      <OpsTableHeaderCell>目录分组</OpsTableHeaderCell>
                      <OpsTableHeaderCell>日期规则</OpsTableHeaderCell>
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
                          {!item.audit_applicable ? (
                            <Text size="xs" c="dimmed" mt={4}>{item.not_applicable_reason || "未配置可审计规则"}</Text>
                          ) : null}
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
          <SectionCard title="审计记录" description="只读取独立日期完整性审计表，不混用任务中心记录。">
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
                  {(runsQuery.data?.items || []).map((item) => (
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
                        {item.expected_bucket_count} / {item.actual_bucket_count} / {item.missing_bucket_count} / {item.excluded_bucket_count}
                      </OpsTableCell>
                      <OpsTableCell>{runModeLabel(item.run_mode)}</OpsTableCell>
                      <OpsTableCell>
                        <Button size="xs" variant="light" onClick={() => setSelectedRun(item)}>查看详情</Button>
                      </OpsTableCell>
                    </Table.Tr>
                  ))}
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
              <StatCard label="缺失桶" value={selectedRun.missing_bucket_count} />
              <StatCard label="缺口区间" value={selectedRun.gap_range_count} />
              <StatCard label="规则排除" value={selectedRun.excluded_bucket_count} />
            </SimpleGrid>
            <SectionCard title="规则快照">
              <Stack gap={4}>
                <Text size="sm">范围：{formatDateLabel(selectedRun.start_date)} 至 {formatDateLabel(selectedRun.end_date)}</Text>
                <Text size="sm">规则：{selectedRun.date_axis} / {selectedRun.bucket_rule}</Text>
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
            <SectionCard title="缺口区间">
              <TableShell
                loading={gapsQuery.isLoading}
                hasData={(gapsQuery.data?.items || []).length > 0}
                emptyState={<EmptyState title="未发现缺口" description="当前审计范围内没有缺失日期桶。" />}
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
