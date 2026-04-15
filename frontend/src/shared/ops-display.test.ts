import { describe, expect, it } from "vitest";

import {
  formatCategoryLabel,
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
  });

  it("把任务键映射成用户可读名称", () => {
    expect(formatSpecDisplayLabel("sync_history.stock_basic", null)).toBe("历史同步 / 股票基础信息");
    expect(formatSpecDisplayLabel("daily_market_close_sync", null)).toBe("每日收盘后同步");
    expect(formatResourceLabel("biying_moneyflow")).toBe("BIYING 资金流向");
  });
});
