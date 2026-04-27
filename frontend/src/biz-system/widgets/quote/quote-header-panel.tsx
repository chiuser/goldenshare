import { Group, Paper, Stack, Text } from "@mantine/core";

import type { QuoteInstrumentVM, QuoteSummaryVM } from "../../entities/quote/quote-view-model";
import { ChangeText } from "../../../shared/ui/change-text";
import { PriceText } from "../../../shared/ui/price-text";

interface QuoteHeaderPanelProps {
  instrument: QuoteInstrumentVM;
  summary: QuoteSummaryVM;
}

export function QuoteHeaderPanel({ instrument, summary }: QuoteHeaderPanelProps) {
  return (
    <Paper withBorder radius="md" p="md">
      <Stack gap="xs">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Text fw={700} size="lg">
              {instrument.name}
            </Text>
            <Text size="sm" c="dimmed">
              {instrument.tsCode} · {instrument.market}
            </Text>
          </Stack>
          <Stack gap={2} align="flex-end">
            <Text size="xs" c="dimmed">
              最近交易日
            </Text>
            <Text size="sm">{summary.tradeDate ?? "—"}</Text>
          </Stack>
        </Group>
        <Group gap="md" align="flex-end">
          <PriceText value={summary.latestPrice} fw={800} size="2rem" />
          <ChangeText value={summary.changeAmount} fw={700} />
          <ChangeText value={summary.pctChg} suffix="%" fw={700} />
        </Group>
      </Stack>
    </Paper>
  );
}
