import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarketOverviewPage } from "./MarketOverviewPage";

describe("MarketOverviewPage", () => {
  it("renders the V1.1 market overview structure", async () => {
    render(<MarketOverviewPage />);

    expect(await screen.findByRole("heading", { name: "市场总览" })).toBeInTheDocument();
    expect(screen.getByLabelText("TopMarketBar")).toBeInTheDocument();
    expect(screen.getByLabelText("今日市场客观总结")).toBeInTheDocument();
    expect(screen.getByLabelText("主要指数")).toBeInTheDocument();
    expect(screen.getByLabelText("涨跌停统计与分布")).toBeInTheDocument();
    expect(screen.getByLabelText("板块速览")).toBeInTheDocument();
  });

  it("keeps leaderboard Top10 columns and range switching behavior", async () => {
    render(<MarketOverviewPage />);

    const table = await screen.findByRole("table", { name: "个股榜单" });
    ["排名", "股票", "最新价", "涨跌幅", "换手率", "量比", "成交量", "成交额"].forEach((column) => {
      expect(within(table).getByText(column)).toBeInTheDocument();
    });
    ["涨幅榜", "跌幅榜", "成交额榜", "换手榜", "异动榜·量比"].forEach((tab) => {
      expect(screen.getByRole("button", { name: tab })).toBeInTheDocument();
    });
    expect(within(table).getAllByRole("row")).toHaveLength(11);

    fireEvent.click(screen.getByRole("button", { name: "异动榜·量比" }));
    expect(within(table).getAllByRole("row")).toHaveLength(11);

    fireEvent.click(screen.getAllByRole("button", { name: "3个月" })[0]);
    expect(screen.getAllByRole("button", { name: "3个月" })[0]).toHaveClass("active");
  });

  it("renders sector matrix and heatmap exactly as the showcase requires", async () => {
    render(<MarketOverviewPage />);

    await screen.findByRole("heading", { name: "市场总览" });
    expect(screen.getByText("行业涨幅前五")).toBeInTheDocument();
    expect(screen.getByText("资金流出前五")).toBeInTheDocument();
    expect(screen.getAllByLabelText(/^板块热力图-/)).toHaveLength(20);
  });

  it("uses lightweight toast for reserved navigation feedback", async () => {
    render(<MarketOverviewPage />);

    fireEvent.click(await screen.findByRole("button", { name: /手动刷新/ }));
    expect(screen.getByRole("button", { name: "刷新中" })).toBeInTheDocument();
  });
});
