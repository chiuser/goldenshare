import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { dataCenterApi } from "../api/dataCenterApi";
import type { Conditions, QueryResult } from "../api/contracts";
import { contextFixture } from "../model/fixtures";
import { QueryPanel } from "./QueryPanel";

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });
const conditions: Conditions = { ...contextFixture.queryDefaults, tsCode: null, titleKeyword: "" };
const ready = (id = "q1", page = 1): QueryResult => ({ queryId: id, conditions,
  pageState: { status: "ready", code: null, message: null, asOfTime: "2026-10-06T00:00:00Z" },
  sourceVersion: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", items: [], total: 100, page, pageSize: 50,
  hasPrevious: page > 1, hasNext: page === 1, downloadStatusAvailable: true, preparation: null });
const buttons = () => ["查询", "重置", "刷新列表"].map(name => screen.getByRole("button", { name }));

it("buttons stay enabled during observation; terminal failure stops GETs and manual retry creates a new query", async () => {
  vi.useFakeTimers();
  let resolveCreate!: (r: QueryResult) => void; let resolveRead!: (r: QueryResult) => void;
  const create = vi.spyOn(dataCenterApi, "createQuery").mockImplementation(() => new Promise(r => { resolveCreate = r; }));
  const read = vi.spyOn(dataCenterApi, "query").mockImplementationOnce(() => new Promise(r => { resolveRead = r; })).mockResolvedValue(ready("q2"));
  render(<QueryPanel context={contextFixture} refreshContext={() => {}} />);
  buttons().forEach(b => expect(b).toBeDisabled());
  const preparing: QueryResult = { ...ready(), total: null, hasNext: false, downloadStatusAvailable: false,
    pageState: { status: "preparing", code: null, message: null, asOfTime: "2026-10-07T00:00:00Z" },
    preparation: { stage: "counting", artifactsChecked: 0, datesScanned: 29, datesTotal: 30, recordsScanned: 100 } };
  await act(async () => { resolveCreate(preparing); });
  expect(read).toHaveBeenCalledTimes(1);
  buttons().forEach(b => expect(b).toBeEnabled());
  await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
  buttons().forEach(b => expect(b).toBeEnabled());
  const message = "本地尚未同步 2026-10-07 的公告数据，请调整查询日期或等待同步后刷新列表";
  await act(async () => { resolveRead({ ...preparing, preparation: null,
    pageState: { status: "error", code: "DC_SOURCE_UNAVAILABLE", message, asOfTime: "2026-10-07T00:00:00Z" } }); });
  expect(screen.getByText(message)).toBeVisible();
  expect(screen.getByText("列表暂不可获取")).toBeVisible();
  expect(screen.queryByText("没有符合条件的公告")).toBeNull();
  await act(async () => { await vi.advanceTimersByTimeAsync(20000); });
  expect(read).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "重新读取" }));
  expect(create).toHaveBeenCalledTimes(2); expect(create.mock.calls[1][0]).toEqual(conditions);
  buttons().forEach(b => expect(b).toBeDisabled());
  await act(async () => { resolveCreate(ready("q2")); });
  expect(read.mock.calls.at(-1)?.slice(0, 2)).toEqual(["q2", 1]);
  buttons().forEach(b => expect(b).toBeEnabled());
  expect(screen.queryByText(message)).toBeNull();
});

it("page navigation remains locked during a GET while query actions remain enabled", async () => {
  vi.useFakeTimers(); let resolvePage!: (r: QueryResult) => void;
  vi.spyOn(dataCenterApi, "createQuery").mockResolvedValue(ready());
  const read = vi.spyOn(dataCenterApi, "query").mockResolvedValueOnce(ready()).mockImplementationOnce(() => new Promise(r => { resolvePage = r; }));
  render(<QueryPanel context={contextFixture} refreshContext={() => {}} />);
  await act(async () => {});
  fireEvent.click(screen.getByRole("button", { name: "下一页" }));
  expect(read.mock.calls.at(-1)?.slice(0, 2)).toEqual(["q1", 2]);
  expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
  buttons().forEach(b => expect(b).toBeEnabled());
  await act(async () => { resolvePage(ready("q1", 2)); });
  expect(screen.getByRole("button", { name: "上一页" })).toBeEnabled();
});
