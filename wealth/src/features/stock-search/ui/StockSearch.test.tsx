import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchStockSearch } from "../api/stockSearchApi";
import { StockSearch } from "./StockSearch";

vi.mock("../api/stockSearchApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/stockSearchApi")>();
  return { ...actual, fetchStockSearch: vi.fn() };
});

const fetchStockSearchMock = vi.mocked(fetchStockSearch);

async function showResults() {
  fireEvent.change(screen.getByRole("combobox", { name: "搜索股票" }), {
    target: { value: "600" },
  });
  act(() => vi.advanceTimersByTime(500));
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("StockSearch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    fetchStockSearchMock.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the standard input contract and focused visual state", () => {
    render(<StockSearch onSelect={vi.fn()} />);
    const input = screen.getByRole("combobox", { name: "搜索股票" });

    expect(input).toHaveAttribute("placeholder", "搜索股票代码 / 拼音首字母");
    expect(input).toHaveAttribute("maxlength", "32");
    expect(input).toHaveAttribute("autocomplete", "off");
    expect(input).toHaveAttribute("aria-autocomplete", "list");
    expect(input).toHaveAttribute("aria-expanded", "false");
    expect(input.closest(".stock-search")).toHaveAttribute("data-state", "idle");

    fireEvent.focus(input);
    expect(input.closest(".stock-search")).toHaveClass("active");
  });

  it("renders loading, empty and error as fixed polite status messages", async () => {
    const pending = new Promise<never>(() => {});
    fetchStockSearchMock.mockReturnValueOnce(pending);
    const first = render(<StockSearch onSelect={vi.fn()} />);
    fireEvent.change(screen.getByRole("combobox", { name: "搜索股票" }), {
      target: { value: "600" },
    });
    act(() => vi.advanceTimersByTime(500));
    expect(screen.getByText("搜索中…")).toHaveAttribute("aria-live", "polite");
    first.unmount();

    fetchStockSearchMock.mockResolvedValueOnce({ keyword: "ZZZZ", items: [] });
    const second = render(<StockSearch onSelect={vi.fn()} />);
    fireEvent.change(screen.getByRole("combobox", { name: "搜索股票" }), {
      target: { value: "ZZZZ" },
    });
    act(() => vi.advanceTimersByTime(500));
    await act(async () => Promise.resolve());
    expect(screen.getByText("未找到匹配的当前上市 A 股")).toHaveAttribute("aria-live", "polite");
    second.unmount();

    fetchStockSearchMock.mockRejectedValueOnce(new Error("backend detail"));
    render(<StockSearch onSelect={vi.fn()} />);
    fireEvent.change(screen.getByRole("combobox", { name: "搜索股票" }), {
      target: { value: "600" },
    });
    act(() => vi.advanceTimersByTime(500));
    await act(async () => Promise.resolve());
    expect(screen.getByText("搜索暂不可用，请稍后重试")).toHaveAttribute("aria-live", "polite");
    expect(screen.queryByText("backend detail")).not.toBeInTheDocument();
  });

  it("renders results with listbox semantics and cycles keyboard selection", async () => {
    fetchStockSearchMock.mockResolvedValue({
      keyword: "600",
      items: [
        { tsCode: "600000.SH", name: "浦发银行" },
        { tsCode: "600009.SH", name: "上海机场" },
      ],
    });
    const onSelect = vi.fn();
    render(<StockSearch onSelect={onSelect} />);
    await showResults();

    const input = screen.getByRole("combobox", { name: "搜索股票" });
    const listbox = screen.getByRole("listbox", { name: "股票搜索联想" });
    const options = within(listbox).getAllByRole("option");
    expect(options).toHaveLength(2);
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    expect(input).toHaveAttribute("aria-expanded", "true");
    expect(input).toHaveAttribute("aria-activedescendant", options[0].id);

    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(options[1]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("600000.SH");
  });

  it("commits pointer selection before blur and closes with Escape or Tab blur", async () => {
    fetchStockSearchMock.mockResolvedValue({
      keyword: "600",
      items: [
        { tsCode: "600000.SH", name: "浦发银行" },
        { tsCode: "600009.SH", name: "上海机场" },
      ],
    });
    const onSelect = vi.fn();
    const first = render(<StockSearch onSelect={onSelect} />);
    await showResults();

    fireEvent.pointerDown(screen.getByRole("option", { name: "上海机场 600009.SH" }));
    expect(onSelect).toHaveBeenCalledWith("600009.SH");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    first.unmount();

    const onSelectAfterEscape = vi.fn();
    const second = render(<StockSearch onSelect={onSelectAfterEscape} />);
    await showResults();
    const input = screen.getByRole("combobox", { name: "搜索股票" });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(input).toHaveValue("600");

    fireEvent.keyDown(input, { key: "Enter" });
    await act(async () => Promise.resolve());
    expect(onSelectAfterEscape).toHaveBeenCalledWith("600000.SH");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    second.unmount();

    render(<StockSearch onSelect={vi.fn()} />);
    await showResults();
    const blurInput = screen.getByRole("combobox", { name: "搜索股票" });
    fireEvent.blur(blurInput);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(blurInput).toHaveValue("600");
  });
});
