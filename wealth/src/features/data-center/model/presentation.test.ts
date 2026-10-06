import { expect, it } from "vitest";
import { byteText, canContinue, dateError, intervalError, numberText, recheckKind, sourceLink, waitText } from "./presentation";
import type { Task } from "../api/contracts";
it.each(["javascript:alert(1)", "data:application/pdf,body", "file:///Volumes/datasource/x.pdf", "/relative", "https://user:pass@x/a"])("rejects unsafe external address %s", v => expect(sourceLink(v)).toBeNull());
it("external source URL and unknown counts have explicit semantics", () => { expect(sourceLink("https://source.test/a.pdf")).toBe("https://source.test/a.pdf"); expect(numberText(null)).toBe("—"); expect(numberText(0)).toBe("0"); });
it.each([["", "2026-01-01"], ["2026-02-30", "2026-03-01"], ["20260930", "2026-10-01"], ["2026-10-01", "2026-09-30"]])("invalid date range %s %s", (a,b) => expect(dateError(a,b)).not.toBeNull());
it("includes a single same-day date and zero interval", () => { expect(dateError("2026-09-30", "2026-09-30")).toBeNull(); expect(intervalError("0")).toBeNull(); expect(intervalError("5.2")).toBeNull(); });
it.each(["", "-1", "NaN", "Infinity", "foo"])("rejects interval %s", v => expect(intervalError(v)).not.toBeNull());
it("volume/local checks cannot grant remote-blocked continue", () => {
  const t = { actions: { canContinue: true }, blockedReason: { code: "DC_REMOTE_BLOCKED" }, check: { state: "passed", kind: "volume" } } as Task;
  expect(recheckKind(t)).toBe("remoteSource"); expect(canContinue(t)).toBe(false); t.check!.kind = "remoteSource"; expect(canContinue(t)).toBe(true); t.check!.state = "blocked"; expect(canContinue(t)).toBe(false);
});
it("wait countdown reflects persisted wait deadline, unknown length is not a ratio", () => {
  const t = { wait: { kind: "cooldown", until: "2026-10-06T02:00:10Z" } } as Task;
  expect(waitText(t, Date.parse("2026-10-06T02:00:05Z"))).toBe("等待源站冷却 5 秒"); expect(byteText(1024)).toBe("1,024 B");
});
