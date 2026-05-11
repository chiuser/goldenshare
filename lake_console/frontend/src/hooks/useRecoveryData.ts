import { useEffect, useState } from "react";
import { loadRecoveryRepositorySummary, loadRecoverySnapshotDetail, loadRecoverySnapshots } from "../services/lakeApi";
import type { RecoveryRepositorySummary, RecoverySnapshotDetail, RecoverySnapshotSummary } from "../types";

export type RecoveryFilters = {
  scope: string;
  datasetKey: string;
  pinnedOnly: boolean;
  baselineOnly: boolean;
  query: string;
};

export const DEFAULT_RECOVERY_FILTERS: RecoveryFilters = {
  scope: "",
  datasetKey: "",
  pinnedOnly: false,
  baselineOnly: false,
  query: "",
};

export function useRecoveryRepositorySummary() {
  const [summary, setSummary] = useState<RecoveryRepositorySummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [summaryLoading, setSummaryLoading] = useState<boolean>(true);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function loadData() {
      setSummaryLoading(true);
      try {
        const payload = await loadRecoveryRepositorySummary();
        if (!cancelled) {
          setSummary(payload);
          setSummaryError(null);
        }
      } catch (caught) {
        if (!cancelled) {
          setSummaryError(caught instanceof Error ? caught.message : "未知错误");
        }
      } finally {
        if (!cancelled) {
          setSummaryLoading(false);
        }
      }
    }
    void loadData();
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  return {
    summary,
    summaryError,
    summaryLoading,
    reloadSummary: () => setReloadKey((value) => value + 1),
  };
}

export function useRecoverySnapshots(filters: RecoveryFilters) {
  const [records, setRecords] = useState<RecoverySnapshotSummary[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [recordsError, setRecordsError] = useState<string | null>(null);
  const [recordsLoading, setRecordsLoading] = useState<boolean>(true);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function loadData() {
      setRecordsLoading(true);
      try {
        const payload = await loadRecoverySnapshots({
          scope: filters.scope || undefined,
          datasetKey: filters.datasetKey || undefined,
          pinned: filters.pinnedOnly ? true : undefined,
          baselineOnly: filters.baselineOnly ? true : undefined,
          query: filters.query.trim() || undefined,
          limit: 100,
          offset: 0,
        });
        if (!cancelled) {
          setRecords(payload.items);
          setTotal(payload.total);
          setRecordsError(null);
        }
      } catch (caught) {
        if (!cancelled) {
          setRecordsError(caught instanceof Error ? caught.message : "未知错误");
          setRecords([]);
          setTotal(0);
        }
      } finally {
        if (!cancelled) {
          setRecordsLoading(false);
        }
      }
    }
    void loadData();
    return () => {
      cancelled = true;
    };
  }, [filters, reloadKey]);

  return {
    records,
    total,
    recordsError,
    recordsLoading,
    reloadSnapshots: () => setReloadKey((value) => value + 1),
  };
}

export function useRecoverySnapshotDetail(recordId: string) {
  const [detail, setDetail] = useState<RecoverySnapshotDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState<boolean>(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    if (!recordId) {
      setDetail(null);
      setDetailError(null);
      setDetailLoading(false);
      return () => {
        cancelled = true;
      };
    }
    async function loadData() {
      setDetailLoading(true);
      try {
        const payload = await loadRecoverySnapshotDetail(recordId);
        if (!cancelled) {
          setDetail(payload);
          setDetailError(null);
        }
      } catch (caught) {
        if (!cancelled) {
          setDetailError(caught instanceof Error ? caught.message : "未知错误");
          setDetail(null);
        }
      } finally {
        if (!cancelled) {
          setDetailLoading(false);
        }
      }
    }
    void loadData();
    return () => {
      cancelled = true;
    };
  }, [recordId, reloadKey]);

  return {
    detail,
    detailError,
    detailLoading,
    reloadDetail: () => setReloadKey((value) => value + 1),
  };
}
