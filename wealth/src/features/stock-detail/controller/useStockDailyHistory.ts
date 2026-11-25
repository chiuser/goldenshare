import { useCallback, useEffect, useMemo, useState } from "react";

import { DAILY_CHART_PAGE_SIZE, SSE_DAILY_PREFETCH_REMAINING } from "../../../shared/charts/dailyChartRequestLimits";
import type { DetailChartHistoryViewport } from "../../../shared/charts/detail-workspace/detailChartTypes";
import type { TrendChannelPoint } from "../../../shared/charts/trend-channel/trendChannelGeometry";
import type { NineTurnMarkerDto } from "../../nine-turn/api/nineTurnApiTypes";
import { fetchStockDetailKline } from "../api/stockDetailApiClient";
import { buildStockDailyTrendChannelPoints, toCandlePoint } from "../api/stockDetailViewModelAdapter";
import type { StockCandlePoint } from "../model/stockDetailTypes";

export interface StockDailyHistorySeed {
  tsCode: string;
  tradeDate: string;
  candles: StockCandlePoint[];
  nextEndDate: string;
  debug?: 1;
}

interface HistoryPage {
  endDate: string;
  dates: ReadonlySet<string>;
  nineTurnMarkers: readonly NineTurnMarkerDto[];
  trendPoints: readonly TrendChannelPoint[];
}
interface HistorySession {
  seed: StockDailyHistorySeed;
  candles: StockCandlePoint[];
  nextEndDate: string | null;
  pages: HistoryPage[];
  phase: "idle" | "loading" | "error";
  failedGesture?: symbol;
  signal?: AbortSignal;
}

export function useStockDailyHistory(seed: StockDailyHistorySeed | null, active: boolean) {
  const session = useMemo<HistorySession | null>(() => seed && active ? {
    seed, candles: seed.candles, nextEndDate: seed.nextEndDate, pages: [], phase: "idle",
  } : null, [seed, active]);
  const [state, setState] = useState<{
    owner: HistorySession;
    candles: StockCandlePoint[];
    pages: HistoryPage[];
    phase: HistorySession["phase"];
  } | null>(null);

  useEffect(() => {
    setState(current => current?.owner === session ? current : null);
    if (!session) return;
    const controller = new AbortController();
    session.signal = controller.signal;
    return () => controller.abort();
  }, [session]);

  const publish = useCallback((owner: HistorySession) => {
    setState({ owner, candles: owner.candles, pages: [...owner.pages], phase: owner.phase });
  }, []);

  const loadPage = useCallback(async (owner: HistorySession, gesture?: symbol) => {
    const { signal, nextEndDate: endDate, seed } = owner;
    if (!signal || signal.aborted || !endDate || owner.phase === "loading") return;
    owner.phase = "loading";
    publish(owner);
    try {
      const payload = await fetchStockDetailKline({
        tsCode: seed.tsCode, period: "day", adjustment: "forward", tradeDate: seed.tradeDate,
        endDate, limit: DAILY_CHART_PAGE_SIZE, debug: seed.debug,
      }, { signal });
      if (signal.aborted) return;
      const { bars, meta, nineTurnMarkers } = payload;
      const first = bars[0];
      const last = bars.at(-1);
      const next = meta.nextEndDate;
      if (!Array.isArray(nineTurnMarkers) || payload.stockRef.tsCode !== seed.tsCode || meta.endDate !== endDate ||
          (last && (last.tradeDate > endDate || last.tradeDate >= owner.candles[0]!.fullDate)) ||
          bars.some((bar, index) => index > 0 && bar.tradeDate <= bars[index - 1]!.tradeDate) ||
          (next !== null && (typeof next !== "string" || !first || next >= first.tradeDate))) {
        throw new Error("股票日线分页信息与请求不一致");
      }
      const candles = bars.map(toCandlePoint);
      const trendPoints = buildStockDailyTrendChannelPoints(bars);
      const page: HistoryPage | null = first && last ? {
        endDate: last.tradeDate, dates: new Set(bars.map(bar => bar.tradeDate)), nineTurnMarkers, trendPoints,
      } : null;
      owner.nextEndDate = next;
      owner.phase = "idle";
      if (page) {
        owner.candles = [...candles, ...owner.candles];
        owner.pages.unshift(page);
      }
    } catch {
      if (signal.aborted) return;
      owner.phase = "error";
      owner.failedGesture = gesture;
    }
    publish(owner);
  }, [publish]);

  const onViewport = useCallback((viewport: DetailChartHistoryViewport) => {
    if (!session || viewport.firstDate !== session.candles[0]?.fullDate ||
        viewport.direction !== "history" || viewport.remaining > SSE_DAILY_PREFETCH_REMAINING) return;
    if (session.phase === "error" &&
        (!viewport.beyondLeft || !viewport.gesture || viewport.gesture === session.failedGesture)) return;
    void loadPage(session, viewport.gesture);
  }, [loadPage, session]);

  const current = state?.owner === session ? state : null;
  return {
    active: session !== null,
    visible: current,
    onViewport,
  };
}

export type StockDailyHistory = ReturnType<typeof useStockDailyHistory>;
