import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StockDetailNewsPanel } from "./StockDetailNewsPanel";

describe("StockDetailNewsPanel", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("does not request while inactive and preserves the API array order after activation", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({
      stockRef: { tsCode: "603806.SH", name: "福斯特" },
      items: [
        { newsId: "3", publishTime: "2026-05-29T16:00:03+08:00", title: "第三条" },
        { newsId: "1", publishTime: "2026-05-29T16:00:01+08:00", title: "第一条" },
        { newsId: "2", publishTime: "2026-05-29T16:00:02+08:00", title: "第二条" },
      ],
      meta: { count: 3, limit: 50, startAt: "2026-06-23T00:00:00+08:00", endAt: "2026-08-23T00:00:00+08:00" },
    })));
    vi.stubGlobal("fetch", fetchMock);

    const view = render(<StockDetailNewsPanel tsCode="603806.SH" active={false} />);
    expect(fetchMock).not.toHaveBeenCalled();

    view.rerender(<StockDetailNewsPanel tsCode="603806.SH" active />);
    await waitFor(() => expect(screen.getByText("第三条")).toBeInTheDocument());

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "第三条05-29",
      "第一条05-29",
      "第二条05-29",
    ]);
  });

  it("shows empty and error states distinctly", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        stockRef: { tsCode: "603806.SH", name: "福斯特" },
        items: [],
        meta: { count: 0, limit: 50, startAt: "", endAt: "" },
      })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ message: "接口失败" }), { status: 500 }));
    vi.stubGlobal("fetch", fetchMock);

    const view = render(<StockDetailNewsPanel tsCode="603806.SH" active />);
    await waitFor(() => expect(screen.getByText("暂无相关新闻")).toBeInTheDocument());
    view.rerender(<StockDetailNewsPanel tsCode="000001.SZ" active />);
    await waitFor(() => expect(screen.getByText("接口失败")).toBeInTheDocument());
  });

  it("aborts the old request when the stock changes", async () => {
    const requestSignals: (AbortSignal | null | undefined)[] = [];
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      requestSignals.push(init?.signal);
      return new Promise<Response>(() => undefined);
    });
    vi.stubGlobal("fetch", fetchMock);

    const view = render(<StockDetailNewsPanel tsCode="603806.SH" active />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    view.rerender(<StockDetailNewsPanel tsCode="000001.SZ" active />);
    await act(async () => Promise.resolve());
    expect(requestSignals[0]?.aborted).toBe(true);
  });
});
