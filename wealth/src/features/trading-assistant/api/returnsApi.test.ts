import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { saveAuthSession } from "../../auth/model/authStorage";
import { getCompletedRounds, getReturnCurve, getRoundDetail } from "./returnsApi";
import { parseContract } from "./contractValidation";

const accountId = "10000000-0000-4000-8000-000000000001", roundId = "20000000-0000-4000-8000-000000000001";
const account = { accountId, name:"主账户", brokerName:"券商" };
const scope = { accountMode:"SINGLE", accounts:[account], stockMode:"ALL", stockRef:null };
const context = { contextToken:"specific", targetThrough:"2026-09-11T15:00:00+08:00", accounts:[{
  accountId, factVersion:"1", calculationTargetVersion:"1", publishedGenerationId:null }] };
const cover = { accountId, initializedOn:"2026-09-11", effectiveStartDate:null, targetThroughDate:null,
  calculatedThroughDate:null, valuationAt:null, dataStatus:"Delayed", reason:"待计算" };
beforeEach(() => {
  localStorage.clear();
  saveAuthSession({ token:"test", refresh_token:"test-refresh", username:"first", is_admin:false });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("keeps unavailable round data empty and permits server-validated ALL narrowing", async () => {
  const result = { readContext:context, coverage:{ dataStatus:"Delayed", reason:"待计算", isFinal:false, accounts:[cover] }, detail:null };
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(result)));
  vi.stubGlobal("fetch", fetchMock);
  expect(await getRoundDetail(accountId, roundId, "parent-all", new AbortController().signal)).toEqual(result);
  expect(String(fetchMock.mock.calls[0][0])).toContain(`/accounts/${accountId}/holding-rounds/${roundId}?readContext=parent-all`);
});
it("rejects a response belonging to another account", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ readContext:context,
    coverage:{ dataStatus:"Delayed", reason:"待计算", isFinal:false, accounts:[cover] }, detail:null }))));
  await expect(getRoundDetail("10000000-0000-4000-8000-000000000002", roundId, "parent", new AbortController().signal)).rejects.toThrow();
});
it("completed rounds use closing dates and never silently substitute another range", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ scope,
    closedStartDate:"2026-09-01", closedEndDate:"2026-09-30", items:[], nextCursor:null, completedRoundCount:0,
    coverage:{ dataStatus:"Empty", reason:null, isFinal:true, accounts:[] } }))));
  await expect(getCompletedRounds({ accountMode:"SINGLE", accountId, stockMode:"ALL", requestedStartDate:"2026-09-11",
    requestedEndDate:"2026-09-11" }, new AbortController().signal)).rejects.toThrow();
});
it("validates curve query before any HTTP request", async () => {
  const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
  await expect(getReturnCurve({ accountMode:"SINGLE", accountId, stockMode:"ALL", requestedStartDate:"2026-09-30",
    requestedEndDate:"2026-09-01", granularity:"DAY" }, new AbortController().signal)).rejects.toThrow();
  expect(fetchMock).not.toHaveBeenCalled();
});

it("requires a canonical historical start independently of the requested range", async () => {
  const result = { scope, requestedStartDate:"2026-09-01", requestedEndDate:"2026-09-11", granularity:"DAY",
    historyStartDate:"2020-01-02", readContext:context, points:[],
    coverage:{ dataStatus:"Empty", reason:null, isFinal:true, accounts:[] } };
  const query = { accountMode:"SINGLE" as const, accountId, stockMode:"ALL" as const,
    requestedStartDate:result.requestedStartDate, requestedEndDate:result.requestedEndDate, granularity:"DAY" as const };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(result))));
  expect((await getReturnCurve(query, new AbortController().signal)).historyStartDate).toBe("2020-01-02");
  expect(parseContract("CurveResponse", { ...result, historyStartDate:null }).historyStartDate).toBeNull();
  const { historyStartDate: _removed, ...missing } = result;
  expect(() => parseContract("CurveResponse", missing)).toThrow();
  for (const value of ["2020-02-30", "20200102", 20200102, ""]) {
    expect(() => parseContract("CurveResponse", { ...result, historyStartDate:value })).toThrow();
  }
});
