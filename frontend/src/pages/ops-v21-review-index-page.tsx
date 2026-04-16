import { Alert, Button, Group, Loader, NumberInput, Paper, Select, Stack, Table, Text, TextInput } from "@mantine/core";
import { IconSearch } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useNavigate, useSearch } from "@tanstack/react-router";

import { apiRequest } from "../shared/api/client";
import type { OpsReviewActiveIndexResponse } from "../shared/api/types";
import { formatDateLabel, formatDateTimeLabel } from "../shared/date-format";
import { SectionCard } from "../shared/ui/section-card";


const resourceOptions = [
  { value: "index_daily", label: "指数日线池" },
  { value: "index_weekly", label: "指数周线池" },
  { value: "index_monthly", label: "指数月线池" },
];

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
  const resource = pickString((search as Record<string, unknown>)?.resource, "index_daily");
  const keyword = pickString((search as Record<string, unknown>)?.keyword, "");
  const page = Math.max(1, pickNumber((search as Record<string, unknown>)?.page, 1));
  const pageSize = Math.min(200, Math.max(10, pickNumber((search as Record<string, unknown>)?.page_size, 50)));

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

  return (
    <Stack gap="lg">
      <SectionCard title="审查中心 · 指数" description="查看当前纳入同步池的激活指数列表（只读）。">
        <Stack gap="sm">
          <Group align="flex-end" wrap="wrap">
            <Select
              label="资源池"
              data={resourceOptions}
              value={resource}
              onChange={(value) => {
                void navigate({
                  to: "/ops/v21/review/index",
                  search: {
                    ...((search as Record<string, unknown>) || {}),
                    resource: value || "index_daily",
                    page: 1,
                  },
                  replace: true,
                });
              }}
              w={220}
            />
            <TextInput
              label="关键词"
              placeholder="输入指数代码过滤"
              value={keyword}
              onChange={(event) => {
                void navigate({
                  to: "/ops/v21/review/index",
                  search: {
                    ...((search as Record<string, unknown>) || {}),
                    keyword: event.currentTarget.value,
                    page: 1,
                  },
                  replace: true,
                });
              }}
              leftSection={<IconSearch size={14} />}
              w={260}
            />
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
              w={120}
            />
          </Group>
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
        </Stack>
      </SectionCard>

      <SectionCard title="激活指数列表">
        {query.isLoading ? <Loader size="sm" /> : null}
        {query.error ? (
          <Alert color="red" title="读取激活指数失败">
            {query.error instanceof Error ? query.error.message : "未知错误"}
          </Alert>
        ) : null}
        {!query.isLoading && !query.error ? (
          <Paper withBorder radius="md" p="sm">
            <Table striped highlightOnHover horizontalSpacing="md" verticalSpacing="xs" withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>资源</Table.Th>
                  <Table.Th>指数代码</Table.Th>
                  <Table.Th>首次观测</Table.Th>
                  <Table.Th>最近观测</Table.Th>
                  <Table.Th>最近检查时间</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {(query.data?.items || []).map((item) => (
                  <Table.Tr key={`${item.resource}-${item.ts_code}`}>
                    <Table.Td>{item.resource}</Table.Td>
                    <Table.Td>{item.ts_code}</Table.Td>
                    <Table.Td>{formatDateLabel(item.first_seen_date)}</Table.Td>
                    <Table.Td>{formatDateLabel(item.last_seen_date)}</Table.Td>
                    <Table.Td>{formatDateTimeLabel(item.last_checked_at)}</Table.Td>
                  </Table.Tr>
                ))}
                {(query.data?.items || []).length === 0 ? (
                  <Table.Tr>
                    <Table.Td colSpan={5}>
                      <Text size="sm" c="dimmed" ta="center">
                        当前没有符合条件的记录
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ) : null}
              </Table.Tbody>
            </Table>
          </Paper>
        ) : null}
      </SectionCard>
    </Stack>
  );
}
