import { describe, expect, it } from "vitest";

import {
  formatCategoryLabel,
  formatEventTypeLabel,
  formatExecutionResourceLabel,
  formatResourceLabel,
  formatSpecDisplayLabel,
  formatStatusLabel,
  formatTriggerSourceLabel,
} from "./ops-display";


describe("运维前端显示层映射", () => {
  it("把内部状态和值映射成中文", () => {
    expect(formatStatusLabel("queued")).toBe("等待开始");
    expect(formatStatusLabel("canceling")).toBe("停止中");
    expect(formatTriggerSourceLabel("retry")).toBe("重新提交");
    expect(formatCategoryLabel("backfill_index_series")).toBe("指数纵向回补");
    expect(formatEventTypeLabel("serving_light_refreshed")).toBe("轻量层刷新成功");
  });

  it("把任务键映射成用户可读名称", () => {
    expect(formatSpecDisplayLabel("sync_history.stock_basic", null)).toBe("历史同步 / 股票基础信息");
    expect(formatSpecDisplayLabel("sync_daily.stk_limit", null)).toBe("日常同步 / 每日涨跌停价格");
    expect(formatSpecDisplayLabel("sync_minute_history.stk_mins", null)).toBe("分钟行情同步 / 股票历史分钟行情");
    expect(formatSpecDisplayLabel("daily_market_close_sync", null)).toBe("每日收盘后同步");
    expect(formatSpecDisplayLabel("daily_moneyflow_sync", null)).toBe("每日资金流向同步");
    expect(formatResourceLabel("biying_moneyflow")).toBe("BIYING 资金流向");
    expect(formatResourceLabel("moneyflow_ind_dc")).toBe("板块资金流向（东方财富）");
    expect(formatResourceLabel("margin")).toBe("融资融券交易汇总");
    expect(formatResourceLabel("stock_st")).toBe("ST股票列表");
    expect(formatResourceLabel("stk_nineturn")).toBe("神奇九转指标");
    expect(formatResourceLabel("stk_mins")).toBe("股票历史分钟行情");
  });

  it("任务记录和详情优先使用维护对象名称", () => {
    expect(formatExecutionResourceLabel({
      resource_display_name: "股票日线",
      action_display_name: "维护股票日线",
      spec_display_name: "日常同步 / daily",
      spec_key: "sync_daily.daily",
    })).toBe("股票日线");
    expect(formatExecutionResourceLabel({
      action_display_name: "维护东方财富热榜",
      spec_display_name: "按交易日回补 / dc_hot",
      spec_key: "backfill_by_trade_date.dc_hot",
    })).toBe("东方财富热榜");
    expect(formatExecutionResourceLabel({
      spec_display_name: "维护股票历史分钟行情",
      spec_key: "sync_minute_history.stk_mins",
    })).toBe("股票历史分钟行情");
    expect(formatExecutionResourceLabel({
      spec_display_name: "股票日线维护",
      spec_key: "backfill_equity_series.daily",
    })).toBe("股票日线");
    expect(formatExecutionResourceLabel({
      spec_key: "unknown.spec",
    })).toBe("unknown.spec");
  });
});
