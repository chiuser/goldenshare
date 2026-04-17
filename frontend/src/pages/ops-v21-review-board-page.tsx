import {
  Alert,
  Autocomplete,
  Badge,
  Button,
  Drawer,
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
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearch } from "@tanstack/react-router";

import { apiRequest } from "../shared/api/client";
import type {
  OpsReviewDcBoardsResponse,
  OpsReviewEquitySuggestResponse,
  OpsReviewEquityMembershipResponse,
  OpsReviewThsBoardsResponse,
} from "../shared/api/types";
import { formatDateLabel } from "../shared/date-format";
import { SectionCard } from "../shared/ui/section-card";


type ReviewBoardTab = "ths" | "dc" | "equity";
type ReviewBoardMember = { ts_code: string; name: string | null };
type ReviewEquityBoard = { provider: string; board_code: string; board_name: string | null };

const THS_BOARD_TYPE_LABELS: Record<string, string> = {
  N: "概念指数",
  I: "行业指数",
  R: "地域指数",
  S: "同花顺特色指数",
  ST: "同花顺风格指数",
  TH: "同花顺主题指数",
  BB: "同花顺宽基指数",
};

const THS_EXCHANGE_LABELS: Record<string, string> = {
  A: "A股",
  HK: "港股",
  US: "美股",
};

const MEMBER_PREVIEW_LIMIT = 5;
const MEMBER_DRAWER_PAGE_SIZE = 20;
const EQUITY_BOARD_PREVIEW_LIMIT = 8;
const THS_TYPE_OPTIONS = [
  { value: "", label: "全部类型" },
  ...Object.entries(THS_BOARD_TYPE_LABELS).map(([value, label]) => ({ value, label: `${value} - ${label}` })),
];

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

function mapWithFallback(value: string | null, mapping: Record<string, string>): string {
  if (!value) return "—";
  return mapping[value] || value;
}

function normalizeEquityKeyword(raw: string, suggestionCodeMap: Map<string, string>): string {
  const trimmed = raw.trim();
  if (!trimmed) return "";
  const mappedCode = suggestionCodeMap.get(trimmed);
  if (mappedCode) return mappedCode;
  const splitByPipe = trimmed.split("|");
  if (splitByPipe.length > 1) {
    return splitByPipe[0].trim();
  }
  return trimmed;
}

export function OpsV21ReviewBoardPage() {
  const navigate = useNavigate();
  const search = useSearch({ strict: false });
  const activeTab = useMemo(() => resolveTab((search as Record<string, unknown>)?.tab), [search]);
  const page = Math.max(1, pickNumber((search as Record<string, unknown>)?.page, 1));
  const pageSize = Math.min(100, Math.max(10, pickNumber((search as Record<string, unknown>)?.page_size, 30)));

  const thsKeyword = pickString((search as Record<string, unknown>)?.ths_keyword, "");
  const thsType = pickString((search as Record<string, unknown>)?.ths_type, "");
  const thsMin = Math.max(0, pickNumber((search as Record<string, unknown>)?.ths_min, 0));
  const dcTradeDate = pickString((search as Record<string, unknown>)?.dc_trade_date, "");
  const dcIdxType = pickString((search as Record<string, unknown>)?.dc_idx_type, "");
  const dcKeyword = pickString((search as Record<string, unknown>)?.dc_keyword, "");
  const dcMin = Math.max(0, pickNumber((search as Record<string, unknown>)?.dc_min, 0));
  const equityTradeDate = pickString((search as Record<string, unknown>)?.equity_trade_date, "");
  const equityProvider = pickString((search as Record<string, unknown>)?.equity_provider, "all");
  const equityKeyword = pickString((search as Record<string, unknown>)?.equity_keyword, "");
  const equityMin = Math.max(0, pickNumber((search as Record<string, unknown>)?.equity_min, 0));
  const [thsKeywordInput, setThsKeywordInput] = useState(thsKeyword);
  const [dcKeywordInput, setDcKeywordInput] = useState(dcKeyword);
  const [equityKeywordInput, setEquityKeywordInput] = useState(equityKeyword);
  const [memberDrawer, setMemberDrawer] = useState<{
    title: string;
    members: ReviewBoardMember[];
  } | null>(null);
  const [memberDrawerPage, setMemberDrawerPage] = useState(1);
  const [equityBoardDrawer, setEquityBoardDrawer] = useState<{
    title: string;
    provider: "all" | "ths" | "dc";
    boards: ReviewEquityBoard[];
  } | null>(null);

  useEffect(() => {
    setThsKeywordInput(thsKeyword);
  }, [thsKeyword]);
  useEffect(() => {
    setDcKeywordInput(dcKeyword);
  }, [dcKeyword]);
  useEffect(() => {
    setEquityKeywordInput(equityKeyword);
  }, [equityKeyword]);

  const applyThsKeywordSearch = () => {
    void navigate({
      to: "/ops/v21/review/board",
      search: {
        ...((search as Record<string, unknown>) || {}),
        tab: "ths",
        ths_keyword: thsKeywordInput.trim(),
        page: 1,
      },
      replace: true,
    });
  };
  const applyDcKeywordSearch = () => {
    void navigate({
      to: "/ops/v21/review/board",
      search: {
        ...((search as Record<string, unknown>) || {}),
        tab: "dc",
        dc_keyword: dcKeywordInput.trim(),
        page: 1,
      },
      replace: true,
    });
  };

  const equitySuggestQuery = useQuery({
    queryKey: ["ops", "review", "board", "equity-suggest", equityKeywordInput.trim()],
    enabled: activeTab === "equity" && equityKeywordInput.trim().length > 0,
    queryFn: () => {
      const params = new URLSearchParams();
      params.set("keyword", equityKeywordInput.trim());
      params.set("limit", "20");
      return apiRequest<OpsReviewEquitySuggestResponse>(`/api/v1/ops/review/board/equity-suggest?${params.toString()}`);
    },
  });

  const equitySuggestionCodeMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const item of equitySuggestQuery.data?.items || []) {
      const display = item.name ? `${item.ts_code} | ${item.name}` : item.ts_code;
      map.set(display, item.ts_code);
    }
    return map;
  }, [equitySuggestQuery.data?.items]);
  const equitySuggestionOptions = useMemo(
    () => (equitySuggestQuery.data?.items || []).map((item) => (item.name ? `${item.ts_code} | ${item.name}` : item.ts_code)),
    [equitySuggestQuery.data?.items],
  );

  const applyEquityKeywordSearch = () => {
    const normalizedKeyword = normalizeEquityKeyword(equityKeywordInput, equitySuggestionCodeMap);
    void navigate({
      to: "/ops/v21/review/board",
      search: {
        ...((search as Record<string, unknown>) || {}),
        tab: "equity",
        equity_keyword: normalizedKeyword,
        page: 1,
      },
      replace: true,
    });
  };

  const openMemberDrawer = (title: string, members: ReviewBoardMember[]) => {
    setEquityBoardDrawer(null);
    setMemberDrawer({ title, members });
    setMemberDrawerPage(1);
  };

  const closeMemberDrawer = () => {
    setMemberDrawer(null);
    setMemberDrawerPage(1);
  };
  const openEquityBoardDrawer = (title: string, boards: ReviewEquityBoard[], provider: string) => {
    setMemberDrawer(null);
    const resolvedProvider = provider === "ths" || provider === "dc" ? provider : "all";
    setEquityBoardDrawer({
      title,
      provider: resolvedProvider,
      boards,
    });
  };
  const closeEquityBoardDrawer = () => {
    setEquityBoardDrawer(null);
  };

  const drawerMembers = memberDrawer?.members || [];
  const drawerPageCount = Math.max(1, Math.ceil(drawerMembers.length / MEMBER_DRAWER_PAGE_SIZE));
  const drawerCurrentPage = Math.min(memberDrawerPage, drawerPageCount);
  const drawerPageMembers = drawerMembers.slice(
    (drawerCurrentPage - 1) * MEMBER_DRAWER_PAGE_SIZE,
    drawerCurrentPage * MEMBER_DRAWER_PAGE_SIZE
  );

  const renderMemberCell = (params: {
    members: ReviewBoardMember[];
    boardCode: string;
    boardName: string | null;
    sourceLabel: string;
  }) => {
    if (params.members.length === 0) return <Text size="sm" c="dimmed">—</Text>;
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 8, width: "100%" }}>
        <Group gap={4} wrap="wrap" style={{ flex: 1 }}>
          {params.members.slice(0, MEMBER_PREVIEW_LIMIT).map((member, index) => (
            <Badge key={`${params.boardCode}-${member.ts_code}-${index}`} size="xs" variant="light">
              {member.name || "未知名称"}
            </Badge>
          ))}
        </Group>
        {params.members.length > MEMBER_PREVIEW_LIMIT ? (
          <Button
            size="xs"
            variant="subtle"
            style={{ marginLeft: "auto" }}
            onClick={() => openMemberDrawer(`${params.sourceLabel}成分股 · ${params.boardName || params.boardCode}`, params.members)}
          >
            查看更多
          </Button>
        ) : null}
      </div>
    );
  };
  const renderEquityBoardCell = (params: {
    boards: ReviewEquityBoard[];
    tsCode: string;
    equityName: string | null;
    providerFilter: string;
  }) => {
    if (params.boards.length === 0) return <Text size="sm" c="dimmed">—</Text>;
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 8, width: "100%" }}>
        <Group gap={4} wrap="wrap" style={{ flex: 1 }}>
          {params.boards.slice(0, EQUITY_BOARD_PREVIEW_LIMIT).map((board) => (
            <Badge
              key={`${params.tsCode}-${board.provider}-${board.board_code}`}
              size="xs"
              variant="light"
              color={badgeColor(board.provider)}
            >
              {board.provider.toUpperCase()} · {board.board_name || board.board_code}
            </Badge>
          ))}
        </Group>
        {params.boards.length > EQUITY_BOARD_PREVIEW_LIMIT ? (
          <Button
            size="xs"
            variant="subtle"
            style={{ marginLeft: "auto" }}
            onClick={() => openEquityBoardDrawer(
              `所属板块 · ${params.equityName || params.tsCode}`,
              params.boards,
              params.providerFilter,
            )}
          >
            查看更多
          </Button>
        ) : null}
      </div>
    );
  };

  const thsQuery = useQuery({
    queryKey: ["ops", "review", "board", "ths", thsType, thsKeyword, thsMin, page, pageSize],
    enabled: activeTab === "ths",
    queryFn: () => {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", String(pageSize));
      if (thsType) params.set("board_type", thsType);
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
  const dcTypeSelectData = useMemo(() => {
    const options = dcQuery.data?.idx_type_options || [];
    const data = [{ value: "", label: "全部类型" }, ...options.map((type) => ({ value: type, label: type }))];
    if (dcIdxType && !options.includes(dcIdxType)) {
      data.push({ value: dcIdxType, label: dcIdxType });
    }
    return data;
  }, [dcQuery.data?.idx_type_options, dcIdxType]);
  const equityDrawerDcBoards = useMemo(
    () => (equityBoardDrawer?.boards || []).filter((board) => board.provider === "dc"),
    [equityBoardDrawer?.boards],
  );
  const equityDrawerThsBoards = useMemo(
    () => (equityBoardDrawer?.boards || []).filter((board) => board.provider === "ths"),
    [equityBoardDrawer?.boards],
  );

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
              <Select
                label="类型"
                data={THS_TYPE_OPTIONS}
                value={thsType}
                onChange={(value) => {
                  void navigate({
                    to: "/ops/v21/review/board",
                    search: {
                      ...((search as Record<string, unknown>) || {}),
                      tab: "ths",
                      ths_type: value || "",
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
                value={thsKeywordInput}
                onChange={(event) => setThsKeywordInput(event.currentTarget.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    applyThsKeywordSearch();
                  }
                }}
                w={260}
              />
              <Button leftSection={<IconSearch size={14} />} onClick={applyThsKeywordSearch}>
                搜索
              </Button>
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
              <Select
                label="板块类型"
                data={dcTypeSelectData}
                value={dcIdxType}
                onChange={(value) => {
                  void navigate({
                    to: "/ops/v21/review/board",
                    search: {
                      ...((search as Record<string, unknown>) || {}),
                      tab: "dc",
                      dc_idx_type: value || "",
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
                value={dcKeywordInput}
                onChange={(event) => {
                  setDcKeywordInput(event.currentTarget.value);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    applyDcKeywordSearch();
                  }
                }}
                leftSection={<IconSearch size={14} />}
                w={240}
              />
              <Button leftSection={<IconSearch size={14} />} onClick={applyDcKeywordSearch}>
                搜索
              </Button>
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
              <Autocomplete
                label="股票关键词"
                placeholder="代码、名称首字母或中文名"
                value={equityKeywordInput}
                onChange={(value) => {
                  setEquityKeywordInput(value);
                }}
                onOptionSubmit={(value) => {
                  setEquityKeywordInput(value);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    applyEquityKeywordSearch();
                  }
                }}
                data={equitySuggestionOptions}
                limit={20}
                leftSection={<IconSearch size={14} />}
                rightSection={equitySuggestQuery.isFetching ? <Loader size={14} /> : undefined}
                w={240}
              />
              <Button leftSection={<IconSearch size={14} />} onClick={applyEquityKeywordSearch}>
                搜索
              </Button>
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
                    <Table.Td>{mapWithFallback(item.exchange, THS_EXCHANGE_LABELS)}</Table.Td>
                    <Table.Td>{mapWithFallback(item.board_type, THS_BOARD_TYPE_LABELS)}</Table.Td>
                    <Table.Td>{item.constituent_count}</Table.Td>
                    <Table.Td>{renderMemberCell({
                      members: item.members,
                      boardCode: item.board_code,
                      boardName: item.board_name,
                      sourceLabel: "同花顺",
                    })}</Table.Td>
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
                      <Table.Td>{renderMemberCell({
                        members: item.members,
                        boardCode: item.board_code,
                        boardName: item.board_name,
                        sourceLabel: "东方财富",
                      })}</Table.Td>
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
                        {renderEquityBoardCell({
                          boards: item.boards,
                          tsCode: item.ts_code,
                          equityName: item.equity_name,
                          providerFilter: equityProvider,
                        })}
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
      <Drawer
        opened={memberDrawer !== null}
        onClose={closeMemberDrawer}
        title={memberDrawer?.title || "成分股明细"}
        position="right"
        size="70%"
      >
        <Stack gap="sm">
          <Text size="sm" c="dimmed">共 {drawerMembers.length} 只股票</Text>
          <Paper withBorder radius="md" p="sm">
            <Table striped highlightOnHover withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>代码</Table.Th>
                  <Table.Th>中文名称</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {drawerPageMembers.map((member, index) => (
                  <Table.Tr key={`${member.ts_code}-${index}`}>
                    <Table.Td>{member.ts_code}</Table.Td>
                    <Table.Td>{member.name || "—"}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Paper>
          <Group justify="space-between">
            <Button
              size="xs"
              variant="light"
              disabled={drawerCurrentPage <= 1}
              onClick={() => setMemberDrawerPage((prev) => Math.max(1, prev - 1))}
            >
              上一页
            </Button>
            <Text size="sm" c="dimmed">{drawerCurrentPage}/{drawerPageCount}</Text>
            <Button
              size="xs"
              variant="light"
              disabled={drawerCurrentPage >= drawerPageCount}
              onClick={() => setMemberDrawerPage((prev) => Math.min(drawerPageCount, prev + 1))}
            >
              下一页
            </Button>
          </Group>
        </Stack>
      </Drawer>
      <Drawer
        opened={equityBoardDrawer !== null}
        onClose={closeEquityBoardDrawer}
        title={equityBoardDrawer?.title || "所属板块明细"}
        position="right"
        size="70%"
      >
        <Stack gap="md">
          <Text size="sm" c="dimmed">共 {(equityBoardDrawer?.boards || []).length} 个板块</Text>
          {equityBoardDrawer?.provider === "all" ? (
            <>
              <Group align="flex-start" wrap="nowrap">
                <Text size="sm" fw={500} miw={84}>
                  东方财富
                </Text>
                <Group gap={6} wrap="wrap">
                  {equityDrawerDcBoards.length > 0 ? (
                    equityDrawerDcBoards.map((board) => (
                      <Badge key={`drawer-dc-${board.board_code}`} size="sm" variant="light" color={badgeColor("dc")}>
                        {board.board_name || board.board_code}
                      </Badge>
                    ))
                  ) : (
                    <Text size="sm" c="dimmed">—</Text>
                  )}
                </Group>
              </Group>
              <Group align="flex-start" wrap="nowrap">
                <Text size="sm" fw={500} miw={84}>
                  同花顺
                </Text>
                <Group gap={6} wrap="wrap">
                  {equityDrawerThsBoards.length > 0 ? (
                    equityDrawerThsBoards.map((board) => (
                      <Badge key={`drawer-ths-${board.board_code}`} size="sm" variant="light" color={badgeColor("ths")}>
                        {board.board_name || board.board_code}
                      </Badge>
                    ))
                  ) : (
                    <Text size="sm" c="dimmed">—</Text>
                  )}
                </Group>
              </Group>
            </>
          ) : (
            <Group gap={6} wrap="wrap">
              {(equityBoardDrawer?.boards || []).map((board) => (
                <Badge
                  key={`drawer-${board.provider}-${board.board_code}`}
                  size="sm"
                  variant="light"
                  color={badgeColor(board.provider)}
                >
                  {board.board_name || board.board_code}
                </Badge>
              ))}
            </Group>
          )}
        </Stack>
      </Drawer>
    </Stack>
  );
}
