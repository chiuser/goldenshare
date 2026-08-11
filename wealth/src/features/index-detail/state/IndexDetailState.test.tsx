import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { IndexDetailLoadingSkeleton } from "./IndexDetailLoadingSkeleton";
import { IndexDetailPageState } from "./IndexDetailPageState";
import { IndexDetailPartialNotice } from "./IndexDetailPartialNotice";

describe("index detail state components", () => {
  it("does not claim to load a trend channel for unsupported indices", () => {
    render(<IndexDetailLoadingSkeleton supportsTrend={false} />);
    expect(screen.getByText("正在读取日线与技术指标")).toBeInTheDocument();
    expect(screen.queryByText(/趋势通道/)).not.toBeInTheDocument();
  });

  it("uses the frozen state copy and actions", () => {
    const onBack = vi.fn();
    const onRetry = vi.fn();
    render(<IndexDetailPageState onBack={onBack} onRetry={onRetry} variant="error" />);
    expect(screen.getByText("指数详情加载失败")).toBeInTheDocument();
    expect(screen.getByText("ERROR · 请求未完成")).toBeInTheDocument();
    screen.getByRole("button", { name: "重新加载" }).click();
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("keeps Partial copy response-driven", () => {
    render(<IndexDetailPartialNotice reasons={["市净率", "成分涨跌统计（缺少 3 个成分行情）"]} variant="partial" />);
    const notice = screen.getByLabelText("部分数据缺失");
    expect(notice).toHaveTextContent("市净率");
    expect(notice).toHaveTextContent("缺少 3 个成分行情");
    expect(notice).not.toHaveTextContent("金额、TTM 市盈率、平盘数");
  });

  it("uses system semantic tokens and not market direction tokens for M4 states", () => {
    const css = readFileSync(resolve(process.cwd(), "src/pages/index-detail/index-detail-page.css"), "utf8");
    const start = css.indexOf(".index-page-state-error");
    const end = css.indexOf(".index-detail-toast");
    const stateCss = css.slice(start, end);
    expect(stateCss).toContain("var(--cs-color-danger-system)");
    expect(stateCss).toContain("var(--cs-color-warning)");
    expect(stateCss).toContain("var(--cs-color-info)");
    expect(stateCss).not.toContain("var(--cs-color-market-up)");
    expect(stateCss).not.toContain("var(--cs-color-market-down)");
  });
});
