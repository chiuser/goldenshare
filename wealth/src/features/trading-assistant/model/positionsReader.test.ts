import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CalculationStatus, PositionsResponse } from "../api/generatedContracts";
import { PositionsReader, type PositionsReadApi } from "./positionsReader";

const response = (accounts: [string, string][] = [["a", "Recalculating"]]) => ({
  coverage: { accounts: accounts.map(([accountId, dataStatus]) => ({ accountId, dataStatus })) },
  readContext: { accounts: accounts.map(([accountId]) => ({ accountId, calculationTargetVersion: "1" })) },
}) as unknown as PositionsResponse;
const status = (accountId: string, stage: string) => ({ accountId, stage, calculationTargetVersion: "1" }) as CalculationStatus;
const settle = async () => { await vi.advanceTimersByTimeAsync(0); };
function setup(data = response()) {
  const api = { positions: vi.fn().mockResolvedValue(data), status: vi.fn().mockResolvedValue(status("a", "CALCULATING")), epoch: () => 1 };
  const events = vi.fn(), reader = new PositionsReader("ALL", api as PositionsReadApi, events);
  return { api, events, reader };
}
describe("approved positions read cadence", () => {
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(0); });
  afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); });
  it("checks active accounts at 2 seconds, refreshes once on publication and stops", async () => {
    const { api, reader } = setup();
    reader.start(); await settle();
    await vi.advanceTimersByTimeAsync(1999); expect(api.status).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1); expect(api.status).toHaveBeenCalledTimes(1);
    api.status.mockResolvedValue(status("a", "PUBLISHED"));
    await vi.advanceTimersByTimeAsync(2000);
    expect(api.positions).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(120000);
    expect(api.status).toHaveBeenCalledTimes(2);
    reader.stop();
  });
  it("keeps waiting accounts at 60 seconds despite another active account", async () => {
    const { api, reader } = setup(response([["a", "Delayed"], ["b", "Recalculating"]]));
    api.status.mockImplementation(async (id: string) => status(id, id === "a" ? "WAITING_DATA" : "CALCULATING"));
    reader.start(); await settle(); await vi.advanceTimersByTimeAsync(60001);
    expect(api.status.mock.calls.filter(([id]) => id === "a")).toHaveLength(1);
    expect(api.status.mock.calls.filter(([id]) => id === "b").length).toBeGreaterThan(1);
    await vi.advanceTimersByTimeAsync(1999);
    expect(api.status.mock.calls.filter(([id]) => id === "a")).toHaveLength(2);
    reader.stop();
  });
  it("does not overlap slow status and complete data requests", async () => {
    const { api, reader } = setup();
    let finish!: (value: CalculationStatus) => void;
    api.status.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    reader.start(); await settle(); await vi.advanceTimersByTimeAsync(20000);
    expect(api.status).toHaveBeenCalledTimes(1); expect(api.positions).toHaveBeenCalledTimes(1);
    finish(status("a", "PUBLISHED")); await settle();
    expect(api.positions).toHaveBeenCalledTimes(2);
    reader.stop();
  });
  it("stops on a failed calculation and on a read error without inventing FAILED", async () => {
    const { api, reader, events } = setup();
    api.status.mockResolvedValue(status("a", "FAILED"));
    reader.start(); await settle(); await vi.advanceTimersByTimeAsync(120000);
    expect(api.status).toHaveBeenCalledTimes(1); expect(api.positions).toHaveBeenCalledTimes(2);
    api.status.mockRejectedValue(new Error("network"));
    reader.start(); await settle(); await vi.advanceTimersByTimeAsync(120000);
    expect(events.mock.calls.at(-1)?.[0]).toEqual({ kind: "error" });
    expect(api.status).toHaveBeenCalledTimes(2);
    reader.stop();
  });
  it("aborts hidden/old scope, ignores late data and starts one fresh read on return", async () => {
    const { api, reader, events } = setup();
    let late!: (data: PositionsResponse) => void;
    api.positions.mockImplementationOnce(() => new Promise(resolve => { late = resolve; }));
    reader.start(); await settle();
    const signal = api.positions.mock.calls[0][1] as AbortSignal;
    reader.stop(); expect(signal.aborted).toBe(true);
    reader.start(); await settle(); const count = events.mock.calls.length;
    late(response([["other", "Ready"]])); await settle();
    expect(events).toHaveBeenCalledTimes(count);
    expect(api.positions).toHaveBeenCalledTimes(2);
    reader.stop(); await vi.advanceTimersByTimeAsync(120000); expect(api.status).not.toHaveBeenCalled();
  });
  it("rejects a prior login's late response and schedules no timer", async () => {
    const { api, reader, events } = setup();
    let late!: (data: PositionsResponse) => void;
    api.positions.mockImplementationOnce(() => new Promise(resolve => { late = resolve; }));
    reader.start(); await settle(); api.epoch = () => 2;
    late(response()); await settle(); await vi.advanceTimersByTimeAsync(120000);
    expect(events).not.toHaveBeenCalled(); expect(api.status).not.toHaveBeenCalled(); reader.stop();
  });
});
