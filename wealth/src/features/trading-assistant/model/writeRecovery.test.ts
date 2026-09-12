import { describe, expect, it } from "vitest";
import type { RecoveryStatusDto } from "../api/generatedContracts";
import { mayReturnToEditing, reduceWriteRecovery, type WriteRecoveryState } from "./writeRecovery";

const identity = { authEpoch: 2, pageGeneration: 3, requestId: "request" };
const status: RecoveryStatusDto = { requestId: "request", attemptId: "attempt", operationType: "ACCOUNT_CREATE",
  scope: { scopeType: "ACCOUNT_CREATE" }, target: null, stateVersion: "9007199254740993", outcome: "PROCESSING",
  inputRetained: true, summary: { title: "创建账户", lines: [] }, receipt: null, rejection: null, updatedAt: "2026-09-12T10:00:00+08:00" };
const initial: WriteRecoveryState = { ...identity, status: null, queryUnavailable: false, inconsistentResponse: false };
const update = (current: WriteRecoveryState, next: RecoveryStatusDto) => reduceWriteRecovery(current, { ...identity, kind: "status", status: next });

describe("R11 pure evidence merge", () => {
  it("retention and lookup errors never permit a repeated save", () => {
    const processing = update(initial, status);
    expect(mayReturnToEditing(processing)).toBe(false);
    const failed = reduceWriteRecovery(processing, { ...identity, kind: "queryFailed" });
    expect(failed.status).toBe(status); expect(mayReturnToEditing(failed)).toBe(false);
  });
  it.each([{ authEpoch: 1 }, { pageGeneration: 2 }, { requestId: "other" }])("ignores a different identity %j", patch => {
    expect(reduceWriteRecovery(initial, { ...identity, ...patch, kind: "status", status })).toBe(initial);
  });
  it("orders versions exactly beyond safe JS integers", () => {
    const current = update(initial, status);
    expect(update(current, { ...status, stateVersion: "9007199254740992", outcome: "NOT_SAVED" })).toBe(current);
  });
  it("rejects equal-version contradictions but not key order", () => {
    const current = update(initial, status);
    expect(update(current, { ...status, outcome: "NOT_SAVED" }).inconsistentResponse).toBe(true);
    expect(update(current, { ...status }).queryUnavailable).toBe(false);
  });
  it("allows editing only on confirmed failure; new attempts require a newer version and attempt", () => {
    const failed = update(initial, { ...status, outcome: "NOT_SAVED" });
    expect(mayReturnToEditing(failed)).toBe(true);
    expect(update(failed, { ...status, stateVersion: "9007199254740994" }).inconsistentResponse).toBe(true);
    const retry = update(failed, { ...status, attemptId: "new", stateVersion: "9007199254740994" });
    expect(retry.status?.attemptId).toBe("new"); expect(mayReturnToEditing(retry)).toBe(false);
  });
  it("does not downgrade a saved operation when detail or status lookup fails", () => {
    // Reducer input has already passed runtime DTO validation at the API boundary.
    const saved = { ...initial, status: { ...status, outcome: "SAVED" as const } };
    expect(reduceWriteRecovery(saved, { ...identity, kind: "queryFailed" }).status?.outcome).toBe("SAVED");
    expect(update(saved, { ...status, stateVersion: "9007199254740994" }).status?.outcome).toBe("SAVED");
  });
});
