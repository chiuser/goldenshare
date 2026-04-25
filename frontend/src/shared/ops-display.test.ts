import { describe, expect, it } from "vitest";

import {
  formatCategoryLabel,
  formatEventTypeLabel,
  formatExecutionResourceLabel,
  formatProgressMessageLabel,
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
    expect(formatCategoryLabel("maintenance")).toBe("维护动作");
    expect(formatEventTypeLabel("serving_light_refreshed")).toBe("轻量层刷新成功");
  });

  it("把任务键映射成用户可读名称", () => {
    expect(formatSpecDisplayLabel("stock_basic.maintain", "维护股票主数据")).toBe("股票主数据");
    expect(formatSpecDisplayLabel("stk_limit.maintain", null)).toBe("每日涨跌停价格");
    expect(formatSpecDisplayLabel("stk_mins.maintain", null)).toBe("股票历史分钟行情");
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
      spec_display_name: "维护股票日线",
      spec_key: "daily.maintain",
    })).toBe("股票日线");
    expect(formatExecutionResourceLabel({
      action_display_name: "维护东方财富热榜",
      spec_display_name: "维护东方财富热榜",
      spec_key: "dc_hot.maintain",
    })).toBe("东方财富热榜");
    expect(formatExecutionResourceLabel({
      spec_display_name: "维护股票历史分钟行情",
      spec_key: "stk_mins.maintain",
    })).toBe("股票历史分钟行情");
    expect(formatExecutionResourceLabel({
      spec_display_name: "股票日线维护",
      spec_key: "daily.maintain",
    })).toBe("股票日线");
    expect(formatExecutionResourceLabel({
      spec_key: "unknown.spec",
    })).toBe("unknown.spec");
  });

  it("把同步进度 token 转成运营可读说明", () => {
    expect(formatProgressMessageLabel(
      "dc_hot: 4/5 trade_date=2026-04-23 unit_fetched=4751 unit_written=4751 unit_committed=4751 fetched=12000 written=12000 committed=12000 rejected=0",
    )).toBe(
      "东方财富热榜：已完成 4/5 个处理单元。当前日期：2026-04-23。当前处理对象结果：读取 4751 条，已提交 4751 条。累计结果：读取 12000 条，已提交 12000 条，拒绝 0 条。",
    );
  });
});
