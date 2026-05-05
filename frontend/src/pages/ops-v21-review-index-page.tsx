import { Alert, Badge, Button, Group, Modal, NumberInput, Select, SimpleGrid, Stack, Table, Text, TextInput } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconSearch } from "@tabler/icons-react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearch } from "@tanstack/react-router";

import { apiRequest } from "../shared/api/client";
import type {
  OpsReviewActiveIndexCandidateResponse,
  OpsReviewActiveIndexMutationResponse,
  OpsReviewActiveIndexResponse,
  OpsReviewActiveIndexSummaryResponse,
} from "../shared/api/types";
import { formatDateLabel } from "../shared/date-format";
import { EmptyState } from "../shared/ui/empty-state";
import { FilterBar, FilterBarItem } from "../shared/ui/filter-bar";
import { OpsTable, OpsTableCell, OpsTableHeaderCell } from "../shared/ui/ops-table";
import { PageHeader } from "../shared/ui/page-header";
import { SectionCard } from "../shared/ui/section-card";
import { StatCard } from "../shared/ui/stat-card";
import { TableShell } from "../shared/ui/table-shell";

type ActiveIndexItem = OpsReviewActiveIndexResponse["items"][number];
type ActiveIndexCandidate = OpsReviewActiveIndexCandidateResponse["items"][number];

const DATA_STATUS_OPTIONS = [
  { value: "all", label: "全部" },
  { value: "complete", label: "完整" },
  { value: "pending", label: "待处理" },
  { value: "unsynced", label: "未同步" },
  { value: "missing_daily", label: "缺日线" },
  { value: "missing_weekly", label: "缺周线" },
  { value: "missing_monthly", label: "缺月线" },
];

const LAYER_LABELS: Record<string, string> = {
  daily: "日线",
  weekly: "周线",
  monthly: "月线",
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

function formatStatusLabel(item: ActiveIndexItem): string {
  if (item.data_status === "complete") return "完整";
  if (item.data_status === "unsynced") return "未同步";
  const missingLabels = item.missing_layers.map((layer) => LAYER_LABELS[layer] || layer);
  if (missingLabels.length > 0) return `缺${missingLabels.join("、")}`;
  return "待处理";
}

function statusColor(item: ActiveIndexItem): string {
  if (item.data_status === "complete") return "success";
  if (item.data_status === "unsynced") return "error";
  return "warning";
}

function formatRecentMarketDates(item: ActiveIndexItem): string {
  return [
    `日 ${formatDateLabel(item.latest_daily_date)}`,
    `周 ${formatDateLabel(item.latest_weekly_date)}`,
    `月 ${formatDateLabel(item.latest_monthly_date)}`,
  ].join(" · ");
}

function formatCandidateMeta(candidate: ActiveIndexCandidate): string {
  return [candidate.market, candidate.publisher].filter(Boolean).join(" / ") || "—";
}

export function OpsV21ReviewIndexPage() {
  const navigate = useNavigate();
  const search = useSearch({ strict: false });
  const queryClient = useQueryClient();
  const resource = "index_daily";
  const keyword = pickString((search as Record<string, unknown>)?.keyword, "");
  const dataStatus = pickString((search as Record<string, unknown>)?.data_status, "all");
  const [keywordDraft, setKeywordDraft] = useState(keyword);
  const [addModalOpened, setAddModalOpened] = useState(false);
  const [candidateKeyword, setCandidateKeyword] = useState("");
  const [selectedCandidate, setSelectedCandidate] = useState<ActiveIndexCandidate | null>(null);
  const [removeTarget, setRemoveTarget] = useState<ActiveIndexItem | null>(null);
  const page = Math.max(1, pickNumber((search as Record<string, unknown>)?.page, 1));
  const pageSize = Math.min(200, Math.max(10, pickNumber((search as Record<string, unknown>)?.page_size, 50)));

  useEffect(() => {
    setKeywordDraft(keyword);
  }, [keyword]);

  const listQueryKey = useMemo(
    () => ["ops", "review", "index", "active", resource, keyword, dataStatus, page, pageSize],
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
      return apiRequest<OpsReviewActiveIndexResponse>(`/api/v1/ops/review/index/active?${params.toString()}`);
    },
  });
  const summaryQuery = useQuery({
    queryKey: ["ops", "review", "index", "active", "summary", resource],
    queryFn: () => apiRequest<OpsReviewActiveIndexSummaryResponse>(`/api/v1/ops/review/index/active/summary?resource=${resource}`),
  });
  const candidateQuery = useQuery({
    queryKey: ["ops", "review", "index", "active", "candidates", resource, candidateKeyword],
    enabled: addModalOpened && candidateKeyword.trim().length > 0,
    queryFn: () => {
      const params = new URLSearchParams();
      params.set("resource", resource);
      params.set("keyword", candidateKeyword.trim());
      return apiRequest<OpsReviewActiveIndexCandidateResponse>(`/api/v1/ops/review/index/active/candidates?${params.toString()}`);
    },
  });

  const addMutation = useMutation({
    mutationFn: (candidate: ActiveIndexCandidate) => apiRequest<OpsReviewActiveIndexMutationResponse>("/api/v1/ops/review/index/active", {
      method: "POST",
      body: { resource, ts_code: candidate.ts_code },
    }),
    onSuccess: async (_, candidate) => {
      notifications.show({
        color: "success",
        title: "已加入激活池",
        message: `${candidate.ts_code} ${candidate.index_name || ""}`.trim(),
      });
      setAddModalOpened(false);
      setCandidateKeyword("");
      setSelectedCandidate(null);
      await queryClient.invalidateQueries({ queryKey: ["ops", "review", "index", "active"] });
    },
    onError: (error) => {
      notifications.show({
        color: "red",
        title: "加入激活池失败",
        message: error instanceof Error ? error.message : "请稍后重试。",
      });
    },
  });

  const removeMutation = useMutation({
    mutationFn: (item: ActiveIndexItem) => apiRequest<OpsReviewActiveIndexMutationResponse>(
      `/api/v1/ops/review/index/active/${encodeURIComponent(item.ts_code)}?resource=${resource}`,
      { method: "DELETE" },
    ),
    onSuccess: async (_, item) => {
      notifications.show({
        color: "success",
        title: "已移出激活池",
        message: `${item.ts_code} ${item.index_name || ""}`.trim(),
      });
      setRemoveTarget(null);
      await queryClient.invalidateQueries({ queryKey: ["ops", "review", "index", "active"] });
    },
    onError: (error) => {
      notifications.show({
        color: "red",
        title: "移出激活池失败",
        message: error instanceof Error ? error.message : "请稍后重试。",
      });
    },
  });

  const total = query.data?.total || 0;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));

  const applyKeywordSearch = () => {
    void navigate({
      to: "/ops/v21/review/index",
      search: {
        ...((search as Record<string, unknown>) || {}),
        keyword: keywordDraft.trim(),
        page: 1,
      },
      replace: true,
    });
  };

  return (
    <Stack gap="lg">
      <PageHeader title="审查中心 · 指数激活池" />

      <SectionCard
        title="激活池管理"
        description="激活池决定哪些指数可以进入服务层。加入后需要重新维护行情，历史数据才会补齐；移出后不会自动删除历史数据。"
        action={(
          <Button onClick={() => setAddModalOpened(true)}>
            加入指数
          </Button>
        )}
      >
        <SimpleGrid cols={{ base: 1, sm: summaryQuery.data?.pending_count ? 5 : 4 }} spacing="md">
          <StatCard label="激活指数" value={summaryQuery.data?.active_count ?? "—"} />
          <StatCard label="日线可用" value={summaryQuery.data?.daily_available_count ?? "—"} />
          <StatCard label="周线可用" value={summaryQuery.data?.weekly_available_count ?? "—"} />
          <StatCard label="月线可用" value={summaryQuery.data?.monthly_available_count ?? "—"} />
          {summaryQuery.data?.pending_count ? (
            <StatCard label="待处理" value={summaryQuery.data.pending_count} />
          ) : null}
        </SimpleGrid>
      </SectionCard>

      <SectionCard title="指数列表">
        <Stack gap="md">
          <FilterBar
            actions={(
              <Button variant="light" onClick={applyKeywordSearch}>
                搜索
              </Button>
            )}
          >
            <FilterBarItem span={{ base: 12, md: 5 }}>
              <TextInput
                label="关键词"
                placeholder="输入指数代码或名称"
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
                onChange={(value) => {
                  void navigate({
                    to: "/ops/v21/review/index",
                    search: {
                      ...((search as Record<string, unknown>) || {}),
                      data_status: value || "all",
                      page: 1,
                    },
                    replace: true,
                  });
                }}
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
                  void navigate({
                    to: "/ops/v21/review/index",
                    search: {
                      ...((search as Record<string, unknown>) || {}),
                      page_size: Number.isFinite(next) ? Math.max(10, Math.min(200, next)) : 50,
                      page: 1,
                    },
                    replace: true,
                  });
                }}
              />
            </FilterBarItem>
          </FilterBar>

          {query.error ? (
            <Alert color="error" title="读取指数激活池失败">
              {query.error instanceof Error ? query.error.message : "未知错误"}
            </Alert>
          ) : null}
          {!query.error ? (
            <TableShell
              loading={query.isLoading}
              hasData={(query.data?.items || []).length > 0}
              emptyState={<EmptyState title="当前没有符合条件的指数" description="可以调整关键词或数据状态后重试。" />}
              summary={(
                <Group justify="space-between" mt={4}>
                  <Text c="dimmed" size="sm">共 {total} 条</Text>
                  <Group gap="xs">
                    <Button
                      size="xs"
                      variant="light"
                      disabled={page <= 1}
                      onClick={() => {
                        void navigate({
                          to: "/ops/v21/review/index",
                          search: { ...((search as Record<string, unknown>) || {}), page: page - 1 },
                          replace: true,
                        });
                      }}
                    >
                      上一页
                    </Button>
                    <Text size="sm" c="dimmed">{page}/{pageCount}</Text>
                    <Button
                      size="xs"
                      variant="light"
                      disabled={page >= pageCount}
                      onClick={() => {
                        void navigate({
                          to: "/ops/v21/review/index",
                          search: { ...((search as Record<string, unknown>) || {}), page: page + 1 },
                          replace: true,
                        });
                      }}
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
                    <OpsTableHeaderCell align="left">指数代码</OpsTableHeaderCell>
                    <OpsTableHeaderCell align="left">指数名称</OpsTableHeaderCell>
                    <OpsTableHeaderCell align="left">市场</OpsTableHeaderCell>
                    <OpsTableHeaderCell align="left">发布方</OpsTableHeaderCell>
                    <OpsTableHeaderCell align="left">数据状态</OpsTableHeaderCell>
                    <OpsTableHeaderCell align="left">最近行情</OpsTableHeaderCell>
                    <OpsTableHeaderCell align="right">操作</OpsTableHeaderCell>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {(query.data?.items || []).map((item) => (
                    <Table.Tr key={`${item.resource}-${item.ts_code}`}>
                      <OpsTableCell align="left">{item.ts_code}</OpsTableCell>
                      <OpsTableCell align="left">{item.index_name || "—"}</OpsTableCell>
                      <OpsTableCell align="left">{item.market || "—"}</OpsTableCell>
                      <OpsTableCell align="left">{item.publisher || "—"}</OpsTableCell>
                      <OpsTableCell align="left">
                        <Badge variant="light" color={statusColor(item)}>{formatStatusLabel(item)}</Badge>
                      </OpsTableCell>
                      <OpsTableCell align="left">{formatRecentMarketDates(item)}</OpsTableCell>
                      <OpsTableCell align="right">
                        <Button size="compact-xs" variant="subtle" color="error" onClick={() => setRemoveTarget(item)}>
                          移出
                        </Button>
                      </OpsTableCell>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </OpsTable>
            </TableShell>
          ) : null}
        </Stack>
      </SectionCard>

      <Modal
        opened={addModalOpened}
        onClose={() => {
          setAddModalOpened(false);
          setSelectedCandidate(null);
        }}
        title="加入指数"
        size="lg"
      >
        <Stack gap="md">
          <TextInput
            label="搜索指数"
            placeholder="输入指数代码或名称"
            value={candidateKeyword}
            onChange={(event) => {
              setCandidateKeyword(event.currentTarget.value);
              setSelectedCandidate(null);
            }}
            leftSection={<IconSearch size={14} />}
          />
          {candidateQuery.error ? (
            <Alert color="error" title="搜索候选指数失败">
              {candidateQuery.error instanceof Error ? candidateQuery.error.message : "未知错误"}
            </Alert>
          ) : null}
          <TableShell
            loading={candidateQuery.isLoading}
            hasData={(candidateQuery.data?.items || []).length > 0}
            emptyState={<EmptyState title="没有可加入的指数" description="请输入指数代码或名称搜索，已在激活池中的指数不会出现在这里。" />}
          >
            <OpsTable withTableBorder verticalSpacing="xs">
              <Table.Thead>
                <Table.Tr>
                  <OpsTableHeaderCell align="left">指数代码</OpsTableHeaderCell>
                  <OpsTableHeaderCell align="left">指数名称</OpsTableHeaderCell>
                  <OpsTableHeaderCell align="left">信息</OpsTableHeaderCell>
                  <OpsTableHeaderCell align="right">选择</OpsTableHeaderCell>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {(candidateQuery.data?.items || []).map((candidate) => (
                  <Table.Tr key={candidate.ts_code}>
                    <OpsTableCell align="left">{candidate.ts_code}</OpsTableCell>
                    <OpsTableCell align="left">{candidate.index_name || "—"}</OpsTableCell>
                    <OpsTableCell align="left">{formatCandidateMeta(candidate)}</OpsTableCell>
                    <OpsTableCell align="right">
                      <Button
                        size="compact-xs"
                        variant={selectedCandidate?.ts_code === candidate.ts_code ? "filled" : "light"}
                        onClick={() => setSelectedCandidate(candidate)}
                      >
                        选择
                      </Button>
                    </OpsTableCell>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </OpsTable>
          </TableShell>
          <Alert color="info" variant="light">
            加入后，该指数允许进入服务层。若需要补齐历史行情，请再发起行情维护任务。
          </Alert>
          <Group justify="flex-end">
            <Button variant="light" onClick={() => setAddModalOpened(false)}>取消</Button>
            <Button
              disabled={!selectedCandidate}
              loading={addMutation.isPending}
              onClick={() => {
                if (selectedCandidate) addMutation.mutate(selectedCandidate);
              }}
            >
              确认加入
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={removeTarget !== null}
        onClose={() => setRemoveTarget(null)}
        title="移出激活池"
      >
        <Stack gap="md">
          <Text>
            确认将 {removeTarget?.ts_code} {removeTarget?.index_name || ""} 移出激活池？
          </Text>
          <Alert color="warning" variant="light">
            移出后，该指数后续不会再写入服务层；raw 源站数据不受影响，已存在的服务层历史数据也不会在本操作中自动删除。
          </Alert>
          <Group justify="flex-end">
            <Button variant="light" onClick={() => setRemoveTarget(null)}>取消</Button>
            <Button
              color="error"
              loading={removeMutation.isPending}
              onClick={() => {
                if (removeTarget) removeMutation.mutate(removeTarget);
              }}
            >
              确认移出
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
