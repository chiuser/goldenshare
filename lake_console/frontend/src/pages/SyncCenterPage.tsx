import { useEffect, useState } from "react";
import { Badge, type BadgeTone } from "../components/Badge";
import { DataTableCard, type DataTableColumn } from "../components/DataTableCard";
import { EmptyState } from "../components/EmptyState";
import { ErrorStateBlock } from "../components/ErrorStateBlock";
import { LoadingBlock } from "../components/LoadingBlock";
import { Metric } from "../components/Metric";
import { PageHeader } from "../components/PageHeader";
import { Panel } from "../components/Panel";
import { SectionCard } from "../components/SectionCard";
import { useSyncCenterStatus, useSyncRecommendations, useSyncRunArtifacts } from "../hooks/useSyncCenterData";
import { createSyncPlan, startSyncRun } from "../services/lakeApi";
import type { SyncLock, SyncPlanDatasetPlan, SyncPlanIssue, SyncPlanResponse, SyncProfileSummary, SyncRecommendationItem, SyncRunEvent } from "../types";
import { formatDateTime } from "../utils/format";

const RUNNABLE_PROFILE_KEYS = new Set([
  "prod_db_daily",
  "prod_db_snapshot_refresh",
  "prod_db_manual_backfill",
  "lake_reference_refresh",
]);

export function SyncCenterPage() {
  const { currentRun, error, loading, lock, profiles, reloadStatus } = useSyncCenterStatus();
  const [selectedProfileKey, setSelectedProfileKey] = useState<string>("");
  const [selectedDatasetKey, setSelectedDatasetKey] = useState<string>("");
  const [targetDate, setTargetDate] = useState<string>(todayInputValue());
  const [startDate, setStartDate] = useState<string>("");
  const [endDate, setEndDate] = useState<string>("");
  const [plan, setPlan] = useState<SyncPlanResponse | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);
  const [planLoading, setPlanLoading] = useState<boolean>(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [runLoading, setRunLoading] = useState<boolean>(false);
  const [selectedRunId, setSelectedRunId] = useState<string>("");

  const selectedProfile = profiles.find((profile) => profile.profile_key === selectedProfileKey) ?? null;
  const {
    error: recommendationError,
    loading: recommendationLoading,
    recommendations,
    reloadRecommendations,
  } = useSyncRecommendations("prod_db_daily");
  const activeRunId = selectedRunId || currentRun?.active_run_id || "";
  const { detail, error: artifactError, events, loading: artifactLoading, reloadArtifacts } = useSyncRunArtifacts(activeRunId);

  useEffect(() => {
    if (!profiles.length || selectedProfileKey) {
      return;
    }
    const preferred = profiles.find((profile) => profile.profile_key === "prod_db_snapshot_refresh");
    setSelectedProfileKey((preferred ?? profiles[0]).profile_key);
  }, [profiles, selectedProfileKey]);

  useEffect(() => {
    if (!selectedProfile) {
      return;
    }
    const keys = selectedProfile.datasets.map((item) => item.dataset_key);
    if (keys.includes(selectedDatasetKey)) {
      return;
    }
    setSelectedDatasetKey(keys[0] ?? "");
  }, [selectedDatasetKey, selectedProfile]);

  useEffect(() => {
    setPlan(null);
    setPlanError(null);
    setRunError(null);
  }, [endDate, selectedDatasetKey, selectedProfileKey, startDate, targetDate]);

  const canRunSelectedScope = Boolean(selectedProfile && isRunnableProfile(selectedProfile));
  const canStartRun = Boolean(plan && !plan.blockers.length && canRunSelectedScope && lock?.status === "idle" && !runLoading);
  const requestCount = plan?.dataset_plans.reduce((total, item) => total + item.request_count, 0) ?? 0;

  async function handleCreatePlan() {
    if (!selectedProfile) {
      return;
    }
    setPlanLoading(true);
    setPlanError(null);
    setRunError(null);
    try {
      const nextPlan = await createSyncPlan({
        profileKey: selectedProfile.profile_key,
        datasetKeys: selectedDatasetKey ? [selectedDatasetKey] : [],
        targetDate: shouldUseTargetDate(selectedProfile.profile_key) ? targetDate : null,
        startDate: shouldUseDateRange(selectedProfile.profile_key) ? startDate || null : null,
        endDate: shouldUseDateRange(selectedProfile.profile_key) ? endDate || null : null,
      });
      setPlan(nextPlan);
    } catch (caught) {
      setPlanError(caught instanceof Error ? caught.message : "未知错误");
      setPlan(null);
    } finally {
      setPlanLoading(false);
    }
  }

  async function handleStartRun() {
    if (!plan || !canStartRun) {
      return;
    }
    setRunLoading(true);
    setRunError(null);
    try {
      const response = await startSyncRun(plan.plan_token);
      setSelectedRunId(response.run_id);
      reloadStatus();
    } catch (caught) {
      setRunError(caught instanceof Error ? caught.message : "未知错误");
    } finally {
      setRunLoading(false);
    }
  }

  function handleApplyRecommendation(item: SyncRecommendationItem) {
    if (!item.plan_hint) {
      return;
    }
    setSelectedProfileKey(item.plan_hint.profile_key);
    setSelectedDatasetKey(item.plan_hint.dataset_keys[0] ?? "");
    setTargetDate(item.plan_hint.target_date ?? todayInputValue());
    setStartDate(item.plan_hint.start_date ?? "");
    setEndDate(item.plan_hint.end_date ?? "");
    setPlan(null);
    setPlanError(null);
    setRunError(null);
  }

  return (
    <div className="sync-center-layout">
      <PageHeader
        eyebrow="Local Lake / Write / Prod DB Sync"
        title="Sync Center"
        description="从远程生产库或本地参考源刷新本地 Parquet Lake。页面只暴露 Profile、白名单数据集和日期参数，不提供 SQL 能力。"
        right={<SyncLockSummary lock={lock} loading={loading} onRefresh={reloadStatus} />}
        variant="accent"
      />

      {error ? <ErrorStateBlock title="Sync Center 状态加载失败" description={error} /> : null}
      {planError ? <ErrorStateBlock title="计划生成失败" description={planError} /> : null}
      {runError ? <ErrorStateBlock title="任务启动失败" description={runError} /> : null}
      {artifactError ? <ErrorStateBlock title="任务详情加载失败" description={artifactError} /> : null}

      <section className="metric-grid sync-center-metrics">
        <Metric label="Task Gate" value={lockStatusLabel(lock?.status, loading)} hint={lockHint(lock)} variant={lockTone(lock)} />
        <Metric label="Runnable Scope" value="4 profiles" hint="M6 已开放远程 DB 与本地参考数据刷新" variant="info" />
        <Metric label="Default Lookback" value="1 day" hint="每日类 Profile 默认看最近 1 日" variant="subtle" />
        <Metric label="Remote DB" value="Read-only" hint="页面不暴露 SQL、表名或字段条件" variant="success" />
      </section>

      <Panel
        title="建议同步窗口"
        description="只读扫描本地 Lake 文件事实和本地交易日历，给出日期型数据集的建议补数范围；不会自动创建计划或启动同步。"
      >
        <div className="sync-recommendation-head">
          <div className="sync-cell-stack sync-cell-stack-tight">
            <strong>Profile: {recommendations?.profile_key ?? "prod_db_daily"}</strong>
            <span>
              参考日期 {recommendations?.expected_reference_date ?? "—"}，cutoff {recommendations?.cutoff_time ?? "20:00"}
            </span>
          </div>
          <button className="sync-inline-button" onClick={reloadRecommendations} type="button">
            刷新建议
          </button>
        </div>
        {recommendationError ? <ErrorStateBlock title="建议同步窗口加载失败" description={recommendationError} /> : null}
        {recommendationLoading ? <LoadingBlock title="正在生成建议" description="读取本地分区与交易日历。" /> : null}
        {!recommendationLoading && recommendations ? (
          <RecommendationTable rows={recommendations.items} onApply={handleApplyRecommendation} />
        ) : null}
      </Panel>

      <section className="sync-center-grid">
        <Panel title="选择同步 Profile" description="本页展示全部 Profile；只有 enabled 且 M6 runner 已接入的 profile 可以启动。">
          {loading ? <LoadingBlock title="正在加载 Profile" description="读取 Sync Center profiles / lock / current run。" /> : null}
          {!loading && profiles.length === 0 ? <EmptyState title="暂无 Profile" description="后端未返回可用 Sync Center Profile。" /> : null}
          <div className="sync-profile-grid">
            {profiles.map((profile) => (
              <button
                className={profile.profile_key === selectedProfileKey ? "sync-profile-card sync-profile-card-active" : "sync-profile-card"}
                key={profile.profile_key}
                onClick={() => setSelectedProfileKey(profile.profile_key)}
                type="button"
              >
                <span className="sync-profile-head">
                  <strong>{profile.profile_key}</strong>
                  <Badge tone={profileTone(profile)}>{profile.profile_status}</Badge>
                </span>
                <span className="sync-profile-title">{profile.display_name}</span>
                <span className="sync-profile-desc">{profile.description}</span>
                <span className="sync-profile-meta">
                  <Badge tone={profile.requires_kopia_backup ? "warning" : "muted"}>Kopia prewrite</Badge>
                  <Badge tone={profile.default_lookback_days ? "brand" : "muted"}>
                    {profile.default_lookback_days ? `lookback=${profile.default_lookback_days}` : "no default date"}
                  </Badge>
                  <Badge tone={isRunnableProfile(profile) ? "success" : "muted"}>
                    {isRunnableProfile(profile) ? "M6 可执行" : "专项待接入"}
                  </Badge>
                </span>
                {profile.disabled_reason ? <span className="sync-profile-disabled">{profile.disabled_reason}</span> : null}
              </button>
            ))}
          </div>
        </Panel>

        <Panel title="计划参数" description="先生成计划，再按计划启动任务。启动前后端会强制做 Kopia prewrite backup。">
          <div className="sync-form-grid">
            <label className="sync-field">
              <span>Profile</span>
              <select value={selectedProfileKey} onChange={(event) => setSelectedProfileKey(event.target.value)}>
                {profiles.map((profile) => (
                  <option key={profile.profile_key} value={profile.profile_key}>
                    {profile.profile_key}
                  </option>
                ))}
              </select>
            </label>

            <label className="sync-field">
              <span>数据集</span>
              <select value={selectedDatasetKey} onChange={(event) => setSelectedDatasetKey(event.target.value)}>
                {(selectedProfile?.datasets ?? []).map((dataset) => (
                  <option key={dataset.dataset_key} value={dataset.dataset_key}>
                    {dataset.dataset_key}
                  </option>
                ))}
              </select>
            </label>

            <label className="sync-field">
              <span>Target Date</span>
              <input
                disabled={!shouldUseTargetDate(selectedProfileKey)}
                type="date"
                value={targetDate}
                onChange={(event) => setTargetDate(event.target.value)}
              />
            </label>

            <label className="sync-field">
              <span>Start Date</span>
              <input
                disabled={!shouldUseDateRange(selectedProfileKey)}
                type="date"
                value={startDate}
                onChange={(event) => setStartDate(event.target.value)}
              />
            </label>

            <label className="sync-field">
              <span>End Date</span>
              <input
                disabled={!shouldUseDateRange(selectedProfileKey)}
                type="date"
                value={endDate}
                onChange={(event) => setEndDate(event.target.value)}
              />
            </label>
          </div>

          <div className="sync-action-row">
            <button className="sync-button sync-button-muted" onClick={reloadStatus} type="button">
              刷新状态
            </button>
            <button className="sync-button" disabled={!selectedProfile || planLoading} onClick={handleCreatePlan} type="button">
              {planLoading ? "生成中..." : "生成计划"}
            </button>
            <button className="sync-button sync-button-primary" disabled={!canStartRun} onClick={handleStartRun} type="button">
              {runLoading ? "启动中..." : "启动同步任务"}
            </button>
          </div>

          {!canRunSelectedScope ? (
            <div className="alert warning">
              <div>
                当前选择的范围尚未接入 M6 runner。可以生成计划做预览，但不能启动写入任务。
              </div>
            </div>
          ) : null}
        </Panel>
      </section>

      <section className="sync-center-grid sync-center-grid-plan">
        <Panel title="计划预览" description="确认会写哪些数据集、目标路径、请求数和 blockers。">
          {plan ? (
            <>
              <section className="sync-plan-stats">
                <SyncMiniStat label="Datasets" value={String(plan.summary.dataset_count ?? plan.dataset_plans.length)} />
                <SyncMiniStat label="Requests" value={requestCount.toLocaleString("zh-CN")} />
                <SyncMiniStat label="Backup Paths" value={String(plan.backup_plan.backup_paths.length)} />
                <SyncMiniStat label="Missing Paths" value={String(plan.backup_plan.path_missing_before_write.length)} />
              </section>
              <PlanTable rows={plan.dataset_plans} />
              <IssueList title="Blockers" items={plan.blockers} tone="error" />
              <IssueList title="Warnings" items={plan.warnings} tone="warning" />
            </>
          ) : (
            <EmptyState title="尚未生成计划" description="先选择 Profile 与数据集，再点击“生成计划”。" />
          )}
        </Panel>

        <Panel title="Kopia 备份范围" description="启动写入前，后端会按计划范围创建 prewrite snapshot。">
          {plan ? (
            <div className="sync-backup-stack">
              <BackupList title="将备份的路径" paths={plan.backup_plan.backup_paths} empty="当前目标路径尚不存在，写入前会记录 missing path。" />
              <BackupList title="写入前不存在" paths={plan.backup_plan.path_missing_before_write} empty="没有 missing path。" />
              <div className="sync-kv-grid">
                <div><span>Provider</span><strong>{plan.backup_plan.provider}</strong></div>
                <div><span>Pin Policy</span><strong>{plan.backup_plan.pin_policy}</strong></div>
                <div><span>Token Expires</span><strong>{formatDateTime(plan.plan_token_expires_at)}</strong></div>
              </div>
            </div>
          ) : (
            <EmptyState title="等待计划" description="备份范围来自后端 plan，不在前端拼接。" />
          )}
        </Panel>
      </section>

      <section className="sync-center-grid sync-center-grid-run">
        <SectionCard
          title="运行中 / 最近任务"
          description="任务详情和事件流均来自 Sync Center 状态文件。"
          side={(
            <button className="sync-inline-button" disabled={!activeRunId} onClick={reloadArtifacts} type="button">
              刷新事件
            </button>
          )}
        >
          {artifactLoading ? <LoadingBlock title="正在读取任务详情" description="加载 run detail 与 events。" /> : null}
          {!artifactLoading && !detail ? (
            <EmptyState title="暂无任务详情" description="启动同步任务后，这里会展示 run 结果与事件流。" />
          ) : null}
          {detail ? <RunDetailBlock detail={detail} /> : null}
        </SectionCard>

        <SectionCard title="事件流" description="事件按后端 seq 顺序展示，页面不自行推导进度。">
          <EventTable rows={events} />
        </SectionCard>
      </section>
    </div>
  );
}

function RecommendationTable({ onApply, rows }: { onApply: (item: SyncRecommendationItem) => void; rows: SyncRecommendationItem[] }) {
  const columns: DataTableColumn<SyncRecommendationItem>[] = [
    {
      key: "dataset",
      header: "数据集",
      render: (row) => (
        <div className="sync-cell-stack sync-cell-stack-tight">
          <strong>{row.dataset_key}</strong>
          <span>{row.display_name}</span>
        </div>
      ),
    },
    {
      key: "status",
      header: "状态",
      render: (row) => (
        <div className="sync-cell-stack sync-cell-stack-tight">
          <Badge tone={recommendationTone(row.status)}>{recommendationStatusLabel(row.status)}</Badge>
          <span>{row.source}</span>
        </div>
      ),
    },
    {
      key: "dates",
      header: "本地 / 应到",
      render: (row) => (
        <div className="sync-cell-stack sync-cell-stack-tight">
          <strong>{row.local_latest_trade_date ?? "—"} → {row.expected_latest_trade_date ?? "—"}</strong>
          <span>{row.reason}</span>
        </div>
      ),
    },
    {
      key: "lag",
      header: "延迟",
      render: (row) => (
        <div className="sync-cell-stack sync-cell-stack-tight">
          <strong>{row.lag_anchor_count.toLocaleString("zh-CN")} anchors</strong>
          <span>{row.lag_calendar_days.toLocaleString("zh-CN")} calendar days</span>
        </div>
      ),
    },
    {
      key: "window",
      header: "建议窗口",
      render: (row) => (
        <div className="sync-cell-stack sync-cell-stack-tight">
          <strong>{row.suggested_start_date ?? "—"} ~ {row.suggested_end_date ?? "—"}</strong>
          <span>{row.plan_hint ? "可带入手动补数计划" : "无可自动带入窗口"}</span>
        </div>
      ),
    },
    {
      key: "action",
      header: "操作",
      render: (row) => (
        <button className="sync-inline-button" disabled={!row.plan_hint} onClick={() => onApply(row)} type="button">
          带入计划参数
        </button>
      ),
    },
  ];
  return (
    <DataTableCard
      columns={columns}
      empty={<EmptyState title="暂无建议" description="后端没有返回可展示的同步建议。" />}
      getRowKey={(row) => row.dataset_key}
      label="Sync recommendation list"
      rowTone={(row) => (row.status === "lagging" ? "warning" : row.status === "blocked_missing_calendar" ? "error" : "default")}
      rows={rows}
    />
  );
}

function SyncLockSummary({ lock, loading, onRefresh }: { lock: SyncLock | null; loading: boolean; onRefresh: () => void }) {
  return (
    <div className="sync-header-side">
      <strong>{lockStatusLabel(lock?.status, loading)}</strong>
      <span>{lock?.run_id ?? lockHint(lock)}</span>
      <button className="sync-inline-button" onClick={onRefresh} type="button">
        刷新
      </button>
    </div>
  );
}

function PlanTable({ rows }: { rows: SyncPlanDatasetPlan[] }) {
  const columns: DataTableColumn<SyncPlanDatasetPlan>[] = [
    {
      key: "dataset",
      header: "数据集",
      render: (row) => (
        <div className="sync-cell-stack">
          <strong>{row.dataset_key}</strong>
          <span>{row.display_name}</span>
        </div>
      ),
    },
    {
      key: "source",
      header: "来源 / 策略",
      render: (row) => (
        <div className="sync-cell-stack">
          <strong>{row.source}</strong>
          <span>{row.request_strategy_key}</span>
        </div>
      ),
    },
    {
      key: "paths",
      header: "写入路径",
      render: (row) => (
        <div className="sync-path-list">
          {row.write_paths.map((path) => (
            <code key={path}>{path}</code>
          ))}
        </div>
      ),
    },
    {
      key: "counts",
      header: "请求 / 分区",
      render: (row) => (
        <div className="sync-cell-stack">
          <strong>{row.request_count.toLocaleString("zh-CN")} requests</strong>
          <span>{row.partition_count.toLocaleString("zh-CN")} partitions</span>
        </div>
      ),
    },
    {
      key: "status",
      header: "状态",
      render: (row) => <Badge tone={row.status === "will_run" ? "success" : "muted"}>{row.status}</Badge>,
    },
  ];
  return (
    <DataTableCard
      columns={columns}
      empty={<EmptyState title="计划为空" description="后端没有返回 dataset plan。" />}
      getRowKey={(row) => row.dataset_key}
      label="Sync plan dataset list"
      rows={rows}
    />
  );
}

function EventTable({ rows }: { rows: SyncRunEvent[] }) {
  const columns: DataTableColumn<SyncRunEvent>[] = [
    {
      key: "time",
      header: "时间",
      render: (row) => (
        <div className="sync-cell-stack sync-cell-stack-tight">
          <strong>{formatDateTime(row.created_at)}</strong>
          <span>seq={row.seq}</span>
        </div>
      ),
    },
    {
      key: "event",
      header: "事件",
      render: (row) => (
        <div className="sync-cell-stack sync-cell-stack-tight">
          <strong>{row.event_type}</strong>
          <span>{row.message}</span>
        </div>
      ),
    },
    {
      key: "dataset",
      header: "数据集",
      render: (row) => row.dataset_key ? <Badge tone="brand">{row.dataset_key}</Badge> : <Badge tone="muted">run</Badge>,
    },
    {
      key: "metrics",
      header: "指标",
      render: (row) => <span className="sync-json-line">{compactJson(row.metrics)}</span>,
    },
  ];
  return (
    <DataTableCard
      columns={columns}
      empty={<EmptyState title="暂无事件" description="启动任务后，事件会按后端 seq 展示。" />}
      getRowKey={(row) => row.event_id}
      label="Sync run events"
      rowTone={(row) => (row.level === "error" ? "error" : row.level === "warning" ? "warning" : "default")}
      rows={rows}
    />
  );
}

function RunDetailBlock({ detail }: { detail: { status: string; run_id: string; started_at: string; finished_at: string | null; progress: Record<string, unknown>; dataset_results: Record<string, unknown>[]; backup: Record<string, unknown> | null; errors: SyncPlanIssue[] } }) {
  return (
    <div className="sync-run-detail">
      <div className="sync-run-head">
        <div>
          <strong>{detail.run_id}</strong>
          <span>{formatDateTime(detail.started_at)} ~ {formatDateTime(detail.finished_at)}</span>
        </div>
        <Badge tone={runTone(detail.status)}>{detail.status}</Badge>
      </div>
      <div className="sync-kv-grid">
        <div><span>Progress</span><strong>{String(detail.progress.summary ?? "—")}</strong></div>
        <div><span>Backup Snapshots</span><strong>{snapshotCount(detail.backup)}</strong></div>
        <div><span>Dataset Results</span><strong>{String(detail.dataset_results.length)}</strong></div>
      </div>
      {detail.dataset_results.length ? (
        <div className="sync-result-list">
          {detail.dataset_results.map((item, index) => (
            <div className="sync-result-row" key={`${String(item.dataset_key ?? "dataset")}-${index}`}>
              <strong>{String(item.dataset_key ?? "dataset")}</strong>
              <span>fetched={String(item.fetched_rows ?? "—")} written={String(item.written_rows ?? "—")} manifest={String(item.manifest_written_rows ?? "—")}</span>
            </div>
          ))}
        </div>
      ) : null}
      <IssueList title="Errors" items={detail.errors} tone="error" />
    </div>
  );
}

function BackupList({ empty, paths, title }: { empty: string; paths: string[]; title: string }) {
  return (
    <div className="sync-backup-list">
      <strong>{title}</strong>
      {paths.length ? paths.slice(0, 8).map((path) => <code key={path}>{path}</code>) : <span>{empty}</span>}
      {paths.length > 8 ? <span>另有 {paths.length - 8} 条路径</span> : null}
    </div>
  );
}

function IssueList({ items, title, tone }: { items: SyncPlanIssue[]; title: string; tone: BadgeTone }) {
  if (!items.length) {
    return null;
  }
  return (
    <div className="sync-issue-list">
      <strong>{title}</strong>
      {items.map((item, index) => (
        <div className="sync-issue-row" key={`${title}-${index}`}>
          <Badge tone={tone}>{item.code ?? title}</Badge>
          <span>{item.message ?? compactJson(item)}</span>
        </div>
      ))}
    </div>
  );
}

function SyncMiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="sync-mini-stat">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function lockStatusLabel(status: string | undefined, loading: boolean): string {
  if (loading) {
    return "Loading";
  }
  if (!status || status === "idle") {
    return "Idle";
  }
  return status;
}

function lockHint(lock: SyncLock | null): string {
  if (!lock || lock.status === "idle") {
    return "当前没有写入任务持锁";
  }
  if (lock.status === "stale") {
    return `stale after ${lock.stale_after_seconds}s`;
  }
  return lock.profile_key ?? "任务运行中";
}

function lockTone(lock: SyncLock | null): "default" | "success" | "warning" | "error" | "info" {
  if (!lock || lock.status === "idle") {
    return "success";
  }
  if (lock.status === "stale") {
    return "warning";
  }
  if (lock.status === "running") {
    return "info";
  }
  return "default";
}

function profileTone(profile: SyncProfileSummary): BadgeTone {
  if (profile.profile_status === "enabled") {
    return "success";
  }
  if (profile.profile_status === "planned") {
    return "warning";
  }
  return "muted";
}

function runTone(status: string): BadgeTone {
  if (status === "success") {
    return "success";
  }
  if (status.includes("failed")) {
    return "error";
  }
  if (status === "running" || status === "planned" || status === "lock_acquired") {
    return "processing";
  }
  return "muted";
}

function recommendationTone(status: string): BadgeTone {
  if (status === "up_to_date") {
    return "success";
  }
  if (status === "lagging" || status === "empty") {
    return "warning";
  }
  if (status === "blocked_missing_calendar") {
    return "error";
  }
  return "muted";
}

function recommendationStatusLabel(status: string): string {
  const mapping: Record<string, string> = {
    blocked_missing_calendar: "缺交易日历",
    empty: "未落盘",
    lagging: "落后",
    not_applicable: "不适用",
    up_to_date: "已到最新",
  };
  return mapping[status] ?? status;
}

function isRunnableProfile(profile: SyncProfileSummary): boolean {
  return profile.profile_status === "enabled" && RUNNABLE_PROFILE_KEYS.has(profile.profile_key);
}

function shouldUseTargetDate(profileKey: string): boolean {
  return profileKey === "prod_db_daily";
}

function shouldUseDateRange(profileKey: string): boolean {
  return profileKey === "prod_db_manual_backfill";
}

function snapshotCount(backup: Record<string, unknown> | null): string {
  const value = backup?.snapshot_ids;
  return Array.isArray(value) ? String(value.length) : "—";
}

function compactJson(value: unknown): string {
  if (!value || (typeof value === "object" && Object.keys(value).length === 0)) {
    return "—";
  }
  return JSON.stringify(value);
}

function todayInputValue(): string {
  return new Date().toISOString().slice(0, 10);
}
