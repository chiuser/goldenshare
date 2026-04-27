import { Badge, Group, Paper, Stack, Table, Text } from "@mantine/core";

import type { QuoteBarVM } from "../../entities/quote/quote-view-model";

interface QuoteChartPanelProps {
  bars: QuoteBarVM[];
  periodLabel: string;
  adjustmentLabel: string;
}

export function QuoteChartPanel({ bars, periodLabel, adjustmentLabel }: QuoteChartPanelProps) {
  return (
    <Paper withBorder radius="md" p="md">
      <Stack gap="sm">
        <Group justify="space-between">
          <Text fw={700}>K线数据（首批表格占位）</Text>
          <Group gap="xs">
            <Badge variant="light">{periodLabel}</Badge>
            <Badge variant="light">{adjustmentLabel}</Badge>
          </Group>
        </Group>
        <Table striped highlightOnHover withColumnBorders stickyHeader stickyHeaderOffset={0}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>交易日</Table.Th>
              <Table.Th>开</Table.Th>
              <Table.Th>高</Table.Th>
              <Table.Th>低</Table.Th>
              <Table.Th>收</Table.Th>
              <Table.Th>成交量</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {bars.slice(0, 20).map((bar) => (
              <Table.Tr key={`${bar.tradeDate}-${bar.close}`}>
                <Table.Td>{bar.tradeDate}</Table.Td>
                <Table.Td>{bar.open.toFixed(2)}</Table.Td>
                <Table.Td>{bar.high.toFixed(2)}</Table.Td>
                <Table.Td>{bar.low.toFixed(2)}</Table.Td>
                <Table.Td>{bar.close.toFixed(2)}</Table.Td>
                <Table.Td>{bar.vol?.toLocaleString("zh-CN") ?? "—"}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Stack>
    </Paper>
  );
}
