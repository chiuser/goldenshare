import { useCallback, useEffect, useRef, useState } from "react";
import type { Context, Preview, Task } from "../api/contracts";
import { dataCenterApi, DataCenterApiError, errorMessage } from "../api/dataCenterApi";
import { dateError, intervalError, isActive } from "./presentation";
import { useObserver } from "./useObserver";
export function useDownloads(context: Context, enabled: boolean, routeRunId: string | null, selectRun: (id: string | null) => void, refreshContext: () => void) {
  const [startDate, setStart] = useState(""); const [endDate, setEnd] = useState("");
  const [interval, setInterval] = useState(String(context.downloadDefaults.intervalSeconds));
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const [historyRevision, setHistoryRevision] = useState(0);
  const runId = routeRunId ?? context.currentRunId;
  const taskRead = useCallback((s: AbortSignal) => dataCenterApi.task(runId!, s), [runId]);
  const task = useObserver(enabled && runId ? taskRead : null, isActive, context.policy.pollSeconds);
  const previewRead = useCallback((s: AbortSignal) => dataCenterApi.preview(preview!.previewId, s), [preview?.previewId]);
  const previewObserved = useObserver(enabled && preview?.state === "preparing" ? previewRead : null, p => p.state === "preparing", context.policy.pollSeconds);
  useEffect(() => { if (previewObserved.value) setPreview(previewObserved.value); }, [previewObserved.value]);
  const pending = useRef<{ key: string; send: (key: string) => Promise<Task> } | null>(null);
  const lock = useRef(false); const mounted = useRef(true); const preparation = useRef<AbortController | null>(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; preparation.current?.abort(); }; }, []);
  async function command(send: (key: string) => Promise<Task>, retry = false) {
    if (lock.current || (!retry && pending.current)) return;
    const intent = retry ? pending.current : { key: crypto.randomUUID(), send };
    if (!intent) return;
    pending.current = intent; lock.current = true; setBusy(true); setError(null);
    try {
      const response = await intent.send(intent.key);
      pending.current = null;
      if (mounted.current) { task.setValue(response); task.refresh(); selectRun(response.runId); setPreview(null); setStart(""); setEnd(""); setHistoryRevision(v => v + 1); refreshContext(); }
    } catch (e) {
      // A received 4xx is a definitive refusal; an unknown outcome retains the exact intent/key.
      if (e instanceof DataCenterApiError && e.status < 500) { pending.current = null; task.refresh(); refreshContext(); }
      if (mounted.current) setError(`${errorMessage(e)}${pending.current ? "。操作结果尚未确认，请先重新读取任务，再使用原操作重试。" : ""}`);
      if (e instanceof DataCenterApiError && e.code === "DC_PREVIEW_STALE") setPreview(null);
    } finally { lock.current = false; if (mounted.current) setBusy(false); }
  }
  async function action(send: () => Promise<Task>) {
    if (lock.current || pending.current) return;
    lock.current = true; setBusy(true); setError(null);
    try { const response = await send(); if (mounted.current) { task.setValue(response); task.refresh(); setHistoryRevision(v => v + 1); refreshContext(); } }
    catch (e) { if (mounted.current) { setError(errorMessage(e)); task.refresh(); } }
    finally { lock.current = false; if (mounted.current) setBusy(false); }
  }
  async function prepare() {
    if (lock.current || pending.current || dateError(startDate, endDate) || intervalError(interval)) return;
    lock.current = true; setBusy(true); setError(null);
    const controller = new AbortController(); preparation.current = controller;
    try { const result = await dataCenterApi.createPreview({ startDate, endDate, intervalSeconds: Number(interval) }, controller.signal); if (mounted.current && !controller.signal.aborted) setPreview(result); }
    catch (e) { if (mounted.current && !controller.signal.aborted) setError(errorMessage(e)); }
    finally { lock.current = false; if (mounted.current) setBusy(false); }
  }
  function change(update: () => void) { preparation.current?.abort(); setPreview(null); setError(null); update(); }
  async function stopPreview() {
    if (lock.current || !preview) return;
    lock.current = true; setBusy(true);
    try { setPreview(await dataCenterApi.stopPreview(preview.previewId)); }
    catch (e) { setError(errorMessage(e)); }
    finally { lock.current = false; setBusy(false); }
  }
  const run = task.value && task.value.runId.replaceAll("-", "") === runId?.replaceAll("-", "") ? task.value : null;
  return { startDate, endDate, interval, setStart: (v: string) => change(() => setStart(v)), setEnd: (v: string) => change(() => setEnd(v)),
    setInterval: (v: string) => change(() => setInterval(v)), preview, adjust: () => setPreview(null), prepare, stopPreview,
    validation: dateError(startDate, endDate) ?? intervalError(interval), busy, unresolvedCommand: pending.current !== null,
    error: error ?? previewObserved.error, run, runId, observationError: task.error, observing: task.loading, historyRevision,
    refresh: () => { task.refresh(); refreshContext(); }, retryCommand: () => void command(() => Promise.reject(), true),
    start: () => preview && void command(key => dataCenterApi.createRun(preview.previewId, key)),
    continueRun: () => run && void command(key => dataCenterApi.continue(run.runId, key)),
    retry: (key: string | null) => run && void command(intent => dataCenterApi.retry(run.runId, key, intent)),
    stop: () => run && void action(() => dataCenterApi.stop(run.runId)),
    recheck: (kind: "volume" | "localSource" | "remoteSource") => run && void action(() => dataCenterApi.recheck(run.runId, kind)),
    newDownload: () => { selectRun(null); setStart(""); setEnd(""); setPreview(null); setError(null); refreshContext(); } };
}
export type DownloadsController = ReturnType<typeof useDownloads>;
