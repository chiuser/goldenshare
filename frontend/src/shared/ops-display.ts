const statusLabelMap: Record<string, string> = {
  queued: "等待开始",
  running: "执行中",
  canceling: "停止中",
  success: "执行成功",
  failed: "执行失败",
  canceled: "已取消",
  partial_success: "部分成功",
  active: "已启用",
  paused: "已暂停",
  disabled: "已停用",
  fresh: "正常",
  lagging: "滞后",
  stale: "严重滞后",
  unknown: "未知",
  info: "提示",
  warning: "警告",
  error: "错误",
};

const triggerSourceLabelMap: Record<string, string> = {
  manual: "手动",
  scheduled: "自动",
  retry: "重新提交",
  system: "系统触发",
};

const scheduleTypeLabelMap: Record<string, string> = {
  once: "单次执行",
  cron: "按周期执行",
};

const environmentLabelMap: Record<string, string> = {
  local: "本地开发",
  dev: "开发环境",
  production: "生产环境",
  test: "测试环境",
};

const healthStatusLabelMap: Record<string, string> = {
  ok: "正常",
  loading: "加载中",
  active: "已登录",
  anonymous: "未登录",
};

const categoryLabelMap: Record<string, string> = {
  sync_history: "历史同步",
  sync_daily: "日常同步",
  backfill_trade_cal: "交易日历回补",
  backfill_equity_series: "股票纵向回补",
  backfill_by_trade_date: "按交易日回补",
  backfill_by_date_range: "按日期区间回补",
  backfill_low_frequency: "低频事件回补",
  backfill_fund_series: "基金纵向回补",
  backfill_index_series: "指数纵向回补",
  maintenance: "维护动作",
};

const executorKindLabelMap: Record<string, string> = {
  sync_service: "同步服务",
  history_backfill_service: "历史回补服务",
  maintenance: "维护任务",
};

const parallelPolicyLabelMap: Record<string, string> = {
  by_dependency: "按依赖顺序推进",
};

const revisionActionLabelMap: Record<string, string> = {
  created: "新建",
  updated: "修改",
  paused: "暂停",
  resumed: "恢复",
};

const eventTypeLabelMap: Record<string, string> = {
  created: "已创建",
  queued: "已提交",
  cancel_requested: "已请求取消",
  canceled: "已取消",
  started: "开始执行",
  succeeded: "执行完成",
  failed: "执行失败",
  partial_success: "部分成功",
  step_started: "步骤开始",
  step_succeeded: "步骤完成",
  step_failed: "步骤失败",
  step_progress: "步骤进度",
};

const runTypeLabelMap: Record<string, string> = {
  FULL: "全量执行",
  INCREMENTAL: "增量执行",
};

const unitKindLabelMap: Record<string, string> = {
  ts_code: "证券代码",
  trade_date: "交易日期",
  index_code: "指数代码",
  con_code: "板块代码",
  exchange: "交易所",
  dataset: "数据集",
  security: "证券",
};

const timezoneLabelMap: Record<string, string> = {
  "Asia/Shanghai": "北京时间",
};

const serviceNameLabelMap: Record<string, string> = {
  "goldenshare-web": "财势乾坤 Web 服务",
};

const resourceLabelMap: Record<string, string> = {
  trade_cal: "交易日历",
  stock_basic: "股票基础信息",
  hk_basic: "港股列表",
  us_basic: "美股列表",
  etf_basic: "ETF 基础信息",
  index_basic: "指数基础信息",
  daily: "股票日线",
  adj_factor: "复权因子",
  daily_basic: "每日指标",
  moneyflow: "资金流向",
  top_list: "龙虎榜",
  block_trade: "大宗交易",
  dividend: "分红送转",
  stk_holdernumber: "股东户数",
  limit_list_d: "涨跌停明细",
  fund_daily: "基金日线",
  index_daily: "指数日线",
  stk_period_bar_week: "股票周线",
  stk_period_bar_month: "股票月线",
  stk_period_bar_adj_week: "股票周线（复权）",
  stk_period_bar_adj_month: "股票月线（复权）",
  index_weekly: "指数周线",
  index_monthly: "指数月线",
  index_weight: "指数成分权重",
  index_daily_basic: "指数每日指标",
  ths_index: "同花顺概念和行业指数",
  ths_member: "同花顺板块成分",
  ths_daily: "同花顺板块行情",
  dc_index: "东方财富概念板块",
  dc_member: "东方财富板块成分",
  dc_daily: "东方财富板块行情",
  ths_hot: "同花顺热榜",
  dc_hot: "东方财富热榜",
  kpl_list: "开盘啦榜单",
  kpl_concept_cons: "开盘啦题材成分",
  rebuild_dm: "数据集市刷新",
};

const specPrefixLabelMap: Record<string, string> = {
  sync_history: "历史同步",
  sync_daily: "日常同步",
  backfill_trade_cal: "交易日历回补",
  backfill_equity_series: "股票纵向回补",
  backfill_by_trade_date: "按交易日回补",
  backfill_by_date_range: "按日期区间回补",
  backfill_low_frequency: "低频事件回补",
  backfill_fund_series: "基金纵向回补",
  backfill_index_series: "指数纵向回补",
  maintenance: "维护动作",
};

const workflowLabelMap: Record<string, string> = {
  reference_data_refresh: "基础主数据刷新",
  daily_market_close_sync: "每日收盘后同步",
  index_extension_backfill: "指数扩展数据补齐",
  board_reference_refresh: "板块主数据刷新",
};

function normalizeKey(value: string | null | undefined): string {
  return (value || "").trim();
}

export function formatStatusLabel(value: string | null | undefined): string {
  const key = normalizeKey(value).toLowerCase();
  return statusLabelMap[key] || "未定义";
}

export function formatTriggerSourceLabel(value: string | null | undefined): string {
  const key = normalizeKey(value).toLowerCase();
  return triggerSourceLabelMap[key] || "未定义";
}

export function formatScheduleTypeLabel(value: string | null | undefined): string {
  const key = normalizeKey(value).toLowerCase();
  return scheduleTypeLabelMap[key] || "未定义";
}

export function formatEnvironmentLabel(value: string | null | undefined): string {
  const key = normalizeKey(value).toLowerCase();
  return environmentLabelMap[key] || "未识别环境";
}

export function formatHealthStatusLabel(value: string | null | undefined): string {
  const key = normalizeKey(value).toLowerCase();
  return healthStatusLabelMap[key] || "未知";
}

export function formatCategoryLabel(value: string | null | undefined): string {
  const key = normalizeKey(value).toLowerCase();
  return categoryLabelMap[key] || "其他";
}

export function formatExecutorKindLabel(value: string | null | undefined): string {
  const key = normalizeKey(value).toLowerCase();
  return executorKindLabelMap[key] || "其他执行方式";
}

export function formatParallelPolicyLabel(value: string | null | undefined): string {
  const key = normalizeKey(value).toLowerCase();
  return parallelPolicyLabelMap[key] || "未定义";
}

export function formatRevisionActionLabel(value: string | null | undefined): string {
  const key = normalizeKey(value).toLowerCase();
  return revisionActionLabelMap[key] || "未知操作";
}

export function formatEventTypeLabel(value: string | null | undefined): string {
  const key = normalizeKey(value).toLowerCase();
  return eventTypeLabelMap[key] || "未定义事件";
}

export function formatRunTypeLabel(value: string | null | undefined): string {
  const key = normalizeKey(value).toUpperCase();
  return runTypeLabelMap[key] || "未定义方式";
}

export function formatUnitKindLabel(value: string | null | undefined): string {
  const key = normalizeKey(value).toLowerCase();
  return unitKindLabelMap[key] || "执行单元";
}

export function formatTimezoneLabel(value: string | null | undefined): string {
  const key = normalizeKey(value);
  return timezoneLabelMap[key] || "自定义时区";
}

export function formatServiceNameLabel(value: string | null | undefined): string {
  const key = normalizeKey(value);
  return serviceNameLabelMap[key] || "系统服务";
}

export function formatResourceLabel(value: string | null | undefined): string {
  const key = normalizeKey(value);
  return resourceLabelMap[key] || `未配置显示名称（${key || "未知资源"}）`;
}

export function formatSpecDisplayLabel(
  specKey: string | null | undefined,
  specDisplayName: string | null | undefined,
): string {
  const key = normalizeKey(specKey);
  if (!key) {
    return specDisplayName || "未命名任务";
  }

  if (workflowLabelMap[key]) {
    return workflowLabelMap[key];
  }

  if (key.includes(".")) {
    const [prefix, resource] = key.split(".", 2);
    return `${specPrefixLabelMap[prefix] || "任务"} / ${formatResourceLabel(resource)}`;
  }

  return specDisplayName || "未命名任务";
}
