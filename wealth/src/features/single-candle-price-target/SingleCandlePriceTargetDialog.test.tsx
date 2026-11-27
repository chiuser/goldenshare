import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SingleCandlePriceTargetDialog } from "./SingleCandlePriceTargetDialog";
import { calculatePriceTarget, type PriceTargetAsset } from "./singleCandlePriceTarget";

const stocks = [
  { kind: "stock", name: "贵州茅台", tsCode: "600519.SH" },
  { kind: "stock", name: "宁德时代", tsCode: "300750.SZ" },
] as const;
const indices = [
  { kind: "index", name: "上证指数", tsCode: "000001.SH" },
  { kind: "index", name: "创业板指", tsCode: "399006.SZ" },
] as const;
const selectedDate = "2025-06-26";
const previousDate = "2025-06-23";
// Keys and optional price fields follow StockDailyKlineBarDto and IndexKlineBarDto.
// Use distinct values and a different preClose to catch accidental field substitution.
const current = { tradeDate: selectedDate, open: 102, high: 107, low: 101, close: 105, preClose: 88, changePct: 0 };
const previous = { ...current, tradeDate: previousDate, close: 100 };

function payload(asset: PriceTargetAsset, bars: object[] = [previous, current]) {
  const identity = { tsCode: asset.tsCode, name: asset.name };
  return asset.kind === "stock"
    ? { stockRef: identity, period: "day", adjustment: "forward", sourceAdjustment: "qfq", bars, dataStatus: { status: "READY" } }
    : { indexRef: identity, period: "day", bars, dataStatus: { status: "PARTIAL" } };
}

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}

function mockFetch() {
  const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>();
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function openDialog(asset: PriceTargetAsset) {
  function Harness() {
    const [trigger, setTrigger] = useState<HTMLButtonElement | null>(null);
    return <>
      <button type="button" onClick={(event) => setTrigger(event.currentTarget)}>打开测算</button>
      {trigger && <SingleCandlePriceTargetDialog asset={asset} trigger={trigger} onClose={() => setTrigger(null)} />}
    </>;
  }
  const view = render(<Harness />);
  const launch = screen.getByRole("button", { name: "打开测算" });
  fireEvent.click(launch);
  const dialog = screen.getByRole("dialog", { name: "单阳测顶" });
  const body = within(dialog);
  return {
    view, launch, dialog, body,
    date: body.getByLabelText<HTMLInputElement>("交易日"),
    coefficient: body.getByLabelText<HTMLInputElement>("测算系数"),
    calculate: body.getByRole("button", { name: "计算" }),
    result: dialog.querySelector("output")!,
  };
}

describe("single candle price target", () => {
  afterEach(() => vi.unstubAllGlobals());

  it.each([
    [stocks[0], "0.85", "1.15"], [stocks[1], "0.85", "1.15"],
    [indices[0], "0.90", "1.10"], [indices[1], "0.90", "1.10"],
  ])("uses the fixed defaults for $name and resets on reopen", (asset, top, bottom) => {
    const fetchMock = mockFetch();
    const { launch, body, date, coefficient, calculate, result } = openDialog(asset);
    expect(body.getByText(asset.name)).toBeInTheDocument();
    expect(body.getByText(asset.tsCode)).toBeInTheDocument();
    expect(date).toHaveFocus();
    expect(date).toHaveValue("");
    expect(coefficient.value).toBe(top);
    expect(calculate).toBeDisabled();
    expect(result).toHaveTextContent("—");
    expect(body.getByText("选择交易日后查看行情")).toBeInTheDocument();
    fireEvent.click(body.getByRole("button", { name: "单阴测底" }));
    expect(screen.getByRole("dialog", { name: "单阴测底" })).toBeInTheDocument();
    expect(coefficient.value).toBe(bottom);
    fireEvent.change(coefficient, { target: { value: "1" } });
    fireEvent.click(body.getByRole("button", { name: "单阴测底" }));
    expect(coefficient.value).toBe("1");
    fireEvent.click(body.getByRole("button", { name: "关闭" }));
    expect(launch).toHaveFocus();
    fireEvent.click(launch);
    const reopened = within(screen.getByRole("dialog", { name: "单阳测顶" }));
    expect(reopened.getByLabelText<HTMLInputElement>("测算系数").value).toBe(top);
    expect(reopened.getByLabelText("交易日")).toHaveValue("");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([[stocks[0], "129.71", "元"], [indices[0], "122.50", "点"]])(
    "loads two actual daily rows and computes using their closes for $name",
    async (asset, expected, unit) => {
      const fetchMock = mockFetch().mockResolvedValueOnce(json(payload(asset)));
      const { body, date, coefficient, calculate, result } = openDialog(asset);
      fireEvent.change(date, { target: { value: selectedDate } });
      expect(body.getByText("正在读取日线行情…")).toBeInTheDocument();
      expect(await body.findByText("107.00")).toBeInTheDocument();
      for (const value of ["102.00", "101.00", "105.00", "0.00%", "100.00", previousDate]) {
        expect(body.getByText(value)).toBeInTheDocument();
      }
      expect(body.queryByText("88.00")).not.toBeInTheDocument();
      const [address, options] = fetchMock.mock.calls[0]!;
      const url = new URL(address);
      expect(url.pathname).toBe(`/api/v1/wealth/market/${asset.kind}-detail/kline`);
      expect(Object.fromEntries(url.searchParams)).toEqual({
        tsCode: asset.tsCode, period: "day", endDate: selectedDate, limit: "2",
        ...(asset.kind === "stock" ? { adjustment: "forward" } : {}),
      });
      expect(options?.signal).toBeInstanceOf(AbortSignal);

      fireEvent.click(calculate);
      expect(result).toHaveTextContent(expected + unit);
      expect(within(result).getByText(expected)).toHaveClass("up");
      fireEvent.change(coefficient, { target: { value: "1" } });
      expect(result).toHaveTextContent("—");
      expect(within(result).queryByText(unit)).not.toBeInTheDocument();
      fireEvent.click(calculate);
      expect(result).toHaveTextContent("110.25" + unit);
      fireEvent.click(body.getByRole("button", { name: "单阴测底" }));
      expect(result).toHaveTextContent("—");
      fireEvent.click(calculate);
      expect(result.querySelector("strong")).toHaveClass("down");
      expect(fetchMock).toHaveBeenCalledTimes(1);
    },
  );

  it.each([
    [[previous], "所选交易日暂无日线行情"],
    [[current], "缺少前一交易日收盘价"],
    [[previous, { ...current, close: null }], "缺少所选交易日收盘价"],
  ])("requires a matching day and valid closes (%j)", async (bars, message) => {
    mockFetch().mockResolvedValueOnce(json(payload(stocks[0], bars)));
    const { body, date, calculate } = openDialog(stocks[0]);
    fireEvent.change(date, { target: { value: selectedDate } });
    expect(await body.findByText(message)).toBeInTheDocument();
    expect(date).toHaveValue(selectedDate);
    expect(calculate).toBeDisabled();
  });

  it("cancels superseded and closed requests, ignores late results, and retries the same date", async () => {
    const next = "2025-06-27";
    const late = "2025-06-30";
    let resolveFirst!: (value: Response) => void;
    const fetchMock = mockFetch()
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }))
      .mockResolvedValueOnce(json({ message: "unavailable" }, 503))
      .mockResolvedValueOnce(json(payload(stocks[0], [current, { ...current, tradeDate: next, close: 104 }])))
      .mockImplementationOnce(() => new Promise(() => {}));
    const { body, dialog, date, coefficient, calculate, launch } = openDialog(stocks[0]);
    fireEvent.change(date, { target: { value: selectedDate } });
    fireEvent.change(coefficient, { target: { value: "1.025" } });
    fireEvent.change(date, { target: { value: next } });
    expect(fetchMock.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
    expect(await body.findByText("日线行情读取失败")).toBeInTheDocument();
    fireEvent.click(body.getByRole("button", { name: "重试" }));
    expect(new URL(fetchMock.mock.calls[2]![0]).searchParams.get("endDate")).toBe(next);
    expect(await body.findByText("104.00")).toBeInTheDocument();
    await act(async () => resolveFirst(json(payload(stocks[0]))));
    expect(body.getByText("104.00")).toBeInTheDocument();
    expect(coefficient.value).toBe("1.025");
    expect(calculate).toBeEnabled();
    fireEvent.change(date, { target: { value: late } });
    fireEvent(dialog, new Event("cancel", { cancelable: true }));
    expect(fetchMock.mock.calls[3]?.[1]?.signal?.aborted).toBe(true);
    expect(launch).toHaveFocus();
  });

  it("rejects invalid coefficients and a non-finite result", async () => {
    mockFetch().mockResolvedValueOnce(json(payload(indices[0])));
    const { body, date, coefficient, calculate, result } = openDialog(indices[0]);
    fireEvent.change(date, { target: { value: selectedDate } });
    expect(await body.findByText("105.00")).toBeInTheDocument();
    for (const value of ["", "0", "-1", "1e309"]) {
      fireEvent.change(coefficient, { target: { value } });
      expect(calculate).toBeDisabled();
      expect(body.getByText("请输入大于 0 的有效系数")).toBeInTheDocument();
    }
    fireEvent.change(coefficient, { target: { value: "1e-320" } });
    fireEvent.click(calculate);
    expect(result).toHaveTextContent("—");
    expect(body.getByText("测算结果超出可显示范围")).toBeInTheDocument();
    fireEvent.change(coefficient, { target: { value: "0.01" } });
    fireEvent.click(calculate);
    expect(result).toHaveTextContent("11,025.00点");
  });

  it("matches independent arithmetic for both bottom coefficients", () => {
    expect(calculatePriceTarget(95, 100, 1.1)?.toFixed(2)).toBe("82.05");
    expect(calculatePriceTarget(95, 100, 1.15)?.toFixed(2)).toBe("78.48");
  });
});
