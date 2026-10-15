export type IndexDetailRequestKind = "chart" | "nineTurn" | "xxm" | "forecast";

const PRIORITY: Record<IndexDetailRequestKind, number> = { chart: 0, nineTurn: 1, xxm: 2, forecast: 3 };
const MAX_LIGHT_REQUESTS = 2;
interface Pending {
  kind: IndexDetailRequestKind;
  work: () => Promise<unknown>;
  resolve: (value: unknown) => void;
  reject: (reason: unknown) => void;
  signal?: AbortSignal;
  abort: () => void;
}

export class IndexDetailRequestScheduler {
  private queue: Pending[] = [];
  private running = 0;
  private exclusive = false;
  private scheduled = false;

  run<T>(kind: IndexDetailRequestKind, work: () => Promise<T>, signal?: AbortSignal): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      if (signal?.aborted) { reject(signal.reason ?? new DOMException("Aborted", "AbortError")); return; }
      const task: Pending = {
        kind, work, resolve: value => resolve(value as T), reject, signal,
        abort: () => {
          this.queue = this.queue.filter(item => item !== task);
          signal?.removeEventListener("abort", task.abort);
          reject(signal?.reason ?? new DOMException("Aborted", "AbortError"));
          this.schedule();
        },
      };
      signal?.addEventListener("abort", task.abort, { once: true });
      this.queue.push(task);
      this.schedule();
    });
  }

  private schedule() {
    if (this.scheduled) return;
    this.scheduled = true;
    void Promise.resolve().then(() => { this.scheduled = false; this.pump(); });
  }

  private pump() {
    this.queue.sort((a, b) => PRIORITY[a.kind] - PRIORITY[b.kind]);
    while (!this.exclusive && this.running < MAX_LIGHT_REQUESTS && this.queue.length) {
      const task = this.queue[0];
      const exclusive = task.kind === "xxm" || task.kind === "forecast";
      if (exclusive && this.running) return;
      this.queue.shift();
      task.signal?.removeEventListener("abort", task.abort);
      this.running++;
      this.exclusive = exclusive;
      void Promise.resolve().then(() => {
        task.signal?.throwIfAborted();
        return task.work();
      }).then(task.resolve, task.reject).finally(() => {
        this.running--;
        if (exclusive) this.exclusive = false;
        this.schedule();
      });
    }
  }
}

// One queue per browser realm; separate tabs share the server's source loads.
export const indexDetailRequests = new IndexDetailRequestScheduler();
