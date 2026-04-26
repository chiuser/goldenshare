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
  previewing: "预览中",
  completed: "已完成",
  rolled_back: "已回滚",
  fresh: "正常",
  lagging: "滞后",
  stale: "严重滞后",
  unknown: "未知",
  skipped: "未启用",
  unobserved: "未观测",
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
  maintenance: "维护动作",
};

const executorKindLabelMap: Record<string, string> = {
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
  deleted: "删除",
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
  serving_light_refreshed: "轻量层刷新成功",
  serving_light_refresh_failed: "轻量层刷新失败",
  serving_light_refresh_skipped: "轻量层刷新跳过",
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

function stripMaintenanceAffix(value: string): string {
  if (value.startsWith("维护")) {
    return value.slice("维护".length).trim() || value;
  }
  if (value.endsWith("维护")) {
    return value.slice(0, -"维护".length).trim() || value;
  }
  return value;
}

export function formatExecutionResourceLabel(item: {
  title?: string | null;
  resource_display_name?: string | null;
  action_display_name?: string | null;
}): string {
  const title = normalizeKey(item.title);
  if (title) {
    return stripMaintenanceAffix(title);
  }

  const resourceDisplayName = normalizeKey(item.resource_display_name);
  if (resourceDisplayName) {
    return resourceDisplayName;
  }

  const actionDisplayName = normalizeKey(item.action_display_name);
  if (actionDisplayName) {
    return stripMaintenanceAffix(actionDisplayName);
  }

  return "未命名任务";
}
