import { describe, expect, it } from "vitest";

import {
  formatCategoryLabel,
  formatEventTypeLabel,
  formatExecutionResourceLabel,
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

  it("任务记录和详情只使用后端返回的结构化名称", () => {
    expect(formatExecutionResourceLabel({
      resource_display_name: "股票日线",
      action_display_name: "维护股票日线",
    })).toBe("股票日线");
    expect(formatExecutionResourceLabel({
      action_display_name: "维护东方财富热榜",
    })).toBe("东方财富热榜");
    expect(formatExecutionResourceLabel({
      title: "维护股票日线",
    })).toBe("股票日线");
    expect(formatExecutionResourceLabel({})).toBe("未命名任务");
  });
});
