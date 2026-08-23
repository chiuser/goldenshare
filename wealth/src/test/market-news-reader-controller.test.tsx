import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { MarketNewsViewItem } from "../features/market-overview/news/api/marketNewsAdapter";
import { useState } from "react";
import { useMarketNewsReader } from "../features/market-overview/news/model/useMarketNewsReader";
import { NewsReaderDialog } from "../shared/ui/news-reader/NewsReaderDialog";


const itemA: MarketNewsViewItem = {
  newsId: "news-a",
  publishTime: "2026-08-23T09:30:00+08:00",
  displayTime: "08-23 09:30:00",
  title: "新闻 A",
  readerMode: "TEXT",
  clickable: true,
};

const itemB: MarketNewsViewItem = {
  ...itemA,
  newsId: "news-b",
  title: "新闻 B",
};


function responseJson(payload: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => payload } as Response;
}


function Harness() {
  const reader = useMarketNewsReader();
  return (
    <>
      <button type="button" data-news-reader-trigger data-news-id="news-a" onClick={(event) => reader.open(itemA, event.currentTarget)}>
        打开 A
      </button>
      <button type="button" data-news-reader-trigger data-news-id="news-b" onClick={(event) => reader.open(itemB, event.currentTarget)}>
        打开 B
      </button>
      <NewsReaderDialog state={reader.state} onClose={reader.close} onRetry={reader.retry} />
    </>
  );
}


function RefreshHarness() {
  const reader = useMarketNewsReader();
  const [version, setVersion] = useState(0);
  return (
    <>
      <button
        key={version}
        type="button"
        data-news-reader-trigger
        data-news-id="news-a"
        onClick={(event) => reader.open(itemA, event.currentTarget)}
      >
        打开 A
      </button>
      <button type="button" onClick={() => setVersion((value) => value + 1)}>刷新列表</button>
      <NewsReaderDialog state={reader.state} onClose={reader.close} onRetry={reader.retry} />
    </>
  );
}


afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});


describe("useMarketNewsReader", () => {
  it("opens immediately, resolves one item, and restores trigger focus", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      responseJson({
        newsId: "news-a",
        title: "新闻 A 详情",
        source: "Tushare",
        publishTime: itemA.publishTime,
        readerMode: "TEXT",
        url: null,
        html: null,
        content: "A 正文",
      }),
    );
    render(<Harness />);

    const trigger = screen.getByRole("button", { name: "打开 A" });
    fireEvent.click(trigger);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("新闻 A")).toBeInTheDocument();
    expect(await screen.findByText("A 正文")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "关闭新闻阅读器" }));
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("restores focus to a refreshed trigger with the same news id", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      responseJson({
        newsId: "news-a",
        title: "新闻 A 详情",
        source: null,
        publishTime: itemA.publishTime,
        readerMode: "TEXT",
        url: null,
        html: null,
        content: "A 正文",
      }),
    );
    render(<RefreshHarness />);

    const original = screen.getByRole("button", { name: "打开 A" });
    fireEvent.click(original);
    expect(await screen.findByText("A 正文")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "刷新列表" }));
    const replacement = screen.getByRole("button", { name: "打开 A" });
    expect(replacement).not.toBe(original);

    fireEvent.click(screen.getByRole("button", { name: "关闭新闻阅读器" }));
    await waitFor(() => expect(replacement).toHaveFocus());
  });

  it("aborts A and prevents its late response from overwriting B", async () => {
    let resolveA: ((value: Response) => void) | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.includes("news-a")) {
        return new Promise<Response>((resolve, reject) => {
          resolveA = resolve;
          init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
        });
      }
      return Promise.resolve(
        responseJson({
          newsId: "news-b",
          title: "新闻 B 详情",
          source: null,
          publishTime: itemB.publishTime,
          readerMode: "TEXT",
          url: null,
          html: null,
          content: "B 正文",
        }),
      );
    });
    render(<Harness />);

    fireEvent.click(screen.getByRole("button", { name: "打开 A" }));
    fireEvent.click(screen.getByRole("button", { name: "打开 B" }));
    expect(await screen.findByText("B 正文")).toBeInTheDocument();

    if (!resolveA) throw new Error("A resolver missing");
    await act(async () => {
      resolveA?.(
        responseJson({
          newsId: "news-a",
          title: "新闻 A 详情",
          source: null,
          publishTime: itemA.publishTime,
          readerMode: "TEXT",
          url: null,
          html: null,
          content: "A 晚到正文",
        }),
      );
    });
    expect(screen.queryByText("A 晚到正文")).not.toBeInTheDocument();
    expect(screen.getByText("B 正文")).toBeInTheDocument();
  });

  it("maps not found to empty and server errors to retryable state", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockResolvedValueOnce(
      responseJson({ code: "NEWS_READER_NOT_FOUND", message: "内容已下线" }, 404),
    );
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "打开 A" }));
    expect(await screen.findByText("内容暂不可读")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重新加载" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "关闭新闻阅读器" }));
    fetchMock.mockResolvedValueOnce(
      responseJson({ code: "NEWS_READER_QUERY_FAILED", message: "加载失败" }, 500),
    );
    fireEvent.click(screen.getByRole("button", { name: "打开 B" }));
    expect(await screen.findByText("新闻加载失败")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument();
  });

  it("aborts a pending detail request on close and reports the five-second timeout", async () => {
    vi.useFakeTimers();
    let abortCount = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((_input, init) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => {
            abortCount += 1;
            reject(new DOMException("aborted", "AbortError"));
          },
          { once: true },
        );
      }),
    );
    render(<Harness />);

    fireEvent.click(screen.getByRole("button", { name: "打开 A" }));
    fireEvent.click(screen.getByRole("button", { name: "关闭新闻阅读器" }));
    expect(abortCount).toBe(1);

    fireEvent.click(screen.getByRole("button", { name: "打开 B" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
      await Promise.resolve();
    });
    expect(abortCount).toBe(2);
    expect(screen.getByText("新闻内容请求超时，请稍后重试。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument();
  });
});
