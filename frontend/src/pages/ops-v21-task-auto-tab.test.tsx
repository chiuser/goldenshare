import { describe, expect, it } from "vitest";

import {
  actionSupportsTriggerDayPointPolicy,
  actionSupportsRemoteStkMinsProbe,
  actionSupportsTriggerDaySingleRangePolicy,
  buildCronExpression,
  formatProbeConditionLabel,
  formatScheduleRule,
  parseCronExpression,
  resolveEffectiveCalendarPolicy,
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
  });
});
