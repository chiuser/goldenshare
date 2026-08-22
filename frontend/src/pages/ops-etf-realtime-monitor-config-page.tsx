import {
  Alert,
  Badge,
  Button,
  Drawer,
  Group,
  NumberInput,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Tabs,
  Text,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { apiRequest } from "../shared/api/client";
import type {
  EtfRealtimeMonitorActiveEtfListResponse,
  EtfRealtimeMonitorAlertListResponse,
  EtfRealtimeMonitorPoolItem,
  EtfRealtimeMonitorPoolListResponse,
  EtfRealtimeMonitorRuleItem,
  EtfRealtimeMonitorRuleListResponse,
  EtfRealtimeMonitorSummaryResponse,
} from "../shared/api/etf-realtime-monitor-types";
import { formatDateLabel, formatDateTimeLabel } from "../shared/date-format";
import { EmptyState } from "../shared/ui/empty-state";
import { FilterBar, FilterBarItem } from "../shared/ui/filter-bar";
import { OpsTable, OpsTableCell, OpsTableHeaderCell } from "../shared/ui/ops-table";
import { PageHeader } from "../shared/ui/page-header";
import { SectionCard } from "../shared/ui/section-card";
import { StatCard } from "../shared/ui/stat-card";
import { TableShell } from "../shared/ui/table-shell";

const API_PREFIX = "/api/v1/ops/realtime/etf-monitor";
const GROUP_OPTIONS = [
  { value: "broad_base", label: "宽基ETF" },
  { value: "theme", label: "主题ETF" },
];
const SCOPE_OPTIONS = [
  { value: "global", label: "全局" },
  { value: "group", label: "分组" },
  { value: "etf", label: "ETF" },
];
const WINDOW_OPTIONS = [
  { value: "1", label: "1m" },
  { value: "5", label: "5m" },
  { value: "15", label: "15m" },
];

type PoolDraft = {
  id?: number;
  ts_code: string;
  group_key: string;
  group_name: string;
  enabled: boolean;
};

type RuleDraft = {
  id?: number;
  scope_type: string;
  scope_key: string;
  window_minutes: number;
  observe_ratio: number;
  alert_ratio: number;
  strong_ratio: number;
  cooldown_minutes: number;
  feishu_enabled: boolean;
  enabled: boolean;
};

export function OpsEtfRealtimeMonitorConfigPage() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<string | null>("pool");
  const [poolKeyword, setPoolKeyword] = useState("");
  const [activeEtfKeyword, setActiveEtfKeyword] = useState("");
  const [poolPage, setPoolPage] = useState(1);
  const [activeEtfPage, setActiveEtfPage] = useState(1);
  const [poolDrawerOpen, setPoolDrawerOpen] = useState(false);
  const [ruleDrawerOpen, setRuleDrawerOpen] = useState(false);
  const [poolDraft, setPoolDraft] = useState<PoolDraft>(() => emptyPoolDraft());
  const [ruleDraft, setRuleDraft] = useState<RuleDraft>(() => emptyRuleDraft());
  const today = new Date().toISOString().slice(0, 10);

  const poolQuery = useQuery({
    queryKey: ["ops", "etf-realtime-monitor", "pool", poolKeyword, poolPage],
    placeholderData: keepPreviousData,
    queryFn: () => {
      const params = new URLSearchParams({ page: String(poolPage), page_size: "50" });
      if (poolKeyword.trim()) params.set("keyword", poolKeyword.trim());
      return apiRequest<EtfRealtimeMonitorPoolListResponse>(`${API_PREFIX}/pool?${params.toString()}`);
    },
  });
  const activeEtfQuery = useQuery({
    queryKey: ["ops", "etf-realtime-monitor", "active-etfs", activeEtfKeyword, activeEtfPage],
    enabled: poolDrawerOpen && !poolDraft.id,
    placeholderData: keepPreviousData,
    queryFn: () => {
      const params = new URLSearchParams({ page: String(activeEtfPage), page_size: "50" });
      if (activeEtfKeyword.trim()) params.set("keyword", activeEtfKeyword.trim());
      return apiRequest<EtfRealtimeMonitorActiveEtfListResponse>(`${API_PREFIX}/active-etfs?${params.toString()}`);
    },
  });
  const rulesQuery = useQuery({
    queryKey: ["ops", "etf-realtime-monitor", "rules"],
    queryFn: () => apiRequest<EtfRealtimeMonitorRuleListResponse>(`${API_PREFIX}/rules`),
  });
  const alertsQuery = useQuery({
    queryKey: ["ops", "etf-realtime-monitor", "alerts", today],
    queryFn: () => apiRequest<EtfRealtimeMonitorAlertListResponse>(`${API_PREFIX}/alerts?trade_date=${today}&page=1&page_size=50`),
  });
  const summaryQuery = useQuery({
    queryKey: ["ops", "etf-realtime-monitor", "summary", today],
    queryFn: () => apiRequest<EtfRealtimeMonitorSummaryResponse>(`${API_PREFIX}/summary?trade_date=${today}`),
  });

  const poolPageCount = Math.max(1, Math.ceil((poolQuery.data?.total || 0) / 50));

  const savePoolMutation = useMutation({
    mutationFn: (draft: PoolDraft) => {
      const body = {
        ts_code: draft.ts_code,
        group_key: draft.group_key,
        group_name: draft.group_name,
        enabled: draft.enabled,
      };
      if (draft.id) {
        return apiRequest(`${API_PREFIX}/pool/${draft.id}`, {
          method: "PUT",
          body: { ...body, ts_code: undefined },
        });
      }
      return apiRequest(`${API_PREFIX}/pool`, { method: "POST", body });
    },
    onSuccess: async (_response, draft) => {
      if (draft.id) {
        setPoolDrawerOpen(false);
        notifications.show({ color: "green", title: "已保存", message: "ETF监控池已更新。" });
      } else {
        notifications.show({ color: "green", title: "已添加", message: `${draft.ts_code} 已加入监控池。` });
      }
      await queryClient.invalidateQueries({ queryKey: ["ops", "etf-realtime-monitor"] });
    },
    onError: (error, draft) => {
      notifications.show({
        color: "red",
        title: draft.id ? "保存失败" : "添加失败",
        message: error instanceof Error ? error.message : `${draft.ts_code} 操作失败。`,
      });
    },
  });
  const deletePoolMutation = useMutation({
    mutationFn: (id: number) => apiRequest(`${API_PREFIX}/pool/${id}`, { method: "DELETE" }),
    onSuccess: async () => {
      notifications.show({ color: "green", title: "已删除", message: "监控关系已删除。" });
      await queryClient.invalidateQueries({ queryKey: ["ops", "etf-realtime-monitor"] });
    },
  });
  const saveRuleMutation = useMutation({
    mutationFn: () => {
      const body = { ...ruleDraft };
      if (ruleDraft.id) {
        return apiRequest(`${API_PREFIX}/rules/${ruleDraft.id}`, { method: "PUT", body });
      }
      return apiRequest(`${API_PREFIX}/rules`, { method: "POST", body });
    },
    onSuccess: async () => {
      setRuleDrawerOpen(false);
      notifications.show({ color: "green", title: "已保存", message: "阈值规则已更新。" });
      await queryClient.invalidateQueries({ queryKey: ["ops", "etf-realtime-monitor"] });
    },
  });
  const defaultRulesMutation = useMutation({
    mutationFn: () => apiRequest(`${API_PREFIX}/rules/default-global`, { method: "POST" }),
    onSuccess: async () => {
      notifications.show({ color: "green", title: "默认规则已创建", message: "全局 1m/5m/15m 规则已确认。" });
      await queryClient.invalidateQueries({ queryKey: ["ops", "etf-realtime-monitor", "rules"] });
    },
  });

  useEffect(() => {
    setPoolPage(1);
  }, [poolKeyword]);

  useEffect(() => {
    setActiveEtfPage(1);
  }, [activeEtfKeyword]);

  const openAddPoolDrawer = () => {
    setPoolDraft(emptyPoolDraft());
    setActiveEtfKeyword("");
    setActiveEtfPage(1);
    setPoolDrawerOpen(true);
  };

  return (
    <Stack gap="lg">
      <PageHeader title="ETF实时监控配置中心" />
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }} spacing="md">
        <StatCard label="监控ETF" value={summaryQuery.data?.monitor_total ?? "—"} />
        <StatCard label="启用ETF" value={summaryQuery.data?.monitor_enabled ?? "—"} />
        <StatCard label="今日提醒" value={(summaryQuery.data?.alert_count ?? 0) + (summaryQuery.data?.strong_count ?? 0)} />
        <StatCard label="飞书失败" value={summaryQuery.data?.feishu_failed_count ?? "—"} />
      </SimpleGrid>

      <SectionCard title="ETF实时监控">
        <Stack gap="md">
          <FilterBar actions={<Button onClick={openAddPoolDrawer}>添加ETF</Button>}>
            <FilterBarItem span={{ base: 12, md: 6 }}>
              <TextInput label="监控池关键词" placeholder="ETF 代码或名称" value={poolKeyword} onChange={(event) => setPoolKeyword(event.currentTarget.value)} />
            </FilterBarItem>
          </FilterBar>
          <Tabs value={tab} onChange={setTab}>
            <Tabs.List>
              <Tabs.Tab value="pool">监控池</Tabs.Tab>
              <Tabs.Tab value="rules">阈值规则</Tabs.Tab>
              <Tabs.Tab value="alerts">告警记录</Tabs.Tab>
            </Tabs.List>
            <Tabs.Panel value="pool" pt="md">
              <PoolTable
                data={poolQuery.data}
                loading={poolQuery.isLoading}
                error={poolQuery.error}
                page={poolPage}
                pageCount={poolPageCount}
                onPageChange={setPoolPage}
                onEdit={(item) => { setPoolDraft(poolDraftFromItem(item)); setPoolDrawerOpen(true); }}
                onDelete={(id) => deletePoolMutation.mutate(id)}
              />
            </Tabs.Panel>
            <Tabs.Panel value="rules" pt="md">
              <RuleTable
                data={rulesQuery.data}
                loading={rulesQuery.isLoading}
                error={rulesQuery.error}
                onCreateDefault={() => defaultRulesMutation.mutate()}
                onCreate={() => { setRuleDraft(emptyRuleDraft()); setRuleDrawerOpen(true); }}
                onEdit={(item) => { setRuleDraft(ruleDraftFromItem(item)); setRuleDrawerOpen(true); }}
              />
            </Tabs.Panel>
            <Tabs.Panel value="alerts" pt="md">
              <AlertTable data={alertsQuery.data} loading={alertsQuery.isLoading} error={alertsQuery.error} />
            </Tabs.Panel>
          </Tabs>
        </Stack>
      </SectionCard>

      <PoolDrawer
        opened={poolDrawerOpen}
        draft={poolDraft}
        activeEtfs={activeEtfQuery.data}
        activeEtfsLoading={activeEtfQuery.isLoading}
        activeEtfPage={activeEtfPage}
        activeEtfKeyword={activeEtfKeyword}
        onActiveEtfPageChange={setActiveEtfPage}
        onActiveEtfKeywordChange={setActiveEtfKeyword}
        onClose={() => setPoolDrawerOpen(false)}
        onDraftChange={setPoolDraft}
        onAdd={(draft) => savePoolMutation.mutate(draft)}
        onSubmit={() => savePoolMutation.mutate(poolDraft)}
        addingTsCode={savePoolMutation.isPending && savePoolMutation.variables && !savePoolMutation.variables.id ? savePoolMutation.variables.ts_code : null}
        saving={savePoolMutation.isPending}
      />
      <RuleDrawer
        opened={ruleDrawerOpen}
        draft={ruleDraft}
        onClose={() => setRuleDrawerOpen(false)}
        onDraftChange={setRuleDraft}
        onSubmit={() => saveRuleMutation.mutate()}
        saving={saveRuleMutation.isPending}
      />
    </Stack>
  );
}

function PoolTable({
  data,
  loading,
  error,
  page,
  pageCount,
  onPageChange,
  onEdit,
  onDelete,
}: {
  data?: EtfRealtimeMonitorPoolListResponse;
  loading: boolean;
  error: unknown;
  page: number;
  pageCount: number;
  onPageChange: (page: number) => void;
  onEdit: (item: EtfRealtimeMonitorPoolItem) => void;
  onDelete: (id: number) => void;
}) {
  if (error) return <Alert color="error" title="读取监控池失败">{error instanceof Error ? error.message : "未知错误"}</Alert>;
  return (
    <TableShell
      loading={loading}
      hasData={(data?.items ?? []).length > 0}
      emptyState={<EmptyState title="监控池为空" description="点击添加ETF，从实时 ETF 活跃池中选择代表性 ETF。" />}
      summary={<Pager page={page} pageCount={pageCount} total={data?.total ?? 0} onPageChange={onPageChange} />}
      minWidth={1180}
    >
      <OpsTable>
        <Table.Thead>
          <Table.Tr>
            <OpsTableHeaderCell align="left">ETF</OpsTableHeaderCell>
            <OpsTableHeaderCell align="left">分组</OpsTableHeaderCell>
            <OpsTableHeaderCell align="left">总份额</OpsTableHeaderCell>
            <OpsTableHeaderCell align="left">总规模</OpsTableHeaderCell>
            <OpsTableHeaderCell align="left">状态</OpsTableHeaderCell>
            <OpsTableHeaderCell align="left">阈值覆盖</OpsTableHeaderCell>
            <OpsTableHeaderCell align="left">最近告警</OpsTableHeaderCell>
            <OpsTableHeaderCell align="left">操作</OpsTableHeaderCell>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {(data?.items ?? []).map((item) => (
            <Table.Tr key={item.id}>
              <OpsTableCell align="left"><Stack gap={2}><Text fw={600}>{item.etf_name || "—"}</Text><Text size="xs" c="dimmed">{item.ts_code}</Text></Stack></OpsTableCell>
              <OpsTableCell align="left"><Badge variant="light">{item.group_name}</Badge></OpsTableCell>
              <OpsTableCell align="left">{formatEtfShare(item.total_share_wan)}</OpsTableCell>
              <OpsTableCell align="left">{formatEtfSize(item.total_size_wan)}</OpsTableCell>
              <OpsTableCell align="left"><Badge color={item.enabled ? "green" : "gray"}>{item.enabled ? "启用" : "停用"}</Badge></OpsTableCell>
              <OpsTableCell align="left">{item.has_etf_rule_override ? <Badge color="blue" variant="light">ETF专属</Badge> : <Badge color="gray" variant="light">继承规则</Badge>}</OpsTableCell>
              <OpsTableCell align="left">{item.latest_alert_at ? `${formatDateTimeLabel(item.latest_alert_at)} · ${item.latest_alert_severity}` : "—"}</OpsTableCell>
              <OpsTableCell align="left"><Group gap="xs"><Button size="xs" variant="light" onClick={() => onEdit(item)}>编辑</Button><Button size="xs" color="red" variant="light" onClick={() => onDelete(item.id)}>删除</Button></Group></OpsTableCell>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </OpsTable>
    </TableShell>
  );
}

function RuleTable({
  data,
  loading,
  error,
  onCreateDefault,
  onCreate,
  onEdit,
}: {
  data?: EtfRealtimeMonitorRuleListResponse;
  loading: boolean;
  error: unknown;
  onCreateDefault: () => void;
  onCreate: () => void;
  onEdit: (item: EtfRealtimeMonitorRuleItem) => void;
}) {
  if (error) return <Alert color="error" title="读取阈值规则失败">{error instanceof Error ? error.message : "未知错误"}</Alert>;
  return (
    <TableShell
      loading={loading}
      hasData={(data?.items ?? []).length > 0}
      emptyState={<EmptyState title="暂无阈值规则" description="可以先创建默认全局规则，再按分组或 ETF 覆盖。" />}
      toolbar={<Group justify="flex-end"><Button variant="light" onClick={onCreateDefault}>创建默认全局规则</Button><Button onClick={onCreate}>新增规则</Button></Group>}
      minWidth={980}
    >
      <OpsTable>
        <Table.Thead>
          <Table.Tr>
            <OpsTableHeaderCell align="left">层级</OpsTableHeaderCell>
            <OpsTableHeaderCell align="left">对象</OpsTableHeaderCell>
            <OpsTableHeaderCell align="left">窗口</OpsTableHeaderCell>
            <OpsTableHeaderCell align="left">observe</OpsTableHeaderCell>
            <OpsTableHeaderCell align="left">alert</OpsTableHeaderCell>
            <OpsTableHeaderCell align="left">strong</OpsTableHeaderCell>
            <OpsTableHeaderCell align="left">冷却</OpsTableHeaderCell>
            <OpsTableHeaderCell align="left">飞书</OpsTableHeaderCell>
            <OpsTableHeaderCell align="left">操作</OpsTableHeaderCell>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {(data?.items ?? []).map((item) => (
            <Table.Tr key={item.id}>
              <OpsTableCell align="left">{scopeLabel(item.scope_type)}</OpsTableCell>
              <OpsTableCell align="left">{item.scope_display_name || item.scope_key}</OpsTableCell>
              <OpsTableCell align="left"><Badge variant="light">{item.window_minutes}m</Badge></OpsTableCell>
              <OpsTableCell align="left">{item.observe_ratio}</OpsTableCell>
              <OpsTableCell align="left">{item.alert_ratio}</OpsTableCell>
              <OpsTableCell align="left">{item.strong_ratio}</OpsTableCell>
              <OpsTableCell align="left">{item.cooldown_minutes} 分钟</OpsTableCell>
              <OpsTableCell align="left"><Badge color={item.feishu_enabled ? "green" : "gray"}>{item.feishu_enabled ? "启用" : "关闭"}</Badge></OpsTableCell>
              <OpsTableCell align="left"><Button size="xs" variant="light" onClick={() => onEdit(item)}>编辑</Button></OpsTableCell>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </OpsTable>
    </TableShell>
  );
}

function AlertTable({ data, loading, error }: { data?: EtfRealtimeMonitorAlertListResponse; loading: boolean; error: unknown }) {
  if (error) return <Alert color="error" title="读取告警记录失败">{error instanceof Error ? error.message : "未知错误"}</Alert>;
  return (
    <TableShell loading={loading} hasData={(data?.items ?? []).length > 0} emptyState={<EmptyState title="今日暂无告警" description="没有 observe/alert/strong 记录。" />} minWidth={1080}>
      <OpsTable>
        <Table.Thead>
          <Table.Tr>
            <OpsTableHeaderCell align="left">时间</OpsTableHeaderCell>
            <OpsTableHeaderCell align="left">ETF</OpsTableHeaderCell>
            <OpsTableHeaderCell align="left">窗口</OpsTableHeaderCell>
            <OpsTableHeaderCell align="left">当前成交额</OpsTableHeaderCell>
            <OpsTableHeaderCell align="left">历史基准</OpsTableHeaderCell>
            <OpsTableHeaderCell align="left">倍数</OpsTableHeaderCell>
            <OpsTableHeaderCell align="left">等级</OpsTableHeaderCell>
            <OpsTableHeaderCell align="left">通知</OpsTableHeaderCell>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {(data?.items ?? []).map((item) => (
            <Table.Tr key={item.id}>
              <OpsTableCell align="left">{formatDateTimeLabel(item.triggered_at)}</OpsTableCell>
              <OpsTableCell align="left">{item.ts_code}<Text size="xs" c="dimmed">{item.etf_name || "—"}</Text></OpsTableCell>
              <OpsTableCell align="left">{item.window_minutes}m</OpsTableCell>
              <OpsTableCell align="left">{formatYuan(item.current_amount_yuan)}</OpsTableCell>
              <OpsTableCell align="left">{formatYuan(item.baseline_amount_yuan)}</OpsTableCell>
              <OpsTableCell align="left">{item.ratio}</OpsTableCell>
              <OpsTableCell align="left"><Badge color={severityColor(item.severity)}>{item.severity}</Badge></OpsTableCell>
              <OpsTableCell align="left">{item.feishu_status}</OpsTableCell>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </OpsTable>
    </TableShell>
  );
}

function PoolDrawer({
  opened,
  draft,
  activeEtfs,
  activeEtfsLoading,
  activeEtfPage,
  activeEtfKeyword,
  onActiveEtfPageChange,
  onClose,
  onActiveEtfKeywordChange,
  onDraftChange,
  onAdd,
  onSubmit,
  addingTsCode,
  saving,
}: {
  opened: boolean;
  draft: PoolDraft;
  activeEtfs?: EtfRealtimeMonitorActiveEtfListResponse;
  activeEtfsLoading: boolean;
  activeEtfPage: number;
  activeEtfKeyword: string;
  onActiveEtfPageChange: (page: number) => void;
  onActiveEtfKeywordChange: (keyword: string) => void;
  onClose: () => void;
  onDraftChange: (draft: PoolDraft) => void;
  onAdd: (draft: PoolDraft) => void;
  onSubmit: () => void;
  addingTsCode: string | null;
  saving: boolean;
}) {
  const activePageCount = Math.max(1, Math.ceil((activeEtfs?.total || 0) / 50));
  const [rowDrafts, setRowDrafts] = useState<Record<string, PoolDraft>>({});

  useEffect(() => {
    if (opened && !draft.id) setRowDrafts({});
  }, [opened, draft.id]);

  useEffect(() => {
    if (draft.id || !activeEtfs) return;
    setRowDrafts((current) => {
      const next = { ...current };
      for (const item of activeEtfs.items) {
        if (!next[item.ts_code]) next[item.ts_code] = emptyPoolDraft(item.ts_code);
      }
      return next;
    });
  }, [activeEtfs, draft.id]);

  return (
    <Drawer opened={opened} onClose={onClose} title={draft.id ? "编辑监控ETF" : "添加监控ETF"} position="right" size={1120}>
      <Stack gap="md">
        {!draft.id ? (
          <SectionCard title="选择并添加 ETF">
            <Stack gap="md">
              <TextInput
                label="搜索待添加 ETF"
                placeholder="输入代码或名称"
                value={activeEtfKeyword}
                onChange={(event) => onActiveEtfKeywordChange(event.currentTarget.value)}
              />
              <TableShell loading={activeEtfsLoading} hasData={(activeEtfs?.items ?? []).length > 0} emptyState={<EmptyState title="没有匹配的 ETF" />} summary={<Pager page={activeEtfPage} pageCount={activePageCount} total={activeEtfs?.total ?? 0} onPageChange={onActiveEtfPageChange} />} minWidth={0}>
                <OpsTable>
                  <Table.Thead>
                    <Table.Tr>
                      <OpsTableHeaderCell align="left" width="23%">ETF</OpsTableHeaderCell>
                      <OpsTableHeaderCell align="left" width="14%">总份额</OpsTableHeaderCell>
                      <OpsTableHeaderCell align="left" width="14%">总规模</OpsTableHeaderCell>
                      <OpsTableHeaderCell align="left" width="8%">交易所</OpsTableHeaderCell>
                      <OpsTableHeaderCell align="left" width="20%">监控分组</OpsTableHeaderCell>
                      <OpsTableHeaderCell align="left" width="12%">启用监控</OpsTableHeaderCell>
                      <OpsTableHeaderCell align="left" width="9%">操作</OpsTableHeaderCell>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {(activeEtfs?.items ?? []).map((item) => (
                      <Table.Tr key={item.ts_code}>
                        <OpsTableCell align="left"><Stack gap={0}><Text fw={600}><HighlightMatch value={item.csname || item.extname || item.cname || "—"} keyword={activeEtfKeyword} /></Text><Text size="xs" c="dimmed"><HighlightMatch value={item.ts_code} keyword={activeEtfKeyword} /></Text></Stack></OpsTableCell>
                        <OpsTableCell align="left">{formatEtfShare(item.total_share_wan)}</OpsTableCell>
                        <OpsTableCell align="left">{formatEtfSize(item.total_size_wan)}</OpsTableCell>
                        <OpsTableCell align="left">{item.exchange || "—"}</OpsTableCell>
                        <OpsTableCell align="left">
                          <Select
                            aria-label={`${item.ts_code}监控分组`}
                            data={GROUP_OPTIONS}
                            value={(rowDrafts[item.ts_code] || emptyPoolDraft(item.ts_code)).group_key}
                            allowDeselect={false}
                            disabled={item.in_monitor_pool}
                            onChange={(value) => {
                              const rowDraft = rowDrafts[item.ts_code] || emptyPoolDraft(item.ts_code);
                              setRowDrafts((current) => ({
                                ...current,
                                [item.ts_code]: { ...rowDraft, group_key: value || "broad_base", group_name: groupName(value || "broad_base") },
                              }));
                            }}
                          />
                        </OpsTableCell>
                        <OpsTableCell align="left">
                          <Switch
                            aria-label={`${item.ts_code}启用监控`}
                            checked={(rowDrafts[item.ts_code] || emptyPoolDraft(item.ts_code)).enabled}
                            disabled={item.in_monitor_pool}
                            onChange={(event) => {
                              const rowDraft = rowDrafts[item.ts_code] || emptyPoolDraft(item.ts_code);
                              setRowDrafts((current) => ({ ...current, [item.ts_code]: { ...rowDraft, enabled: event.currentTarget.checked } }));
                            }}
                          />
                        </OpsTableCell>
                        <OpsTableCell align="left">
                          {item.in_monitor_pool ? (
                            <Button size="xs" color="green" variant="light" disabled>已添加</Button>
                          ) : (
                            <Button
                              size="xs"
                              loading={addingTsCode === item.ts_code}
                              disabled={Boolean(addingTsCode) && addingTsCode !== item.ts_code}
                              onClick={() => onAdd(rowDrafts[item.ts_code] || emptyPoolDraft(item.ts_code))}
                            >
                              添加
                            </Button>
                          )}
                        </OpsTableCell>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </OpsTable>
              </TableShell>
            </Stack>
          </SectionCard>
        ) : null}
        {draft.id ? (
          <>
            <TextInput label="ETF代码" value={draft.ts_code} disabled />
            <Select label="监控分组" data={GROUP_OPTIONS} value={draft.group_key} allowDeselect={false} onChange={(value) => onDraftChange({ ...draft, group_key: value || "broad_base", group_name: groupName(value || "broad_base") })} />
            <Switch label="启用监控" checked={draft.enabled} onChange={(event) => onDraftChange({ ...draft, enabled: event.currentTarget.checked })} />
            <Button onClick={onSubmit} loading={saving} disabled={!draft.ts_code}>保存</Button>
          </>
        ) : null}
      </Stack>
    </Drawer>
  );
}

function RuleDrawer({ opened, draft, onClose, onDraftChange, onSubmit, saving }: {
  opened: boolean;
  draft: RuleDraft;
  onClose: () => void;
  onDraftChange: (draft: RuleDraft) => void;
  onSubmit: () => void;
  saving: boolean;
}) {
  return (
    <Drawer opened={opened} onClose={onClose} title={draft.id ? "编辑阈值规则" : "新增阈值规则"} position="right" size="md">
      <Stack gap="md">
        <Select label="生效层级" data={SCOPE_OPTIONS} value={draft.scope_type} allowDeselect={false} onChange={(value) => onDraftChange({ ...draft, scope_type: value || "global", scope_key: value === "global" ? "__GLOBAL__" : draft.scope_key })} />
        <TextInput label="对象" value={draft.scope_key} onChange={(event) => onDraftChange({ ...draft, scope_key: event.currentTarget.value })} />
        <Select label="窗口" data={WINDOW_OPTIONS} value={String(draft.window_minutes)} allowDeselect={false} onChange={(value) => onDraftChange({ ...draft, window_minutes: Number(value || 1) })} />
        <NumberInput label="observe 倍数" decimalScale={4} value={draft.observe_ratio} onChange={(value) => onDraftChange({ ...draft, observe_ratio: Number(value || 0) })} />
        <NumberInput label="alert 倍数" decimalScale={4} value={draft.alert_ratio} onChange={(value) => onDraftChange({ ...draft, alert_ratio: Number(value || 0) })} />
        <NumberInput label="strong 倍数" decimalScale={4} value={draft.strong_ratio} onChange={(value) => onDraftChange({ ...draft, strong_ratio: Number(value || 0) })} />
        <NumberInput label="冷却分钟" value={draft.cooldown_minutes} onChange={(value) => onDraftChange({ ...draft, cooldown_minutes: Number(value || 15) })} />
        <Switch label="发送飞书" checked={draft.feishu_enabled} onChange={(event) => onDraftChange({ ...draft, feishu_enabled: event.currentTarget.checked })} />
        <Switch label="启用规则" checked={draft.enabled} onChange={(event) => onDraftChange({ ...draft, enabled: event.currentTarget.checked })} />
        <Button onClick={onSubmit} loading={saving}>保存</Button>
      </Stack>
    </Drawer>
  );
}

function Pager({ page, pageCount, total, onPageChange }: { page: number; pageCount: number; total: number; onPageChange: (page: number) => void }) {
  return (
    <Group justify="space-between">
      <Text size="sm" c="dimmed">共 {total} 条</Text>
      <Group gap="xs">
        <Button size="xs" variant="light" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>上一页</Button>
        <Text size="sm" c="dimmed">{page}/{pageCount}</Text>
        <Button size="xs" variant="light" disabled={page >= pageCount} onClick={() => onPageChange(page + 1)}>下一页</Button>
      </Group>
    </Group>
  );
}

function emptyPoolDraft(tsCode = ""): PoolDraft {
  return { ts_code: tsCode, group_key: "broad_base", group_name: "宽基ETF", enabled: true };
}

function emptyRuleDraft(): RuleDraft {
  return { scope_type: "global", scope_key: "__GLOBAL__", window_minutes: 1, observe_ratio: 2, alert_ratio: 3, strong_ratio: 5, cooldown_minutes: 15, feishu_enabled: true, enabled: true };
}

function poolDraftFromItem(item: EtfRealtimeMonitorPoolItem): PoolDraft {
  return { id: item.id, ts_code: item.ts_code, group_key: item.group_key, group_name: item.group_name, enabled: item.enabled };
}

function ruleDraftFromItem(item: EtfRealtimeMonitorRuleItem): RuleDraft {
  return { id: item.id, scope_type: item.scope_type, scope_key: item.scope_key, window_minutes: item.window_minutes, observe_ratio: Number(item.observe_ratio), alert_ratio: Number(item.alert_ratio), strong_ratio: Number(item.strong_ratio), cooldown_minutes: item.cooldown_minutes, feishu_enabled: item.feishu_enabled, enabled: item.enabled };
}

function groupName(groupKey: string): string {
  return GROUP_OPTIONS.find((item) => item.value === groupKey)?.label || "宽基ETF";
}

function scopeLabel(scopeType: string): string {
  if (scopeType === "global") return "全局";
  if (scopeType === "group") return "分组";
  if (scopeType === "etf") return "ETF";
  return scopeType;
}

function severityColor(severity: string): string {
  if (severity === "strong") return "red";
  if (severity === "alert") return "orange";
  if (severity === "observe") return "blue";
  return "gray";
}

function formatYuan(value: string): string {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "—";
  if (amount >= 100_000_000) return `${(amount / 100_000_000).toFixed(2)} 亿`;
  if (amount >= 10_000) return `${(amount / 10_000).toFixed(2)} 万`;
  return `${amount.toFixed(2)} 元`;
}

function formatEtfShare(value: string | null): string {
  return formatEtfScale(value, "份");
}

function formatEtfSize(value: string | null): string {
  return formatEtfScale(value, "元");
}

function formatEtfScale(value: string | null, unit: "份" | "元"): string {
  if (value === null || value.trim() === "") return "—";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "—";
  const useYi = Math.abs(amount) >= 10_000;
  const displayValue = useYi ? amount / 10_000 : amount;
  return `${new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(displayValue)} ${useYi ? "亿" : "万"}${unit}`;
}

function HighlightMatch({ value, keyword }: { value: string; keyword: string }) {
  const query = keyword.trim();
  if (!query) return <>{value}</>;

  const parts = value.split(new RegExp(`(${escapeRegExp(query)})`, "ig"));
  return (
    <>
      {parts.map((part, index) => part.toLowerCase() === query.toLowerCase() ? (
        <mark key={`${part}-${index}`} style={{ backgroundColor: "var(--mantine-color-orange-2)", borderRadius: "var(--mantine-radius-xs)", color: "inherit", padding: "0 2px" }}>
          {part}
        </mark>
      ) : part)}
    </>
  );
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
