import type { CalculationStatus, PositionsResponse } from "../api/generatedContracts";
import { CALCULATION_READ_POLICY } from "./calculationReadPolicy";

export type PositionsReadApi = {
  positions: (selected: string, signal: AbortSignal) => Promise<PositionsResponse>;
  status: (account: string, signal: AbortSignal) => Promise<CalculationStatus>;
  epoch: () => number;
};
export type PositionsReadEvent = { kind: "data"; data: PositionsResponse } | { kind: "error" };
type Pending = { version: string; due: number };

/** One visible scope, one serial chain. It never saves, retries writes or starts calculations. */
export class PositionsReader {
  private stopped = true;
  private epoch: number;
  private controller: AbortController | null = null;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private pending = new Map<string, Pending>();
  private terminal = new Map<string, string>();
  private generation = 0;

  constructor(private selected: string, private api: PositionsReadApi, private publish: (event: PositionsReadEvent) => void) {
    this.epoch = api.epoch();
  }
  start() {
    this.stop();
    this.stopped = false;
    this.epoch = this.api.epoch();
    this.pending.clear(); this.terminal.clear();
    void this.run(true);
  }
  stop() {
    this.stopped = true; ++this.generation;
    clearTimeout(this.timer); this.timer = undefined;
    this.controller?.abort(); this.controller = null;
  }
  private current(generation: number) {
    return !this.stopped && generation === this.generation && this.epoch === this.api.epoch();
  }
  private async full(signal: AbortSignal, generation: number) {
    const data = await this.api.positions(this.selected, signal);
    if (!this.current(generation)) return;
    const next = new Map<string, Pending>();
    for (const account of data.coverage.accounts) {
      if (!["Recalculating", "Delayed", "Partial"].includes(account.dataStatus)) continue;
      const reference = data.readContext.accounts.find(ref => ref.accountId === account.accountId);
      if (!reference) throw new Error("Account coverage has no fixed read reference");
      const version = reference.calculationTargetVersion;
      if (this.terminal.get(account.accountId) === version) continue;
      const previous = this.pending.get(account.accountId);
      next.set(account.accountId, previous?.version === version ? previous : {
        version, due: Date.now() + CALCULATION_READ_POLICY.activeDelayMs });
    }
    this.pending = next;
    this.publish({ kind: "data", data });
  }
  private async run(full: boolean) {
    const generation = this.generation;
    if (!this.current(generation) || this.controller !== null) return;
    const controller = new AbortController(); this.controller = controller;
    try {
      if (full) await this.full(controller.signal, generation);
      else {
        const due = [...this.pending].filter(([, value]) => value.due <= Date.now()).sort(([a], [b]) => a.localeCompare(b));
        let refresh = false;
        for (const [account, pending] of due) {
          if (!this.current(generation)) return;
          const status = await this.api.status(account, controller.signal);
          if (!this.current(generation)) return;
          if (status.stage === "PUBLISHED" || status.stage === "FAILED") {
            this.pending.delete(account); this.terminal.set(account, status.calculationTargetVersion);
            refresh = true;
          } else {
            this.pending.set(account, { version: status.calculationTargetVersion, due: Date.now()
              + (status.stage === "WAITING_DATA" ? CALCULATION_READ_POLICY.waitingDataDelayMs : CALCULATION_READ_POLICY.activeDelayMs) });
            if (status.calculationTargetVersion !== pending.version) refresh = true;
          }
        }
        if (refresh) await this.full(controller.signal, generation);
      }
    } catch {
      if (this.current(generation)) { this.stop(); this.publish({ kind: "error" }); }
    } finally {
      if (this.current(generation)) {
        this.controller = null;
        if (this.pending.size) {
          let earliest = Infinity;
          for (const pending of this.pending.values()) earliest = Math.min(earliest, pending.due);
          const delay = Math.max(0, earliest - Date.now());
          this.timer = setTimeout(() => { this.timer = undefined; void this.run(false); }, delay);
        }
      }
    }
  }
}
