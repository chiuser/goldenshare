import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../../features/auth/model/AuthProvider";
import { WealthRouter } from "../../app/routes/WealthRouter";
import { StockDetailPage } from "./StockDetailPage";

describe("StockDetailPage", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    window.localStorage.clear();
    window.history.replaceState({}, "", "/wealth/market/overview");
  });

  it("renders stock detail route for authenticated users", () => {
    window.localStorage.setItem("wealth.auth.access-token", "mock-token");
    window.history.replaceState({}, "", "/wealth/market/stock/603806.SH");

    render(
      <AuthProvider>
        <WealthRouter />
      </AuthProvider>,
    );

    expect(screen.getByLabelText("TopMarketBar")).toBeInTheDocument();
    expect(screen.getByText("福斯特 603806.SH")).toBeInTheDocument();
    expect(screen.getByLabelText("K线主图")).toBeInTheDocument();
    expect(screen.getByLabelText("右侧信息栏")).toBeInTheDocument();
  });

  it("supports visible period, overlay, tab and toast interactions", () => {
    render(<StockDetailPage tsCode="603806.SH" />);

    fireEvent.click(screen.getByRole("button", { name: "周K" }));
    expect(screen.getByText(/周期：week/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("主图指标切换"), { target: { value: "BOLL" } });
    expect(screen.getByText(/UPPER:/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "资料" }));
    expect(screen.getByText("公司资料、财务摘要与公告入口将在后续真实 API 方案中接入。")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "主力密码" }));
    expect(screen.getByText("主力密码 指标暂未支持")).toBeInTheDocument();
  });
});
