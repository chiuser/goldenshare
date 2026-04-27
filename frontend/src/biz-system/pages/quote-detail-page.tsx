import {
  Button,
  Container,
  Group,
  Select,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";

import { useQuoteKlineControls } from "../features/quote/use-quote-kline-controls";
import { useQuotePageQueries } from "../features/quote/use-quote-page-queries";
import { useQuotePageState } from "../features/quote/use-quote-page-state";
import { QuoteEmptyState } from "../shared/ui/state/quote-empty-state";
import { QuoteErrorState } from "../shared/ui/state/quote-error-state";
import { QuoteLoadingState } from "../shared/ui/state/quote-loading-state";
import { QuoteStaleBanner } from "../shared/ui/state/quote-stale-banner";
import { QuoteChartPanel } from "../widgets/quote/quote-chart-panel";
import { QuoteDetailLayout } from "../widgets/quote/quote-detail-layout";
import { QuoteHeaderPanel } from "../widgets/quote/quote-header-panel";
import { QuoteRelatedPanel } from "../widgets/quote/quote-related-panel";

const securityTypeOptions = [
  { value: "stock", label: "股票" },
  { value: "index", label: "指数" },
  { value: "etf", label: "ETF" },
] as const;

const periodLabelMap: Record<string, string> = {
  day: "日线",
  week: "周线",
  month: "月线",
};

const adjustmentLabelMap: Record<string, string> = {
  none: "不复权",
  forward: "前复权",
  backward: "后复权",
};

export function QuoteDetailPage() {
  const quoteState = useQuotePageState();
  const controls = useQuoteKlineControls(quoteState.state.securityType);
  const queries = useQuotePageQueries(quoteState.state);

  return (
    <Container size="xl" py="md">
      <Stack gap="md">
        <Stack gap={4}>
          <Title order={2}>行情详情（首批）</Title>
          <Text c="dimmed" size="sm">
            当前页面已接入 page-init / kline / related-info，并使用统一四态渲染。
          </Text>
        </Stack>

        <Group align="flex-end" wrap="wrap" gap="sm">
          <TextInput
            label="证券代码"
            value={quoteState.state.tsCode}
            onChange={(event) => quoteState.setTsCode(event.currentTarget.value)}
            w={180}
          />
          <Select
            label="标的类型"
            data={securityTypeOptions.map((item) => ({ value: item.value, label: item.label }))}
            value={quoteState.state.securityType}
            onChange={(value) => {
              if (value === "stock" || value === "index" || value === "etf") {
                quoteState.setSecurityType(value);
              }
            }}
            w={140}
          />
          <Select
            label="周期"
            data={controls.periods.map((value) => ({ value, label: periodLabelMap[value] ?? value }))}
            value={quoteState.state.period}
            onChange={(value) => {
              if (value === "day" || value === "week" || value === "month") {
                quoteState.setPeriod(value);
              }
            }}
            w={120}
          />
          <Select
            label="复权"
            data={controls.adjustments.map((value) => ({ value, label: adjustmentLabelMap[value] ?? value }))}
            value={quoteState.state.adjustment}
            onChange={(value) => {
              if (value === "none" || value === "forward" || value === "backward") {
                quoteState.setAdjustment(value);
              }
            }}
            w={140}
          />
          <Button variant="light" onClick={() => quoteState.reset()}>
            重置
          </Button>
        </Group>

        {queries.status.loading ? <QuoteLoadingState /> : null}
        {queries.status.error ? <QuoteErrorState error={queries.status.error} onRetry={queries.refetchAll} /> : null}
        {queries.status.empty ? <QuoteEmptyState onRetry={queries.refetchAll} /> : null}
        {queries.status.stale && queries.status.staleReason ? (
          <QuoteStaleBanner reason={queries.status.staleReason} />
        ) : null}

        {!queries.status.loading && !queries.status.error && !queries.status.empty && queries.viewModel ? (
          <QuoteDetailLayout
            header={<QuoteHeaderPanel instrument={queries.viewModel.instrument} summary={queries.viewModel.summary} />}
            chart={
              <QuoteChartPanel
                bars={queries.viewModel.chart.bars}
                periodLabel={periodLabelMap[queries.viewModel.chart.period] ?? queries.viewModel.chart.period}
                adjustmentLabel={adjustmentLabelMap[queries.viewModel.chart.adjustment] ?? queries.viewModel.chart.adjustment}
              />
            }
            related={<QuoteRelatedPanel items={queries.viewModel.related} />}
          />
        ) : null}
      </Stack>
    </Container>
  );
}
