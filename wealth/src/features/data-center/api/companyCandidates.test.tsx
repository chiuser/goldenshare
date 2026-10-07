import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { dataCenterApi } from "./dataCenterApi";
import { companyCandidates, ANNOUNCEMENT_SEARCH_INTERACTION, type CompanyOption } from "./companyCandidates";
import { useStockSearchController, type CandidateLoader } from "../../stock-search/model/useStockSearchController";

const company: CompanyOption = { tsCode: "600000.SH", codeText: "600000.SH", name: "浦发银行", initials: "PFYH", matchedAlias: null, nameSource: "master", matchKind: "initials" };
const dates = { startDate: "2026-09-30", endDate: "2026-09-30" };
beforeEach(() => vi.useFakeTimers());
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

it("announcement Enter requires explicit navigation and selects the complete option exactly once", async () => {
  const select = vi.fn(); const loader = vi.fn().mockResolvedValue([company]);
  const { result } = renderHook(() => useStockSearchController({ onSelectOption: select, loadCandidates: loader, interaction: ANNOUNCEMENT_SEARCH_INTERACTION }));
  act(() => result.current.handleInputChange("pfyh"));
  await act(async () => vi.advanceTimersByTimeAsync(299)); expect(loader).not.toHaveBeenCalled();
  await act(async () => vi.advanceTimersByTimeAsync(1));
  expect(result.current.state).toMatchObject({ kind: "ready", activeIndex: -1 });
  act(() => result.current.handleKeyDown("Enter")); expect(select).not.toHaveBeenCalled();
  act(() => result.current.handleKeyDown("ArrowDown"));
  act(() => result.current.handleKeyDown("Enter"));
  expect(select).toHaveBeenCalledExactlyOnceWith(company);
  act(() => result.current.handleKeyDown("Enter")); expect(select).toHaveBeenCalledTimes(1);
});

it("date reset and blur abort old candidate requests before their response can overwrite state", async () => {
  let finish!: (options: CompanyOption[]) => void;
  const loader: CandidateLoader<CompanyOption> = vi.fn(() => new Promise<CompanyOption[]>(resolve => { finish = resolve; }));
  const select = vi.fn();
  const { result } = renderHook(() => useStockSearchController({ onSelectOption: select, loadCandidates: loader, interaction: ANNOUNCEMENT_SEARCH_INTERACTION }));
  act(() => result.current.handleInputChange("旧简称")); await act(async () => vi.advanceTimersByTimeAsync(300));
  const signal = vi.mocked(loader).mock.calls[0][0].signal;
  act(() => result.current.resetInput("")); expect(signal.aborted).toBe(true);
  await act(async () => finish([company])); expect(result.current.state.kind).toBe("idle"); expect(select).not.toHaveBeenCalled();
  act(() => result.current.handleInputChange("600")); await act(async () => vi.advanceTimersByTimeAsync(300));
  act(() => result.current.handleBlur()); await act(async () => vi.advanceTimersByTimeAsync(200));
  expect(vi.mocked(loader).mock.calls[1][0].signal.aborted).toBe(true);
});

it("observes 202 preparation then adapts local company fields without a second search state machine", async () => {
  const initial = { keyword: "PFYH", items: [], hasMore: null, queryId: "q", pageState: { status: "preparing" } };
  const candidates = vi.spyOn(dataCenterApi, "companies").mockResolvedValueOnce(initial as never).mockResolvedValueOnce({ keyword: "PFYH", items: [company], hasMore: true, pageState: null, preparation: null, queryId: null });
  const observe = vi.spyOn(dataCenterApi, "query").mockResolvedValueOnce({ pageState: { status: "preparing" } } as never).mockResolvedValueOnce({ pageState: { status: "ready" } } as never);
  const hasMore = vi.fn(); const signal = new AbortController().signal;
  const pending = companyCandidates(dates, hasMore)({ keyword: "PFYH", signal });
  await vi.advanceTimersByTimeAsync(4000);
  expect(await pending).toEqual([company]); expect(observe).toHaveBeenCalledTimes(2);
  expect(candidates).toHaveBeenCalledTimes(2); expect(hasMore).toHaveBeenCalledExactlyOnceWith(true);
});

it("terminal source failure stops candidate observation and allows a later manual search", async () => {
  const candidates = vi.spyOn(dataCenterApi, "companies").mockResolvedValueOnce({ keyword: "x", items: [], hasMore: null, queryId: "q", pageState: { status: "preparing" } } as never).mockResolvedValueOnce({ keyword: "x", items: [company], hasMore: false, pageState: null, preparation: null, queryId: null });
  const observe = vi.spyOn(dataCenterApi, "query").mockResolvedValue({ pageState: { status: "error", message: "缺少日期" } } as never);
  const loader = companyCandidates(dates, vi.fn()); const signal = new AbortController().signal;
  const failed = expect(loader({ keyword: "x", signal })).rejects.toThrow("缺少日期");
  await vi.advanceTimersByTimeAsync(10000); await failed; expect(observe).toHaveBeenCalledTimes(1);
  expect(await loader({ keyword: "x", signal })).toEqual([company]); expect(candidates).toHaveBeenCalledTimes(2);
});
