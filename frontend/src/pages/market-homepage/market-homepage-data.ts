export type Trend = "up" | "down" | "flat" | "neutral";

export type NavKey = "home" | "temperature" | "emotion" | "capital" | "rotation" | "watchlist";

export interface IndexQuote {
  name: string;
  value: string;
  change: string;
  pct: string;
  trend: "up" | "down";
}

export interface RankItem {
  name: string;
  desc: string;
  heat: string;
  change: string;
  trend: "up" | "down";
}

export interface NewsItem {
  tag: string;
  title: string;
  desc: string;
  time: string;
}

export interface HistoryPoint {
  date: string;
  turnover: number;
  rising: number;
  falling: number;
  flow: number;
  insight: string;
}

export interface LadderStock {
  name: string;
  desc: string;
  meta: string;
}

export interface LadderStage {
  key: string;
  label: string;
  count: number;
  note: string;
  levelClass: string;
  stocks: LadderStock[];
}

export const navItems: Array<{ key: NavKey; label: string }> = [
  { key: "home", label: "首页" },
  { key: "temperature", label: "市场温度" },
  { key: "emotion", label: "情绪分析" },
  { key: "capital", label: "资金面" },
  { key: "rotation", label: "板块轮动" },
  { key: "watchlist", label: "自选" },
];

export const indexQuotes: IndexQuote[] = [
  { name: "上证指数", value: "3,286.17", change: "+18.42", pct: "+0.56%", trend: "up" },
  { name: "深证成指", value: "10,428.91", change: "+94.21", pct: "+0.91%", trend: "up" },
  { name: "创业板指", value: "2,118.36", change: "+27.14", pct: "+1.30%", trend: "up" },
  { name: "科创 50", value: "812.48", change: "-3.72", pct: "-0.46%", trend: "down" },
  { name: "沪深 300", value: "3,871.25", change: "+22.18", pct: "+0.58%", trend: "up" },
  { name: "中证 500", value: "5,634.92", change: "+41.73", pct: "+0.75%", trend: "up" },
  { name: "中证 1000", value: "5,812.77", change: "+63.52", pct: "+1.11%", trend: "up" },
  { name: "北证 50", value: "934.18", change: "-8.61", pct: "-0.91%", trend: "down" },
  { name: "恒生指数", value: "17,801.42", change: "+126.35", pct: "+0.71%", trend: "up" },
  { name: "恒生科技", value: "3,682.64", change: "+48.17", pct: "+1.33%", trend: "up" },
  { name: "中证红利", value: "5,218.93", change: "+11.86", pct: "+0.23%", trend: "up" },
  { name: "国证 2000", value: "7,104.33", change: "-19.47", pct: "-0.27%", trend: "down" },
];

export const sectorLeaders: RankItem[] = [
  { name: "黄金概念", desc: "避险资金回流，趋势延续", heat: "热度 96", change: "+4.82%", trend: "up" },
  { name: "液冷服务器", desc: "算力链补涨扩散", heat: "热度 93", change: "+4.37%", trend: "up" },
  { name: "铜缆高速连接", desc: "CPO 方向同步发酵", heat: "热度 89", change: "+3.91%", trend: "up" },
  { name: "电力高股息", desc: "防御资金低吸", heat: "热度 82", change: "+2.24%", trend: "up" },
];

export const sectorLosers: RankItem[] = [
  { name: "旅游酒店", desc: "节前兑现压力", heat: "热度 38", change: "-2.64%", trend: "down" },
  { name: "影视传媒", desc: "短线资金退潮", heat: "热度 34", change: "-2.21%", trend: "down" },
  { name: "白酒", desc: "权重承压拖累", heat: "热度 31", change: "-1.86%", trend: "down" },
  { name: "教育", desc: "题材轮动降温", heat: "热度 29", change: "-1.53%", trend: "down" },
];

export const stockGainers: RankItem[] = [
  { name: "华峰算力", desc: "AI 算力 · 市场高度龙头", heat: "封单 5.4 亿", change: "+10.01%", trend: "up" },
  { name: "鸿远黄金", desc: "黄金概念 · 趋势加强", heat: "换手 18.6%", change: "+10.00%", trend: "up" },
  { name: "北辰液冷", desc: "液冷服务器 · 主线补涨", heat: "封单 2.6 亿", change: "+9.99%", trend: "up" },
  { name: "盛景铜业", desc: "有色金属 · 资源轮动", heat: "换手 22.4%", change: "+9.98%", trend: "up" },
];

export const stockLosers: RankItem[] = [
  { name: "云海文旅", desc: "旅游酒店 · 高位兑现", heat: "放量回落", change: "-7.82%", trend: "down" },
  { name: "青禾传媒", desc: "影视传媒 · 资金流出", heat: "量比 2.1", change: "-6.33%", trend: "down" },
  { name: "国酿酒业", desc: "白酒 · 权重调整", heat: "弱承接", change: "-4.92%", trend: "down" },
  { name: "卓育科技", desc: "教育 · 题材降温", heat: "低开低走", change: "-4.15%", trend: "down" },
];

export const newsByTab: Record<string, NewsItem[]> = {
  今日热点: [
    { tag: "热点", title: "算力链午后再度拉升，液冷服务器方向领涨", desc: "高位龙头继续打出空间，低位补涨资金开始扩散。", time: "14:28" },
    { tag: "主题", title: "黄金、有色继续活跃，避险与通胀交易共振", desc: "资源品方向维持较高资金关注度。", time: "13:56" },
    { tag: "资金", title: "高股息电力板块逆势走强，防御资金回流", desc: "市场分歧中稳定现金流资产获得承接。", time: "11:24" },
  ],
  政策宏观: [
    { tag: "政策", title: "稳增长政策预期升温，基建链局部异动", desc: "资金更关注具备订单兑现能力的细分方向。", time: "10:42" },
    { tag: "宏观", title: "资金利率维持平稳，市场风险偏好小幅修复", desc: "量能仍未形成持续放大。", time: "09:58" },
  ],
  财经新闻: [
    { tag: "财经", title: "A 股成交额维持两万亿附近，结构分化明显", desc: "指数稳定与个股分歧并存。", time: "14:02" },
    { tag: "全球", title: "外围科技股反弹，映射国内算力方向", desc: "关注业绩与订单兑现节奏。", time: "12:18" },
  ],
  个股新闻: [
    { tag: "个股", title: "华峰算力六连板，继续刷新市场高度", desc: "短线情绪核心标的承接强。", time: "14:35" },
    { tag: "公告", title: "多家有色公司披露一季度业绩预增", desc: "资源价格上行带来业绩弹性。", time: "09:42" },
  ],
};

export const historyPoints: HistoryPoint[] = [
  { date: "04-05", turnover: 15280, rising: 2480, falling: 2760, flow: 46, insight: "量能温和，上涨家数略占优，资金仍在试探主线方向。" },
  { date: "04-06", turnover: 16120, rising: 2860, falling: 2388, flow: 68, insight: "成交额小幅放大，市场广度修复，适合观察主线延续性。" },
  { date: "04-07", turnover: 14890, rising: 1980, falling: 3320, flow: -82, insight: "缩量且下跌家数扩张，市场出现明显分歧。" },
  { date: "04-08", turnover: 17360, rising: 3120, falling: 2150, flow: 96, insight: "量能回升，上涨家数扩张，短线情绪修复。" },
  { date: "04-09", turnover: 18540, rising: 3560, falling: 1690, flow: 121, insight: "资金流入配合广度改善，市场进入偏热区。" },
  { date: "04-10", turnover: 17820, rising: 2410, falling: 2916, flow: -36, insight: "成交额仍高，但下跌家数增加，说明高位开始分歧。" },
  { date: "04-11", turnover: 19170, rising: 3218, falling: 2034, flow: 84, insight: "量能重新放大，主线承接强，交易机会集中。" },
  { date: "04-12", turnover: 18260, rising: 2260, falling: 3024, flow: -58, insight: "量能未明显衰退，但广度承压，追高风险上升。" },
  { date: "04-15", turnover: 19620, rising: 3588, falling: 1640, flow: 146, insight: "放量上涨配合资金流入，题材进入加速阶段。" },
  { date: "04-16", turnover: 18840, rising: 2940, falling: 2320, flow: 38, insight: "高位分歧但承接尚可，适合做主线内轮动。" },
  { date: "04-17", turnover: 17420, rising: 2140, falling: 3186, flow: -74, insight: "缩量回落，亏钱效应抬头，需要降低追涨频率。" },
  { date: "04-18", turnover: 16280, rising: 1820, falling: 3560, flow: -118, insight: "量能收缩且下跌家数占优，市场偏弱。" },
  { date: "04-19", turnover: 16930, rising: 2386, falling: 2904, flow: -42, insight: "弱修复，资金仍然谨慎。" },
  { date: "04-20", turnover: 18810, rising: 3180, falling: 2086, flow: 76, insight: "成交额回升，广度改善，结构性机会重新出现。" },
  { date: "04-21", turnover: 18140, rising: 2712, falling: 2540, flow: 18, insight: "多空接近平衡，适合等方向确认。" },
  { date: "04-22", turnover: 19760, rising: 3440, falling: 1818, flow: 132, insight: "资金与广度共振，市场情绪明显回暖。" },
  { date: "04-23", turnover: 20590, rising: 3026, falling: 2240, flow: 64, insight: "高成交维持，但个股分化加剧，主线以核心为主。" },
  { date: "04-24", turnover: 21473, rising: 1140, falling: 4299, flow: -128, insight: "当前选中日期量能低于近 10 日均值，同时下跌家数明显扩张，说明市场属于“缩量弱势、广度承压”的结构，追高性价比偏低。" },
  { date: "04-25", turnover: 19240, rising: 2860, falling: 2416, flow: 24, insight: "分歧后修复，仍需看量能能否继续扩张。" },
  { date: "04-26", turnover: 18330, rising: 2588, falling: 2680, flow: -16, insight: "市场重新接近平衡，热点轮动速度较快。" },
];

export const ladderStages: LadderStage[] = [
  {
    key: "first",
    label: "首板",
    count: 43,
    levelClass: "level-1",
    note: "低位补涨与新分支试错活跃。",
    stocks: [
      { name: "中科智联", desc: "算力分支 · 首板放量", meta: "封单 1.8 亿" },
      { name: "华跃资源", desc: "黄金 / 有色 · 午后回封", meta: "封单 0.9 亿" },
      { name: "远东电气", desc: "高股息电力 · 缩量首板", meta: "换手 6.4%" },
      { name: "新瀚汽车", desc: "汽车零部件 · 低位启动", meta: "换手 11.8%" },
    ],
  },
  {
    key: "two",
    label: "2 板",
    count: 8,
    levelClass: "level-2",
    note: "补涨方向开始形成梯队。",
    stocks: [
      { name: "天岳智能", desc: "AI 应用 · 竞价强势", meta: "换手 18.1%" },
      { name: "宏图材料", desc: "铜铝材料 · 跟风扩散", meta: "换手 14.5%" },
      { name: "正华科技", desc: "机器人 · 下午加强", meta: "换手 20.8%" },
    ],
  },
  {
    key: "three",
    label: "3 板",
    count: 5,
    levelClass: "level-3",
    note: "开始验证分支持续性。",
    stocks: [
      { name: "瑞能通信", desc: "CPO 概念 · 高开高走", meta: "封单 1.1 亿" },
      { name: "金盛矿业", desc: "黄金链 · 换手充分", meta: "换手 22.4%" },
      { name: "城发建设", desc: "城投基建 · 尾盘回封", meta: "封单 0.7 亿" },
    ],
  },
  {
    key: "four",
    label: "4 板",
    count: 3,
    levelClass: "level-4",
    note: "高位分歧中仍有承接。",
    stocks: [
      { name: "盛景铜业", desc: "有色金属 · 资源轮动", meta: "封单 2.4 亿" },
      { name: "远航电网", desc: "高股息电力 · 稳定承接", meta: "换手 8.1%" },
      { name: "智创互联", desc: "算力链分支 · 弹性品种", meta: "换手 24.6%" },
    ],
  },
  {
    key: "five",
    label: "5 板",
    count: 2,
    levelClass: "level-5",
    note: "核心补涨品种继续晋级。",
    stocks: [
      { name: "鸿远黄金", desc: "黄金概念 · 趋势加强", meta: "封单 3.2 亿" },
      { name: "北辰液冷", desc: "液冷服务器 · 主线补涨", meta: "封单 2.6 亿" },
    ],
  },
  {
    key: "six",
    label: "6 板",
    count: 1,
    levelClass: "level-6",
    note: "市场高度龙头仍在场。",
    stocks: [
      { name: "华峰算力", desc: "AI 算力 · 市场高度龙头", meta: "换手 21.8%" },
    ],
  },
];
