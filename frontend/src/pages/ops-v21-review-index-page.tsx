import { Alert, Badge, Button, Group, NumberInput, Stack, Table, Text, TextInput } from "@mantine/core";
import { IconSearch } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearch } from "@tanstack/react-router";

import { apiRequest } from "../shared/api/client";
import type { OpsReviewActiveIndexResponse } from "../shared/api/types";
import { formatDateLabel, formatDateTimeLabel } from "../shared/date-format";
import { EmptyState } from "../shared/ui/empty-state";
import { FilterBar, FilterBarItem } from "../shared/ui/filter-bar";
import { OpsTable, OpsTableCell, OpsTableHeaderCell } from "../shared/ui/ops-table";
import { PageHeader } from "../shared/ui/page-header";
import { SectionCard } from "../shared/ui/section-card";
import { TableShell } from "../shared/ui/table-shell";

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

export function OpsV21ReviewIndexPage() {
  const navigate = useNavigate();
  const search = useSearch({ strict: false });
  const resource = "index_daily";
  const keyword = pickString((search as Record<string, unknown>)?.keyword, "");
  const [keywordDraft, setKeywordDraft] = useState(keyword);
  const page = Math.max(1, pickNumber((search as Record<string, unknown>)?.page, 1));
  const pageSize = Math.min(200, Math.max(10, pickNumber((search as Record<string, unknown>)?.page_size, 50)));

  useEffect(() => {
    setKeywordDraft(keyword);
  }, [keyword]);

  const queryKey = useMemo(() => ["ops", "review", "index", resource, keyword, page, pageSize], [resource, keyword, page, pageSize]);
  const query = useQuery({
    queryKey,
    queryFn: () => {
      const params = new URLSearchParams();
      params.set("resource", resource);
      params.set("page", String(page));
      params.set("page_size", String(pageSize));
      if (keyword.trim()) params.set("keyword", keyword.trim());
      return apiRequest<OpsReviewActiveIndexResponse>(`/api/v1/ops/review/index/active?${params.toString()}`);
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
      <PageHeader
        title="审查中心 · 指数"
        description="查看当前纳入同步池的激活指数列表，并按关键词或分页规模进行只读审查。"
      />

      <SectionCard title="筛选与资源池" description="指数周线/月线与日线共用同一激活池，当前只提供只读审查。">
        <Stack gap="md">
          <Group gap={8}>
            <Badge variant="light" color="info">指数日线池</Badge>
            <Text size="xs" c="dimmed">周线/月线与日线共用同一激活池</Text>
          </Group>
          <FilterBar
            actions={(
              <Button variant="light" onClick={applyKeywordSearch}>
                搜索
              </Button>
            )}
          >
            <FilterBarItem span={{ base: 12, md: 6 }}>
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
        </Stack>
      </SectionCard>

      <SectionCard title="激活指数列表">
        {query.error ? (
          <Alert color="error" title="读取激活指数失败">
            {query.error instanceof Error ? query.error.message : "未知错误"}
          </Alert>
        ) : null}
        {!query.error ? (
          <TableShell
            loading={query.isLoading}
            hasData={(query.data?.items || []).length > 0}
            emptyState={<EmptyState title="当前没有符合条件的记录" description="你可以调整关键词或分页条件后重试。" />}
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
                  <OpsTableHeaderCell align="left">首次收录</OpsTableHeaderCell>
                  <OpsTableHeaderCell align="left">最近收录</OpsTableHeaderCell>
                  <OpsTableHeaderCell align="left">最近检查时间</OpsTableHeaderCell>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {(query.data?.items || []).map((item) => (
                  <Table.Tr key={`${item.resource}-${item.ts_code}`}>
                    <OpsTableCell align="left">{item.ts_code}</OpsTableCell>
                    <OpsTableCell align="left">{item.index_name || "—"}</OpsTableCell>
                    <OpsTableCell align="left">{formatDateLabel(item.first_seen_date)}</OpsTableCell>
                    <OpsTableCell align="left">{formatDateLabel(item.last_seen_date)}</OpsTableCell>
                    <OpsTableCell align="left">{formatDateTimeLabel(item.last_checked_at)}</OpsTableCell>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </OpsTable>
          </TableShell>
        ) : null}
      </SectionCard>
    </Stack>
  );
}
