import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import dayjs from "dayjs";

import {
  fetchQuoteKline,
  fetchQuotePageInit,
  fetchQuoteRelatedInfo,
} from "../../shared/api/quote-client";
import type { QuotePageState } from "./use-quote-page-state.types";
import { mapKlineBars } from "../../entities/quote/mappers/map-kline";
import { mapPageInitInstrument, mapPageInitSummary } from "../../entities/quote/mappers/map-page-init";
import { mapRelatedInfo } from "../../entities/quote/mappers/map-related-info";
import type { QuotePageViewModel } from "../../entities/quote/quote-view-model";

export interface QuoteQueryStatus {
  loading: boolean;
  empty: boolean;
  error: Error | null;
  stale: boolean;
  staleReason: string | null;
}

function buildStaleInfo(latestTradeDate: string | null): Pick<QuoteQueryStatus, "stale" | "staleReason"> {
  if (!latestTradeDate) {
    return {
      stale: true,
      staleReason: "当前暂无最近交易日数据，请检查同步状态。",
    };
  }
  const lagDays = dayjs().diff(dayjs(latestTradeDate), "day");
  if (lagDays <= 2) {
    return { stale: false, staleReason: null };
  }
  return {
    stale: true,
    staleReason: `当前行情数据可能滞后（最近交易日：${latestTradeDate}）。`,
  };
}

export function useQuotePageQueries(state: QuotePageState) {
  const pageInitQuery = useQuery({
    queryKey: ["biz-system", "quote", "page-init", state.tsCode, state.securityType],
    queryFn: () => fetchQuotePageInit(state.tsCode, state.securityType),
  });

  const klineQuery = useQuery({
    queryKey: ["biz-system", "quote", "kline", state.tsCode, state.securityType, state.period, state.adjustment],
    queryFn: () =>
      fetchQuoteKline({
        ts_code: state.tsCode,
        security_type: state.securityType,
        period: state.period,
        adjustment: state.adjustment,
      }),
  });

  const relatedInfoQuery = useQuery({
    queryKey: ["biz-system", "quote", "related-info", state.tsCode, state.securityType],
    queryFn: () => fetchQuoteRelatedInfo(state.tsCode, state.securityType),
    retry: false,
  });

  const viewModel = useMemo<QuotePageViewModel | null>(() => {
    if (!pageInitQuery.data || !klineQuery.data) {
      return null;
    }
    return {
      instrument: mapPageInitInstrument(pageInitQuery.data),
      summary: mapPageInitSummary(pageInitQuery.data),
      chart: {
        period: klineQuery.data.period,
        adjustment: klineQuery.data.adjustment,
        bars: mapKlineBars(klineQuery.data),
      },
      related: relatedInfoQuery.data ? mapRelatedInfo(relatedInfoQuery.data) : [],
    };
  }, [klineQuery.data, pageInitQuery.data, relatedInfoQuery.data]);

  const firstError =
    (pageInitQuery.error as Error | null) ||
    (klineQuery.error as Error | null) ||
    null;

  const loading =
    (pageInitQuery.isPending || klineQuery.isPending || relatedInfoQuery.isPending) &&
    !pageInitQuery.data;

  const empty = !loading && !firstError && Boolean(viewModel && viewModel.chart.bars.length === 0);

  const staleInfo = buildStaleInfo(viewModel?.summary.tradeDate ?? null);

  return {
    viewModel,
    status: {
      loading,
      empty,
      error: firstError,
      stale: staleInfo.stale,
      staleReason: staleInfo.staleReason,
    } as QuoteQueryStatus,
    refetchAll: async () => {
      await Promise.all([pageInitQuery.refetch(), klineQuery.refetch(), relatedInfoQuery.refetch()]);
    },
  };
}
