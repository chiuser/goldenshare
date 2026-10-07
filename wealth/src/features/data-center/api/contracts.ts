/** Mirrors the approved Biz DTOs; NULL means unknown, never zero or undownloaded. */
export interface ModuleCard { moduleKey: string; title: string; description: string; path: string; badge: string }
export type DownloadStatus = "all" | "downloaded" | "undownloaded";
export interface Conditions { startDate: string; endDate: string; tsCode: string | null; titleKeyword: string; downloadStatus: DownloadStatus }
export interface Context {
  moduleEnabled: boolean; archiveAvailability: string; sourceAvailability: string; ledgerAvailability: string;
  archiveLocation: string; currentRunId: string | null;
  queryDefaults: Pick<Conditions, "startDate" | "endDate" | "downloadStatus">;
  downloadDefaults: { startDate: null; endDate: null; intervalSeconds: number };
  policy: { pageSize: 50; companyLimit: number; pollSeconds: number };
  observedAnnDate: string | null; sourceUpdateSucceededAt: string | null;
}
export interface PageState { status: "preparing" | "ready" | "empty" | "error"; code: string | null; message: string | null; asOfTime: string }
export interface Preparation { stage: "readingSource" | "checkingStatus" | "counting"; artifactsChecked: number; datesScanned: number; datesTotal: number; recordsScanned: number }
export interface AnnouncementRow {
  recordKey: string; annDate: string; tsCode: string | null; companyName: string;
  companyNameSource: "master" | "announcement" | "code"; title: string | null; sourceUrl: string | null;
  downloadStatus: Exclude<DownloadStatus, "all"> | null; statusCheckedAt: string | null;
}
export interface QueryResult {
  queryId: string; pageState: PageState; sourceVersion: string | null; conditions: Conditions;
  items: AnnouncementRow[]; total: number | null; page: number; pageSize: 50;
  hasPrevious: boolean; hasNext: boolean; downloadStatusAvailable: boolean; preparation: Preparation | null;
}
export interface Company {
  tsCode: string; name: string; initials: string | null; matchedAlias: string | null;
  nameSource: "master" | "announcement" | "code"; matchKind: "exactCode" | "codePrefix" | "name" | "initials" | "alias";
}
export interface Companies { keyword: string; items: Company[]; hasMore: boolean | null; pageState: PageState | null; preparation: Preparation | null; queryId: string | null }
export interface PublicError { code: string; message: string }
export interface PreviewRequest { startDate: string; endDate: string; intervalSeconds: number }
export interface Preview extends PreviewRequest {
  previewId: string; state: "preparing" | "ready" | "empty" | "error" | "cancelled";
  recordCount: number | null; artifactCount: number | null; missingUrlCount: number | null;
  reusableEstimate: number | null; downloadEstimate: number | null; canStart: boolean;
  expiresAt: string | null; preparation: Pick<Preparation, "datesScanned" | "datesTotal" | "recordsScanned">; error: PublicError | null;
}
export type Phase = "preparing" | "downloading" | "stopping" | "completed" | "partial_failed" | "cancelled" | "blocked" | "stopped" | "interrupted";
export interface Task {
  runId: string; rootRunId: string; retryOfRunId: string | null; batchKind: "date" | "retry"; phase: Phase; revision: number;
  startDate: string; endDate: string; intervalSeconds: number; archiveLocation: string;
  createdAt: string; startedAt: string | null; finishedAt: string | null;
  recordCount: number; missingUrlCount: number; total: number | null; processed: number;
  succeeded: number; reused: number; failed: number; remaining: number | null; percent: number | null; unresolvedFailureCount: number;
  preparation: { datesScanned: number; datesTotal: number; currentDate: string | null };
  current: { artifactKey: string; annDate: string; tsCode: string | null; companyName: string; title: string | null;
    attemptNumber: number; maxAttempts: 3; bytesReceived: number; bytesTotal: number | null; transferState: "receiving" | "verifying" } | null;
  wait: { kind: "interval" | "backoff" | "cooldown"; until: string } | null;
  businessUpdatedAt: string; heartbeatAt: string; etaSeconds: null; blockedReason: PublicError | null;
  actions: { canStop: boolean; canContinue: boolean; canRetryFailed: boolean; canCreateNew: boolean; canRecheck: boolean; reason: string | null };
  check: { state: "checking" | "passed" | "blocked" | "unknown" | "cancelled"; kind: "volume" | "localSource" | "remoteSource"; code: string | null; updatedAt: string } | null;
}
export type RecheckKind = NonNullable<Task["check"]>["kind"];
export type ResultFilter = "all" | "failed" | "pending" | "succeeded" | "reused";
export interface RunFile {
  artifactKey: string; representativeRecordKey: string | null; annDate: string | null; tsCode: string | null; companyName: string;
  title: string | null; result: "pending" | "processing" | "succeeded" | "reused" | "failed"; attempts: number;
  lastError: (PublicError & { httpStatus: number | null }) | null; canRetry: boolean;
}
export interface Files { runId: string; items: RunFile[]; nextCursor: string | null }
export interface HistoryItem {
  runId: string; startDate: string | null; endDate: string | null; phase: string; createdAt: string | null;
  total: number; succeeded: number; reused: number; failed: number; rootRunId: string; retryOfRunId: string | null;
}
export interface History { currentRunId: string | null; items: HistoryItem[]; nextCursor: string | null }
