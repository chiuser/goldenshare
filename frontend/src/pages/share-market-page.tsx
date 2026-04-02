import { Alert, Grid, Loader, Stack, Table, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "../shared/api/client";
import type { ShareMarketOverviewResponse } from "../shared/api/types";
import { formatDateLabel } from "../shared/date-format";
import { OpsTable, OpsTableCell, OpsTableCellText, OpsTableHeaderCell } from "../shared/ui/ops-table";
import { SectionCard } from "../shared/ui/section-card";
import { StatCard } from "../shared/ui/stat-card";


function formatDecimal(value: string | null, digits = 2) {
  if (!value) return "—";
  const parsed = Number(value);
  if (Number.isNaN(parsed)) return value;
  return parsed.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function formatAmount(value: string | null) {
  if (!value) return "—";
  const parsed = Number(value);
  if (Number.isNaN(parsed)) return value;
  if (Math.abs(parsed) >= 1e8) {
    return `${(parsed / 1e8).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} 亿`;
  }
  return parsed.toLocaleString("zh-CN", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

function renderSnapshotTable(
  title: string,
  description: string,
  items: ShareMarketOverviewResponse["top_by_amount"],
) {
  return (
    <SectionCard title={title} description={description}>
      <OpsTable>
        <Table.Thead>
          <Table.Tr>
            <OpsTableHeaderCell align="left" width="20%">代码</OpsTableHeaderCell>
            <OpsTableHeaderCell align="left" width="24%">名称</OpsTableHeaderCell>
            <OpsTableHeaderCell align="left" width="18%">业务日期</OpsTableHeaderCell>
            <OpsTableHeaderCell width="12%">收盘价</OpsTableHeaderCell>
            <OpsTableHeaderCell width="12%">涨跌幅</OpsTableHeaderCell>
            <OpsTableHeaderCell width="14%">成交额</OpsTableHeaderCell>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {items.map((item) => (
            <Table.Tr key={`${item.ts_code}-${item.trade_date || "na"}`}>
              <OpsTableCell align="left" width="20%">
                <OpsTableCellText ff="IBM Plex Mono, SFMono-Regular, monospace" fw={500} size="xs">{item.ts_code}</OpsTableCellText>
              </OpsTableCell>
              <OpsTableCell align="left" width="24%">
                <OpsTableCellText fw={600} size="sm">{item.name || "—"}</OpsTableCellText>
              </OpsTableCell>
              <OpsTableCell align="left" width="18%">
                <OpsTableCellText ff="IBM Plex Mono, SFMono-Regular, monospace" fw={500} size="xs">{formatDateLabel(item.trade_date)}</OpsTableCellText>
              </OpsTableCell>
              <OpsTableCell width="12%">
                <OpsTableCellText size="xs">{formatDecimal(item.close, 2)}</OpsTableCellText>
              </OpsTableCell>
              <OpsTableCell width="12%">
                <OpsTableCellText size="xs" c={(item.pct_change && Number(item.pct_change) > 0) ? "var(--gs-teal)" : (item.pct_change && Number(item.pct_change) < 0) ? "var(--gs-magenta)" : undefined}>
                  {item.pct_change ? `${formatDecimal(item.pct_change, 2)}%` : "—"}
                </OpsTableCellText>
              </OpsTableCell>
              <OpsTableCell width="14%">
                <OpsTableCellText size="xs">{formatAmount(item.amount)}</OpsTableCellText>
              </OpsTableCell>
            </Table.Tr>
          ))}
          {!items.length ? (
            <Table.Tr>
              <Table.Td colSpan={6}>
                <Text c="dimmed" size="sm">暂无可展示的数据。</Text>
              </Table.Td>
            </Table.Tr>
          ) : null}
        </Table.Tbody>
      </OpsTable>
    </SectionCard>
  );
}

export function ShareMarketPage() {
  const overviewQuery = useQuery({
    queryKey: ["share", "market-overview"],
    queryFn: () => apiRequest<ShareMarketOverviewResponse>("/api/v1/share/market-overview?limit=10"),
    refetchInterval: 15000,
  });

  const overview = overviewQuery.data;

  return (
    <Stack gap="lg">
      <Text c="dimmed" size="sm">
        这个页面直接读取数据集市 `dm.equity_daily_snapshot`，用于验证汇总层是否已经产出最新行情快照。
      </Text>

      {overviewQuery.isLoading ? <Loader size="sm" /> : null}
      {overviewQuery.error ? (
        <Alert color="red" title="无法读取市场快照">
          {overviewQuery.error instanceof Error ? overviewQuery.error.message : "未知错误"}
        </Alert>
      ) : null}

      {(overview && !overview.available) ? (
        <Alert color="yellow" title="数据集市暂不可用">
          {overview.unavailable_reason || "暂时无法读取 dm.equity_daily_snapshot。"}
        </Alert>
      ) : null}

      {(overview && overview.available && overview.summary) ? (
        <>
          <SectionCard
            title="市场总览"
            description="如果这里日期是最新的，说明数据集市已经完成刷新，后续行情页面可以直接复用。"
          >
            <Grid>
              <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
                <StatCard label="快照日期" value={formatDateLabel(overview.summary.as_of_date)} />
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
                <StatCard label="股票数量" value={overview.summary.total_symbols} />
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
                <StatCard label="上涨家数" value={overview.summary.up_count ?? "—"} />
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
                <StatCard label="下跌家数" value={overview.summary.down_count ?? "—"} />
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
                <StatCard label="平均涨跌幅" value={overview.summary.avg_pct_change ? `${formatDecimal(overview.summary.avg_pct_change, 2)}%` : "—"} />
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6, xl: 2 }}>
                <StatCard label="总成交额" value={formatAmount(overview.summary.total_amount)} />
              </Grid.Col>
            </Grid>
          </SectionCard>

          {renderSnapshotTable("成交额前十", "用于快速确认资金集中在哪些标的。", overview.top_by_amount)}
          {renderSnapshotTable("涨幅前十", "用于快速验证涨跌幅排序字段是否正常。", overview.top_gainers)}
          {renderSnapshotTable("跌幅前十", "用于快速验证负向波动与排序是否正常。", overview.top_losers)}
        </>
      ) : null}
    </Stack>
  );
}
