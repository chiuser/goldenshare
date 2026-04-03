import {
  ActionIcon,
  Alert,
  Autocomplete,
  Badge,
  Box,
  Button,
  Checkbox,
  Collapse,
  Divider,
  Grid,
  Group,
  Loader,
  Menu,
  Modal,
  NumberInput,
  Paper,
  ScrollArea,
  SegmentedControl,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type LogicalRange,
  type Time,
} from "lightweight-charts";
import { IconChartCandle, IconChevronDown, IconChevronUp, IconPlus, IconSettings, IconTrash } from "@tabler/icons-react";
import { useDeferredValue, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

import { apiRequest } from "../shared/api/client";
import type {
  ShareKlineResponse,
  ShareNewsResponse,
  ShareQuoteResponse,
  ShareSecuritySuggestionsResponse,
} from "../shared/api/types";
import { formatDateLabel } from "../shared/date-format";


type Period = "d" | "w" | "m";

type CandlePoint = {
  tradeDate: string;
  time: Time;
  open: number;
  high: number;
  low: number;
  close: number;
  preClose: number | null;
  pctChg: number | null;
  volume: number;
  amount: number;
  turnoverRate: number | null;
};

type MAConfig = {
  id: string;
  period: number;
  enabled: boolean;
  width: number;
  color: string;
};

const DEFAULT_MA_CONFIGS: MAConfig[] = [
  { id: "ma1", period: 5, enabled: true, width: 1, color: "#f2f4f8" },
  { id: "ma2", period: 10, enabled: true, width: 1, color: "#f7c948" },
  { id: "ma3", period: 15, enabled: false, width: 1, color: "#ffcf40" },
  { id: "ma4", period: 20, enabled: true, width: 1, color: "#dc6bff" },
  { id: "ma5", period: 30, enabled: false, width: 1, color: "#2de46b" },
  { id: "ma6", period: 60, enabled: true, width: 1, color: "#ff4d4f" },
  { id: "ma7", period: 120, enabled: false, width: 1, color: "#21d4d2" },
  { id: "ma8", period: 250, enabled: false, width: 1, color: "#2f7bff" },
];

const MA_COLOR_SWATCHES = [
  "#f2f4f8",
  "#f7c948",
  "#ffcf40",
  "#dc6bff",
  "#2de46b",
  "#ff4d4f",
  "#21d4d2",
  "#2f7bff",
  "#ff2d55",
  "#5ad15a",
];

const TERMINAL_THEME = {
  background: "#090f1a",
  panel: "#0f1727",
  panelRaised: "#131e33",
  border: "#223654",
  text: "#dce7fb",
  textMuted: "#8fa6c7",
  up: "#ff4d4f",
  down: "#00c076",
  grid: "#1b2a42",
  accent: "#4c8bff",
  buttonBg: "#1b2a44",
  buttonHover: "#24375a",
  buttonActive: "#2a4270",
  buttonBorder: "#36547f",
  buttonText: "#d9e7ff",
  buttonSoftBg: "rgba(27,42,68,0.35)",
  buttonSoftHover: "rgba(36,55,90,0.55)",
};

const PRIMARY_BUTTON_STYLES = {
  root: {
    background: TERMINAL_THEME.buttonBg,
    border: `1px solid ${TERMINAL_THEME.buttonBorder}`,
    color: "#c6d8f6",
    fontWeight: 600,
    "&:hover": { background: TERMINAL_THEME.buttonHover },
    "&:active": { background: TERMINAL_THEME.buttonActive },
  },
  label: {
    color: "#c6d8f6",
  },
} as const;

const SOFT_BUTTON_STYLES = {
  root: {
    background: TERMINAL_THEME.buttonSoftBg,
    border: `1px solid ${TERMINAL_THEME.buttonBorder}`,
    color: "#bdd0f0",
    fontWeight: 600,
    "&:hover": { background: TERMINAL_THEME.buttonSoftHover },
  },
  label: {
    color: "#bdd0f0",
  },
} as const;

const TOOLBAR_ICON_STYLES = {
  root: {
    background: TERMINAL_THEME.buttonSoftBg,
    border: `1px solid ${TERMINAL_THEME.buttonBorder}`,
    color: "#b9cbed",
    "&:hover": { background: TERMINAL_THEME.buttonSoftHover },
  },
} as const;

const DEFAULT_VISIBLE_BARS: Record<Period, number> = {
  d: 65,
  w: 52,
  m: 60,
};

function toBusinessDay(value: string): Time {
  const [year, month, day] = value.split("-").map((item) => Number(item));
  return { year, month, day };
}

function toNumber(value: string | null | undefined) {
  if (value === null || value === undefined) return 0;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function computeMA(points: CandlePoint[], period: number) {
  const data: Array<{ time: Time; value: number }> = [];
  let rolling = 0;
  for (let i = 0; i < points.length; i += 1) {
    rolling += points[i].close;
    if (i >= period) {
      rolling -= points[i - period].close;
    }
    if (i >= period - 1) {
      data.push({ time: points[i].time, value: Number((rolling / period).toFixed(4)) });
    }
  }
  return data;
}

function computeMACD(points: CandlePoint[]) {
  let ema12 = 0;
  let ema26 = 0;
  let dea = 0;
  const alpha12 = 2 / 13;
  const alpha26 = 2 / 27;
  const alpha9 = 2 / 10;
  return points.map((point, index) => {
    if (index === 0) {
      ema12 = point.close;
      ema26 = point.close;
      dea = 0;
    } else {
      ema12 = alpha12 * point.close + (1 - alpha12) * ema12;
      ema26 = alpha26 * point.close + (1 - alpha26) * ema26;
    }
    const diff = ema12 - ema26;
    dea = alpha9 * diff + (1 - alpha9) * dea;
    const macd = (diff - dea) * 2;
    return {
      time: point.time,
      diff: Number(diff.toFixed(4)),
      dea: Number(dea.toFixed(4)),
      macd: Number(macd.toFixed(4)),
    };
  });
}

function computeKDJ(points: CandlePoint[]) {
  const result: Array<{ time: Time; k: number; d: number; j: number }> = [];
  let k = 50;
  let d = 50;
  const period = 9;
  for (let i = 0; i < points.length; i += 1) {
    const start = Math.max(0, i - period + 1);
    let highest = -Number.MAX_SAFE_INTEGER;
    let lowest = Number.MAX_SAFE_INTEGER;
    for (let cursor = start; cursor <= i; cursor += 1) {
      highest = Math.max(highest, points[cursor].high);
      lowest = Math.min(lowest, points[cursor].low);
    }
    const rsv = highest === lowest ? 50 : ((points[i].close - lowest) / (highest - lowest)) * 100;
    k = (2 / 3) * k + (1 / 3) * rsv;
    d = (2 / 3) * d + (1 / 3) * k;
    const j = 3 * k - 2 * d;
    result.push({
      time: points[i].time,
      k: Number(k.toFixed(4)),
      d: Number(d.toFixed(4)),
      j: Number(j.toFixed(4)),
    });
  }
  return result;
}

function formatCompact(value: string | number | null | undefined, digits = 2) {
  if (value === null || value === undefined) return "—";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return String(value);
  return parsed.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function formatPercent(value: string | number | null | undefined, digits = 2) {
  if (value === null || value === undefined) return "—";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "—";
  return `${parsed.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits })}%`;
}

function formatAmount(value: string | number | null | undefined) {
  if (value === null || value === undefined) return "—";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return String(value);
  if (Math.abs(parsed) >= 1e8) {
    return `${(parsed / 1e8).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}亿`;
  }
  if (Math.abs(parsed) >= 1e4) {
    return `${(parsed / 1e4).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}万`;
  }
  return parsed.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
}

function formatVolumeHuman(value: number) {
  if (!Number.isFinite(value)) return "—";
  if (Math.abs(value) >= 1e8) return `${(value / 1e8).toFixed(2)}亿`;
  if (Math.abs(value) >= 1e4) return `${(value / 1e4).toFixed(2)}万`;
  return value.toFixed(0);
}

function formatAmountHuman(value: number) {
  if (!Number.isFinite(value)) return "—";
  if (Math.abs(value) >= 1e8) return `${(value / 1e8).toFixed(2)}亿`;
  if (Math.abs(value) >= 1e4) return `${(value / 1e4).toFixed(2)}万`;
  return value.toFixed(0);
}

function syncVisibleRange(source: IChartApi, targets: IChartApi[]) {
  let syncing = false;
  source.timeScale().subscribeVisibleLogicalRangeChange((range: LogicalRange | null) => {
    if (syncing || range === null) return;
    syncing = true;
    for (const target of targets) {
      target.timeScale().setVisibleLogicalRange(range);
    }
    syncing = false;
  });
}

function parseTsCodeFromSearch(value: string) {
  const first = value.trim().split(/\s+/)[0];
  return (first || "").toUpperCase();
}

function cloneDefaultMaConfigs() {
  return DEFAULT_MA_CONFIGS.map((item) => ({ ...item }));
}

function toTimeKey(time: Time | undefined) {
  if (time === undefined) return "";
  if (typeof time === "number") return String(time);
  if (typeof time === "string") return time;
  return `${time.year}-${String(time.month).padStart(2, "0")}-${String(time.day).padStart(2, "0")}`;
}

type MetricSectionId = "intraday" | "activity" | "valuation";
type MetricTone = "up" | "down";
type MetricSection = {
  id: MetricSectionId;
  title: string;
  items: Array<{ label: string; value: string; tone?: MetricTone }>;
};

export function ShareTerminalPage() {
  const [searchValue, setSearchValue] = useState("");
  const deferredSearchValue = useDeferredValue(searchValue);
  const [tsCode, setTsCode] = useState("002245.SZ");
  const [period, setPeriod] = useState<Period>("d");
  const [maConfigs, setMaConfigs] = useState<MAConfig[]>(() => cloneDefaultMaConfigs());
  const [maDialogOpen, setMaDialogOpen] = useState(false);
  const [maDraft, setMaDraft] = useState<MAConfig[]>(() => cloneDefaultMaConfigs());
  const [newsExpanded, setNewsExpanded] = useState(false);
  const [focusActive, setFocusActive] = useState(false);
  const [focusIndex, setFocusIndex] = useState<number | null>(null);
  const [focusCrosshairPoint, setFocusCrosshairPoint] = useState<{ x: number; y: number } | null>(null);
  const [metricSectionOpen, setMetricSectionOpen] = useState<Record<MetricSectionId, boolean>>({
    intraday: true,
    activity: true,
    valuation: false,
  });

  const mainContainerRef = useRef<HTMLDivElement | null>(null);
  const macdContainerRef = useRef<HTMLDivElement | null>(null);
  const kdjContainerRef = useRef<HTMLDivElement | null>(null);

  const suggestionsQuery = useQuery({
    queryKey: ["share", "securities", deferredSearchValue],
    queryFn: () => apiRequest<ShareSecuritySuggestionsResponse>(`/api/v1/share/securities?query=${encodeURIComponent(deferredSearchValue)}&limit=12`),
    enabled: deferredSearchValue.trim().length >= 1,
    staleTime: 20000,
  });

  const klineQuery = useQuery({
    queryKey: ["share", "kline", tsCode, period],
    queryFn: () => apiRequest<ShareKlineResponse>(`/api/v1/share/kline?ts_code=${encodeURIComponent(tsCode)}&period=${period}&adjust_mode=qfq&limit=1800`),
  });

  const quoteQuery = useQuery({
    queryKey: ["share", "quote", tsCode],
    queryFn: () => apiRequest<ShareQuoteResponse>(`/api/v1/share/quote?ts_code=${encodeURIComponent(tsCode)}`),
    refetchInterval: 15000,
  });

  const newsQuery = useQuery({
    queryKey: ["share", "news", tsCode],
    queryFn: () => apiRequest<ShareNewsResponse>(`/api/v1/share/news?ts_code=${encodeURIComponent(tsCode)}&limit=30`),
    refetchInterval: 30000,
  });

  const suggestionOptions = useMemo(
    () =>
      (suggestionsQuery.data?.items || []).map((item) =>
        item.cnspell
          ? `${item.ts_code} ${item.name} ${item.cnspell}`
          : item.symbol
            ? `${item.ts_code} ${item.name} ${item.symbol}`
            : `${item.ts_code} ${item.name}`,
      ),
    [suggestionsQuery.data?.items],
  );

  useEffect(() => {
    setFocusActive(false);
    setFocusIndex(null);
    setFocusCrosshairPoint(null);
  }, [tsCode, period]);

  const points = useMemo<CandlePoint[]>(() => {
    return (klineQuery.data?.items || []).map((item) => ({
      tradeDate: item.trade_date,
      time: toBusinessDay(item.trade_date),
      open: toNumber(item.open),
      high: toNumber(item.high),
      low: toNumber(item.low),
      close: toNumber(item.close),
      preClose: item.pre_close == null ? null : toNumber(item.pre_close),
      pctChg: item.pct_chg == null ? null : toNumber(item.pct_chg),
      volume: toNumber(item.volume),
      amount: toNumber(item.amount),
      turnoverRate: item.turnover_rate == null ? null : toNumber(item.turnover_rate),
    }));
  }, [klineQuery.data?.items]);

  const closeFocusPanel = () => {
    setFocusActive(false);
    setFocusIndex(null);
    setFocusCrosshairPoint(null);
  };

  useEffect(() => {
    const mainContainer = mainContainerRef.current;
    const macdContainer = macdContainerRef.current;
    const kdjContainer = kdjContainerRef.current;
    if (!mainContainer || !macdContainer || !kdjContainer || !points.length) {
      return;
    }

    const commonOptions = {
      layout: {
        background: { type: ColorType.Solid, color: TERMINAL_THEME.background },
        textColor: TERMINAL_THEME.textMuted,
      },
      grid: {
        vertLines: { color: TERMINAL_THEME.grid },
        horzLines: { color: TERMINAL_THEME.grid },
      },
      rightPriceScale: {
        borderColor: TERMINAL_THEME.border,
        minimumWidth: 70,
      },
      timeScale: {
        borderColor: TERMINAL_THEME.border,
        rightOffset: 2,
        lockVisibleTimeRangeOnResize: true,
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: "#3d5a80", width: 1, style: 0 },
        horzLine: { color: "#3d5a80", width: 1, style: 0 },
      },
      localization: {
        dateFormat: "yyyy-MM-dd",
      },
    } as const;

    const mainChart = createChart(mainContainer, {
      ...commonOptions,
      width: mainContainer.clientWidth,
      height: 360,
      handleScroll: true,
      handleScale: true,
    });
    const macdChart = createChart(macdContainer, {
      ...commonOptions,
      width: macdContainer.clientWidth,
      height: 120,
      handleScroll: false,
      handleScale: false,
    });
    const kdjChart = createChart(kdjContainer, {
      ...commonOptions,
      width: kdjContainer.clientWidth,
      height: 120,
      handleScroll: false,
      handleScale: false,
    });

    mainChart.applyOptions({
      timeScale: { visible: false, borderVisible: false },
    });
    macdChart.applyOptions({
      timeScale: { visible: false, borderVisible: false },
    });
    kdjChart.applyOptions({
      timeScale: { visible: true, borderVisible: true },
    });

    syncVisibleRange(mainChart, [macdChart, kdjChart]);

    const candleSeries = mainChart.addSeries(CandlestickSeries, {
      upColor: TERMINAL_THEME.up,
      downColor: TERMINAL_THEME.down,
      wickUpColor: TERMINAL_THEME.up,
      wickDownColor: TERMINAL_THEME.down,
      borderUpColor: TERMINAL_THEME.up,
      borderDownColor: TERMINAL_THEME.down,
      priceLineVisible: true,
      lastValueVisible: true,
    });
    candleSeries.setData(points.map((item) => ({
      time: item.time,
      open: item.open,
      high: item.high,
      low: item.low,
      close: item.close,
    })));

    // 成交量并入K线区域下方，不额外占垂直空间
    const volumeSeries = mainChart.addSeries(HistogramSeries, {
      priceScaleId: "volume",
      priceFormat: { type: "volume" },
      priceLineVisible: false,
      lastValueVisible: false,
    });
    volumeSeries.setData(
      points.map((item, index) => {
        const prev = index > 0 ? points[index - 1].close : item.open;
        return {
          time: item.time,
          value: item.volume,
          color: item.close >= prev ? TERMINAL_THEME.up : TERMINAL_THEME.down,
        };
      }),
    );
    mainChart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.78, bottom: 0 },
      visible: false,
    });

    for (const config of maConfigs) {
      if (!config.enabled || config.period <= 0) continue;
      const maSeries = mainChart.addSeries(LineSeries, {
        color: config.color,
        lineWidth: Math.min(4, Math.max(1, Math.round(config.width))) as 1 | 2 | 3 | 4,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      maSeries.setData(computeMA(points, config.period));
    }

    const macd = computeMACD(points);
    const macdHistogram = macdChart.addSeries(HistogramSeries, {
      priceLineVisible: false,
      lastValueVisible: false,
    });
    macdHistogram.setData(
      macd.map((item) => ({
        time: item.time,
        value: item.macd,
        color: item.macd >= 0 ? TERMINAL_THEME.up : TERMINAL_THEME.down,
      })),
    );
    const diffLine = macdChart.addSeries(LineSeries, {
      color: "#f0a138",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    diffLine.setData(macd.map((item) => ({ time: item.time, value: item.diff })));
    const deaLine = macdChart.addSeries(LineSeries, {
      color: "#2f7bff",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    deaLine.setData(macd.map((item) => ({ time: item.time, value: item.dea })));

    const kdj = computeKDJ(points);
    const kLine = kdjChart.addSeries(LineSeries, {
      color: "#ffcf40",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    kLine.setData(kdj.map((item) => ({ time: item.time, value: item.k })));
    const dLine = kdjChart.addSeries(LineSeries, {
      color: "#37a0ff",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    dLine.setData(kdj.map((item) => ({ time: item.time, value: item.d })));
    const jLine = kdjChart.addSeries(LineSeries, {
      color: "#ff4cc4",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    jLine.setData(kdj.map((item) => ({ time: item.time, value: item.j })));

    const pointIndexByTime = new Map<string, number>();
    for (let index = 0; index < points.length; index += 1) {
      pointIndexByTime.set(toTimeKey(points[index].time), index);
    }
    let syncingCrosshair = false;
    const syncCrosshairFrom = (source: "main" | "macd" | "kdj", param: { time?: Time }) => {
      if (syncingCrosshair) return;
      syncingCrosshair = true;
      if (!param.time) {
        if (source !== "main") mainChart.clearCrosshairPosition();
        if (source !== "macd") macdChart.clearCrosshairPosition();
        if (source !== "kdj") kdjChart.clearCrosshairPosition();
        syncingCrosshair = false;
        return;
      }
      const pointIndex = pointIndexByTime.get(toTimeKey(param.time));
      if (pointIndex === undefined) {
        syncingCrosshair = false;
        return;
      }
      const time = points[pointIndex].time;
      if (source !== "main") {
        mainChart.setCrosshairPosition(points[pointIndex].close, time, candleSeries);
      }
      if (source !== "macd") {
        macdChart.setCrosshairPosition(macd[pointIndex]?.diff ?? 0, time, diffLine);
      }
      if (source !== "kdj") {
        kdjChart.setCrosshairPosition(kdj[pointIndex]?.k ?? 0, time, kLine);
      }
      syncingCrosshair = false;
    };
    const onMainCrosshairMove = (param: { time?: Time; point?: { x: number; y: number } }) => {
      syncCrosshairFrom("main", param);
      if (!focusActive) return;
      if (!param.time) {
        closeFocusPanel();
        return;
      }
      const idx = pointIndexByTime.get(toTimeKey(param.time));
      if (idx !== undefined) {
        setFocusIndex(idx);
      }
      if (param.point) {
        setFocusCrosshairPoint({ x: param.point.x, y: param.point.y });
      }
    };
    const onMacdCrosshairMove = (param: { time?: Time }) => syncCrosshairFrom("macd", param);
    const onKdjCrosshairMove = (param: { time?: Time }) => syncCrosshairFrom("kdj", param);
    const onMainClick = (param: { time?: Time; point?: { x: number; y: number } }) => {
      if (focusActive) {
        closeFocusPanel();
        return;
      }
      if (!param.time) {
        return;
      }
      const idx = pointIndexByTime.get(toTimeKey(param.time));
      if (idx === undefined) {
        return;
      }
      setFocusActive(true);
      setFocusIndex(idx);
      if (param.point) {
        setFocusCrosshairPoint({ x: param.point.x, y: param.point.y });
      }
    };
    mainChart.subscribeCrosshairMove(onMainCrosshairMove);
    macdChart.subscribeCrosshairMove(onMacdCrosshairMove);
    kdjChart.subscribeCrosshairMove(onKdjCrosshairMove);
    mainChart.subscribeClick(onMainClick);

    mainChart.timeScale().fitContent();
    const bars = DEFAULT_VISIBLE_BARS[period];
    const to = points.length + 3;
    const from = Math.max(0, to - bars);
    mainChart.timeScale().setVisibleLogicalRange({ from, to });
    macdChart.timeScale().setVisibleLogicalRange({ from, to });
    kdjChart.timeScale().setVisibleLogicalRange({ from, to });

    const handleResize = () => {
      mainChart.resize(mainContainer.clientWidth, 360);
      macdChart.resize(macdContainer.clientWidth, 120);
      kdjChart.resize(kdjContainer.clientWidth, 120);
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      mainChart.unsubscribeCrosshairMove(onMainCrosshairMove);
      macdChart.unsubscribeCrosshairMove(onMacdCrosshairMove);
      kdjChart.unsubscribeCrosshairMove(onKdjCrosshairMove);
      mainChart.unsubscribeClick(onMainClick);
      mainChart.remove();
      macdChart.remove();
      kdjChart.remove();
    };
  }, [focusActive, maConfigs, points, period]);

  const quote = quoteQuery.data;
  const changePct = Number(quote?.change_pct || 0);
  const quoteColor = changePct >= 0 ? TERMINAL_THEME.up : TERMINAL_THEME.down;
  const headline = quote?.name || tsCode;
  const toggleMetricSection = (sectionId: MetricSectionId) => {
    setMetricSectionOpen((current) => ({ ...current, [sectionId]: !current[sectionId] }));
  };
  const metricSections: MetricSection[] = [
    {
      id: "intraday" as const,
      title: "日内表现",
      items: [
        { label: "今开", value: formatCompact(quote?.open, 2) },
        { label: "昨收", value: formatCompact(quote?.prev_close, 2) },
        { label: "最高", value: formatCompact(quote?.high, 2), tone: "up" as const },
        { label: "最低", value: formatCompact(quote?.low, 2), tone: "down" as const },
      ],
    },
    {
      id: "activity" as const,
      title: "成交活跃",
      items: [
        { label: "成交量", value: formatAmount(quote?.volume) },
        { label: "成交额", value: formatAmount(quote?.amount) },
        { label: "换手率", value: formatPercent(quote?.turnover_rate_f, 2) },
        { label: "量比", value: formatCompact(quote?.volume_ratio, 2) },
      ],
    },
    {
      id: "valuation" as const,
      title: "估值与市值",
      items: [
        { label: "市盈率(TTM)", value: formatCompact(quote?.pe_ttm, 2) },
        { label: "市净率(PB)", value: formatCompact(quote?.pb, 2) },
        { label: "股息率", value: formatPercent(quote?.dv_ratio, 2) },
        { label: "股息率(TTM)", value: formatPercent(quote?.dv_ttm, 2) },
        { label: "总股本(万股)", value: formatCompact(quote?.total_share, 2) },
        { label: "流通股本(万股)", value: formatCompact(quote?.float_share, 2) },
        { label: "自由流通股本(万)", value: formatCompact(quote?.free_share, 2) },
        { label: "总市值(万元)", value: formatCompact(quote?.total_mv, 2) },
        { label: "流通市值(万元)", value: formatCompact(quote?.circ_mv, 2) },
      ],
    },
  ];
  const activeMaConfigs = maConfigs.filter((item) => item.enabled && item.period > 0);
  const focusedPointIndex = focusIndex ?? -1;
  const focusedPoint = focusedPointIndex >= 0 ? points[focusedPointIndex] : null;
  const effectivePreClose = focusedPoint
    ? (focusedPoint.preClose ?? (focusedPointIndex > 0 ? points[focusedPointIndex - 1].close : null))
    : null;
  const amplitude = (focusedPoint && effectivePreClose && effectivePreClose !== 0)
    ? ((focusedPoint.high - focusedPoint.low) / effectivePreClose) * 100
    : null;
  const risePct = focusedPoint
    ? (focusedPoint.pctChg ?? (effectivePreClose && effectivePreClose !== 0
      ? ((focusedPoint.close - effectivePreClose) / effectivePreClose) * 100
      : null))
    : null;
  const floatingWidth = 172;
  const floatingHitHeight = 184;
  const plotRightInset = 70;
  const floatingShouldRight = Boolean(
    focusCrosshairPoint
    && focusCrosshairPoint.x <= (12 + floatingWidth)
    && focusCrosshairPoint.y <= (12 + floatingHitHeight),
  );
  const floatingStyle: CSSProperties = floatingShouldRight
    ? {
      top: 10,
      right: plotRightInset + 8,
      width: floatingWidth,
    }
    : {
      top: 10,
      left: 10,
      width: floatingWidth,
    };

  const valueColorByComparison = (value: number | null, base: number | null) => {
    if (value === null || base === null) return TERMINAL_THEME.text;
    if (value > base) return TERMINAL_THEME.up;
    if (value < base) return TERMINAL_THEME.down;
    return TERMINAL_THEME.text;
  };

  const cardStyle = {
    background: TERMINAL_THEME.panel,
    border: `1px solid ${TERMINAL_THEME.border}`,
    boxShadow: "inset 0 1px 0 rgba(255,255,255,0.03), 0 10px 24px rgba(2,10,24,0.35)",
  } as const;

  return (
    <div className="terminal-root">
      <div className="terminal-window">
        <div className="terminal-topbar">
          <Group justify="space-between" align="center" wrap="nowrap">
            <Group gap={6} wrap="nowrap">
              <Autocomplete
                value={searchValue}
                onChange={setSearchValue}
                data={suggestionOptions}
                onOptionSubmit={(value) => {
                  setSearchValue(value);
                  const code = parseTsCodeFromSearch(value);
                  if (code) setTsCode(code);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    const code = parseTsCodeFromSearch(searchValue);
                    if (code) setTsCode(code);
                  }
                }}
                size="xs"
                w={220}
                placeholder="输入代码/简称/拼音"
                styles={{
                  input: {
                    background: TERMINAL_THEME.background,
                    borderColor: TERMINAL_THEME.border,
                    color: TERMINAL_THEME.text,
                    fontSize: 12,
                    height: 30,
                    borderRadius: 8,
                  },
                  dropdown: { background: TERMINAL_THEME.panelRaised, borderColor: TERMINAL_THEME.border },
                  option: {
                    fontSize: 12,
                    color: TERMINAL_THEME.text,
                    borderRadius: 6,
                    "&[data-combobox-selected]": {
                      background: "rgba(44, 74, 120, 0.45)",
                    },
                  },
                }}
              />
              <div className="terminal-chip terminal-date-chip">{quote?.trade_date ? formatDateLabel(quote.trade_date) : "暂无交易日"}</div>
              <div className={`terminal-chip ${changePct >= 0 ? "terminal-chip-up" : "terminal-chip-down"}`}>
                涨跌 {formatPercent(quote?.change_pct, 2)}
              </div>
              <div className="terminal-chip terminal-chip-muted">额 {formatAmount(quote?.amount)}</div>
            </Group>
            <SegmentedControl
              value={period}
              onChange={(value) => setPeriod(value as Period)}
              size="xs"
              radius="sm"
              data={[
                { label: "日K", value: "d" },
                { label: "周K", value: "w" },
                { label: "月K", value: "m" },
              ]}
              styles={{
                root: {
                  background: "rgba(18, 30, 50, 0.92)",
                  border: `1px solid ${TERMINAL_THEME.buttonBorder}`,
                  padding: 2,
                  minWidth: 146,
                },
                indicator: {
                  background: "linear-gradient(180deg, #2a4270 0%, #23395f 100%)",
                  border: `1px solid rgba(87, 132, 208, 0.75)`,
                  boxShadow: "0 0 0 1px rgba(70, 106, 168, 0.25)",
                },
                label: {
                  color: "#a5bbdd",
                  fontWeight: 600,
                  fontSize: 11,
                  "&[data-active]": {
                    color: "#e0ecff",
                  },
                },
              }}
            />
          </Group>
        </div>

        <Stack gap={6} p={6} style={{ fontSize: 12 }}>
          <Grid gutter={6}>
            <Grid.Col span={{ base: 12, lg: 10 }}>
              <Paper p={4} radius="sm" style={{ ...cardStyle, minHeight: 610 }} className="terminal-card">
                <div className="terminal-panel-header">
                  <Group gap={8}>
                    <IconChartCandle size={14} color={TERMINAL_THEME.accent} />
                    <Stack gap={0}>
                      <Text className="terminal-panel-title">{headline}</Text>
                      <Text className="terminal-panel-subtitle">{tsCode} · 前复权</Text>
                    </Stack>
                  </Group>
                  <Group gap={10} wrap="nowrap">
                    <Menu shadow="md" width={160} position="bottom-end">
                      <Menu.Target>
                        <ActionIcon variant="subtle" size="sm" aria-label="功能设置" styles={TOOLBAR_ICON_STYLES}>
                          <IconSettings size={14} />
                        </ActionIcon>
                      </Menu.Target>
                      <Menu.Dropdown
                        style={{
                          background: TERMINAL_THEME.panelRaised,
                          border: `1px solid ${TERMINAL_THEME.border}`,
                          color: TERMINAL_THEME.text,
                        }}
                      >
                        <Menu.Item
                          styles={{
                            item: {
                              color: "#c6d8f6",
                              background: "transparent",
                            },
                            itemLabel: {
                              color: "#c6d8f6",
                            },
                          }}
                          onClick={() => {
                            setMaDraft(maConfigs.map((item) => ({ ...item })));
                            setMaDialogOpen(true);
                          }}
                        >
                          均线设置
                        </Menu.Item>
                      </Menu.Dropdown>
                    </Menu>
                    <Group gap={8}>
                      {activeMaConfigs.map((item, index) => (
                        <Text key={item.id} size="10px" c={item.color} fw={700}>{`MA${index + 1}:${item.period}`}</Text>
                      ))}
                    </Group>
                  </Group>
                </div>
            {klineQuery.isLoading ? <Loader size="xs" /> : null}
            {klineQuery.error ? (
              <Alert color="red" title="K线读取失败">
                {klineQuery.error instanceof Error ? klineQuery.error.message : "未知错误"}
              </Alert>
            ) : null}
            <Box style={{ position: "relative" }} onMouseLeave={closeFocusPanel}>
              <div ref={mainContainerRef} />
              {(focusActive && focusedPoint) ? (
                <Paper
                  p={6}
                  radius="sm"
                  style={{
                    ...floatingStyle,
                    position: "absolute",
                    zIndex: 30,
                    background: "rgba(8,12,22,0.42)",
                    border: "1px solid rgba(255,255,255,0.9)",
                    backdropFilter: "blur(1px)",
                  }}
                >
                  <Stack gap={3}>
                    <Text size="10px" c={TERMINAL_THEME.text} fw={700}>{focusedPoint.tradeDate}</Text>
                    <Divider color="rgba(255,255,255,0.28)" />
                    <Group justify="space-between" wrap="nowrap"><Text size="10px" c={TERMINAL_THEME.text}>开盘</Text><Text size="10px" c={valueColorByComparison(focusedPoint.open, effectivePreClose)}>{formatCompact(focusedPoint.open, 2)}</Text></Group>
                    <Group justify="space-between" wrap="nowrap"><Text size="10px" c={TERMINAL_THEME.text}>收盘</Text><Text size="10px" c={valueColorByComparison(focusedPoint.close, focusedPoint.open)}>{formatCompact(focusedPoint.close, 2)}</Text></Group>
                    <Group justify="space-between" wrap="nowrap"><Text size="10px" c={TERMINAL_THEME.text}>最高</Text><Text size="10px" c={valueColorByComparison(focusedPoint.high, effectivePreClose)}>{formatCompact(focusedPoint.high, 2)}</Text></Group>
                    <Group justify="space-between" wrap="nowrap"><Text size="10px" c={TERMINAL_THEME.text}>最低</Text><Text size="10px" c={valueColorByComparison(focusedPoint.low, effectivePreClose)}>{formatCompact(focusedPoint.low, 2)}</Text></Group>
                    <Group justify="space-between" wrap="nowrap"><Text size="10px" c={TERMINAL_THEME.text}>涨幅</Text><Text size="10px" c={valueColorByComparison(focusedPoint.close, focusedPoint.open)}>{risePct === null ? "—" : `${formatCompact(risePct, 2)}%`}</Text></Group>
                    <Group justify="space-between" wrap="nowrap"><Text size="10px" c={TERMINAL_THEME.text}>振幅</Text><Text size="10px" c={TERMINAL_THEME.text}>{amplitude === null ? "—" : `${formatCompact(amplitude, 2)}%`}</Text></Group>
                    <Group justify="space-between" wrap="nowrap"><Text size="10px" c={TERMINAL_THEME.text}>成交量</Text><Text size="10px" c={TERMINAL_THEME.text}>{formatVolumeHuman(focusedPoint.volume)}</Text></Group>
                    <Group justify="space-between" wrap="nowrap"><Text size="10px" c={TERMINAL_THEME.text}>成交额</Text><Text size="10px" c={TERMINAL_THEME.text}>{formatAmountHuman(focusedPoint.amount)}</Text></Group>
                    <Group justify="space-between" wrap="nowrap"><Text size="10px" c={TERMINAL_THEME.text}>换手率</Text><Text size="10px" c={TERMINAL_THEME.text}>{focusedPoint.turnoverRate === null ? "—" : `${formatCompact(focusedPoint.turnoverRate, 2)}%`}</Text></Group>
                  </Stack>
                </Paper>
              ) : null}
            </Box>
            <Divider my={2} color={TERMINAL_THEME.border} />
            <Box px={6} py={2}>
              <Text size="10px" c={TERMINAL_THEME.textMuted}>MACD(12,26,9)</Text>
            </Box>
            <div ref={macdContainerRef} />
            <Divider my={2} color={TERMINAL_THEME.border} />
            <Box px={6} py={2}>
              <Text size="10px" c={TERMINAL_THEME.textMuted}>KDJ(9,3,3)</Text>
            </Box>
            <div ref={kdjContainerRef} />
              </Paper>
            </Grid.Col>

            <Grid.Col span={{ base: 12, lg: 2 }}>
              <Paper p={8} radius="sm" style={{ ...cardStyle, height: "100%" }} className="terminal-card">
                <div className="terminal-panel-header" style={{ margin: "-8px -8px 8px -8px", borderTopLeftRadius: 6, borderTopRightRadius: 6 }}>
                  <Text className="terminal-panel-title">股票指标</Text>
                </div>
                <Stack gap={8} className="terminal-quote-panel">
                  <div className="terminal-quote-head">
                    <Text c={TERMINAL_THEME.text} fw={700} size="sm">{quote?.name || tsCode}</Text>
                    <Text c={TERMINAL_THEME.textMuted} ff="IBM Plex Mono, SFMono-Regular, monospace" size="xs">{tsCode}</Text>
                    <div className="terminal-quote-price-line">
                      <Text fw={700} size="xl" c={quoteColor}>{formatCompact(quote?.close, 2)}</Text>
                      <Text c={quoteColor} fw={600} size="xs">{formatCompact(quote?.change_amount, 2)} / {formatPercent(quote?.change_pct, 2)}</Text>
                    </div>
                  </div>
                  {metricSections.map((section) => (
                    <div key={section.title} className="terminal-metric-section">
                      <button
                        type="button"
                        className="terminal-metric-section-title"
                        onClick={() => toggleMetricSection(section.id)}
                      >
                        <span>{section.title}</span>
                        <span className="terminal-metric-section-action">
                          {metricSectionOpen[section.id] ? <IconChevronUp size={12} /> : <IconChevronDown size={12} />}
                        </span>
                      </button>
                      <Collapse in={metricSectionOpen[section.id]}>
                        <div className="terminal-metric-grid">
                          {section.items.map((item) => (
                            <div key={`${section.title}-${item.label}`} className="terminal-metric-row">
                              <span className="label">{item.label}</span>
                              <span className={`value${item.tone ? ` is-${item.tone}` : ""}`}>{item.value}</span>
                            </div>
                          ))}
                        </div>
                      </Collapse>
                    </div>
                  ))}
                </Stack>
              </Paper>
            </Grid.Col>
          </Grid>

          <Paper p={0} radius="sm" style={{ ...cardStyle, overflow: "hidden" }} className="terminal-card">
        <Button
          fullWidth
          variant="subtle"
          className="terminal-news-toggle"
          size="xs"
          onClick={() => setNewsExpanded((current) => !current)}
          rightSection={newsExpanded ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />}
          styles={{
            root: {
              borderBottom: newsExpanded ? `1px solid ${TERMINAL_THEME.border}` : "none",
              color: TERMINAL_THEME.buttonText,
              background: TERMINAL_THEME.buttonSoftBg,
              fontSize: 12,
              fontWeight: 600,
              "&:hover": { background: TERMINAL_THEME.buttonSoftHover },
            },
            label: { color: TERMINAL_THEME.buttonText },
          }}
        >
          新闻与事件
        </Button>
        <Collapse in={newsExpanded}>
          <Stack p={8} gap={6}>
            <Group justify="space-between" className="terminal-news-header">
              <Text size="xs" c={TERMINAL_THEME.text}>最新新闻与事件</Text>
              <Text size="10px" c={TERMINAL_THEME.textMuted}>{newsQuery.data?.items?.length ?? 0} 条</Text>
            </Group>
            {newsQuery.error ? (
              <Alert color="red" title="新闻读取失败">
                {newsQuery.error instanceof Error ? newsQuery.error.message : "未知错误"}
              </Alert>
            ) : null}
            <ScrollArea h={210}>
              <Table
                highlightOnHover
                withTableBorder
                stickyHeader
                className="terminal-news-table"
                styles={{
                  table: { background: TERMINAL_THEME.panelRaised, borderColor: TERMINAL_THEME.border },
                  thead: { background: "#132038" },
                  th: { color: TERMINAL_THEME.textMuted, fontSize: 11, borderColor: TERMINAL_THEME.border, letterSpacing: "0.03em" },
                  td: { borderColor: TERMINAL_THEME.border, background: "transparent" },
                  tr: { borderColor: TERMINAL_THEME.border },
                }}
              >
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th style={{ width: 88 }}>日期</Table.Th>
                    <Table.Th style={{ width: 84 }}>标签</Table.Th>
                    <Table.Th style={{ width: 320 }}>标题</Table.Th>
                    <Table.Th>摘要</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {(newsQuery.data?.items || []).map((item) => (
                    <Table.Tr key={item.id}>
                      <Table.Td><Text c={TERMINAL_THEME.textMuted} size="xs">{formatDateLabel(item.occurred_at)}</Text></Table.Td>
                      <Table.Td>
                        <Badge
                          variant="light"
                          size="xs"
                          styles={{
                            root: {
                              background: "rgba(43, 85, 156, 0.32)",
                              border: "1px solid rgba(74, 127, 212, 0.5)",
                              color: "#d6e7ff",
                            },
                          }}
                        >
                          {item.tag}
                        </Badge>
                      </Table.Td>
                      <Table.Td><Text c={TERMINAL_THEME.text} size="xs" fw={600} lineClamp={1}>{item.title}</Text></Table.Td>
                      <Table.Td><Text c={TERMINAL_THEME.textMuted} size="xs" lineClamp={2}>{item.summary || "—"}</Text></Table.Td>
                    </Table.Tr>
                  ))}
                  {!newsQuery.data?.items?.length ? (
                    <Table.Tr>
                      <Table.Td colSpan={4}>
                        <Text c={TERMINAL_THEME.textMuted} size="xs">暂无可展示新闻，先同步龙虎榜/分红/股东户数数据。</Text>
                      </Table.Td>
                    </Table.Tr>
                  ) : null}
                </Table.Tbody>
              </Table>
            </ScrollArea>
          </Stack>
        </Collapse>
          </Paper>
        </Stack>
      </div>

      <Modal
        opened={maDialogOpen}
        onClose={() => setMaDialogOpen(false)}
        title="K线均线用法与设置"
        size="xl"
        centered
        classNames={{
          content: "terminal-modal-content",
        }}
        styles={{
          header: { background: TERMINAL_THEME.panelRaised, borderBottom: `1px solid ${TERMINAL_THEME.border}` },
          content: { color: TERMINAL_THEME.text },
          title: { color: TERMINAL_THEME.text, fontWeight: 700 },
          close: { color: TERMINAL_THEME.textMuted },
          body: { background: TERMINAL_THEME.panel, color: TERMINAL_THEME.text },
        }}
      >
        <Table
          className="terminal-modal-table"
          withTableBorder
          styles={{
            table: { background: TERMINAL_THEME.panelRaised, borderColor: TERMINAL_THEME.border },
            th: { color: TERMINAL_THEME.textMuted, fontSize: 12, borderColor: TERMINAL_THEME.border },
            td: { borderColor: TERMINAL_THEME.border, paddingTop: 8, paddingBottom: 8 },
          }}
        >
          <Table.Thead>
            <Table.Tr>
              <Table.Th>参数名称</Table.Th>
              <Table.Th>参数值</Table.Th>
              <Table.Th>指标线</Table.Th>
              <Table.Th>线宽</Table.Th>
              <Table.Th>颜色</Table.Th>
              <Table.Th>操作</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {maDraft.map((item, index) => (
              <Table.Tr key={item.id}>
                <Table.Td><Text c={TERMINAL_THEME.text}>移动平均周期 {index + 1}</Text></Table.Td>
                <Table.Td>
                  <NumberInput
                    size="xs"
                    min={1}
                    max={999}
                    value={item.period}
                    onChange={(value) =>
                      setMaDraft((current) =>
                        current.map((row) => row.id === item.id ? { ...row, period: Number(value || 1) } : row),
                      )
                    }
                    styles={{
                      input: { background: TERMINAL_THEME.background, borderColor: TERMINAL_THEME.border, color: TERMINAL_THEME.text },
                      section: {
                        color: TERMINAL_THEME.text,
                        background: "#1a2438",
                        borderLeft: `1px solid ${TERMINAL_THEME.border}`,
                      },
                    }}
                  />
                </Table.Td>
                <Table.Td>
                  <Checkbox
                    checked={item.enabled}
                    label={`MA${index + 1}`}
                    onChange={(event) =>
                      setMaDraft((current) =>
                        current.map((row) => row.id === item.id ? { ...row, enabled: event.currentTarget.checked } : row),
                      )
                    }
                    styles={{ label: { color: TERMINAL_THEME.text } }}
                  />
                </Table.Td>
                <Table.Td>
                  <NumberInput
                    size="xs"
                    min={1}
                    max={4}
                    value={item.width}
                    onChange={(value) =>
                      setMaDraft((current) =>
                        current.map((row) => row.id === item.id ? { ...row, width: Number(value || 1) } : row),
                      )
                    }
                    styles={{
                      input: { background: TERMINAL_THEME.background, borderColor: TERMINAL_THEME.border, color: TERMINAL_THEME.text },
                      section: {
                        color: TERMINAL_THEME.text,
                        background: "#1a2438",
                        borderLeft: `1px solid ${TERMINAL_THEME.border}`,
                      },
                    }}
                  />
                </Table.Td>
                <Table.Td>
                  <Group gap={6} wrap="nowrap">
                    {MA_COLOR_SWATCHES.map((color) => (
                      <ActionIcon
                        key={`${item.id}-${color}`}
                        size="sm"
                        radius="xl"
                        variant={item.color.toLowerCase() === color.toLowerCase() ? "filled" : "light"}
                        onClick={() =>
                          setMaDraft((current) =>
                            current.map((row) => row.id === item.id ? { ...row, color } : row),
                          )
                        }
                        style={{
                          background: color,
                          border: item.color.toLowerCase() === color.toLowerCase()
                            ? `2px solid ${TERMINAL_THEME.accent}`
                            : `1px solid ${TERMINAL_THEME.border}`,
                          boxShadow: item.color.toLowerCase() === color.toLowerCase()
                            ? "0 0 0 1px rgba(76,139,255,0.35)"
                            : "none",
                        }}
                      />
                    ))}
                  </Group>
                </Table.Td>
                <Table.Td>
                  <ActionIcon
                    variant="light"
                    disabled={maDraft.length <= 1}
                    onClick={() => setMaDraft((current) => current.filter((row) => row.id !== item.id))}
                    styles={{
                      root: {
                        background: "rgba(92,34,50,0.55)",
                        border: "1px solid rgba(156,72,97,0.8)",
                        color: "#ffb3c7",
                        "&:hover": { background: "rgba(109,40,60,0.72)" },
                      },
                    }}
                  >
                    <IconTrash size={14} />
                  </ActionIcon>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>

        <Group justify="space-between" mt="md">
          <Group>
            <Button
              size="xs"
              leftSection={<IconPlus size={14} />}
              styles={SOFT_BUTTON_STYLES}
              onClick={() =>
                setMaDraft((current) => [
                  ...current,
                  {
                    id: `ma_${Date.now()}_${current.length}`,
                    period: 20,
                    enabled: false,
                    width: 1,
                    color: MA_COLOR_SWATCHES[current.length % MA_COLOR_SWATCHES.length],
                  },
                ])
              }
            >
              新增均线
            </Button>
            <Button
              size="xs"
              styles={SOFT_BUTTON_STYLES}
              onClick={() => setMaDraft(cloneDefaultMaConfigs())}
            >
              恢复默认值
            </Button>
          </Group>
          <Group>
            <Button size="xs" styles={SOFT_BUTTON_STYLES} onClick={() => setMaDialogOpen(false)}>取消</Button>
            <Button
              size="xs"
              styles={PRIMARY_BUTTON_STYLES}
              onClick={() => {
                setMaConfigs(maDraft.map((item) => ({ ...item })));
                setMaDialogOpen(false);
              }}
            >
              应用设置
            </Button>
          </Group>
        </Group>
      </Modal>
    </div>
  );
}
