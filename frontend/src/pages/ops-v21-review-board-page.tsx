import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  NumberInput,
  Paper,
  Select,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
} from "@mantine/core";
import { IconSearch } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useNavigate, useSearch } from "@tanstack/react-router";

import { apiRequest } from "../shared/api/client";
import type {
  OpsReviewDcBoardsResponse,
  OpsReviewEquityMembershipResponse,
  OpsReviewThsBoardsResponse,
} from "../shared/api/types";
import { formatDateLabel } from "../shared/date-format";
import { SectionCard } from "../shared/ui/section-card";


type ReviewBoardTab = "ths" | "dc" | "equity";

function resolveTab(value: unknown): ReviewBoardTab {
  if (value === "dc" || value === "equity") return value;
  return "ths";
}

function pickString(value: unknown, fallback: string): string {
  if (typeof value === "string") return value;
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

function badgeColor(provider: string): string {
  if (provider === "ths") return "blue";
  if (provider === "dc") return "violet";
  return "gray";
}

export function OpsV21ReviewBoardPage() {
  const navigate = useNavigate();
  const search = useSearch({ strict: false });
  const activeTab = useMemo(() => resolveTab((search as Record<string, unknown>)?.tab), [search]);
  const page = Math.max(1, pickNumber((search as Record<string, unknown>)?.page, 1));
  const pageSize = Math.min(100, Math.max(10, pickNumber((search as Record<string, unknown>)?.page_size, 30)));

  const thsKeyword = pickString((search as Record<string, unknown>)?.ths_keyword, "");
  const thsMin = Math.max(0, pickNumber((search as Record<string, unknown>)?.ths_min, 0));
  const dcTradeDate = pickString((search as Record<string, unknown>)?.dc_trade_date, "");
  const dcIdxType = pickString((search as Record<string, unknown>)?.dc_idx_type, "");
  const dcKeyword = pickString((search as Record<string, unknown>)?.dc_keyword, "");
  const dcMin = Math.max(0, pickNumber((search as Record<string, unknown>)?.dc_min, 0));
  const equityTradeDate = pickString((search as Record<string, unknown>)?.equity_trade_date, "");
  const equityProvider = pickString((search as Record<string, unknown>)?.equity_provider, "all");
  const equityKeyword = pickString((search as Record<string, unknown>)?.equity_keyword, "");
  const equityMin = Math.max(0, pickNumber((search as Record<string, unknown>)?.equity_min, 0));

  const thsQuery = useQuery({
    queryKey: ["ops", "review", "board", "ths", thsKeyword, thsMin, page, pageSize],
    enabled: activeTab === "ths",
    queryFn: () => {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", String(pageSize));
      if (thsKeyword.trim()) params.set("keyword", thsKeyword.trim());
      if (thsMin > 0) params.set("min_constituent_count", String(thsMin));
      return apiRequest<OpsReviewThsBoardsResponse>(`/api/v1/ops/review/board/ths?${params.toString()}`);
    },
  });

  const dcQuery = useQuery({
    queryKey: ["ops", "review", "board", "dc", dcTradeDate, dcIdxType, dcKeyword, dcMin, page, pageSize],
    enabled: activeTab === "dc",
    queryFn: () => {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", String(pageSize));
      if (dcTradeDate) params.set("trade_date", dcTradeDate);
      if (dcIdxType.trim()) params.set("idx_type", dcIdxType.trim());
      if (dcKeyword.trim()) params.set("keyword", dcKeyword.trim());
      if (dcMin > 0) params.set("min_constituent_count", String(dcMin));
      return apiRequest<OpsReviewDcBoardsResponse>(`/api/v1/ops/review/board/dc?${params.toString()}`);
    },
  });

  const equityQuery = useQuery({
    queryKey: ["ops", "review", "board", "equity", equityTradeDate, equityProvider, equityKeyword, equityMin, page, pageSize],
    enabled: activeTab === "equity",
    queryFn: () => {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", String(pageSize));
      params.set("provider", equityProvider || "all");
      if (equityTradeDate) params.set("trade_date", equityTradeDate);
      if (equityKeyword.trim()) params.set("keyword", equityKeyword.trim());
      if (equityMin > 0) params.set("min_board_count", String(equityMin));
      return apiRequest<OpsReviewEquityMembershipResponse>(`/api/v1/ops/review/board/equity-membership?${params.toString()}`);
    },
  });

  const activeQuery = activeTab === "ths" ? thsQuery : activeTab === "dc" ? dcQuery : equityQuery;
  const total = activeQuery.data?.total || 0;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));

  return (
    <Stack gap="lg">
      <SectionCard title="审查中心 · 板块" description="同花顺板块、东方财富板块、股票所属板块聚合（只读）。">
        <Tabs
          value={activeTab}
          onChange={(value) => {
            const next = resolveTab(value);
            void navigate({
              to: "/ops/v21/review/board",
              search: {
                ...((search as Record<string, unknown>) || {}),
                tab: next,
                page: 1,
              },
              replace: true,
            });
          }}
        >
          <Tabs.List>
            <Tabs.Tab value="ths">同花顺板块与成分股</Tabs.Tab>
            <Tabs.Tab value="dc">东方财富板块与成分股</Tabs.Tab>
            <Tabs.Tab value="equity">股票所属板块</Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="ths" pt="md">
            <Group align="flex-end" wrap="wrap">
              <TextInput
                label="板块关键词"
                placeholder="代码或名称"
                value={thsKeyword}
                onChange={(event) => {
                  void navigate({
                    to: "/ops/v21/review/board",
                    search: {
                      ...((search as Record<string, unknown>) || {}),
                      tab: "ths",
                      ths_keyword: event.currentTarget.value,
                      page: 1,
                    },
                    replace: true,
                  });
                }}
                leftSection={<IconSearch size={14} />}
                w={260}
              />
              <NumberInput
                label="成分个数 ≥"
                min={0}
                step={10}
                value={thsMin}
                onChange={(value) => {
                  const next = typeof value === "number" ? value : Number(value || 0);
                  void navigate({
                    to: "/ops/v21/review/board",
                    search: {
                      ...((search as Record<string, unknown>) || {}),
                      tab: "ths",
                      ths_min: Number.isFinite(next) ? Math.max(0, next) : 0,
                      page: 1,
                    },
                    replace: true,
                  });
                }}
                w={160}
              />
            </Group>
          </Tabs.Panel>

          <Tabs.Panel value="dc" pt="md">
            <Group align="flex-end" wrap="wrap">
              <TextInput
                type="date"
                label="交易日期"
                value={dcTradeDate}
                onChange={(event) => {
                  void navigate({
                    to: "/ops/v21/review/board",
                    search: {
                      ...((search as Record<string, unknown>) || {}),
                      tab: "dc",
                      dc_trade_date: event.currentTarget.value,
                      page: 1,
                    },
                    replace: true,
                  });
                }}
                w={190}
              />
              <TextInput
                label="板块类型"
                placeholder="例如：概念板块"
                value={dcIdxType}
                onChange={(event) => {
                  void navigate({
                    to: "/ops/v21/review/board",
                    search: {
                      ...((search as Record<string, unknown>) || {}),
                      tab: "dc",
                      dc_idx_type: event.currentTarget.value,
                      page: 1,
                    },
                    replace: true,
                  });
                }}
                w={220}
              />
              <TextInput
                label="板块关键词"
                placeholder="代码或名称"
                value={dcKeyword}
                onChange={(event) => {
                  void navigate({
                    to: "/ops/v21/review/board",
                    search: {
                      ...((search as Record<string, unknown>) || {}),
                      tab: "dc",
                      dc_keyword: event.currentTarget.value,
                      page: 1,
                    },
                    replace: true,
                  });
                }}
                leftSection={<IconSearch size={14} />}
                w={240}
              />
              <NumberInput
                label="成分个数 ≥"
                min={0}
                step={10}
                value={dcMin}
                onChange={(value) => {
                  const next = typeof value === "number" ? value : Number(value || 0);
                  void navigate({
                    to: "/ops/v21/review/board",
                    search: {
                      ...((search as Record<string, unknown>) || {}),
                      tab: "dc",
                      dc_min: Number.isFinite(next) ? Math.max(0, next) : 0,
                      page: 1,
                    },
                    replace: true,
                  });
                }}
                w={160}
              />
            </Group>
          </Tabs.Panel>

          <Tabs.Panel value="equity" pt="md">
            <Group align="flex-end" wrap="wrap">
              <TextInput
                type="date"
                label="东方财富快照日"
                value={equityTradeDate}
                onChange={(event) => {
                  void navigate({
                    to: "/ops/v21/review/board",
                    search: {
                      ...((search as Record<string, unknown>) || {}),
                      tab: "equity",
                      equity_trade_date: event.currentTarget.value,
                      page: 1,
                    },
                    replace: true,
                  });
                }}
                w={190}
              />
              <Select
                label="来源"
                data={[
                  { value: "all", label: "全部" },
                  { value: "ths", label: "同花顺" },
                  { value: "dc", label: "东方财富" },
                ]}
                value={equityProvider}
                onChange={(value) => {
                  void navigate({
                    to: "/ops/v21/review/board",
                    search: {
                      ...((search as Record<string, unknown>) || {}),
                      tab: "equity",
                      equity_provider: value || "all",
                      page: 1,
                    },
                    replace: true,
                  });
                }}
                w={150}
              />
              <TextInput
                label="股票关键词"
                placeholder="股票代码或名称"
                value={equityKeyword}
                onChange={(event) => {
                  void navigate({
                    to: "/ops/v21/review/board",
                    search: {
                      ...((search as Record<string, unknown>) || {}),
                      tab: "equity",
                      equity_keyword: event.currentTarget.value,
                      page: 1,
                    },
                    replace: true,
                  });
                }}
                leftSection={<IconSearch size={14} />}
                w={240}
              />
              <NumberInput
                label="所属板块数 ≥"
                min={0}
                step={1}
                value={equityMin}
                onChange={(value) => {
                  const next = typeof value === "number" ? value : Number(value || 0);
                  void navigate({
                    to: "/ops/v21/review/board",
                    search: {
                      ...((search as Record<string, unknown>) || {}),
                      tab: "equity",
                      equity_min: Number.isFinite(next) ? Math.max(0, next) : 0,
                      page: 1,
                    },
                    replace: true,
                  });
                }}
                w={160}
              />
            </Group>
          </Tabs.Panel>
        </Tabs>

        <Group justify="space-between" mt="xs">
          <Text c="dimmed" size="sm">共 {total} 条</Text>
          <Group gap="xs">
            <Button
              size="xs"
              variant="light"
              disabled={page <= 1}
              onClick={() => {
                void navigate({
                  to: "/ops/v21/review/board",
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
                  to: "/ops/v21/review/board",
                  search: { ...((search as Record<string, unknown>) || {}), page: page + 1 },
                  replace: true,
                });
              }}
            >
              下一页
            </Button>
          </Group>
        </Group>
      </SectionCard>

      <SectionCard title="审查结果">
        {activeQuery.isLoading ? <Loader size="sm" /> : null}
        {activeQuery.error ? (
          <Alert color="red" title="读取审查数据失败">
            {activeQuery.error instanceof Error ? activeQuery.error.message : "未知错误"}
          </Alert>
        ) : null}

        {!activeQuery.isLoading && !activeQuery.error && activeTab === "ths" ? (
          <Paper withBorder radius="md" p="sm">
            <Table striped highlightOnHover withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>板块代码</Table.Th>
                  <Table.Th>板块名称</Table.Th>
                  <Table.Th>交易所</Table.Th>
                  <Table.Th>类型</Table.Th>
                  <Table.Th>成分数</Table.Th>
                  <Table.Th>成分股</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {(thsQuery.data?.items || []).map((item) => (
                  <Table.Tr key={item.board_code}>
                    <Table.Td>{item.board_code}</Table.Td>
                    <Table.Td>{item.board_name || "—"}</Table.Td>
                    <Table.Td>{item.exchange || "—"}</Table.Td>
                    <Table.Td>{item.board_type || "—"}</Table.Td>
                    <Table.Td>{item.constituent_count}</Table.Td>
                    <Table.Td>
                      <Group gap={4}>
                        {item.members.slice(0, 12).map((member) => (
                          <Badge key={`${item.board_code}-${member.ts_code}`} size="xs" variant="light">
                            {member.ts_code}
                          </Badge>
                        ))}
                        {item.members.length > 12 ? <Text size="xs" c="dimmed">+{item.members.length - 12}</Text> : null}
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Paper>
        ) : null}

        {!activeQuery.isLoading && !activeQuery.error && activeTab === "dc" ? (
          <Stack gap="xs">
            <Text size="sm" c="dimmed">当前快照日期：{dcQuery.data?.trade_date ? formatDateLabel(dcQuery.data.trade_date) : "—"}</Text>
            <Paper withBorder radius="md" p="sm">
              <Table striped highlightOnHover withTableBorder>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>板块代码</Table.Th>
                    <Table.Th>板块名称</Table.Th>
                    <Table.Th>板块类型</Table.Th>
                    <Table.Th>成分数</Table.Th>
                    <Table.Th>成分股</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {(dcQuery.data?.items || []).map((item) => (
                    <Table.Tr key={item.board_code}>
                      <Table.Td>{item.board_code}</Table.Td>
                      <Table.Td>{item.board_name || "—"}</Table.Td>
                      <Table.Td>{item.idx_type || "—"}</Table.Td>
                      <Table.Td>{item.constituent_count}</Table.Td>
                      <Table.Td>
                        <Group gap={4}>
                          {item.members.slice(0, 12).map((member) => (
                            <Badge key={`${item.board_code}-${member.ts_code}`} size="xs" variant="light">
                              {member.ts_code}
                            </Badge>
                          ))}
                          {item.members.length > 12 ? <Text size="xs" c="dimmed">+{item.members.length - 12}</Text> : null}
                        </Group>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Paper>
          </Stack>
        ) : null}

        {!activeQuery.isLoading && !activeQuery.error && activeTab === "equity" ? (
          <Stack gap="xs">
            <Text size="sm" c="dimmed">当前东财快照日期：{equityQuery.data?.dc_trade_date ? formatDateLabel(equityQuery.data.dc_trade_date) : "—"}</Text>
            <Paper withBorder radius="md" p="sm">
              <Table striped highlightOnHover withTableBorder>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>股票代码</Table.Th>
                    <Table.Th>股票名称</Table.Th>
                    <Table.Th>板块数</Table.Th>
                    <Table.Th>所属板块</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {(equityQuery.data?.items || []).map((item) => (
                    <Table.Tr key={item.ts_code}>
                      <Table.Td>{item.ts_code}</Table.Td>
                      <Table.Td>{item.equity_name || "—"}</Table.Td>
                      <Table.Td>{item.board_count}</Table.Td>
                      <Table.Td>
                        <Group gap={4}>
                          {item.boards.map((board) => (
                            <Badge
                              key={`${item.ts_code}-${board.provider}-${board.board_code}`}
                              size="xs"
                              variant="light"
                              color={badgeColor(board.provider)}
                            >
                              {board.provider.toUpperCase()} · {board.board_name || board.board_code}
                            </Badge>
                          ))}
                        </Group>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Paper>
          </Stack>
        ) : null}

        {!activeQuery.isLoading && !activeQuery.error && total === 0 ? (
          <Alert color="blue" title="没有符合条件的数据">
            你可以放宽筛选条件后重试。
          </Alert>
        ) : null}
      </SectionCard>
    </Stack>
  );
}
