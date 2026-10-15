import { expect, it, vi } from "vitest";
import { IndexDetailRequestScheduler } from "./indexDetailRequestScheduler";

function deferred() {
  let resolve!: (value?: unknown) => void;
  const promise = new Promise<unknown>(done => { resolve = done; });
  return { promise, resolve };
}
async function flush() { for (let i = 0; i < 12; i++) await Promise.resolve(); }

it("prioritizes chart and nine-turn reads; full-history jobs never overlap other work", async () => {
  const queue = new IndexDetailRequestScheduler();
  const start: string[] = [];
  const gates = Array.from({ length: 5 }, deferred);
  const work = (index: number, name: string) => () => { start.push(name); return gates[index].promise; };
  const requests = [queue.run("forecast", work(0, "forecast")), queue.run("xxm", work(1, "xxm")),
    queue.run("nineTurn", work(2, "nine")), queue.run("chart", work(3, "bars")), queue.run("chart", work(4, "indicators"))];
  await flush(); expect(start).toEqual(["bars", "indicators"]);
  gates[3].resolve(); await flush(); expect(start).toEqual(["bars", "indicators", "nine"]);
  gates[4].resolve(); await flush(); expect(start).toHaveLength(3);
  gates[2].resolve(); await flush(); expect(start.at(-1)).toBe("xxm");
  gates[1].resolve(); await flush(); expect(start.at(-1)).toBe("forecast");
  gates[0].resolve(); await Promise.all(requests);
});

it("removes a cancelled queued request before any network work begins", async () => {
  const queue = new IndexDetailRequestScheduler(); const gate = deferred();
  const first = queue.run("forecast", () => gate.promise);
  await flush();
  const controller = new AbortController(); const send = vi.fn();
  const queued = queue.run("chart", send, controller.signal);
  const cancelled = expect(queued).rejects.toMatchObject({ name: "AbortError" });
  controller.abort(); await cancelled;
  gate.resolve(); await first; await flush(); expect(send).not.toHaveBeenCalled();
});

it("keeps an active cancelled job's slot until its transport settles", async () => {
  const queue = new IndexDetailRequestScheduler(); const gate = deferred(); const controller = new AbortController();
  const first = queue.run("forecast", () => gate.promise, controller.signal);
  await flush();
  const send = vi.fn().mockResolvedValue(2); const next = queue.run("chart", send);
  controller.abort(); await flush(); expect(send).not.toHaveBeenCalled();
  gate.resolve(); await first; await next; expect(send).toHaveBeenCalledTimes(1);
});

it("releases failed work, preserves FIFO and isolates two tab queues", async () => {
  const first = new IndexDetailRequestScheduler(), second = new IndexDetailRequestScheduler();
  const gate = deferred(); const blocked = first.run("forecast", () => gate.promise);
  await flush();
  const order: number[] = [];
  const bad = first.run("forecast", async () => { order.push(1); throw Error("failure"); });
  const failure = expect(bad).rejects.toThrow("failure");
  const next = first.run("forecast", async () => { order.push(2); });
  await expect(second.run("forecast", async () => "other tab")).resolves.toBe("other tab");
  expect(order).toEqual([]); gate.resolve(); await blocked; await failure; await next;
  expect(order).toEqual([1, 2]);
});
