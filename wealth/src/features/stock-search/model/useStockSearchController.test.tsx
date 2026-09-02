import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchStockSearch } from "../api/stockSearchApi";
import {
  STOCK_SEARCH_DEBOUNCE_MS,
  STOCK_SEARCH_TIMEOUT_MS,
  useStockSearchController,
} from "./useStockSearchController";

vi.mock("../api/stockSearchApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/stockSearchApi")>();
  return { ...actual, fetchStockSearch: vi.fn() };
});

const fetchStockSearchMock = vi.mocked(fetchStockSearch);

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function ControllerHarness({ onSelect }: { onSelect: (tsCode: string) => void }) {
  const controller = useStockSearchController({ onSelect });
  return (
    <div>
      <input
        aria-label="controller-input"
        value={controller.inputValue}
        onChange={(event) => controller.handleInputChange(event.target.value)}
        onKeyDown={(event) => {
          if (controller.handleKeyDown(event.key)) event.preventDefault();
        }}
      />
      <output aria-label="controller-state">{JSON.stringify(controller.state)}</output>
      {controller.state.kind === "ready"
        ? controller.state.options.map((option, index) => (
            <button
              key={option.tsCode}
              type="button"
              onClick={() => controller.selectIndex(index)}
            >
              {option.tsCode}
            </button>
          ))
        : null}
    </div>
  );
}

async function flushPromises() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("useStockSearchController", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    fetchStockSearchMock.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("waits through 499ms and requests exactly at 500ms", async () => {
    fetchStockSearchMock.mockResolvedValue({ keyword: "600", items: [] });
    render(<ControllerHarness onSelect={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("controller-input"), {
      target: { value: "600" },
    });
    act(() => vi.advanceTimersByTime(STOCK_SEARCH_DEBOUNCE_MS - 1));
    expect(fetchStockSearchMock).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(1));
    expect(fetchStockSearchMock).toHaveBeenCalledTimes(1);
    expect(fetchStockSearchMock).toHaveBeenCalledWith(
      "600",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    await flushPromises();
    expect(screen.getByLabelText("controller-state")).toHaveTextContent('"kind":"empty"');
  });

  it("resets debounce and invalidates an older keyword", async () => {
    fetchStockSearchMock.mockResolvedValue({ keyword: "60", items: [] });
    render(<ControllerHarness onSelect={vi.fn()} />);

    const input = screen.getByLabelText("controller-input");
    fireEvent.change(input, { target: { value: "6" } });
    act(() => vi.advanceTimersByTime(300));
    fireEvent.change(input, { target: { value: "60" } });
    act(() => vi.advanceTimersByTime(500));
    await flushPromises();

    expect(fetchStockSearchMock).toHaveBeenCalledTimes(1);
    expect(fetchStockSearchMock).toHaveBeenCalledWith("60", expect.any(Object));
  });

  it("ignores a stale response that resolves after the latest request", async () => {
    const first = deferred<Awaited<ReturnType<typeof fetchStockSearch>>>();
    const second = deferred<Awaited<ReturnType<typeof fetchStockSearch>>>();
    fetchStockSearchMock
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    render(<ControllerHarness onSelect={vi.fn()} />);

    const input = screen.getByLabelText("controller-input");
    fireEvent.change(input, { target: { value: "6" } });
    act(() => vi.advanceTimersByTime(500));
    fireEvent.change(input, { target: { value: "60" } });
    act(() => vi.advanceTimersByTime(500));

    second.resolve({
      keyword: "60",
      items: [{ tsCode: "600000.SH", name: "浦发银行" }],
    });
    await flushPromises();
    expect(screen.getByText("600000.SH")).toBeInTheDocument();

    first.resolve({
      keyword: "6",
      items: [{ tsCode: "601318.SH", name: "中国平安" }],
    });
    await flushPromises();
    expect(screen.queryByText("601318.SH")).not.toBeInTheDocument();
    expect(screen.getByText("600000.SH")).toBeInTheDocument();
  });

  it("turns a two-second request timeout into error state", async () => {
    fetchStockSearchMock.mockImplementation((_keyword, options) => new Promise((_resolve, reject) => {
      options?.signal?.addEventListener("abort", () => {
        reject(new DOMException("aborted", "AbortError"));
      });
    }));
    render(<ControllerHarness onSelect={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("controller-input"), {
      target: { value: "600" },
    });
    act(() => vi.advanceTimersByTime(STOCK_SEARCH_DEBOUNCE_MS));
    act(() => vi.advanceTimersByTime(STOCK_SEARCH_TIMEOUT_MS));
    await flushPromises();

    expect(screen.getByLabelText("controller-state")).toHaveTextContent('"kind":"error"');
  });

  it("Enter during debounce requests immediately and commits the first result", async () => {
    const response = deferred<Awaited<ReturnType<typeof fetchStockSearch>>>();
    fetchStockSearchMock.mockReturnValue(response.promise);
    const onSelect = vi.fn();
    render(<ControllerHarness onSelect={onSelect} />);

    const input = screen.getByLabelText("controller-input");
    fireEvent.change(input, { target: { value: "payh" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(fetchStockSearchMock).toHaveBeenCalledTimes(1);
    expect(fetchStockSearchMock).toHaveBeenCalledWith("PAYH", expect.any(Object));

    response.resolve({
      keyword: "PAYH",
      items: [{ tsCode: "000001.SZ", name: "平安银行" }],
    });
    await flushPromises();

    expect(onSelect).toHaveBeenCalledWith("000001.SZ");
  });

  it("Enter during loading marks pending commit without duplicating the request", async () => {
    const response = deferred<Awaited<ReturnType<typeof fetchStockSearch>>>();
    fetchStockSearchMock.mockReturnValue(response.promise);
    const onSelect = vi.fn();
    render(<ControllerHarness onSelect={onSelect} />);

    const input = screen.getByLabelText("controller-input");
    fireEvent.change(input, { target: { value: "600" } });
    act(() => vi.advanceTimersByTime(500));
    fireEvent.keyDown(input, { key: "Enter" });
    expect(fetchStockSearchMock).toHaveBeenCalledTimes(1);

    response.resolve({
      keyword: "600",
      items: [{ tsCode: "600000.SH", name: "浦发银行" }],
    });
    await flushPromises();
    expect(onSelect).toHaveBeenCalledWith("600000.SH");
  });
});
