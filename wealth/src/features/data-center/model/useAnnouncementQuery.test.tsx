import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { dataCenterApi } from "../api/dataCenterApi";
import type { Company, Conditions, QueryResult } from "../api/contracts";
import { contextFixture } from "./fixtures";
import { useAnnouncementQuery } from "./useAnnouncementQuery";
afterEach(() => vi.restoreAllMocks());

it("keeps an explicitly selected code when dates change after a missing latest-day query", async () => {
  const create = vi.spyOn(dataCenterApi, "createQuery").mockImplementation(async c => sample(c));
  vi.spyOn(dataCenterApi, "query").mockResolvedValue({ ...sample({ ...contextFixture.queryDefaults, tsCode: null, titleKeyword: "" }), pageState: { status: "error", code: "DC_SOURCE_UNAVAILABLE", message: "最新日期未同步", asOfTime: "2026-10-08T00:00:00Z" } });
  const { result } = renderHook(() => useAnnouncementQuery(contextFixture));
  await waitFor(() => expect(result.current.result?.pageState.status).toBe("error"));
  act(() => result.current.chooseCompany({ tsCode: "000001.SZ", name: "平安银行" } as Company));
  act(() => result.current.setDraft({ ...result.current.draft, startDate: "2026-09-01", endDate: "2026-09-30" }));
  expect(result.current.selected?.tsCode).toBe("000001.SZ");
  await act(async () => result.current.submit());
  expect(create.mock.calls.at(-1)?.[0]).toMatchObject({ startDate: "2026-09-01", endDate: "2026-09-30", tsCode: "000001.SZ" });
});
const sample = (c: Conditions, id = "q1", page = 1) => ({ queryId: id, pageState: { status: "ready", code: null, message: null, asOfTime: "2026-10-06T00:00:00Z" }, sourceVersion: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", conditions: c, effectiveEndDate: c.endDate, items: [], total: 100, page, pageSize: 50, hasPrevious: page > 1, hasNext: page === 1, downloadStatusAvailable: true, preparation: null } as QueryResult);
it("unselected typed company blocks application; selected full code with literal title is applied", async () => {
  const create = vi.spyOn(dataCenterApi, "createQuery").mockImplementation(async c => sample(c)); vi.spyOn(dataCenterApi, "query").mockResolvedValue(sample({ ...contextFixture.queryDefaults, tsCode: null, titleKeyword: "" }));
  const { result } = renderHook(() => useAnnouncementQuery(contextFixture)); await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
  act(() => result.current.setCompanyText("PAYH")); act(() => result.current.submit()); expect(create).toHaveBeenCalledTimes(1); expect(result.current.error).toBe("请先选择公司");
  act(() => { result.current.chooseCompany({ tsCode: "000001.SZ", name: "平安银行" } as Company); result.current.setDraft({ ...result.current.draft, titleKeyword: "  %_董事会  " }); });
  await act(async () => result.current.submit()); expect(create.mock.calls[1][0]).toMatchObject({ tsCode: "000001.SZ", titleKeyword: "%_董事会" });
  act(() => result.current.setCompanyText("600036")); act(() => result.current.submit()); expect(create).toHaveBeenCalledTimes(2);
});
it("refresh uses applied conditions; pagination retains identity; reset immediately queries defaults", async () => {
  let index = 0; let applied!: Conditions;
  const create = vi.spyOn(dataCenterApi, "createQuery").mockImplementation(async c => { applied = c; return sample(c, `q${++index}`); });
  const read = vi.spyOn(dataCenterApi, "query").mockImplementation(async (id,p) => sample(applied,id,p));
  const { result } = renderHook(() => useAnnouncementQuery(contextFixture)); await waitFor(() => expect(result.current.result?.queryId).toBe("q1"));
  act(() => result.current.setDraft({ ...result.current.draft, titleKeyword: "未应用" })); await act(async () => result.current.refresh());
  expect(create.mock.calls[1][0].titleKeyword).toBe(""); await waitFor(() => expect(result.current.result?.queryId).toBe("q2"));
  act(() => result.current.page(2)); await waitFor(() => expect(result.current.result?.page).toBe(2)); expect(read.mock.calls.at(-1)?.slice(0,2)).toEqual(["q2",2]); expect(create).toHaveBeenCalledTimes(2);
  await act(async () => result.current.reset()); expect(create.mock.calls[2][0]).toEqual({ ...contextFixture.queryDefaults, tsCode: null, titleKeyword: "" });
});
