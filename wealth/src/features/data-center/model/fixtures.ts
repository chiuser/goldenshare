/** Isolated DTO samples for negative-state tests; production has no mock adapter. */
import type { Context, Task } from "../api/contracts";
export const contextFixture: Context = { moduleEnabled: true, archiveAvailability: "ready", sourceAvailability: "ready", indexAvailability: "ready", archiveLocation: "/Volumes/datasource/announcements", currentRunId: null,
  queryDefaults: { startDate: "2026-09-07", endDate: "2026-10-06", downloadStatus: "all" }, downloadDefaults: { startDate: null, endDate: null, intervalSeconds: 5 }, policy: { pageSize: 50, companyLimit: 20, pollSeconds: 2 }, observedAnnDate: "2026-09-30", lastIndexedAt: "2026-10-06T02:00:00Z", sourceUpdateSucceededAt: null };
export const taskFixture: Task = { runId: "11111111-1111-4111-8111-111111111111", rootRunId: "11111111-1111-4111-8111-111111111111", retryOfRunId: null, batchKind: "date", phase: "downloading", revision: 1,
  startDate: "2026-09-01", endDate: "2026-09-30", intervalSeconds: 5, archiveLocation: "/Volumes/datasource/announcements", createdAt: "2026-10-06T02:00:00Z", startedAt: "2026-10-06T02:00:00Z", finishedAt: null,
  recordCount: 1028, missingUrlCount: 8, total: 1000, processed: 320, succeeded: 300, reused: 10, failed: 10, remaining: 680, percent: 32, unresolvedFailureCount: 10,
  preparation: { datesScanned: 30, datesTotal: 30, currentDate: null }, current: null, wait: null, businessUpdatedAt: "2026-10-06T02:02:15Z", heartbeatAt: "2026-10-06T02:02:15Z", etaSeconds: null, blockedReason: null,
  actions: { canStop: true, canContinue: false, canRetryFailed: false, canCreateNew: false, canRecheck: false, reason: null }, check: null };
