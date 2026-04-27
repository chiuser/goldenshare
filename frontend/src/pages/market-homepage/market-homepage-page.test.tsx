import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MarketHomepagePage } from "./market-homepage-page";

describe("MarketHomepagePage", () => {
  it("renders the V10 homepage modules", () => {
    render(<MarketHomepagePage />);

    expect(screen.getByRole("heading", { name: "财势乾坤" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "市场总览" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "主要指数" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "板块领涨领跌" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "个股领涨领跌" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "新闻板块" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "操作建议" })).toBeInTheDocument();
    expect(screen.getByText("上证指数")).toBeInTheDocument();
    expect(screen.getByText("+0.56%")).toBeInTheDocument();
    expect(screen.getByText("-0.46%")).toBeInTheDocument();
  });

  it("switches to emotion page, updates range, links hover state, and opens drawer", () => {
    render(<MarketHomepagePage />);

    fireEvent.click(screen.getByRole("button", { name: "情绪分析" }));
    expect(screen.getByRole("heading", { name: "情绪分析" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "成交额" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "涨跌分布" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "连板天梯" })).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("tab", { name: "5日" })[0]);
    expect(screen.getByText("近 5 日均值：18,240 亿")).toBeInTheDocument();

    fireEvent.mouseEnter(screen.getByTestId("turnover-hover-04-23"));
    expect(screen.getAllByText("20,590 亿").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "查看全部 43 只" }));
    const drawer = screen.getByRole("dialog", { name: "连板股票列表" });
    expect(within(drawer).getByText("首板 · 全部 43 只")).toBeInTheDocument();
    expect(within(drawer).getByText("中科智联")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByText("首板 · 全部 43 只")).not.toBeInTheDocument();
  });
});
