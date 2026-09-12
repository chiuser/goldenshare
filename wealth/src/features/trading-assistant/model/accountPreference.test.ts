import { beforeEach, describe, expect, it } from "vitest";
import type { AccountSummary } from "../api/generatedContracts";
import { rememberAccountSelection, restoreAccountSelection } from "./accountPreference";

const accounts: AccountSummary[] = [1, 2].map(n => ({ accountId: `00000000-0000-4000-8000-00000000000${n}`,
  name: `账户${n}`, brokerName: "券商", initializedOn: "2026-09-12", factVersion: "1",
  feeVersionId: "00000000-0000-4000-8000-000000000009" }));
describe("browser account preference", () => {
  beforeEach(() => localStorage.clear());
  it("restores across new reads and isolates authenticated users", () => {
    rememberAccountSelection(1, accounts[1].accountId, accounts);
    expect(restoreAccountSelection(1, accounts)).toBe(accounts[1].accountId);
    expect(restoreAccountSelection(2, accounts)).toBe(accounts[0].accountId);
    expect(localStorage.length).toBe(1);
    expect(localStorage.getItem("wealth.ta.last-account.v1:1")).toBe(accounts[1].accountId);
  });
  it("does not persist ALL or replace the specific preference", () => {
    rememberAccountSelection(1, accounts[1].accountId, accounts);
    rememberAccountSelection(1, "ALL", accounts);
    expect(restoreAccountSelection(1, accounts)).toBe(accounts[1].accountId);
  });
  it.each(["broken", "00000000-0000-4000-8000-000000000099"])("ignores invalid or unowned ID %s", value => {
    localStorage.setItem("wealth.ta.last-account.v1:1", value);
    expect(restoreAccountSelection(1, accounts)).toBe(accounts[0].accountId);
    rememberAccountSelection(1, value, accounts);
    expect(localStorage.getItem("wealth.ta.last-account.v1:1")).toBe(value);
  });
  it("handles empty ownership, unavailable storage, and denied reads/writes", () => {
    const denied = { getItem: () => { throw new Error("denied"); }, setItem: () => { throw new Error("denied"); } };
    expect(restoreAccountSelection(1, [])).toBeNull();
    expect(restoreAccountSelection(1, accounts, null)).toBe(accounts[0].accountId);
    expect(restoreAccountSelection(1, accounts, denied)).toBe(accounts[0].accountId);
    expect(() => rememberAccountSelection(1, accounts[1].accountId, accounts, denied)).not.toThrow();
  });
  it("never persists an unverified user identity", () => {
    for (const id of [0, -1, NaN, 1.5]) rememberAccountSelection(id, accounts[1].accountId, accounts);
    expect(localStorage.length).toBe(0);
  });
});
