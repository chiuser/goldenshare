import { useCallback, useEffect, useMemo, useState } from "react";

import { DAILY_CHART_PAGE_SIZE, SSE_DAILY_PREFETCH_REMAINING } from "../../../shared/charts/dailyChartRequestLimits";
import type { DetailChartHistoryViewport } from "../../../shared/charts/detail-workspace/detailChartTypes";
import type { TrendChannelPoint } from "../../../shared/charts/trend-channel/trendChannelGeometry";
import { fetchStockNineTurnSeries } from "../../nine-turn/api/nineTurnApiClient";
import type { NineTurnMarkerDto } from "../../nine-turn/api/nineTurnApiTypes";
import { adaptNineTurnSeries } from "../../nine-turn/model/nineTurnAdapter";
import { fetchStockDetailKline } from "../api/stockDetailApiClient";
import { toCandlePoint } from "../api/stockDetailViewModelAdapter";
import type { StockCandlePoint } from "../model/stockDetailTypes";
import { fetchStockTrendChannel } from "../trend-channel/api/stockTrendChannelApiClient";
import { buildStockTrendChannelViewModel } from "../trend-channel/api/stockTrendChannelViewModelAdapter";

export interface StockDailyHistorySeed {
  tsCode: string;
  tradeDate: string;
  candles: StockCandlePoint[];
  nextEndDate: string;
  supportsNineTurn: boolean;
  debug?: 1;
}

type LayerName = "nineTurn" | "trend";
type Layer<T> = { phase: "loading" | "error" } | { phase: "ready"; points: readonly T[] };
interface HistoryPage {
  startDate: string;
  endDate: string;
  dates: ReadonlySet<string>;
  nineTurn?: Layer<NineTurnMarkerDto>;
  trend?: Layer<TrendChannelPoint>;
}
interface HistorySession {
  seed: StockDailyHistorySeed;
  candles: StockCandlePoint[];
  nextEndDate: string | null;
  pages: HistoryPage[];
  phase: "idle" | "loading" | "error";
  failedGesture?: symbol;
  signal?: AbortSignal;
  trendSelected: boolean;
}

export function useStockDailyHistory(seed: StockDailyHistorySeed | null, active: boolean) {
  const session = useMemo<HistorySession | null>(() => seed && active ? {
    seed, candles: seed.candles, nextEndDate: seed.nextEndDate, pages: [], phase: "idle", trendSelected: false,
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

  const loadLayer = useCallback(async (owner: HistorySession, page: HistoryPage, name: LayerName) => {
    const signal = owner.signal;
    const { tsCode } = owner.seed;
    const state = page[name];
    if (!signal || signal.aborted || state?.phase === "loading" || state?.phase === "ready") return;
    page[name] = { phase: "loading" };
    publish(owner);
    try {
      if (name === "nineTurn") {
        const response = await fetchStockNineTurnSeries({
          tsCode, period: "day", startDate: page.startDate, endDate: page.endDate, limit: DAILY_CHART_PAGE_SIZE,
        }, { signal });
        if (signal.aborted) return;
        const layer = adaptNineTurnSeries(response, { tsCode, period: "day", subjectType: "stock" });
        page.nineTurn = { phase: "ready", points: layer.markers.filter(marker => page.dates.has(marker.tradeDate)) };
      } else {
        const response = await fetchStockTrendChannel({ tsCode, endDate: page.endDate, limit: page.dates.size }, { signal });
        if (signal.aborted) return;
        const trend = buildStockTrendChannelViewModel(response);
        page.trend = { phase: "ready", points: trend.points.filter(point => page.dates.has(point.time)) };
      }
    } catch {
      if (signal.aborted) return;
      page[name] = { phase: "error" };
    }
    publish(owner);
  }, [publish]);

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
      const { bars, meta } = payload;
      const first = bars[0];
      const last = bars.at(-1);
      const next = meta.nextEndDate;
      if (payload.stockRef.tsCode !== seed.tsCode || meta.endDate !== endDate ||
          (last && (last.tradeDate > endDate || last.tradeDate >= owner.candles[0]!.fullDate)) ||
          bars.some((bar, index) => index > 0 && bar.tradeDate <= bars[index - 1]!.tradeDate) ||
          (next !== null && (typeof next !== "string" || !first || next >= first.tradeDate))) {
        throw new Error("股票日线分页信息与请求不一致");
      }
      owner.nextEndDate = next;
      owner.phase = "idle";
      if (first && last) {
        const page: HistoryPage = {
          startDate: first.tradeDate, endDate: last.tradeDate,
          dates: new Set(bars.map(bar => bar.tradeDate)),
        };
        owner.candles = [...bars.map(toCandlePoint), ...owner.candles];
        owner.pages.unshift(page);
        if (seed.supportsNineTurn) void loadLayer(owner, page, "nineTurn");
        if (owner.trendSelected) void loadLayer(owner, page, "trend");
      }
    } catch {
      if (signal.aborted) return;
      owner.phase = "error";
      owner.failedGesture = gesture;
    }
    publish(owner);
  }, [loadLayer, publish]);

  const onViewport = useCallback((viewport: DetailChartHistoryViewport) => {
    if (!session || viewport.firstDate !== session.candles[0]?.fullDate ||
        viewport.direction !== "history" || viewport.remaining > SSE_DAILY_PREFETCH_REMAINING) return;
    if (session.phase === "error" &&
        (!viewport.beyondLeft || !viewport.gesture || viewport.gesture === session.failedGesture)) return;
    void loadPage(session, viewport.gesture);
  }, [loadPage, session]);

  const ensureTrend = useCallback(() => {
    if (!session || session.trendSelected) return;
    session.trendSelected = true;
    for (const page of session.pages) void loadLayer(session, page, "trend");
  }, [loadLayer, session]);

  const retryLayer = useCallback((page: HistoryPage, name: LayerName) => {
    if (session?.pages.includes(page)) void loadLayer(session, page, name);
  }, [loadLayer, session]);
  const current = state?.owner === session ? state : null;
  return {
    active: session !== null,
    visible: current,
    onViewport,
    ensureTrend,
    retryLayer,
  };
}

export type StockDailyHistory = ReturnType<typeof useStockDailyHistory>;
