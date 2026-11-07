import { useCallback, useEffect, useMemo, useState } from "react";

import { DAILY_CHART_PAGE_SIZE, SSE_DAILY_PREFETCH_REMAINING } from "../../../shared/charts/dailyChartRequestLimits";
import type { DetailChartHistoryViewport } from "../../../shared/charts/detail-workspace/detailChartTypes";
import { adaptNineTurnSeries } from "../../nine-turn/model/nineTurnAdapter";
import type { NineTurnMarkerDto } from "../../nine-turn/api/nineTurnApiTypes";
import type { IndexDetailKlineResponseDto } from "../api/indexDetailApiTypes";
import { fetchIndexDetailKline, IndexDetailApiError } from "../api/indexDetailApiClient";
import { loadIndexNineTurnSeries } from "../api/indexNineTurnLoader";
import { toCandlePoint } from "../api/indexDetailViewModelAdapter";
import { buildTrendChannelViewModel } from "../api/trendChannelAdapter";
import { fetchTrendChannel } from "../api/trendChannelApiClient";
import type { IndexCandlePoint, IndexDetailViewModel, TrendChannelPoint } from "../model/indexDetailTypes";

const SSE_CODE = "000001.SH";

export interface IndexDailyHistorySeed {
  nextEndDate: string | null;
  viewModel: IndexDetailViewModel;
  debug?: 1;
}

type LayerName = "nineTurn" | "trend";
type LayerResult<T> = { phase: "loading" } | { phase: "ready"; data: T[] } | { phase: "error" };
interface Layer<T> {
  result?: LayerResult<T>;
  displayed?: LayerResult<T>;
}
interface HistoryPage {
  startDate: string;
  endDate: string;
  candles: IndexCandlePoint[];
  nearDate: string;
  nineTurn: Layer<NineTurnMarkerDto>;
  trend: Layer<TrendChannelPoint>;
}
interface HistorySession {
  seed: IndexDailyHistorySeed;
  pages: HistoryPage[];
  shown: number;
  candles: IndexCandlePoint[];
  signal: AbortSignal | null;
  nextEndDate: string | null;
  viewport: DetailChartHistoryViewport | null;
  phase: "idle" | "loading" | "error";
  failedGesture?: symbol;
  error?: string;
}
interface VisibleHistory {
  candles: IndexCandlePoint[];
  nineTurnMarkers: NineTurnMarkerDto[];
  trendPoints: TrendChannelPoint[];
  failedLayers: { page: HistoryPage; layer: LayerName }[];
}

export function readSseDailyCursor(response: IndexDetailKlineResponseDto, endDate: string): string | null {
  const { meta, bars } = response;
  const first = bars[0]?.tradeDate;
  const last = bars.at(-1)?.tradeDate;
  if (response.indexRef.tsCode !== SSE_CODE || response.period !== "day" ||
      meta.endDate !== endDate || meta.limit !== DAILY_CHART_PAGE_SIZE ||
      meta.count !== bars.length || bars.length > DAILY_CHART_PAGE_SIZE ||
      (last !== undefined && last > endDate) || !("nextEndDate" in meta) ||
      (meta.nextEndDate !== null && (typeof meta.nextEndDate !== "string" ||
        first === undefined || meta.nextEndDate >= first))) {
    throw new Error("上证日线分页信息与请求不一致");
  }
  return bars.length < DAILY_CHART_PAGE_SIZE ? null : meta.nextEndDate;
}

export function useIndexDailyHistory(seed: IndexDailyHistorySeed | null, active: boolean) {
  const session = useMemo<HistorySession | null>(() => seed && active ? {
    seed, pages: [], shown: 0, candles: seed.viewModel.chart.candles, signal: null,
    nextEndDate: seed.nextEndDate, viewport: null, phase: "idle",
  } : null, [seed, active]);
  const [state, setState] = useState<{
    session: HistorySession;
    visible: VisibleHistory | null;
    phase: HistorySession["phase"];
    error?: string;
  } | null>(null);

  useEffect(() => {
    setState(current => current?.session === session ? current : null);
    if (!session) return;
    const controller = new AbortController();
    session.signal = controller.signal;
    return () => controller.abort();
  }, [session]);

  const publish = useCallback((owner: HistorySession) => {
    const nearDate = owner.viewport?.leftDate;
    let changed = false;
    if (nearDate && owner.viewport?.direction !== "recent") {
      while (owner.shown < owner.pages.length && nearDate <= owner.pages[owner.shown]!.nearDate) {
        const page = owner.pages[owner.shown++]!;
        owner.candles = [...page.candles, ...owner.candles];
        changed = true;
      }
      for (const page of owner.pages.slice(0, owner.shown)) {
        if (nearDate > page.nearDate) continue;
        if (page.nineTurn.displayed !== page.nineTurn.result || page.trend.displayed !== page.trend.result) {
          page.nineTurn.displayed = page.nineTurn.result;
          page.trend.displayed = page.trend.result;
          changed = true;
        }
      }
    }
    const visible = changed ? visibleHistory(owner) : undefined;
    setState(current => {
      if (!visible && current?.session === owner && current.phase === owner.phase && current.error === owner.error) {
        return current;
      }
      return {
        session: owner,
        visible: visible ?? (current?.session === owner ? current.visible : null),
        phase: owner.phase,
        error: owner.error,
      };
    });
  }, []);

  const loadLayer = useCallback(async (owner: HistorySession, page: HistoryPage, name: LayerName, retry = false) => {
    const signal = owner.signal;
    const layer = page[name];
    if (!signal || signal.aborted || (retry ? layer.result?.phase !== "error" : layer.result !== undefined)) return;
    layer.result = { phase: "loading" };
    publish(owner);
    const { startDate, endDate } = page;
    try {
      if (name === "nineTurn") {
        const response = await loadIndexNineTurnSeries(
          { subjectType: "index", tsCode: SSE_CODE, period: "day", startDate, endDate, limit: DAILY_CHART_PAGE_SIZE },
          { signal },
        );
        if (signal.aborted) return;
        if (response.meta.startDate !== startDate || response.meta.endDate !== endDate) {
          throw new Error("九转日期与当前历史页不一致");
        }
        const result = adaptNineTurnSeries(response, { period: "day", subjectType: "index", tsCode: SSE_CODE });
        page.nineTurn.result = { phase: "ready", data: result.markers.filter(marker =>
          marker.tradeDate >= startDate && marker.tradeDate <= endDate) };
      } else {
        const response = await fetchTrendChannel({ startDate, endDate, limit: DAILY_CHART_PAGE_SIZE }, { signal });
        if (signal.aborted) return;
        if (response.instrument.ts_code !== SSE_CODE || response.period !== "day" ||
            (response.meta.start_date !== null && response.meta.start_date < startDate) ||
            (response.meta.end_date !== null && response.meta.end_date > endDate)) {
          throw new Error("趋势通道日期或指数与当前历史页不一致");
        }
        const result = buildTrendChannelViewModel(response);
        page.trend.result = { phase: "ready", data: result.points.filter(point => point.time >= startDate && point.time <= endDate) };
      }
    } catch {
      if (signal.aborted) return;
      layer.result = { phase: "error" };
    }
    publish(owner);
  }, [publish]);

  const loadPage = useCallback(async (owner: HistorySession) => {
    const { nextEndDate: endDate, signal } = owner;
    if (!endDate || !signal || signal.aborted || owner.phase === "loading") return;
    owner.phase = "loading";
    owner.error = undefined;
    publish(owner);
    try {
      const response = await fetchIndexDetailKline(
        { tsCode: SSE_CODE, period: "day", endDate, limit: DAILY_CHART_PAGE_SIZE, debug: owner.seed.debug },
        { signal },
      );
      if (signal.aborted) return;
      const nextEndDate = readSseDailyCursor(response, endDate);
      const last = response.bars.at(-1);
      if (last && last.tradeDate >= owner.candles[0]!.time) {
        throw new Error("上证续页与已加载的K线日期重叠");
      }
      const page: HistoryPage | null = last ? {
        startDate: response.bars[0]!.tradeDate,
        endDate: last.tradeDate,
        candles: response.bars.map(toCandlePoint),
        nearDate: owner.candles[Math.min(SSE_DAILY_PREFETCH_REMAINING, owner.candles.length) - 1]!.time,
        nineTurn: {},
        trend: {},
      } : null;
      owner.nextEndDate = nextEndDate;
      owner.phase = "idle";
      if (page) owner.pages.push(page);
      publish(owner);
      if (page) {
        const { capabilities } = owner.seed.viewModel;
        if (capabilities.supportsNineTurn && capabilities.nineTurnPeriods.includes("day")) {
          void loadLayer(owner, page, "nineTurn");
        }
        if (capabilities.supportsTrendChannel) void loadLayer(owner, page, "trend");
      }
    } catch (error) {
      if (signal.aborted) return;
      owner.phase = "error";
      owner.failedGesture = owner.viewport?.gesture;
      owner.error = error instanceof IndexDetailApiError ? error.message : undefined;
      publish(owner);
    }
  }, [loadLayer, publish]);

  const onViewport = useCallback((viewport: DetailChartHistoryViewport) => {
    if (!session?.signal || session.signal.aborted || viewport.firstDate !== session.candles[0]?.time) return;
    session.viewport = viewport.direction === "stationary" && session.viewport
      ? { ...viewport, direction: session.viewport.direction, gesture: session.viewport.gesture }
      : viewport;
    if (viewport.direction !== "history") return;
    const before = session.shown;
    // A response received while looking at newer dates stays in the cache until
    // a real drag reaches that page's prefetch range.
    if (session.pages.some(page => viewport.leftDate <= page.nearDate && (
      page.nineTurn.displayed !== page.nineTurn.result || page.trend.displayed !== page.trend.result
    )) || session.shown < session.pages.length) {
      publish(session);
    }
    if (before !== session.shown || session.shown < session.pages.length ||
        viewport.remaining > SSE_DAILY_PREFETCH_REMAINING) return;
    if (session.phase === "error" &&
        (!viewport.beyondLeft || !viewport.gesture || viewport.gesture === session.failedGesture)) return;
    void loadPage(session);
  }, [loadPage, publish, session]);

  const retryLayer = useCallback((page: HistoryPage, layer: LayerName) => {
    if (session?.pages.includes(page)) void loadLayer(session, page, layer, true);
  }, [loadLayer, session]);

  const current = state?.session === session ? state : null;
  return { active: session !== null, visible: current?.visible ?? null, phase: current?.phase ?? "idle",
    error: current?.error, onViewport, retryLayer };
}

export type IndexDailyHistory = ReturnType<typeof useIndexDailyHistory>;

function visibleHistory(owner: HistorySession): VisibleHistory {
  const pages = owner.pages.slice(0, owner.shown).reverse();
  return {
    candles: owner.candles,
    nineTurnMarkers: pages.flatMap(page => page.nineTurn.displayed?.phase === "ready" ? page.nineTurn.displayed.data : []),
    trendPoints: pages.flatMap(page => page.trend.displayed?.phase === "ready" ? page.trend.displayed.data : []),
    failedLayers: pages.flatMap(page => (["nineTurn", "trend"] as const)
      .filter(layer => page[layer].displayed?.phase === "error").map(layer => ({ page, layer }))),
  };
}
