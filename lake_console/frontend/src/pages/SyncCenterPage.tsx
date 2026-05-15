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
import type {
  SyncLock,
  SyncPlanDatasetPlan,
  SyncPlanIssue,
  SyncPlanResponse,
  SyncProfileSummary,
  SyncRecommendationItem,
  SyncRecommendationPlanHint,
  SyncRunEvent,
} from "../types";
import { formatDateTime } from "../utils/format";

const RUNNABLE_PROFILE_KEYS = new Set([
  "prod_db_daily",
  "prod_db_snapshot_refresh",
  "prod_db_manual_backfill",
  "lake_reference_refresh",
]);
const RECOMMENDATION_SOURCE_PROFILE_BY_SELECTED_PROFILE: Record<string, string> = {
  prod_db_daily: "prod_db_daily",
  prod_db_manual_backfill: "prod_db_daily",
};

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
  const [datasetKeysOverride, setDatasetKeysOverride] = useState<string[] | null>(null);
  const [recommendationsExpanded, setRecommendationsExpanded] = useState<boolean>(false);

  const selectedProfile = profiles.find((profile) => profile.profile_key === selectedProfileKey) ?? null;
  const recommendationSourceProfileKey = RECOMMENDATION_SOURCE_PROFILE_BY_SELECTED_PROFILE[selectedProfileKey] ?? null;
  const canLoadRecommendations = Boolean(recommendationSourceProfileKey);
  const {
    error: recommendationError,
    loading: recommendationLoading,
    recommendations,
    reloadRecommendations,
  } = useSyncRecommendations(recommendationSourceProfileKey);
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
    if (!selectedDatasetKey) {
      return;
    }
    const keys = selectedProfile.datasets.map((item) => item.dataset_key);
    if (keys.includes(selectedDatasetKey)) {
      return;
    }
    setSelectedDatasetKey("");
  }, [selectedDatasetKey, selectedProfile]);

  useEffect(() => {
    setPlan(null);
    setPlanError(null);
    setRunError(null);
    setRecommendationsExpanded(false);
  }, [datasetKeysOverride, endDate, selectedDatasetKey, selectedProfileKey, startDate, targetDate]);

  const canRunSelectedScope = Boolean(selectedProfile && isRunnableProfile(selectedProfile));
  const canStartRun = Boolean(plan && !plan.blockers.length && canRunSelectedScope && lock?.status === "idle" && !runLoading);
  const requestCount = plan?.dataset_plans.reduce((total, item) => total + item.request_count, 0) ?? 0;
  const recommendationItems = recommendations?.items ?? [];
  const laggingRecommendationCount = recommendationItems.filter((item) => item.status === "lagging" || item.status === "empty").length;
  const blockedRecommendationCount = recommendationItems.filter((item) => item.status === "blocked_missing_calendar").length;
  const maxLagDays = recommendationItems.reduce((max, item) => Math.max(max, item.lag_calendar_days || 0), 0);

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
        datasetKeys: datasetKeysOverride ?? (selectedDatasetKey ? [selectedDatasetKey] : []),
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
    applyPlanHint(item.plan_hint);
  }

  function applyPlanHint(planHint: SyncRecommendationPlanHint) {
    setSelectedProfileKey(planHint.profile_key);
    setSelectedDatasetKey(planHint.dataset_keys.length === 1 ? planHint.dataset_keys[0] : "");
    setDatasetKeysOverride(planHint.dataset_keys.length > 1 ? planHint.dataset_keys : null);
    setTargetDate(planHint.target_date ?? todayInputValue());
    setStartDate(planHint.start_date ?? "");
    setEndDate(planHint.end_date ?? "");
    setPlan(null);
    setPlanError(null);
    setRunError(null);
  }

  function handleApplyDailyProfileRecommendation() {
    setSelectedProfileKey("prod_db_daily");
    setSelectedDatasetKey("");
    setDatasetKeysOverride(null);
    setTargetDate(recommendations?.expected_reference_date ?? todayInputValue());
    setStartDate("");
    setEndDate("");
    setPlan(null);
    setPlanError(null);
    setRunError(null);
  }

  function handleApplyLaggingBackfillRecommendation() {
    if (!recommendations?.aggregate_plan_hint) {
      return;
    }
    applyPlanHint(recommendations.aggregate_plan_hint);
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
        title="主操作台 / Run Console"
        description="先选择同步范围，生成计划确认写入与备份影响面，再启动执行。"
      >
        <section className="sync-command-recommendation" aria-label="建议同步窗口">
          <div className="sync-command-section-head">
            <div>
              <h3>建议同步窗口</h3>
              <p>只读扫描本地 Lake 文件事实和本地交易日历，给出日期型数据集的建议补数范围；确认后可带入主操作台。</p>
            </div>
          </div>
          <div className="sync-recommendation-toolbar">
            <div className="sync-cell-stack sync-cell-stack-tight">
              <strong>{selectedProfile ? `跟随主操作台：${selectedProfile.profile_key}` : "等待选择 Profile"}</strong>
              <span>
                {selectedProfileKey === "prod_db_manual_backfill"
                  ? "当前手动补数会复用 prod_db_daily 的缺口计算结果，一键填入 start/end 与落后数据集。"
                  : canLoadRecommendations
                  ? "当前 Profile 支持自动计算同步日期，可一键把建议参数带回主操作台。"
                  : "当前 Profile 不使用自动日期建议；请在主操作台直接生成计划。"}
              </span>
            </div>
            {canLoadRecommendations ? (
              <div className="sync-recommendation-actions sync-recommendation-actions-primary">
                <button className="sync-inline-button" onClick={reloadRecommendations} type="button">
                  刷新建议
                </button>
                <button
                  className="sync-inline-button"
                  disabled={!recommendations?.expected_reference_date}
                  onClick={handleApplyDailyProfileRecommendation}
                  type="button"
                >
                  带入每日单日全量
                </button>
                <button
                  className="sync-inline-button sync-button-primary"
                  disabled={!recommendations?.aggregate_plan_hint}
                  onClick={handleApplyLaggingBackfillRecommendation}
                  type="button"
                >
                  带入全部落后补数
                </button>
              </div>
            ) : null}
          </div>
          {canLoadRecommendations ? (
            <div className="sync-recommendation-summary">
              <SyncMiniStat label="落后数据集" value={String(laggingRecommendationCount)} />
              <SyncMiniStat label="最长滞后" value={maxLagDays ? `${maxLagDays}d` : "0d"} />
              <SyncMiniStat label="阻断项" value={String(blockedRecommendationCount)} />
              <SyncMiniStat label="参考日期" value={recommendations?.expected_reference_date ?? "—"} />
            </div>
          ) : null}
          {!canLoadRecommendations ? (
            <EmptyState
              title="当前 Profile 不需要建议同步窗口"
              description="建议窗口目前只服务 prod_db_daily 的日期缺口推导，并可带入 prod_db_manual_backfill 执行补数。snapshot/reference 类 Profile 的日期或刷新语义不同，请在下方主操作台直接生成计划。"
            />
          ) : null}
          {canLoadRecommendations ? <div className="sync-recommendation-head">
            <div className="sync-cell-stack sync-cell-stack-tight">
              <strong>Profile: {recommendations?.profile_key ?? "prod_db_daily"}</strong>
              <span>cutoff {recommendations?.cutoff_time ?? "20:00"}，明细只用于带入参数，不会自动启动同步。</span>
            </div>
            <div className="sync-recommendation-actions">
              <button className="sync-inline-button" onClick={() => setRecommendationsExpanded((value) => !value)} type="button">
                {recommendationsExpanded ? "收起明细" : "展开明细"}
              </button>
            </div>
          </div> : null}
          {recommendationError ? <ErrorStateBlock title="建议同步窗口加载失败" description={recommendationError} /> : null}
          {recommendationLoading ? <LoadingBlock title="正在生成建议" description="读取本地分区与交易日历。" /> : null}
          {!recommendationLoading && recommendations && recommendationsExpanded && canLoadRecommendations ? (
            <div className="sync-recommendation-table-wrap">
              <RecommendationTable rows={recommendations.items} onApply={handleApplyRecommendation} />
            </div>
          ) : null}
        </section>

        <div className="sync-command-divider" />

        <div className="sync-command-console">
          <div className="sync-command-main">
            <div className="sync-form-grid sync-form-grid-console">
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
                <span>数据集范围</span>
                <select
                  value={selectedDatasetKey}
                  onChange={(event) => {
                    setDatasetKeysOverride(null);
                    setSelectedDatasetKey(event.target.value);
                  }}
                >
                  <option value="">全部数据集</option>
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

            {datasetKeysOverride ? (
              <div className="alert warning">
                <div>
                  已按建议选择 {datasetKeysOverride.length} 个落后数据集。生成计划时只包含这组数据集，不等同于 profile 全部数据集。
                </div>
              </div>
            ) : null}

            <div className="sync-action-row sync-action-row-console">
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
          </div>

          <aside className="sync-command-side">
            <div className="sync-command-card">
              <span>当前 Profile</span>
              <strong>{selectedProfile?.display_name ?? "未选择"}</strong>
              <p>{selectedProfile?.description ?? "等待后端返回 Profile 列表。"}</p>
              <div className="sync-profile-meta">
                {selectedProfile ? <Badge tone={profileTone(selectedProfile)}>{selectedProfile.profile_status}</Badge> : null}
                {selectedProfile ? (
                  <Badge tone={isRunnableProfile(selectedProfile) ? "success" : "muted"}>
                    {isRunnableProfile(selectedProfile) ? "M6 可执行" : "专项待接入"}
                  </Badge>
                ) : null}
                {selectedProfile ? (
                  <Badge tone={selectedProfile.requires_kopia_backup ? "warning" : "muted"}>Kopia prewrite</Badge>
                ) : null}
              </div>
            </div>

            <div className="sync-command-card sync-command-card-plan">
              <span>当前计划</span>
              <strong>{plan ? `${plan.summary.dataset_count ?? plan.dataset_plans.length} datasets` : "尚未生成"}</strong>
              <p>
                {plan
                  ? `requests=${requestCount.toLocaleString("zh-CN")} · backup=${plan.backup_plan.backup_paths.length} · missing=${plan.backup_plan.path_missing_before_write.length}`
                  : "生成计划后这里会显示请求数、备份路径和 missing path 摘要。"}
              </p>
              {plan?.blockers.length ? <Badge tone="error">Blockers {plan.blockers.length}</Badge> : null}
              {plan && !plan.blockers.length ? <Badge tone="success">Ready to run</Badge> : null}
            </div>
          </aside>
        </div>
      </Panel>

      <section className="sync-center-grid sync-center-grid-plan">
        <Panel title="计划预览" description="确认会写哪些数据集、目标路径、请求数和 blockers。">
          {plan ? (
            <>
              <section className="sync-plan-stats">
                <SyncMiniStat label="Datasets" value={String(plan.summary.dataset_count ?? plan.dataset_plans.length)} />
                <SyncMiniStat label="Requests" value={requestCount.toLocaleString("zh-CN")} />
                <SyncMiniStat label="Snapshot Paths" value={String((plan.backup_plan.snapshot_paths ?? plan.backup_plan.backup_paths).length)} />
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

        <Panel title="Kopia 备份范围" description="启动写入前，后端会按聚合路径创建 prewrite snapshot；明细路径只用于恢复判断，不会逐条创建 snapshot。">
          {plan ? (
            <div className="sync-backup-stack">
              <BackupList title="本次将创建 snapshot 的聚合路径" paths={plan.backup_plan.snapshot_paths ?? plan.backup_plan.backup_paths} empty="当前没有需要创建 snapshot 的已存在路径。" />
              <BackupList title="本次会写且写前已存在的明细路径" paths={plan.backup_plan.backup_paths} empty="当前目标路径尚不存在，写入前会记录 missing path。" />
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
