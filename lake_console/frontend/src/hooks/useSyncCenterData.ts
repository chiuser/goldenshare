import { useEffect, useState } from "react";
import { loadSyncCurrentRun, loadSyncLock, loadSyncProfiles, loadSyncRecommendations, loadSyncRunDetail, loadSyncRunEvents } from "../services/lakeApi";
import type { SyncCurrentRun, SyncLock, SyncProfileSummary, SyncRecommendationResponse, SyncRunDetail, SyncRunEvent } from "../types";

export function useSyncCenterStatus() {
  const [profiles, setProfiles] = useState<SyncProfileSummary[]>([]);
  const [lock, setLock] = useState<SyncLock | null>(null);
  const [currentRun, setCurrentRun] = useState<SyncCurrentRun | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function loadData() {
      setLoading(true);
      try {
        const [profilePayload, lockPayload, currentPayload] = await Promise.all([
          loadSyncProfiles(),
          loadSyncLock(),
          loadSyncCurrentRun(),
        ]);
        if (!cancelled) {
          setProfiles(profilePayload);
          setLock(lockPayload);
          setCurrentRun(currentPayload);
          setError(null);
        }
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "未知错误");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    void loadData();
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  return {
    currentRun,
    error,
    loading,
    lock,
    profiles,
    reloadStatus: () => setReloadKey((value) => value + 1),
  };
}

export function useSyncRecommendations(profileKey: string | null = "prod_db_daily") {
  const [recommendations, setRecommendations] = useState<SyncRecommendationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    if (!profileKey) {
      setRecommendations(null);
      setError(null);
      setLoading(false);
      return () => {
        cancelled = true;
      };
    }
    const effectiveProfileKey = profileKey;
    async function loadData() {
      setLoading(true);
      try {
        const payload = await loadSyncRecommendations(effectiveProfileKey);
        if (!cancelled) {
          setRecommendations(payload);
          setError(null);
        }
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "未知错误");
          setRecommendations(null);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    void loadData();
    return () => {
      cancelled = true;
    };
  }, [profileKey, reloadKey]);

  return {
    error,
    loading,
    recommendations,
    reloadRecommendations: () => setReloadKey((value) => value + 1),
  };
}

export function useSyncRunArtifacts(runId: string) {
  const [detail, setDetail] = useState<SyncRunDetail | null>(null);
  const [events, setEvents] = useState<SyncRunEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    if (!runId) {
      setDetail(null);
      setEvents([]);
      setError(null);
      setLoading(false);
      return () => {
        cancelled = true;
      };
    }

    async function loadData() {
      setLoading(true);
      try {
        const [detailPayload, eventPayload] = await Promise.all([
          loadSyncRunDetail(runId),
          loadSyncRunEvents(runId, 0),
        ]);
        if (!cancelled) {
          setDetail(detailPayload);
          setEvents(eventPayload.items);
          setError(null);
        }
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "未知错误");
          setDetail(null);
          setEvents([]);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadData();
    return () => {
      cancelled = true;
    };
  }, [runId, reloadKey]);

  useEffect(() => {
    if (!runId || !detail || isFinishedRunStatus(detail.status)) {
      return undefined;
    }
    const timer = window.setInterval(() => setReloadKey((value) => value + 1), 3000);
    return () => window.clearInterval(timer);
  }, [detail, runId]);

  return {
    detail,
    error,
    events,
    loading,
    reloadArtifacts: () => setReloadKey((value) => value + 1),
  };
}

function isFinishedRunStatus(status: string): boolean {
  return ["success", "failed", "backup_failed", "cancelled", "stopped_after_stage"].includes(status);
}
