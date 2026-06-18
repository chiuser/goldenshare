import { Alert, Badge, Button, Group, NumberInput, Select, SimpleGrid, Stack, Table, Text, TextInput } from "@mantine/core";
import { IconSearch } from "@tabler/icons-react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearch } from "@tanstack/react-router";

import { apiRequest } from "../shared/api/client";
import type {
  OpsReviewActiveEtfResponse,
  OpsReviewActiveEtfSummaryResponse,
} from "../shared/api/types";
import { formatDateLabel, formatDateTimeLabel } from "../shared/date-format";
import { EmptyState } from "../shared/ui/empty-state";
import { FilterBar, FilterBarItem } from "../shared/ui/filter-bar";
import { OpsTable, OpsTableCell, OpsTableHeaderCell } from "../shared/ui/ops-table";
import { PageHeader } from "../shared/ui/page-header";
import { SectionCard } from "../shared/ui/section-card";
import { StatCard } from "../shared/ui/stat-card";
import { TableShell } from "../shared/ui/table-shell";

type ActiveEtfItem = OpsReviewActiveEtfResponse["items"][number];

const RESOURCE_OPTIONS = [
  { value: "fund_daily", label: "ETF日线池" },
  { value: "etf_rt_daily", label: "ETF实时日线池" },
];

const DATA_STATUS_OPTIONS = [
  { value: "all", label: "全部" },
  { value: "complete", label: "已有日线" },
  { value: "unsynced", label: "未同步" },
  { value: "pending", label: "待处理" },
];

const RESOURCE_LABELS: Record<string, string> = {
  fund_daily: "ETF日线池",
  etf_rt_daily: "ETF实时日线池",
};

const LIST_STATUS_LABELS: Record<string, string> = {
  L: "上市",
  D: "退市",
  P: "发行",
};

function pickString(value: unknown, fallback: string): string {
  if (typeof value === "string" && value.trim()) return value;
  return fallback;
}

function pickNumber(value: unknown, fallback: number): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

function formatEtfName(item: ActiveEtfItem): string {
  return item.csname || item.extname || item.cname || "—";
}

function formatDataStatusLabel(status: string): string {
  if (status === "complete") return "已有日线";
  if (status === "unsynced") return "未同步";
  if (status === "pending") return "待处理";
  return status || "—";
}

function dataStatusColor(status: string): string {
  if (status === "complete") return "success";
  if (status === "unsynced" || status === "pending") return "warning";
  return "gray";
}

function formatListStatus(status: string | null): string {
  if (!status) return "—";
  return LIST_STATUS_LABELS[status] || status;
}

export function OpsV21ReviewEtfPage() {
  const navigate = useNavigate();
  const search = useSearch({ strict: false });
  const resource = pickString((search as Record<string, unknown>)?.resource, "fund_daily");
  const keyword = pickString((search as Record<string, unknown>)?.keyword, "");
  const dataStatus = pickString((search as Record<string, unknown>)?.data_status, "all");
  const [keywordDraft, setKeywordDraft] = useState(keyword);
  const page = Math.max(1, pickNumber((search as Record<string, unknown>)?.page, 1));
  const pageSize = Math.min(200, Math.max(10, pickNumber((search as Record<string, unknown>)?.page_size, 50)));

  useEffect(() => {
    setKeywordDraft(keyword);
  }, [keyword]);

  const listQueryKey = useMemo(
    () => ["ops", "review", "etf", "active", resource, keyword, dataStatus, page, pageSize],
    [resource, keyword, dataStatus, page, pageSize],
  );
  const query = useQuery({
    queryKey: listQueryKey,
    placeholderData: keepPreviousData,
    queryFn: () => {
      const params = new URLSearchParams();
      params.set("resource", resource);
      params.set("page", String(page));
      params.set("page_size", String(pageSize));
      if (keyword.trim()) params.set("keyword", keyword.trim());
      if (dataStatus !== "all") params.set("data_status", dataStatus);
      return apiRequest<OpsReviewActiveEtfResponse>(`/api/v1/ops/review/etf/active?${params.toString()}`);
    },
  });
  const summaryQuery = useQuery({
    queryKey: ["ops", "review", "etf", "active", "summary", resource],
    queryFn: () => apiRequest<OpsReviewActiveEtfSummaryResponse>(`/api/v1/ops/review/etf/active/summary?resource=${resource}`),
  });

  const total = query.data?.total || 0;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));

  const updateSearch = (next: Record<string, unknown>) => {
    void navigate({
      to: "/ops/v21/review/etf",
      search: {
        ...((search as Record<string, unknown>) || {}),
        ...next,
      },
      replace: true,
    });
  };

  const applyKeywordSearch = () => {
    updateSearch({ keyword: keywordDraft.trim(), page: 1 });
  };

  return (
    <Stack gap="lg">
      <PageHeader title="审查中心 · ETF活跃池" />

      <SectionCard
        title="活跃池总览"
        description="这里只查看 ETF 活跃池当前事实，不承接维护动作。是否已有日线只按服务层是否存在任意 fund_daily 行判断。"
      >
        <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="md">
          <StatCard label="活跃ETF" value={summaryQuery.data?.active_count ?? "—"} />
          <StatCard label="日线可用" value={summaryQuery.data?.fund_daily_available_count ?? "—"} />
          <StatCard label="待处理" value={summaryQuery.data?.pending_count ?? "—"} />
        </SimpleGrid>
      </SectionCard>

      <SectionCard title="ETF列表">
        <Stack gap="md">
          <FilterBar
            actions={(
              <Button variant="light" onClick={applyKeywordSearch}>
                搜索
              </Button>
            )}
          >
            <FilterBarItem span={{ base: 12, md: 3 }}>
              <Select
                label="活跃池"
                data={RESOURCE_OPTIONS}
                value={resource}
                allowDeselect={false}
                onChange={(value) => updateSearch({ resource: value || "fund_daily", page: 1 })}
              />
            </FilterBarItem>
            <FilterBarItem span={{ base: 12, md: 4 }}>
              <TextInput
                label="关键词"
                placeholder="输入 ETF 代码或名称"
                value={keywordDraft}
                onChange={(event) => {
                  setKeywordDraft(event.currentTarget.value);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    applyKeywordSearch();
                  }
                }}
                leftSection={<IconSearch size={14} />}
              />
            </FilterBarItem>
            <FilterBarItem span={{ base: 12, md: 3 }}>
              <Select
                label="数据状态"
                data={DATA_STATUS_OPTIONS}
                value={dataStatus}
                allowDeselect={false}
                onChange={(value) => updateSearch({ data_status: value || "all", page: 1 })}
              />
            </FilterBarItem>
            <FilterBarItem span={{ base: 12, md: 2 }}>
              <NumberInput
                label="每页"
                min={10}
                max={200}
                step={10}
                value={pageSize}
                onChange={(value) => {
                  const next = typeof value === "number" ? value : Number(value || 50);
                  updateSearch({
                    page_size: Number.isFinite(next) ? Math.max(10, Math.min(200, next)) : 50,
                    page: 1,
                  });
                }}
              />
            </FilterBarItem>
          </FilterBar>

          {query.error ? (
            <Alert color="error" title="读取 ETF 活跃池失败">
              {query.error instanceof Error ? query.error.message : "未知错误"}
            </Alert>
          ) : null}
          {!query.error ? (
            <TableShell
              loading={query.isLoading}
              hasData={(query.data?.items || []).length > 0}
              emptyState={<EmptyState title="当前没有符合条件的 ETF" description="可以调整活跃池、关键词或数据状态后重试。" />}
              summary={(
                <Group justify="space-between" mt={4}>
                  <Text c="dimmed" size="sm">共 {total} 条</Text>
                  <Group gap="xs">
                    <Button
                      size="xs"
                      variant="light"
                      disabled={page <= 1}
                      onClick={() => updateSearch({ page: page - 1 })}
                    >
                      上一页
                    </Button>
                    <Text size="sm" c="dimmed">{page}/{pageCount}</Text>
                    <Button
                      size="xs"
                      variant="light"
                      disabled={page >= pageCount}
                      onClick={() => updateSearch({ page: page + 1 })}
                    >
                      下一页
                    </Button>
                  </Group>
                </Group>
              )}
            >
              <OpsTable withTableBorder verticalSpacing="xs">
                <Table.Thead>
                  <Table.Tr>
                    <OpsTableHeaderCell align="left">ETF代码</OpsTableHeaderCell>
                    <OpsTableHeaderCell align="left">ETF名称</OpsTableHeaderCell>
                    <OpsTableHeaderCell align="left">活跃池</OpsTableHeaderCell>
                    <OpsTableHeaderCell align="left">交易所</OpsTableHeaderCell>
                    <OpsTableHeaderCell align="left">ETF类型</OpsTableHeaderCell>
                    <OpsTableHeaderCell align="left">上市状态</OpsTableHeaderCell>
                    <OpsTableHeaderCell align="left">上市日期</OpsTableHeaderCell>
                    <OpsTableHeaderCell align="left">最新日线</OpsTableHeaderCell>
                    <OpsTableHeaderCell align="left">入池日期</OpsTableHeaderCell>
                    <OpsTableHeaderCell align="left">最近检查</OpsTableHeaderCell>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {(query.data?.items || []).map((item) => (
                    <Table.Tr key={`${item.resource}-${item.ts_code}`}>
                      <OpsTableCell align="left">{item.ts_code}</OpsTableCell>
                      <OpsTableCell align="left">{formatEtfName(item)}</OpsTableCell>
                      <OpsTableCell align="left">{RESOURCE_LABELS[item.resource] || item.resource}</OpsTableCell>
                      <OpsTableCell align="left">{item.exchange || "—"}</OpsTableCell>
                      <OpsTableCell align="left">{item.etf_type || "—"}</OpsTableCell>
                      <OpsTableCell align="left">{formatListStatus(item.list_status)}</OpsTableCell>
                      <OpsTableCell align="left">{formatDateLabel(item.list_date)}</OpsTableCell>
                      <OpsTableCell align="left">
                        <Group gap="xs">
                          <Badge variant="light" color={dataStatusColor(item.data_status)}>
                            {formatDataStatusLabel(item.data_status)}
                          </Badge>
                          <Text size="sm">{formatDateLabel(item.latest_fund_daily_date)}</Text>
                        </Group>
                      </OpsTableCell>
                      <OpsTableCell align="left">{formatDateLabel(item.first_seen_date)}</OpsTableCell>
                      <OpsTableCell align="left">{formatDateTimeLabel(item.last_checked_at)}</OpsTableCell>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </OpsTable>
            </TableShell>
          ) : null}
        </Stack>
      </SectionCard>
    </Stack>
  );
}
