import { describe, expect, it } from "vitest";

import {
  actionSupportsTriggerDayPointPolicy,
  actionSupportsRemoteIndexDailyProbe,
  actionSupportsRemoteIndexMinsProbe,
  actionSupportsRemoteKplListProbe,
  actionSupportsRemoteProbeCondition,
  actionSupportsRemoteStkMinsProbe,
  actionSupportsTriggerDaySingleRangePolicy,
  buildProbeRunQueryPath,
  buildCronExpression,
  formatProbeConditionLabel,
  formatProbeRunCount,
  formatScheduleRule,
  getScheduleTimeFieldLabel,
  hasRequiredVisibleParameters,
  hasCompleteIndexMinsProbeFreqs,
  parseCronExpression,
  resolveEffectiveCalendarPolicy,
  shouldShowScheduleTimingFields,
} from "./ops-v21-task-auto-tab";

describe("自动任务日期策略", () => {
  const monthlyCalendarAction = {
    action_type: "dataset_action",
    date_selection_rule: "month_end",
  };
  const monthlyTradingAction = {
    action_type: "dataset_action",
    date_selection_rule: "month_last_trading_day",
  };
  const monthlyWindowAction = {
    action_type: "dataset_action",
    date_selection_rule: "month_window",
  };
  const annDateRangeAction = {
    action_type: "dataset_action",
    date_selection_rule: "calendar_day",
    parameters: [
      { key: "start_date" },
      { key: "end_date" },
      { key: "ann_date" },
    ],
  };
  const naturalDayTradeDateAction = {
    action_type: "dataset_action",
    target_key: "daily",
    date_selection_rule: "calendar_day",
    parameters: [
      { key: "trade_date" },
      { key: "start_date" },
      { key: "end_date" },
    ],
  };
  const newsAction = {
    action_type: "dataset_action",
    target_key: "news",
    date_selection_rule: "calendar_day",
    parameters: [
      { key: "trade_date" },
      { key: "start_date" },
      { key: "end_date" },
    ],
  };

  it("recommends monthly calendar policies from dataset date selection rules", () => {
    expect(
      resolveEffectiveCalendarPolicy({
        scheduleType: "cron",
        repeatMode: "monthly",
        selectedAction: monthlyCalendarAction as never,
      }),
    ).toBe("monthly_last_day");
    expect(
      resolveEffectiveCalendarPolicy({
        scheduleType: "cron",
        repeatMode: "monthly",
        selectedAction: monthlyTradingAction as never,
      }),
    ).toBe("monthly_last_trading_day");
    expect(
      resolveEffectiveCalendarPolicy({
        scheduleType: "cron",
        repeatMode: "monthly",
        selectedAction: monthlyWindowAction as never,
      }),
    ).toBe("monthly_window_current_month");
    expect(
      resolveEffectiveCalendarPolicy({
        scheduleType: "once",
        repeatMode: "monthly",
        selectedAction: monthlyCalendarAction as never,
      }),
    ).toBe("");
  });

  it("recommends trigger-day single-range policy for ann_date range-only datasets", () => {
    expect(actionSupportsTriggerDaySingleRangePolicy(annDateRangeAction as never)).toBe(true);
    expect(actionSupportsTriggerDaySingleRangePolicy(naturalDayTradeDateAction as never)).toBe(false);
    expect(
      resolveEffectiveCalendarPolicy({
        scheduleType: "cron",
        repeatMode: "daily",
        selectedAction: annDateRangeAction as never,
      }),
    ).toBe("trigger_day_single_range");
    expect(
      resolveEffectiveCalendarPolicy({
        scheduleType: "once",
        repeatMode: "daily",
        selectedAction: annDateRangeAction as never,
      }),
    ).toBe("");
  });

  it("uses cron only as execution time carrier for monthly_last_day", () => {
    expect(buildCronExpression("monthly", "19:00", [], "1", "monthly_last_day")).toBe("0 19 * * *");
    expect(parseCronExpression("0 19 * * *", "monthly_last_day")).toMatchObject({
      repeatMode: "monthly",
      repeatTime: "19:00",
      repeatMonthDay: "1",
    });
    expect(formatScheduleRule("cron", "0 19 * * *", null, "monthly_last_day")).toBe("每月最后一天 19:00");
  });

  it("uses cron only as execution time carrier for monthly_last_trading_day", () => {
    expect(buildCronExpression("monthly", "19:00", [], "1", "monthly_last_trading_day")).toBe("0 19 * * *");
    expect(parseCronExpression("0 19 * * *", "monthly_last_trading_day")).toMatchObject({
      repeatMode: "monthly",
      repeatTime: "19:00",
      repeatMonthDay: "1",
    });
    expect(formatScheduleRule("cron", "0 19 * * *", null, "monthly_last_trading_day")).toBe("每月最后一个交易日 19:00");
  });

  it("uses cron only as execution time carrier for monthly_window_current_month", () => {
    expect(buildCronExpression("monthly", "19:00", [], "1", "monthly_window_current_month")).toBe("0 19 * * *");
    expect(parseCronExpression("0 19 * * *", "monthly_window_current_month")).toMatchObject({
      repeatMode: "monthly",
      repeatTime: "19:00",
      repeatMonthDay: "1",
    });
    expect(formatScheduleRule("cron", "0 19 * * *", null, "monthly_window_current_month")).toBe(
      "每月最后一天 19:00，维护当月自然月窗口",
    );
  });

  it("keeps trigger_day_single_range on regular cron occurrence and labels trigger-day maintenance", () => {
    expect(buildCronExpression("daily", "19:00", [], "1", "trigger_day_single_range")).toBe("0 19 * * *");
    expect(buildCronExpression("weekly", "19:00", ["1", "5"], "1", "trigger_day_single_range")).toBe("0 19 * * 1,5");
    expect(parseCronExpression("0 19 * * *", "trigger_day_single_range")).toMatchObject({
      repeatMode: "daily",
      repeatTime: "19:00",
    });
    expect(formatScheduleRule("cron", "0 19 * * *", null, "trigger_day_single_range")).toBe("每天 19:00，维护触发日");
  });

  it("supports trigger-day point policy only for intraday news schedules", () => {
    expect(actionSupportsTriggerDayPointPolicy(newsAction as never)).toBe(true);
    expect(actionSupportsTriggerDayPointPolicy(naturalDayTradeDateAction as never)).toBe(false);
    expect(
      resolveEffectiveCalendarPolicy({
        scheduleType: "cron",
        repeatMode: "intraday_interval",
        selectedAction: newsAction as never,
      }),
    ).toBe("trigger_day_point");
    expect(
      resolveEffectiveCalendarPolicy({
        scheduleType: "cron",
        repeatMode: "intraday_interval",
        selectedAction: naturalDayTradeDateAction as never,
      }),
    ).toBe("");
  });

  it("builds and formats intraday interval cron for trigger_day_point", () => {
    expect(buildCronExpression("intraday_interval", "19:00", [], "1", "trigger_day_point", "3")).toBe("*/3 * * * *");
    expect(parseCronExpression("*/3 * * * *", "trigger_day_point")).toMatchObject({
      repeatMode: "intraday_interval",
      intradayIntervalMinutes: "3",
    });
    expect(formatScheduleRule("cron", "*/3 * * * *", null, "trigger_day_point")).toBe("每 3 分钟，维护触发日");
    expect(() => buildCronExpression("intraday_interval", "19:00", [], "1", "trigger_day_point", "2")).toThrow(
      "日内高频策略最小间隔为 3 分钟。",
    );
  });

  it("only enables remote stk_mins source probing for stk_mins maintain", () => {
    expect(actionSupportsRemoteStkMinsProbe("dataset_action", "stk_mins.maintain")).toBe(true);
    expect(actionSupportsRemoteStkMinsProbe("dataset_action", "daily.maintain")).toBe(false);
    expect(actionSupportsRemoteStkMinsProbe("workflow", "stk_mins.maintain")).toBe(false);
    expect(formatProbeConditionLabel("remote_stk_mins_ready")).toBe("源站已有分钟行情");
    expect(formatProbeConditionLabel("freshness_latest_open")).toBe("最新业务日命中最新交易日");
    expect(formatProbeRunCount(4)).toBe("已探测：4 次");
    expect(formatProbeRunCount(undefined)).toBe("已探测：—");
    expect(buildProbeRunQueryPath({ scheduleId: 12, datasetKey: "stk_mins", limit: 1 })).toBe(
      "/api/v1/ops/probes/runs?schedule_id=12&dataset_key=stk_mins&limit=1",
    );
    expect(buildProbeRunQueryPath({ scheduleId: 12, datasetKey: "stk_mins", conditionMatched: true, limit: 1 })).toBe(
      "/api/v1/ops/probes/runs?schedule_id=12&dataset_key=stk_mins&condition_matched=true&limit=1",
    );
  });

  it("only enables remote index_daily source probing for index_daily maintain", () => {
    expect(actionSupportsRemoteIndexDailyProbe("dataset_action", "index_daily.maintain")).toBe(true);
    expect(actionSupportsRemoteIndexDailyProbe("dataset_action", "daily.maintain")).toBe(false);
    expect(actionSupportsRemoteIndexDailyProbe("workflow", "index_daily.maintain")).toBe(false);
    expect(actionSupportsRemoteProbeCondition("dataset_action", "index_daily.maintain", "remote_index_daily_ready")).toBe(true);
    expect(actionSupportsRemoteProbeCondition("dataset_action", "daily.maintain", "remote_index_daily_ready")).toBe(false);
    expect(actionSupportsRemoteProbeCondition("dataset_action", "stk_mins.maintain", "remote_index_daily_ready")).toBe(false);
    expect(formatProbeConditionLabel("remote_index_daily_ready")).toBe("源站已有指数日线");
  });

  it("only enables strict remote index_mins source probing for index_mins maintain", () => {
    expect(actionSupportsRemoteIndexMinsProbe("dataset_action", "index_mins.maintain")).toBe(true);
    expect(actionSupportsRemoteIndexMinsProbe("dataset_action", "index_daily.maintain")).toBe(false);
    expect(actionSupportsRemoteIndexMinsProbe("workflow", "index_mins.maintain")).toBe(false);
    expect(actionSupportsRemoteProbeCondition("dataset_action", "index_mins.maintain", "remote_index_mins_ready")).toBe(true);
    expect(actionSupportsRemoteProbeCondition("dataset_action", "index_mins.maintain", "freshness_latest_open")).toBe(false);
    expect(actionSupportsRemoteProbeCondition("dataset_action", "daily.maintain", "freshness_latest_open")).toBe(true);
    expect(formatProbeConditionLabel("remote_index_mins_ready")).toBe("源站已有指数分钟行情");
    expect(hasCompleteIndexMinsProbeFreqs(["1min", "5min", "15min", "30min", "60min"])).toBe(true);
    expect(hasCompleteIndexMinsProbeFreqs(["1min", "5min", "15min", "30min"])).toBe(false);
    expect(hasCompleteIndexMinsProbeFreqs(["1min", "5min", "15min", "30min", "60min", "60min"])).toBe(false);
  });

  it("only enables remote kpl_list source probing for kpl_list maintain", () => {
    expect(actionSupportsRemoteKplListProbe("dataset_action", "kpl_list.maintain")).toBe(true);
    expect(actionSupportsRemoteKplListProbe("dataset_action", "daily.maintain")).toBe(false);
    expect(actionSupportsRemoteKplListProbe("workflow", "kpl_list.maintain")).toBe(false);
    expect(actionSupportsRemoteProbeCondition("dataset_action", "kpl_list.maintain", "remote_kpl_list_ready")).toBe(true);
    expect(actionSupportsRemoteProbeCondition("dataset_action", "daily.maintain", "remote_kpl_list_ready")).toBe(false);
    expect(formatProbeConditionLabel("remote_kpl_list_ready")).toBe("源站已有开盘啦榜单");
  });

  it("hides schedule timing fields for pure probe and relabels fallback timing", () => {
    expect(shouldShowScheduleTimingFields("probe")).toBe(false);
    expect(shouldShowScheduleTimingFields("schedule")).toBe(true);
    expect(shouldShowScheduleTimingFields("schedule_probe_fallback")).toBe(true);
    expect(getScheduleTimeFieldLabel("schedule")).toBe("执行时间");
    expect(getScheduleTimeFieldLabel("schedule_probe_fallback")).toBe("兜底执行时间");
  });

  it("opens maintenance parameters when visible required parameters exist", () => {
    expect(hasRequiredVisibleParameters([
      {
        key: "ts_code",
        display_name: "证券代码",
        param_type: "string",
        description: "",
        required: true,
        options: [],
        multi_value: false,
        default_value: null,
      },
    ])).toBe(true);
    expect(hasRequiredVisibleParameters([
      {
        key: "trade_date",
        display_name: "交易日期",
        param_type: "date",
        description: "",
        required: true,
        options: [],
        multi_value: false,
        default_value: null,
      },
      {
        key: "limit",
        display_name: "分页条数",
        param_type: "integer",
        description: "",
        required: true,
        options: [],
        multi_value: false,
        default_value: null,
      },
    ])).toBe(false);
  });
});
