import type { MarketOverview, MarketOverviewParams, WealthApiResponse } from "./marketOverviewTypes";

function genDates(count: number) {
  const dates: string[] = [];
  const current = new Date("2026-04-28T00:00:00+08:00");

  while (dates.length < count) {
    const day = current.getDay();
    if (day !== 0 && day !== 6) dates.unshift(current.toISOString().slice(5, 10));
    current.setDate(current.getDate() - 1);
  }

  return dates;
}

function makeSeries(count: number, base: number, amp: number, trend = 0, noise = 1) {
  return Array.from({ length: count }, (_, index) => {
    const wave = Math.sin(index / 3.1) * amp + Math.cos(index / 6.7) * amp * 0.55;
    const jitter = Math.sin(index * 1.73) * amp * 0.18 * noise;
    return base + wave + trend * index + jitter;
  });
}

function rangeData(dates: string[], make: (index: number, total: number) => Record<string, number>) {
  return dates.map((label, index) => ({ label, ...make(index, dates.length) }));
}

const dates1m = genDates(22);
const dates3m = genDates(62);

const leaderboardRows = (rows: Array<[string, string, number, number, number, number, string, string]>) =>
  rows.map(([name, code, latestPrice, changePct, turnoverRate, volumeRatio, volume, amount]) => ({
    name,
    code,
    latestPrice,
    changePct,
    turnoverRate,
    volumeRatio,
    volume,
    amount,
  }));

const ladderStock = (
  stockName: string,
  stockCode: string,
  latestPrice: number,
  changePct: number,
  sectorName: string,
  openTimes: number,
  currentStreakLevel: number,
  advanced = true,
) => ({
  stockName,
  stockCode,
  latestPrice,
  changePct,
  sectorName,
  openTimes,
  currentStreakLevel,
  advanced,
});

const indices = [
  { code: "000001.SH", name: "上证指数", point: 3128.42, change: 28.66, pct: 0.92, direction: "UP" },
  { code: "399001.SZ", name: "深证成指", point: 9842.15, change: -34.21, pct: -0.35, direction: "DOWN" },
  { code: "399006.SZ", name: "创业板指", point: 1986.22, change: 22.03, pct: 1.12, direction: "UP" },
  { code: "000688.SH", name: "科创50", point: 921.56, change: -1.66, pct: -0.18, direction: "DOWN" },
  { code: "000300.SH", name: "沪深300", point: 3726.84, change: 26.58, pct: 0.72, direction: "UP" },
  { code: "000905.SH", name: "中证500", point: 5642.33, change: 58.65, pct: 1.05, direction: "UP" },
  { code: "000852.SH", name: "中证1000", point: 5948.17, change: 86.7, pct: 1.48, direction: "UP" },
  { code: "899050.BJ", name: "北证50", point: 1196.35, change: 24.15, pct: 2.06, direction: "UP" },
  { code: "000510.SH", name: "中证A500", point: 4683.91, change: 38.56, pct: 0.83, direction: "UP" },
  { code: "000016.SH", name: "上证50", point: 2542.08, change: 10.66, pct: 0.42, direction: "UP" },
] as const;

export const marketOverviewMock: MarketOverview = {
  tradeDate: "2026-04-28",
  updateTime: "2026-04-28 15:05:00",
  statusText: "已收盘",
  dataStatus: "DELAYED",
  dataDelayText: "数据延迟 90s",
  tickers: indices.slice(0, 7),
  summaryFacts: [
    { label: "主要指数", value: "8/10", valueTone: "up", sub: "上涨数量" },
    { label: "上涨 / 下跌", value: "3421 / 1488", sub: "平盘 219" },
    { label: "成交总额", value: "10523亿", valueTone: "up", sub: "较昨日 +7.15%" },
    { label: "大盘资金", value: "-52.8亿", valueTone: "down", sub: "净流出" },
    { label: "涨停 / 跌停", value: "59 / 8", sub: "炸板 27" },
  ],
  summaryText:
    "截至收盘，A 股主要指数多数上涨。全市场上涨家数多于下跌家数，成交额较上一交易日放大；涨停家数高于跌停家数。大盘资金今日为净流出，资金分布呈现分化。本卡片仅描述客观事实，不展示市场温度、情绪指数、资金面分数、风险指数，也不构成交易建议。",
  indices: [...indices],
  breadthMetrics: [
    { label: "上涨家数", value: "3421", tone: "up", sub: "红盘率 66.7%" },
    { label: "下跌家数", value: "1488", tone: "down", sub: "绿盘率 29.0%" },
    { label: "平盘家数", value: "219", tone: "flat", sub: "平盘率 4.3%" },
  ],
  styleMetrics: [
    { label: "大盘股平均涨跌幅", value: "+0.72%", tone: "up", sub: "沪深300口径" },
    { label: "小盘股平均涨跌幅", value: "+1.48%", tone: "up", sub: "中证1000口径" },
    { label: "涨跌中位数", value: "+0.48%", tone: "up", sub: "全市场样本" },
  ],
  turnoverMetrics: [
    { label: "今日成交总额", value: "10523亿", tone: "up", sub: "截至 15:00" },
    { label: "较上一交易日", value: "+702亿", tone: "up", sub: "+7.15%" },
    { label: "上一交易日成交", value: "9821亿", tone: "flat", sub: "2026-04-27" },
    { label: "5日均值", value: "10180亿", tone: "flat", sub: "20日均值 9360亿" },
  ],
  moneyFlowMetrics: [
    { label: "今日大盘资金净流入", value: "-52.8亿", tone: "down", sub: "净流出；数据源：moneyflow_mkt_dc" },
    { label: "昨日大盘资金净流入", value: "+31.6亿", tone: "up", sub: "2026-04-27" },
  ],
  moneyFlowOrderSizeStructure: {
    netAmount: -52.8,
    netAmountRate: -0.48,
    items: [
      { orderSize: "superLarge", orderSizeName: "超大单", netAmount: 12.3, netAmountRate: 42.5, absAmount: 12.3, direction: "inflow" },
      { orderSize: "large", orderSizeName: "大单", netAmount: -5.2, netAmountRate: 18.1, absAmount: 5.2, direction: "outflow" },
      { orderSize: "medium", orderSizeName: "中单", netAmount: 3.1, netAmountRate: 10.7, absAmount: 3.1, direction: "inflow" },
      { orderSize: "small", orderSizeName: "小单", netAmount: -8.7, netAmountRate: 28.7, absAmount: 8.7, direction: "outflow" },
    ],
  },
  limitMetrics: [
    { label: "涨停家数", value: "59", tone: "up", sub: "不含 ST" },
    { label: "跌停家数", value: "8", tone: "down", sub: "不含 ST" },
    { label: "炸板家数", value: "27", tone: "flat", sub: "触板 86" },
    { label: "封板率", value: "68.6%", tone: "up", sub: "59 / 86" },
    { label: "连板家数", value: "22", tone: "up", sub: "二板及以上" },
    { label: "最高连板", value: "6板", tone: "up", sub: "五板及以上合并" },
    { label: "天地板", value: "1", tone: "down", sub: "高风险结构" },
    { label: "地天板", value: "2", tone: "up", sub: "反包结构" },
  ],
  charts: {
    breadth: {
      "1m": rangeData(dates1m, (index, total) => ({
        up: Math.round(makeSeries(total, 2600, 680, 10)[index]),
        down: Math.round(makeSeries(total, 2100, 620, -6)[index]),
      })).map((item, index, arr) => (index === arr.length - 1 ? { label: "04-28", up: 3421, down: 1488 } : item)),
      "3m": rangeData(dates3m, (index, total) => ({
        up: Math.round(makeSeries(total, 2480, 720, 6)[index]),
        down: Math.round(makeSeries(total, 2230, 690, -3)[index]),
      })).map((item, index, arr) => (index === arr.length - 1 ? { label: "04-28", up: 3421, down: 1488 } : item)),
    },
    style: {
      "1m": rangeData(dates1m, (index, total) => ({
        large: Number(makeSeries(total, 0.22, 0.74, 0.006)[index].toFixed(2)),
        small: Number(makeSeries(total, 0.38, 1.08, 0.01)[index].toFixed(2)),
        median: Number(makeSeries(total, 0.08, 0.62, 0.006)[index].toFixed(2)),
      })).map((item, index, arr) => (index === arr.length - 1 ? { label: "04-28", large: 0.72, small: 1.48, median: 0.48 } : item)),
      "3m": rangeData(dates3m, (index, total) => ({
        large: Number(makeSeries(total, 0.12, 0.82, 0.004)[index].toFixed(2)),
        small: Number(makeSeries(total, 0.24, 1.2, 0.006)[index].toFixed(2)),
        median: Number(makeSeries(total, -0.02, 0.68, 0.004)[index].toFixed(2)),
      })).map((item, index, arr) => (index === arr.length - 1 ? { label: "04-28", large: 0.72, small: 1.48, median: 0.48 } : item)),
    },
    turnoverIntraday: [
      { label: "09:30", amount: 0 },
      { label: "10:00", amount: 1680 },
      { label: "10:30", amount: 3150 },
      { label: "11:00", amount: 4520 },
      { label: "11:30", amount: 5620 },
      { label: "13:30", amount: 7100 },
      { label: "14:00", amount: 8280 },
      { label: "14:30", amount: 9440 },
      { label: "15:00", amount: 10523 },
    ],
    turnoverHistory: {
      "1m": rangeData(dates1m, (index, total) => ({ amount: Math.round(makeSeries(total, 9300, 980, 34)[index]) })).map((item, index, arr) =>
        index === arr.length - 1 ? { label: "04-28", amount: 10523 } : item,
      ),
      "3m": rangeData(dates3m, (index, total) => ({ amount: Math.round(makeSeries(total, 8800, 1180, 24)[index]) })).map((item, index, arr) =>
        index === arr.length - 1 ? { label: "04-28", amount: 10523 } : item,
      ),
    },
    moneyFlow: {
      "1m": rangeData(dates1m, (index, total) => ({ net: Number(makeSeries(total, -12, 52, 0.42)[index].toFixed(1)) })).map((item, index, arr) =>
        index === arr.length - 1 ? { label: "04-28", net: -52.8 } : item,
      ),
      "3m": rangeData(dates3m, (index, total) => ({ net: Number(makeSeries(total, -8, 62, 0.22)[index].toFixed(1)) })).map((item, index, arr) =>
        index === arr.length - 1 ? { label: "04-28", net: -52.8 } : item,
      ),
    },
    limitHistory: {
      "1m": rangeData(dates1m, (index, total) => ({
        up: Math.max(18, Math.round(makeSeries(total, 48, 18, 0.28)[index])),
        down: Math.max(1, Math.round(makeSeries(total, 12, 9, -0.03)[index])),
      })).map((item, index, arr) => (index === arr.length - 1 ? { label: "04-28", up: 59, down: 8 } : item)),
      "3m": rangeData(dates3m, (index, total) => ({
        up: Math.max(12, Math.round(makeSeries(total, 44, 20, 0.1)[index])),
        down: Math.max(1, Math.round(makeSeries(total, 14, 10, -0.02)[index])),
      })).map((item, index, arr) => (index === arr.length - 1 ? { label: "04-28", up: 59, down: 8 } : item)),
    },
  },
  leaderboards: [
    {
      key: "gainers",
      label: "涨幅榜",
      rows: leaderboardRows([
        ["万丰奥威", "002085.SZ", 18.62, 10.02, 18.4, 3.2, "192.6万手", "34.8亿"],
        ["中际旭创", "300308.SZ", 156.8, 8.72, 7.9, 2.6, "61.4万手", "96.1亿"],
        ["赛力斯", "601127.SH", 92.14, 7.35, 5.8, 2.1, "83.2万手", "76.5亿"],
        ["北方华创", "002371.SZ", 345.6, 6.18, 3.6, 1.9, "19.7万手", "68.2亿"],
        ["宁德时代", "300750.SZ", 213.44, 5.22, 2.9, 1.7, "42.8万手", "91.5亿"],
        ["三花智控", "002050.SZ", 25.88, 4.96, 6.4, 2.4, "146.5万手", "37.9亿"],
        ["工业富联", "601138.SH", 28.19, 3.46, 2.4, 1.5, "270.1万手", "76.1亿"],
        ["东方财富", "300059.SZ", 15.26, 2.91, 4.8, 1.8, "828.6万手", "126.4亿"],
        ["中航沈飞", "600760.SH", 42.38, 2.26, 1.6, 1.4, "39.2万手", "16.6亿"],
        ["贵州茅台", "600519.SH", 1588, 0.82, 0.7, 1.1, "6.2万手", "98.2亿"],
      ]),
    },
    {
      key: "losers",
      label: "跌幅榜",
      rows: leaderboardRows([
        ["*ST广田", "002482.SZ", 1.32, -5.26, 8.6, 2.9, "88.2万手", "1.2亿"],
        ["荣盛发展", "002146.SZ", 1.78, -4.81, 6.1, 2.2, "251.3万手", "4.5亿"],
        ["金龙羽", "002882.SZ", 15.12, -4.15, 9.8, 1.8, "36.4万手", "5.5亿"],
        ["海印股份", "000861.SZ", 0.96, -3.98, 5.2, 2, "142.6万手", "1.4亿"],
        ["桂林旅游", "000978.SZ", 6.83, -3.44, 4.3, 1.7, "22.5万手", "1.6亿"],
        ["保利发展", "600048.SH", 8.18, -2.76, 1.4, 1.5, "166.8万手", "13.7亿"],
        ["中国中免", "601888.SH", 72.4, -2.42, 1.1, 1.3, "21.9万手", "15.8亿"],
        ["中国神华", "601088.SH", 38.66, -1.88, 0.6, 1, "53.3万手", "20.6亿"],
        ["招商银行", "600036.SH", 33.92, -1.22, 0.4, 0.9, "78.5万手", "26.6亿"],
        ["中国平安", "601318.SH", 41.1, -0.95, 0.5, 0.8, "66.1万手", "27.2亿"],
      ]),
    },
    {
      key: "amount",
      label: "成交额榜",
      rows: leaderboardRows([
        ["东方财富", "300059.SZ", 15.26, 2.91, 4.8, 1.8, "828.6万手", "126.4亿"],
        ["贵州茅台", "600519.SH", 1588, 0.82, 0.7, 1.1, "6.2万手", "98.2亿"],
        ["宁德时代", "300750.SZ", 213.44, 5.22, 2.9, 1.7, "42.8万手", "91.5亿"],
        ["中际旭创", "300308.SZ", 156.8, 8.72, 7.9, 2.6, "61.4万手", "96.1亿"],
        ["工业富联", "601138.SH", 28.19, 3.46, 2.4, 1.5, "270.1万手", "76.1亿"],
        ["赛力斯", "601127.SH", 92.14, 7.35, 5.8, 2.1, "83.2万手", "76.5亿"],
        ["北方华创", "002371.SZ", 345.6, 6.18, 3.6, 1.9, "19.7万手", "68.2亿"],
        ["比亚迪", "002594.SZ", 225.32, 1.18, 1.6, 1.2, "22.4万手", "50.5亿"],
        ["长安汽车", "000625.SZ", 15.74, 1.62, 2.2, 1.3, "302.0万手", "47.5亿"],
        ["浪潮信息", "000977.SZ", 41.26, 2.18, 4.2, 1.6, "103.2万手", "42.6亿"],
      ]),
    },
    {
      key: "turnover",
      label: "换手榜",
      rows: leaderboardRows([
        ["C宏工", "301662.SZ", 52.8, 12.34, 71.8, 4.2, "34.1万手", "18.0亿"],
        ["金禄电子", "301282.SZ", 31.65, 6.72, 42.6, 3.5, "28.8万手", "9.1亿"],
        ["华丰科技", "688629.SH", 36.2, 4.11, 39.4, 2.8, "24.5万手", "8.9亿"],
        ["通达海", "301378.SZ", 28.9, -1.86, 34.1, 2.1, "12.2万手", "3.5亿"],
        ["星源卓镁", "301398.SZ", 45.52, 3.18, 32.7, 2.4, "11.8万手", "5.4亿"],
        ["瑞迪智驱", "301596.SZ", 48.31, 20.01, 31.8, 4.8, "16.9万手", "8.2亿"],
        ["胜蓝股份", "300843.SZ", 31.55, 20, 30.6, 4.5, "19.1万手", "6.0亿"],
        ["南京聚隆", "300644.SZ", 27.08, 20.02, 29.3, 3.9, "13.7万手", "3.7亿"],
        ["豪恩汽电", "301488.SZ", 62.9, 20, 27.5, 3.6, "9.6万手", "6.0亿"],
        ["星辰科技", "300998.SZ", 28.6, 20, 26.8, 3.1, "18.2万手", "5.2亿"],
      ]),
    },
    {
      key: "surge",
      label: "异动榜·量比",
      rows: leaderboardRows([
        ["长盈精密", "300115.SZ", 13.54, 6.42, 9.2, 5.8, "236.5万手", "32.0亿"],
        ["三花智控", "002050.SZ", 25.88, 4.96, 6.4, 4.9, "146.5万手", "37.9亿"],
        ["天齐锂业", "002466.SZ", 38.26, 3.12, 4.3, 4.4, "74.2万手", "28.4亿"],
        ["晶澳科技", "002459.SZ", 12.42, -2.32, 3.6, 4, "202.6万手", "25.2亿"],
        ["软通动力", "301236.SZ", 45.7, 5.66, 8.1, 3.8, "51.1万手", "23.4亿"],
        ["华工科技", "000988.SZ", 43.18, 4.2, 5.2, 3.7, "52.8万手", "22.8亿"],
        ["景嘉微", "300474.SZ", 69.88, 3.44, 4.9, 3.6, "21.4万手", "15.0亿"],
        ["万马股份", "002276.SZ", 10.22, 2.88, 7.4, 3.5, "119.2万手", "12.2亿"],
        ["蓝思科技", "300433.SZ", 17.68, 2.16, 4.1, 3.2, "94.7万手", "16.7亿"],
        ["立讯精密", "002475.SZ", 32.46, 1.52, 2.8, 3, "77.5万手", "25.2亿"],
      ]),
    },
  ],
  limitStructures: {
    today: {
      selectedSectorCode: "BK1031",
      selectedStockCode: "002085.SZ",
      sectors: [
        { sectorCode: "BK1031", sectorName: "机器人", sectorType: "CONCEPT", limitUpCount: 12, ratio: 100 },
        { sectorCode: "BK2014", sectorName: "固态电池", sectorType: "CONCEPT", limitUpCount: 9, ratio: 75 },
        { sectorCode: "BK0839", sectorName: "低空经济", sectorType: "CONCEPT", limitUpCount: 8, ratio: 67 },
        { sectorCode: "BK0876", sectorName: "算力设备", sectorType: "CONCEPT", limitUpCount: 7, ratio: 58 },
        { sectorCode: "BK0435", sectorName: "军工电子", sectorType: "INDUSTRY", limitUpCount: 5, ratio: 42 },
      ],
      leaderStocks: {
        BK1031: [
          {
            stockCode: "002085.SZ",
            stockName: "万丰奥威",
            latestPrice: 18.62,
            changePct: 10.02,
            rank: 1,
            streakLabel: "首板",
            recentLimitText: "1天1板",
            firstLimitTime: "09:38:12",
            openTimes: 0,
            sealedAmountDisplayText: "5.8亿",
          },
          {
            stockCode: "002050.SZ",
            stockName: "三花智控",
            latestPrice: 25.88,
            changePct: 10.0,
            rank: 2,
            streakLabel: "首板",
            recentLimitText: "1天1板",
            firstLimitTime: "10:12:44",
            openTimes: 1,
            sealedAmountDisplayText: "3.1亿",
          },
          {
            stockCode: "301596.SZ",
            stockName: "瑞迪智驱",
            latestPrice: 48.31,
            changePct: 20.01,
            rank: 3,
            streakLabel: "2连板",
            recentLimitText: "2天2板",
            firstLimitTime: "09:52:09",
            openTimes: 1,
            sealedAmountDisplayText: "2.2亿",
          },
        ],
        BK2014: [
          {
            stockCode: "002466.SZ",
            stockName: "天齐锂业",
            latestPrice: 38.26,
            changePct: 3.12,
            rank: 1,
            streakLabel: "首板",
            recentLimitText: "1天1板",
            firstLimitTime: "10:08:22",
            openTimes: 2,
            sealedAmountDisplayText: "2.6亿",
          },
          {
            stockCode: "300750.SZ",
            stockName: "宁德时代",
            latestPrice: 213.44,
            changePct: 5.22,
            rank: 2,
            streakLabel: "首板",
            recentLimitText: "1天1板",
            firstLimitTime: "13:26:11",
            openTimes: 3,
            sealedAmountDisplayText: "4.4亿",
          },
        ],
      },
    },
    yesterday: {
      selectedSectorCode: "BK0839",
      selectedStockCode: "603017.SH",
      sectors: [
        { sectorCode: "BK0839", sectorName: "低空经济", sectorType: "CONCEPT", limitUpCount: 10, ratio: 100 },
        { sectorCode: "BK0481", sectorName: "有色金属", sectorType: "INDUSTRY", limitUpCount: 8, ratio: 80 },
        { sectorCode: "BK1031", sectorName: "机器人", sectorType: "CONCEPT", limitUpCount: 6, ratio: 60 },
        { sectorCode: "BK0428", sectorName: "电力设备", sectorType: "INDUSTRY", limitUpCount: 5, ratio: 50 },
        { sectorCode: "BK0447", sectorName: "通信设备", sectorType: "INDUSTRY", limitUpCount: 4, ratio: 40 },
      ],
      leaderStocks: {
        BK0839: [
          {
            stockCode: "603017.SH",
            stockName: "中衡设计",
            latestPrice: 12.74,
            changePct: 10.02,
            rank: 1,
            streakLabel: "2连板",
            recentLimitText: "2天2板",
            firstLimitTime: "09:41:08",
            openTimes: 0,
            sealedAmountDisplayText: "2.9亿",
          },
          {
            stockCode: "300644.SZ",
            stockName: "南京聚隆",
            latestPrice: 27.08,
            changePct: 20.02,
            rank: 2,
            streakLabel: "3连板",
            recentLimitText: "7天5板",
            firstLimitTime: "10:03:31",
            openTimes: 1,
            sealedAmountDisplayText: "1.7亿",
          },
        ],
        BK0481: [
          {
            stockCode: "000960.SZ",
            stockName: "锡业股份",
            latestPrice: 17.62,
            changePct: 10.01,
            rank: 1,
            streakLabel: "首板",
            recentLimitText: "1天1板",
            firstLimitTime: "09:56:40",
            openTimes: 2,
            sealedAmountDisplayText: "2.1亿",
          },
        ],
      },
    },
  },
  ladderV5: {
    tradeDate: "2026-04-28",
    prevTradeDate: "2026-04-27",
    highestStreakLevel: 7,
    aboveFive: [
      ladderStock("东晶电子", "002199.SZ", 10.82, 10.02, "消费电子", 1, 7, true),
      ladderStock("协和电子", "605258.SH", 37.68, 10.01, "PCB", 0, 6, true),
      ladderStock("中通客车", "000957.SZ", 12.46, 10.03, "汽车整车", 2, 6, true),
    ],
    promotions: {
      5: {
        previousLabel: "昨日四板",
        currentLabel: "今日五板",
        previousStocks: [
          ladderStock("正丹股份", "300641.SZ", 29.44, 20.02, "化工材料", 0, 5, true),
          ladderStock("双象股份", "002395.SZ", 18.31, 10.01, "光学材料", 1, 5, true),
          ladderStock("华瓷股份", "001216.SZ", 15.82, 2.16, "外贸出口", 2, 4, false),
          ladderStock("华生科技", "605180.SH", 13.06, -3.12, "低空经济", 4, 4, false),
          ladderStock("联明股份", "603006.SH", 11.27, 1.84, "汽车零部件", 1, 4, false),
        ],
        currentStocks: [
          ladderStock("正丹股份", "300641.SZ", 29.44, 20.02, "化工材料", 0, 5, true),
          ladderStock("双象股份", "002395.SZ", 18.31, 10.01, "光学材料", 1, 5, true),
        ],
      },
      4: {
        previousLabel: "昨日三板",
        currentLabel: "今日四板",
        previousStocks: [
          ladderStock("南京聚隆", "300644.SZ", 27.08, 20.02, "低空经济", 1, 4, true),
          ladderStock("豪恩汽电", "301488.SZ", 62.9, 20.0, "智能驾驶", 2, 4, true),
          ladderStock("川宁生物", "301301.SZ", 14.08, 20.01, "合成生物", 1, 4, true),
          ladderStock("恒银科技", "603106.SH", 8.72, -2.36, "金融科技", 3, 3, false),
          ladderStock("亚振家居", "603389.SH", 7.91, 1.18, "家居用品", 2, 3, false),
          ladderStock("朗威股份", "301202.SZ", 31.18, 4.62, "数据中心", 1, 3, false),
        ],
        currentStocks: [
          ladderStock("南京聚隆", "300644.SZ", 27.08, 20.02, "低空经济", 1, 4, true),
          ladderStock("豪恩汽电", "301488.SZ", 62.9, 20.0, "智能驾驶", 2, 4, true),
          ladderStock("川宁生物", "301301.SZ", 14.08, 20.01, "合成生物", 1, 4, true),
        ],
      },
      3: {
        previousLabel: "昨日二板",
        currentLabel: "今日三板",
        previousStocks: [
          ladderStock("中衡设计", "603017.SH", 12.74, 10.02, "低空经济", 0, 3, true),
          ladderStock("瑞迪智驱", "301596.SZ", 48.31, 20.01, "机器人", 1, 3, true),
          ladderStock("胜蓝股份", "300843.SZ", 31.55, 20.0, "铜缆连接", 3, 3, true),
          ladderStock("长源东谷", "603950.SH", 18.4, 10.02, "汽车零部件", 1, 3, true),
          ladderStock("奥飞数据", "300738.SZ", 12.91, 19.98, "数据中心", 2, 3, true),
          ladderStock("金溢科技", "002869.SZ", 27.66, 4.35, "智能交通", 3, 2, false),
          ladderStock("华塑科技", "301157.SZ", 39.2, -1.58, "电源设备", 2, 2, false),
          ladderStock("新亚电子", "605277.SH", 18.74, 2.06, "铜缆连接", 1, 2, false),
          ladderStock("万控智造", "603070.SH", 14.62, 0.85, "电气设备", 0, 2, false),
          ladderStock("一博科技", "301366.SZ", 41.56, -4.12, "PCB", 4, 2, false),
          ladderStock("光洋股份", "002708.SZ", 9.46, 6.18, "机器人", 1, 2, false),
          ladderStock("铭普光磁", "002902.SZ", 24.18, 1.26, "光通信", 3, 2, false),
          ladderStock("华脉科技", "603042.SH", 13.77, -2.46, "通信设备", 2, 2, false),
          ladderStock("国机精工", "002046.SZ", 13.05, 3.7, "机器人", 1, 2, false),
        ],
        currentStocks: [
          ladderStock("中衡设计", "603017.SH", 12.74, 10.02, "低空经济", 0, 3, true),
          ladderStock("瑞迪智驱", "301596.SZ", 48.31, 20.01, "机器人", 1, 3, true),
          ladderStock("胜蓝股份", "300843.SZ", 31.55, 20.0, "铜缆连接", 3, 3, true),
          ladderStock("长源东谷", "603950.SH", 18.4, 10.02, "汽车零部件", 1, 3, true),
          ladderStock("奥飞数据", "300738.SZ", 12.91, 19.98, "数据中心", 2, 3, true),
        ],
      },
      2: {
        previousLabel: "昨日首板",
        currentLabel: "今日二板",
        previousStocks: [
          ladderStock("万丰奥威", "002085.SZ", 18.62, 10.02, "低空经济", 0, 2, true),
          ladderStock("三花智控", "002050.SZ", 25.88, 10.0, "机器人", 1, 2, true),
          ladderStock("长盈精密", "300115.SZ", 13.54, 20.02, "消费电子", 2, 2, true),
          ladderStock("博俊科技", "300926.SZ", 24.3, 20.0, "汽车零部件", 1, 2, true),
          ladderStock("沃尔核材", "002130.SZ", 17.66, 10.01, "铜缆连接", 0, 2, true),
          ladderStock("金龙羽", "002882.SZ", 24.82, 10.0, "固态电池", 1, 2, true),
          ladderStock("天奇股份", "002009.SZ", 14.57, 3.18, "机器人", 2, 1, false),
          ladderStock("通合科技", "300491.SZ", 21.46, -2.07, "充电桩", 3, 1, false),
          ladderStock("海立股份", "600619.SH", 8.71, 1.55, "家电零部件", 2, 1, false),
          ladderStock("通宇通讯", "002792.SZ", 16.66, -1.38, "通信设备", 4, 1, false),
          ladderStock("鼎通科技", "688668.SH", 54.3, 5.26, "高速连接器", 1, 1, false),
          ladderStock("永贵电器", "300351.SZ", 19.12, 6.42, "轨交设备", 0, 1, false),
          ladderStock("康强电子", "002119.SZ", 13.8, -3.04, "半导体", 2, 1, false),
          ladderStock("凯旺科技", "301182.SZ", 29.84, 4.72, "消费电子", 1, 1, false),
          ladderStock("华丰科技", "688629.SH", 28.06, 7.26, "军工电子", 0, 1, false),
          ladderStock("飞龙股份", "002536.SZ", 13.98, 2.19, "汽车热管理", 2, 1, false),
        ],
        currentStocks: [
          ladderStock("万丰奥威", "002085.SZ", 18.62, 10.02, "低空经济", 0, 2, true),
          ladderStock("三花智控", "002050.SZ", 25.88, 10.0, "机器人", 1, 2, true),
          ladderStock("长盈精密", "300115.SZ", 13.54, 20.02, "消费电子", 2, 2, true),
          ladderStock("博俊科技", "300926.SZ", 24.3, 20.0, "汽车零部件", 1, 2, true),
          ladderStock("沃尔核材", "002130.SZ", 17.66, 10.01, "铜缆连接", 0, 2, true),
          ladderStock("金龙羽", "002882.SZ", 24.82, 10.0, "固态电池", 1, 2, true),
        ],
      },
    },
    firstBoard: [
      ladderStock("华工科技", "000988.SZ", 38.42, 10.01, "CPO概念", 0, 1, true),
      ladderStock("太辰光", "300570.SZ", 62.38, 20.0, "光通信", 1, 1, true),
      ladderStock("兆龙互连", "300913.SZ", 45.76, 20.01, "铜缆连接", 0, 1, true),
      ladderStock("胜宏科技", "300476.SZ", 39.62, 14.84, "PCB", 2, 1, true),
      ladderStock("工业富联", "601138.SH", 26.18, 10.02, "AI服务器", 0, 1, true),
      ladderStock("中际旭创", "300308.SZ", 156.42, 8.72, "光模块", 1, 1, true),
      ladderStock("新易盛", "300502.SZ", 128.31, 9.28, "光模块", 0, 1, true),
      ladderStock("剑桥科技", "603083.SH", 44.06, 10.01, "通信设备", 2, 1, true),
      ladderStock("中贝通信", "603220.SH", 29.64, 10.0, "算力租赁", 1, 1, true),
      ladderStock("东山精密", "002384.SZ", 22.38, 10.02, "消费电子", 0, 1, true),
      ladderStock("沪电股份", "002463.SZ", 31.56, 10.0, "PCB", 1, 1, true),
      ladderStock("世运电路", "603920.SH", 22.64, 10.02, "PCB", 2, 1, true),
      ladderStock("景旺电子", "603228.SH", 28.46, 6.42, "PCB", 1, 1, true),
      ladderStock("立讯精密", "002475.SZ", 34.28, 8.1, "消费电子", 0, 1, true),
      ladderStock("蓝思科技", "300433.SZ", 19.86, 9.42, "AI手机", 1, 1, true),
    ],
  },
  ladder: [
    { level: "首板", count: 37, stocks: [["万丰奥威", "002085.SZ", "低空经济", "18.62", "+10.02%", "0"], ["三花智控", "002050.SZ", "机器人", "25.88", "+10.00%", "1"], ["长盈精密", "300115.SZ", "消费电子", "13.54", "+20.02%", "2"]].map(([name, code, theme, price, changePct, openTimes]) => ({ name, code, theme, price, changePct, openTimes })) },
    { level: "二板", count: 9, stocks: [["中衡设计", "603017.SH", "低空经济", "12.74", "+10.02%", "0"], ["瑞迪智驱", "301596.SZ", "机器人", "48.31", "+20.01%", "1"], ["胜蓝股份", "300843.SZ", "铜缆连接", "31.55", "+20.00%", "3"]].map(([name, code, theme, price, changePct, openTimes]) => ({ name, code, theme, price, changePct, openTimes })) },
    { level: "三板", count: 4, stocks: [["南京聚隆", "300644.SZ", "低空经济", "27.08", "+20.02%", "1"], ["豪恩汽电", "301488.SZ", "智能驾驶", "62.90", "+20.00%", "2"]].map(([name, code, theme, price, changePct, openTimes]) => ({ name, code, theme, price, changePct, openTimes })) },
    { level: "四板", count: 2, stocks: [["正丹股份", "300641.SZ", "化工材料", "29.44", "+20.02%", "0"], ["川宁生物", "301301.SZ", "合成生物", "14.08", "+20.01%", "1"]].map(([name, code, theme, price, changePct, openTimes]) => ({ name, code, theme, price, changePct, openTimes })) },
    { level: "五板及以上", count: 1, stocks: [["同为股份", "002835.SZ", "AI安防", "22.16", "+10.02%", "0"]].map(([name, code, theme, price, changePct, openTimes]) => ({ name, code, theme, price, changePct, openTimes })) },
  ],
  sectors: {
    columns: [
      { key: "industryUp", title: "行业涨幅前五", tone: "up", valueLabel: "涨幅", rows: [{ name: "通信设备", text: "+3.86%", value: 3.86 }, { name: "半导体", text: "+3.12%", value: 3.12 }, { name: "汽车零部件", text: "+2.74%", value: 2.74 }, { name: "电力设备", text: "+2.31%", value: 2.31 }, { name: "军工电子", text: "+2.06%", value: 2.06 }] },
      { key: "conceptUp", title: "概念涨幅前五", tone: "up", valueLabel: "涨幅", rows: [{ name: "铜缆高速连接", text: "+5.42%", value: 5.42 }, { name: "机器人执行器", text: "+4.91%", value: 4.91 }, { name: "CPO概念", text: "+4.36%", value: 4.36 }, { name: "固态电池", text: "+3.88%", value: 3.88 }, { name: "低空经济", text: "+3.42%", value: 3.42 }] },
      { key: "regionUp", title: "地域涨幅前五", tone: "up", valueLabel: "涨幅", rows: [{ name: "广东板块", text: "+2.48%", value: 2.48 }, { name: "江苏板块", text: "+2.12%", value: 2.12 }, { name: "浙江板块", text: "+1.96%", value: 1.96 }, { name: "安徽板块", text: "+1.73%", value: 1.73 }, { name: "四川板块", text: "+1.58%", value: 1.58 }] },
      { key: "fundIn", title: "资金流入前五", tone: "up", valueLabel: "净流入", rows: [{ name: "光模块", text: "+28.6亿", value: 28.6 }, { name: "半导体设备", text: "+23.1亿", value: 23.1 }, { name: "机器人", text: "+18.2亿", value: 18.2 }, { name: "电力设备", text: "+14.8亿", value: 14.8 }, { name: "AI手机", text: "+11.6亿", value: 11.6 }] },
      { key: "industryDown", title: "行业跌幅前五", tone: "down", valueLabel: "跌幅", rows: [{ name: "房地产开发", text: "-2.42%", value: -2.42 }, { name: "酒店餐饮", text: "-1.86%", value: -1.86 }, { name: "煤炭开采", text: "-1.31%", value: -1.31 }, { name: "银行", text: "-0.72%", value: -0.72 }, { name: "保险", text: "-0.55%", value: -0.55 }] },
      { key: "conceptDown", title: "概念跌幅前五", tone: "down", valueLabel: "跌幅", rows: [{ name: "旅游出行", text: "-1.44%", value: -1.44 }, { name: "地产服务", text: "-2.18%", value: -2.18 }, { name: "预制菜", text: "-1.26%", value: -1.26 }, { name: "免税店", text: "-1.04%", value: -1.04 }, { name: "煤化工", text: "-0.92%", value: -0.92 }] },
      { key: "regionDown", title: "地域跌幅前五", tone: "down", valueLabel: "跌幅", rows: [{ name: "海南板块", text: "-1.36%", value: -1.36 }, { name: "山西板块", text: "-1.12%", value: -1.12 }, { name: "云南板块", text: "-0.86%", value: -0.86 }, { name: "黑龙江", text: "-0.72%", value: -0.72 }, { name: "内蒙古", text: "-0.64%", value: -0.64 }] },
      { key: "fundOut", title: "资金流出前五", tone: "down", valueLabel: "净流出", rows: [{ name: "房地产开发", text: "-15.4亿", value: -15.4 }, { name: "煤炭开采", text: "-11.8亿", value: -11.8 }, { name: "银行", text: "-9.6亿", value: -9.6 }, { name: "白酒", text: "-7.4亿", value: -7.4 }, { name: "旅游酒店", text: "-5.2亿", value: -5.2 }] },
    ],
    heatmap: [["算力", 3.8], ["光模块", 5.6], ["AI手机", 2.7], ["机器人", 4.8], ["固态电池", 3.5], ["低空经济", 3.1], ["军工电子", 2.1], ["汽车零部件", 1.9], ["消费电子", 2.8], ["券商", 1.1], ["白酒", 0.4], ["医药", -0.3], ["银行", -0.7], ["煤炭", -1.3], ["旅游", -1.7], ["地产", -2.4], ["保险", -0.5], ["航运港口", -0.9], ["贵金属", -1.1], ["农业", 0.6]].map(([name, pct]) => ({ name, pct })) as never,
  },
};

export async function fetchMarketOverviewMock(_params: MarketOverviewParams = {}): Promise<WealthApiResponse<MarketOverview>> {
  return {
    code: 0,
    message: "ok",
    data: marketOverviewMock,
    traceId: "wealth-mock-market-overview",
    serverTime: "2026-04-28 15:05:18",
  };
}
