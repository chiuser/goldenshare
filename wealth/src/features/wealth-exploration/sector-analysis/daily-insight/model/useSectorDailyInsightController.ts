import { useEffect, useMemo, useRef, useState } from "react";
import { buildSectorDailyInsightMetaViewModel, buildSectorDailyInsightSnapshotViewModel } from "../api/sectorDailyInsightAdapter";
import { DailyInsightApiError, fetchSectorDailyInsightMeta, fetchSectorDailyInsightSnapshot } from "../api/sectorDailyInsightApi";
import { DailyInsightContractError } from "../api/sectorDailyInsightContract";
import type { DailyInsightLevel, DailyInsightMeta, DailyInsightSnapshotRequest, DailyInsightSnapshotViewModel, DailyInsightViewState } from "../api/sectorDailyInsightTypes";
import { buildSectorDailyInsightSearch, parseSectorDailyInsightUrlState } from "./sectorDailyInsightUrlState";

const REQUEST_TIMEOUT_MS = 5000;
type Resource<T> = { key: string; kind: "ready"; data: T } | { key: string; kind: "loading" | "error"; message?: string; retryable?: boolean };
interface Input { enabled: boolean; search: string; onNavigateSearch: (search: string, options?: { replace?: boolean }) => void }

export function useSectorDailyInsightController({ enabled, search, onNavigateSearch }: Input) {
  const parsed = useMemo(() => parseSectorDailyInsightUrlState(search), [search]);
  const urlState = parsed.ok ? parsed.value : null;
  const [metaResource, setMeta] = useState<Resource<DailyInsightMeta> | null>(null);
  const [snapshotResource, setSnapshot] = useState<Resource<DailyInsightSnapshotViewModel> | null>(null);
  const [reload, setReload] = useState(0);
  const [snapshotRetry, setSnapshotRetry] = useState(0);
  const conflictAttempt = useRef({ search, count: 0 });
  if (conflictAttempt.current.search !== search) conflictAttempt.current = { search, count: 0 };
  // Date changes reload coverage; a level-only change never reloads Meta.
  const metaKey = enabled && urlState ? `${urlState.tradeDate ?? "AUTO"}|${reload}` : "";

  useEffect(() => {
    if (!metaKey) return;
    let active = true;
    const abort = new AbortController();
    setMeta({ key: metaKey, kind: "loading" });
    const timer = window.setTimeout(() => {
      if (!active) return;
      abort.abort();
      setMeta({ key: metaKey, kind: "error", message: "请求超时，请稍后重试。", retryable: true });
    }, REQUEST_TIMEOUT_MS);
    fetchSectorDailyInsightMeta(abort.signal).then((payload) => {
      if (active && !abort.signal.aborted) setMeta({ key: metaKey, kind: "ready", data: buildSectorDailyInsightMetaViewModel(payload) });
    }).catch((error: unknown) => {
      if (active && !abort.signal.aborted) setMeta({ key: metaKey, ...safeError(error) });
    }).finally(() => window.clearTimeout(timer));
    return () => { active = false; abort.abort(); window.clearTimeout(timer); };
  }, [metaKey]);

  const meta = metaKey && metaResource?.key === metaKey && metaResource.kind === "ready" ? metaResource.data : null;
  const selection = useMemo(() => {
    if (!meta || !urlState) return null;
    const date = urlState.tradeDate ?? meta.defaultTradeDate;
    if (!date) return { kind: "empty" as const, message: "当前尚无已发布的每日洞察。" };
    const day = meta.tradeDates.find((candidate) => candidate.tradeDate === date);
    if (!day) return { kind: "error" as const, message: "所选交易日不在每日洞察覆盖范围内。" };
    if (day.availability !== "PUBLISHED" || !day.batchKey || !day.hierarchyVersion) return { kind: "empty" as const, message: "所选交易日的每日洞察尚未发布。" };
    return { kind: "ready" as const, request: { tradeDate: date, industryLevel: urlState.level, batchKey: day.batchKey, hierarchyVersion: day.hierarchyVersion } satisfies DailyInsightSnapshotRequest };
  }, [meta, urlState]);
  const request = selection?.kind === "ready" ? selection.request : null;
  const snapshotKey = request ? `${metaKey}|${search}|${request.tradeDate}|${request.batchKey}|${request.hierarchyVersion}|${request.industryLevel}|${snapshotRetry}` : "";
  const liveKey = useRef(snapshotKey);
  liveKey.current = snapshotKey;

  useEffect(() => {
    if (!request || !snapshotKey) return;
    let active = true;
    const abort = new AbortController();
    const key = snapshotKey;
    const current = () => active && !abort.signal.aborted && liveKey.current === key;
    setSnapshot({ key, kind: "loading" });
    const timer = window.setTimeout(() => {
      if (!current()) return;
      abort.abort();
      setSnapshot({ key, kind: "error", message: "请求超时，请稍后重试。", retryable: true });
    }, REQUEST_TIMEOUT_MS);
    fetchSectorDailyInsightSnapshot(request, abort.signal).then((payload) => {
      if (!current()) return;
      const data = buildSectorDailyInsightSnapshotViewModel(payload, request);
      setSnapshot({ key, kind: "ready", data });
    }).catch((error: unknown) => {
      if (!current()) return;
      if (error instanceof DailyInsightApiError && error.status === 409) {
        if (conflictAttempt.current.count === 0) {
          conflictAttempt.current.count = 1;
          setReload((value) => value + 1);
          return;
        }
        setSnapshot({ key, kind: "error", message: "每日洞察版本发生变化，请重新加载。", retryable: true });
      } else setSnapshot({ key, ...safeError(error) });
    }).finally(() => window.clearTimeout(timer));
    return () => { active = false; abort.abort(); window.clearTimeout(timer); };
  // snapshotKey contains the complete request and retry identity.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snapshotKey]);

  let viewState: DailyInsightViewState = { kind: "loading", ...(meta ? { meta } : {}) };
  if (!parsed.ok) viewState = { kind: "error", message: parsed.message, retryable: false };
  else if (metaKey && metaResource?.key === metaKey && metaResource.kind === "error") viewState = { kind: "error", message: metaResource.message, retryable: metaResource.retryable };
  else if (meta && selection && selection.kind !== "ready") viewState = { ...selection, meta, retryable: false };
  else if (meta && snapshotKey && snapshotResource?.key === snapshotKey) {
    if (snapshotResource.kind === "error") viewState = { kind: "error", meta, message: snapshotResource.message, retryable: snapshotResource.retryable };
    else if (snapshotResource.kind === "ready") {
      const snapshot = snapshotResource.data;
      const kind = snapshot.facts.status === "EMPTY" ? "empty" : snapshot.facts.status === "ERROR" ? "error" : urlState?.tradeDate === null && meta.status === "DELAYED" ? "delayed" : "ready";
      viewState = { kind, meta, snapshot, message: kind === "empty" ? "当前层级暂无可展示的每日洞察事实。" : kind === "error" ? "每日洞察读取失败，请稍后重试。" : undefined, retryable: kind === "error" };
    }
  }
  return {
    urlState, viewState, identity: snapshotKey,
    selectLevel: (level: DailyInsightLevel) => { if (urlState) onNavigateSearch(buildSectorDailyInsightSearch({ ...urlState, level })); },
    selectTradeDate: (tradeDate: string | null) => { if (urlState) onNavigateSearch(buildSectorDailyInsightSearch({ ...urlState, tradeDate })); },
    retry: () => {
      conflictAttempt.current.count = 0;
      if (meta) setSnapshotRetry((value) => value + 1);
      else setReload((value) => value + 1);
    },
  };
}
function safeError(error: unknown) {
  if (error instanceof DailyInsightApiError && error.status === 401) return { kind: "error" as const, message: "登录已失效，请重新登录。", retryable: false };
  return { kind: "error" as const, message: error instanceof DailyInsightContractError ? error.message : "每日洞察读取失败，请稍后重试。", retryable: !(error instanceof DailyInsightApiError) || error.status === 409 || error.status >= 500 };
}
export type SectorDailyInsightController = ReturnType<typeof useSectorDailyInsightController>;
