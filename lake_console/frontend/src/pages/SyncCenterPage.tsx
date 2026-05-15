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
import { abortSyncRun, continueSyncRun, createSyncPlan, startSyncRun } from "../services/lakeApi";
import type {
  SyncLock,
  SyncPlanDatasetPlan,
  SyncPlanIssue,
  SyncPlanResponse,
  SyncPipelineStage,
  SyncProfileSummary,
  SyncRecommendationItem,
  SyncRecommendationPlanHint,
  SyncRunDetail,
  SyncRunEvent,
} from "../types";
import { formatDateTime } from "../utils/format";

const RUNNABLE_PROFILE_KEYS = new Set([
  "prod_db_daily",
  "prod_db_snapshot_refresh",
  "prod_db_manual_backfill",
  "lake_reference_refresh",
]);
const STK_MINS_PROFILE_KEY = "stk_mins_sync";
const STK_MINS_FREQ_OPTIONS = [1, 5, 15, 30, 60];
const RECOMMENDATION_SOURCE_PROFILE_BY_SELECTED_PROFILE: Record<string, string> = {
  prod_db_daily: "prod_db_daily",
  prod_db_manual_backfill: "prod_db_daily",
};
const PROFILE_PRESENTATION: Record<string, { description: string; domain: string; mode: string; label: string }> = {
  indicator_compute: {
    description: "技术指标计算入口，当前不在本页启动。",
    domain: "技术指标计算",
    label: "技术指标计算 · 计划中",
    mode: "计划中",
  },
  index_mins_sync: {
    description: "指数历史分钟线独立链路，当前不在本页启动。",
    domain: "指数分钟线专项",
    label: "指数分钟线专项 · 计划中",
    mode: "计划中",
  },
  lake_reference_refresh: {
    description: "刷新本地股票池、交易日历、指数清单等参考数据。",
    domain: "本地参考数据",
    label: "本地参考数据 · 参考数据刷新",
    mode: "参考数据刷新",
  },
  prod_db_daily: {
    description: "按交易日或周/月锚点维护日期分区数据。",
    domain: "日期驱动数据集",
    label: "日期驱动数据集 · 日常增量刷新",
    mode: "日常增量刷新",
  },
  prod_db_manual_backfill: {
    description: "按指定日期区间补齐日期驱动数据集。",
    domain: "日期驱动数据集",
    label: "日期驱动数据集 · 手动区间补数",
    mode: "手动区间补数",
  },
  prod_db_snapshot_refresh: {
    description: "刷新基础资料和当前快照类数据集。",
    domain: "快照数据集",
    label: "快照数据集 · 快照刷新",
    mode: "快照刷新",
  },
  stk_mins_sync: {
    description: "股票历史分钟线阶段化流水线，当前执行到 clean_next 确认点。",
    domain: "股票分钟线专项",
    label: "股票分钟线专项 · 分阶段同步",
    mode: "分阶段同步",
  },
};

export function SyncCenterPage() {
  const { currentRun, error, loading, lock, profiles, reloadStatus } = useSyncCenterStatus();
  const [selectedProfileKey, setSelectedProfileKey] = useState<string>("");
  const [selectedDatasetKey, setSelectedDatasetKey] = useState<string>("");
  const [targetDate, setTargetDate] = useState<string>(todayInputValue());
  const [startDate, setStartDate] = useState<string>("");
  const [endDate, setEndDate] = useState<string>("");
  const [selectedFreqs, setSelectedFreqs] = useState<number[]>(STK_MINS_FREQ_OPTIONS);
  const [plan, setPlan] = useState<SyncPlanResponse | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);
  const [planLoading, setPlanLoading] = useState<boolean>(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [runLoading, setRunLoading] = useState<boolean>(false);
  const [runActionLoading, setRunActionLoading] = useState<boolean>(false);
  const [selectedRunId, setSelectedRunId] = useState<string>("");
  const [datasetKeysOverride, setDatasetKeysOverride] = useState<string[] | null>(null);
  const [recommendationsExpanded, setRecommendationsExpanded] = useState<boolean>(false);

  const selectedProfile = profiles.find((profile) => profile.profile_key === selectedProfileKey) ?? null;
  const isStkMinsProfile = selectedProfileKey === STK_MINS_PROFILE_KEY;
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
  }, [datasetKeysOverride, endDate, selectedDatasetKey, selectedFreqs, selectedProfileKey, startDate, targetDate]);

  const canRunSelectedScope = Boolean(selectedProfile && isRunnableProfile(selectedProfile));
  const canCreatePlan = Boolean(
    selectedProfile &&
    !planLoading &&
    (!isStkMinsProfile || (startDate && endDate && selectedFreqs.length)),
  );
  const canStartRun = Boolean(plan && !plan.blockers.length && canRunSelectedScope && lock?.status === "idle" && !runLoading);
  const canCreateStkMinsStateRun = Boolean(
    plan &&
    isStkMinsProfile &&
    !plan.blockers.length &&
    lock?.status === "idle" &&
    !runLoading,
  );
  const canStartSelectedPlan = canStartRun || canCreateStkMinsStateRun;
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
        freqs: isStkMinsProfile ? selectedFreqs : null,
        scope: isStkMinsProfile ? "all_market" : null,
        mode: isStkMinsProfile ? "manual_gate" : null,
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
    if (!plan || !canStartSelectedPlan) {
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

  async function handleContinueRun(runId: string) {
    setRunActionLoading(true);
    setRunError(null);
    try {
      await continueSyncRun(runId);
      reloadStatus();
      reloadArtifacts();
    } catch (caught) {
      setRunError(caught instanceof Error ? caught.message : "未知错误");
    } finally {
      setRunActionLoading(false);
    }
  }

  async function handleAbortRun(runId: string) {
    setRunActionLoading(true);
    setRunError(null);
    try {
      await abortSyncRun(runId, "运营手动停止后续写入");
      reloadStatus();
      reloadArtifacts();
    } catch (caught) {
      setRunError(caught instanceof Error ? caught.message : "未知错误");
    } finally {
      setRunActionLoading(false);
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

  function handleToggleStkMinsFreq(freq: number) {
    setSelectedFreqs((current) => {
      if (current.includes(freq)) {
        return current.filter((item) => item !== freq);
      }
      return [...current, freq].sort((left, right) => left - right);
    });
  }

  return (
    <div className="sync-center-layout">
      <PageHeader
        eyebrow="本地数据湖 / 写入任务 / 远程只读同步"
        title="同步中心"
        description="从远程生产库或本地参考源刷新本地 Parquet Lake。页面只暴露同步域、操作模式、白名单数据集和日期参数，不提供 SQL 能力。"
        right={<SyncLockSummary lock={lock} loading={loading} onRefresh={reloadStatus} />}
        variant="accent"
      />

      {error ? <ErrorStateBlock title="同步中心状态加载失败" description={error} /> : null}
      {planError ? <ErrorStateBlock title="计划生成失败" description={planError} /> : null}
      {runError ? <ErrorStateBlock title="任务启动失败" description={runError} /> : null}
      {artifactError ? <ErrorStateBlock title="任务详情加载失败" description={artifactError} /> : null}

      <section className="metric-grid sync-center-metrics">
        <Metric label="任务锁" value={lockStatusLabel(lock?.status, loading)} hint={lockHint(lock)} variant={lockTone(lock)} />
        <Metric label="可执行范围" value="4 类" hint="已开放日期驱动、快照、本地参考和手动补数" variant="info" />
        <Metric label="默认回看" value="1 天" hint="日期驱动数据集默认看最近 1 日" variant="subtle" />
        <Metric label="远程数据库" value="只读" hint="页面不暴露 SQL、表名或字段条件" variant="success" />
      </section>

      <Panel
        title="主操作台"
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
              <strong>{selectedProfile ? `跟随主操作台：${profileLabel(selectedProfile)}` : "等待选择同步配置"}</strong>
              <span>
                {selectedProfileKey === "prod_db_manual_backfill"
                  ? "当前为“手动区间补数”，会复用“日期驱动数据集”的缺口计算结果，一键填入起止日期与落后数据集。"
                  : canLoadRecommendations
                  ? "当前同步范围支持自动计算同步日期，可一键把建议参数带回主操作台。"
                  : "当前同步范围不使用自动日期建议；请在主操作台直接生成计划。"}
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
                  带入建议日期刷新
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
              title="当前同步范围不需要建议同步窗口"
              description="建议窗口目前只服务“日期驱动数据集”的日期缺口推导，并可带入“手动区间补数”执行补数。快照数据集和本地参考数据的刷新语义不同，请在下方主操作台直接生成计划。"
            />
          ) : null}
          {canLoadRecommendations ? <div className="sync-recommendation-head">
            <div className="sync-cell-stack sync-cell-stack-tight">
              <strong>建议来源：{profileLabelByKey(recommendations?.profile_key ?? recommendationSourceProfileKey)}</strong>
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
                <span>同步范围 / 操作模式</span>
                <select value={selectedProfileKey} onChange={(event) => setSelectedProfileKey(event.target.value)}>
                  {profiles.map((profile) => (
                    <option key={profile.profile_key} value={profile.profile_key}>
                      {profileLabel(profile)}
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
                <span>目标日期</span>
                <input
                  disabled={!shouldUseTargetDate(selectedProfileKey)}
                  type="date"
                  value={targetDate}
                  onChange={(event) => setTargetDate(event.target.value)}
                />
              </label>

              <label className="sync-field">
                <span>开始日期</span>
                <input
                  disabled={!shouldUseDateRange(selectedProfileKey)}
                  type="date"
                  value={startDate}
                  onChange={(event) => setStartDate(event.target.value)}
                />
              </label>

              <label className="sync-field">
                <span>结束日期</span>
                <input
                  disabled={!shouldUseDateRange(selectedProfileKey)}
                  type="date"
                  value={endDate}
                  onChange={(event) => setEndDate(event.target.value)}
                />
              </label>
            </div>

            {isStkMinsProfile ? (
              <div className="sync-stk-mins-controls">
                <div className="sync-cell-stack sync-cell-stack-tight">
                  <strong>股票分钟线专项参数</strong>
                  <span>scope=all_market，mode=manual_gate；本阶段执行到 clean_next_review 后等待人工确认。</span>
                </div>
                <div className="sync-frequency-toggle-group" aria-label="股票分钟线频率">
                  {STK_MINS_FREQ_OPTIONS.map((freq) => (
                    <label className="sync-frequency-toggle" key={freq}>
                      <input
                        checked={selectedFreqs.includes(freq)}
                        onChange={() => handleToggleStkMinsFreq(freq)}
                        type="checkbox"
                      />
                      <span>{freq}min</span>
                    </label>
                  ))}
                </div>
              </div>
            ) : null}

            {datasetKeysOverride ? (
              <div className="alert warning">
                <div>
                  已按建议选择 {datasetKeysOverride.length} 个落后数据集。生成计划时只包含这组数据集，不等同于当前同步配置下的全部数据集。
                </div>
              </div>
            ) : null}

            <div className="sync-action-row sync-action-row-console">
              <button className="sync-button" disabled={!canCreatePlan} onClick={handleCreatePlan} type="button">
                {planLoading ? "生成中..." : "生成计划"}
              </button>
              <button className="sync-button sync-button-primary" disabled={!canStartSelectedPlan} onClick={handleStartRun} type="button">
                {runLoading ? "处理中..." : isStkMinsProfile ? "执行到 clean_next" : "启动同步任务"}
              </button>
            </div>

            {!canRunSelectedScope ? (
              <div className="alert warning">
                <div>
                  {isStkMinsProfile
                    ? "当前会创建 Kopia 写前备份，执行 raw + clean_next/gate，然后停在 clean_next_review；不会生成 90/120 或 research by month。"
                    : "当前选择的同步配置尚未接入执行器。可以生成只读计划做预览，但不能启动写入任务。"}
                </div>
              </div>
            ) : null}
            {isStkMinsProfile && (!startDate || !endDate || !selectedFreqs.length) ? (
              <div className="alert warning">
                <div>股票分钟线专项必须填写开始日期、结束日期，并至少选择一个 raw 频率后才能生成计划。</div>
              </div>
            ) : null}
          </div>

          <aside className="sync-command-side">
            <div className="sync-command-card">
              <span>当前同步配置</span>
              <strong>{selectedProfile ? profileLabel(selectedProfile) : "未选择"}</strong>
              <p>{selectedProfile ? profileDescription(selectedProfile) : "等待后端返回同步配置列表。"}</p>
              <div className="sync-profile-meta">
                {selectedProfile ? <Badge tone={profileTone(selectedProfile)}>{profileStatusLabel(selectedProfile.profile_status)}</Badge> : null}
                {selectedProfile ? (
                  <Badge tone={isRunnableProfile(selectedProfile) ? "success" : "muted"}>
                    {isRunnableProfile(selectedProfile) ? "可执行" : "计划中"}
                  </Badge>
                ) : null}
                {selectedProfile ? (
                  <Badge tone={selectedProfile.requires_kopia_backup ? "warning" : "muted"}>写入前备份</Badge>
                ) : null}
              </div>
            </div>

            <div className="sync-command-card sync-command-card-plan">
              <span>当前计划</span>
              <strong>{plan ? `${plan.summary.dataset_count ?? plan.dataset_plans.length} 个数据集` : "尚未生成"}</strong>
              <p>
                {plan
                  ? `requests=${requestCount.toLocaleString("zh-CN")} · backup=${plan.backup_plan.backup_paths.length} · missing=${plan.backup_plan.path_missing_before_write.length}`
                  : "生成计划后这里会显示请求数、备份路径和 missing path 摘要。"}
              </p>
              {plan?.blockers.length ? <Badge tone="error">Blockers {plan.blockers.length}</Badge> : null}
              {plan && !plan.blockers.length && canRunSelectedScope ? <Badge tone="success">可启动</Badge> : null}
              {plan && !plan.blockers.length && isStkMinsProfile ? <Badge tone="warning">可执行到 clean_next</Badge> : null}
              {plan && !plan.blockers.length && !canRunSelectedScope && !isStkMinsProfile ? <Badge tone="warning">只读计划</Badge> : null}
            </div>
          </aside>
        </div>
      </Panel>

      <section className="sync-center-grid sync-center-grid-plan">
        <Panel title="计划预览" description="确认会写哪些数据集、目标路径、请求数和 blockers。">
          {plan ? (
            <>
              <section className="sync-plan-stats">
                <SyncMiniStat label="数据集" value={String(plan.summary.dataset_count ?? plan.dataset_plans.length)} />
                <SyncMiniStat label="阶段" value={String(plan.summary.stage_count ?? plan.pipeline_stages.length)} />
                <SyncMiniStat label="请求数" value={requestCount.toLocaleString("zh-CN")} />
                <SyncMiniStat label="快照路径" value={String((plan.backup_plan.snapshot_paths ?? plan.backup_plan.backup_paths).length)} />
                <SyncMiniStat label="备份明细" value={String(plan.backup_plan.backup_paths.length)} />
                <SyncMiniStat label="写前缺失" value={String(plan.backup_plan.path_missing_before_write.length)} />
              </section>
              {plan.pipeline_stages.length ? <PipelineStagePreview plan={plan} /> : null}
              <PlanTable rows={plan.dataset_plans} />
              <IssueList title="阻断项" items={plan.blockers} tone="error" />
              <IssueList title="提醒项" items={plan.warnings} tone="warning" />
            </>
          ) : (
            <EmptyState title="尚未生成计划" description="先选择同步范围与数据集，再点击“生成计划”。" />
          )}
        </Panel>

        <Panel title="Kopia 备份范围" description="启动写入前，后端会按聚合路径创建写入前快照；明细路径只用于恢复判断，不会逐条创建快照。">
          {plan ? (
            <div className="sync-backup-stack">
              <BackupList title="本次将创建快照的聚合路径" paths={plan.backup_plan.snapshot_paths ?? plan.backup_plan.backup_paths} empty="当前没有需要创建快照的已存在路径。" />
              <BackupList title="本次会写且写前已存在的明细路径" paths={plan.backup_plan.backup_paths} empty="当前目标路径尚不存在，写入前会记录 missing path。" />
              <BackupList title="写入前不存在" paths={plan.backup_plan.path_missing_before_write} empty="没有 missing path。" />
              <div className="sync-kv-grid">
                <div><span>备份提供方</span><strong>{plan.backup_plan.provider}</strong></div>
                <div><span>固定策略</span><strong>{plan.backup_plan.pin_policy}</strong></div>
                <div><span>计划令牌过期时间</span><strong>{formatDateTime(plan.plan_token_expires_at)}</strong></div>
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
          description="任务详情和事件流均来自同步中心状态文件。"
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
          {detail ? (
            <RunDetailBlock
              detail={detail}
              onAbort={handleAbortRun}
              onContinue={handleContinueRun}
              runActionLoading={runActionLoading}
            />
          ) : null}
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

function PipelineStagePreview({ plan }: { plan: SyncPlanResponse }) {
  return (
    <PipelineStageBoard
      stages={plan.pipeline_stages}
      subtitle={
        plan.affected_trade_dates.length
          ? `${plan.affected_trade_dates[0]} ~ ${plan.affected_trade_dates[plan.affected_trade_dates.length - 1]} · ${plan.affected_months.join(", ") || "无月份"}`
          : "后端未返回受影响交易日"
      }
    />
  );
}

function PipelineStageBoard({ stages, subtitle }: { stages: SyncPipelineStage[]; subtitle: string }) {
  const firstStageKey = stages[0]?.stage_key ?? "";
  const [selectedStageKey, setSelectedStageKey] = useState<string>(firstStageKey);
  useEffect(() => {
    setSelectedStageKey(firstStageKey);
  }, [firstStageKey]);
  const selectedStage = stages.find((stage) => stage.stage_key === selectedStageKey) ?? stages[0] ?? null;
  const columns: DataTableColumn<SyncPipelineStage>[] = [
    {
      key: "order",
      header: "#",
      render: (row) => <strong>{row.stage_order}</strong>,
    },
    {
      key: "stage",
      header: "阶段",
      render: (row) => (
        <div className="sync-cell-stack sync-cell-stack-tight">
          <strong>{row.stage_title}</strong>
          <span>{row.stage_key}</span>
        </div>
      ),
    },
    {
      key: "status",
      header: "状态",
      render: (row) => <Badge tone={stageTone(row.stage_status)}>{row.stage_status_label}</Badge>,
    },
    {
      key: "summary",
      header: "结果摘要",
      render: (row) => (
        <div className="sync-cell-stack sync-cell-stack-tight">
          <strong>{row.display_summary}</strong>
          <span>{row.requires_confirmation ? row.confirmation_prompt ?? "需要人工确认" : stageMetricLine(row.metrics)}</span>
        </div>
      ),
    },
    {
      key: "action",
      header: "下一步",
      render: (row) => row.next_action ? <Badge tone="warning">{row.next_action.label}</Badge> : <Badge tone="muted">-</Badge>,
    },
  ];
  return (
    <section className="sync-pipeline-preview" aria-label="stk_mins pipeline stages">
      <div className="sync-pipeline-head">
        <div className="sync-cell-stack sync-cell-stack-tight">
          <strong>阶段化流水线</strong>
          <span>{subtitle}</span>
        </div>
        <div className="sync-pipeline-rail" aria-label="阶段状态轨">
          {stages.map((stage) => (
            <button
              className={`sync-pipeline-dot ${stage.stage_status}`}
              key={stage.stage_key}
              onClick={() => setSelectedStageKey(stage.stage_key)}
              title={`${stage.stage_title}：${stage.stage_status_label}`}
              type="button"
            >
              <span>{stage.stage_order}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="sync-pipeline-grid">
        <DataTableCard
          columns={columns}
          empty={<EmptyState title="暂无阶段" description="后端没有返回 pipeline_stages。" />}
          getRowKey={(row) => row.stage_key}
          label="stk_mins pipeline stage list"
          onRowClick={(row) => setSelectedStageKey(row.stage_key)}
          rowTone={(row) => stageRowTone(row.stage_status)}
          rows={stages}
        />
        {selectedStage ? <PipelineStageDetail stage={selectedStage} /> : null}
      </div>
    </section>
  );
}

function PipelineStageDetail({ stage }: { stage: SyncPipelineStage }) {
  const metricEntries = Object.entries(stage.metrics);
  return (
    <aside className="sync-pipeline-detail" aria-label="阶段详情">
      <div className="sync-run-head">
        <div>
          <strong>{stage.stage_title}</strong>
          <span>{stage.stage_key}</span>
        </div>
        <Badge tone={stageTone(stage.stage_status)}>{stage.stage_status_label}</Badge>
      </div>
      <p>{stage.display_summary}</p>
      {stage.requires_confirmation ? (
        <div className="alert warning">
          <div>{stage.confirmation_prompt ?? "该阶段完成后需要人工确认。"}</div>
        </div>
      ) : null}
      <div className="sync-kv-grid">
        <div><span>阶段顺序</span><strong>{String(stage.stage_order)}</strong></div>
        <div><span>下一步动作</span><strong>{stage.next_action?.label ?? "-"}</strong></div>
        <div><span>确认人</span><strong>{stage.confirmed_by ?? "-"}</strong></div>
        <div><span>确认时间</span><strong>{formatDateTime(stage.confirmed_at)}</strong></div>
      </div>
      {metricEntries.length ? (
        <div className="sync-stage-metrics">
          <strong>阶段指标</strong>
          {metricEntries.map(([key, value]) => (
            <div className="sync-stage-metric-row" key={key}>
              <span>{key}</span>
              <strong>{formatUnknown(value)}</strong>
            </div>
          ))}
        </div>
      ) : null}
      <IssueList title="阶段问题" items={stage.issues} tone="warning" />
    </aside>
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
      key: "stage",
      header: "阶段",
      render: (row) => row.stage_key ? <Badge tone="muted">{row.stage_key}</Badge> : <Badge tone="muted">-</Badge>,
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

function RunDetailBlock({
  detail,
  onAbort,
  onContinue,
  runActionLoading,
}: {
  detail: SyncRunDetail;
  onAbort: (runId: string) => void;
  onContinue: (runId: string) => void;
  runActionLoading: boolean;
}) {
  const runStatus = detail.run_status || detail.status;
  const canOperatePipeline = detail.profile_key === STK_MINS_PROFILE_KEY && !isFinishedRunStatus(runStatus);
  return (
    <div className="sync-run-detail">
      <div className="sync-run-head">
        <div>
          <strong>{detail.run_id}</strong>
          <span>{formatDateTime(detail.started_at)} ~ {formatDateTime(detail.finished_at)}</span>
        </div>
        <Badge tone={runTone(runStatus)}>{runStatus}</Badge>
      </div>
      <div className="sync-kv-grid">
        <div><span>Progress</span><strong>{String(detail.progress.summary ?? "—")}</strong></div>
        <div><span>当前阶段</span><strong>{detail.current_stage_key ?? "—"}</strong></div>
        <div><span>Backup Snapshots</span><strong>{snapshotCount(detail.backup)}</strong></div>
        <div><span>Dataset Results</span><strong>{String(detail.dataset_results.length)}</strong></div>
      </div>
      {detail.pipeline_stages.length ? (
        <PipelineStageBoard
          stages={detail.pipeline_stages}
          subtitle={`当前阶段：${detail.current_stage_key ?? "无"} · ${detail.requires_confirmation ? "等待人工确认" : "无需人工确认"}`}
        />
      ) : null}
      {canOperatePipeline ? (
        <div className="sync-run-action-row">
          <button
            className="sync-button"
            disabled={!detail.requires_confirmation || runActionLoading}
            onClick={() => onContinue(detail.run_id)}
            type="button"
          >
            {detail.next_action?.label ?? "继续下一阶段"}
          </button>
          <button
            className="sync-button sync-button-ghost-danger"
            disabled={runActionLoading}
            onClick={() => onAbort(detail.run_id)}
            type="button"
          >
            停止后续写入
          </button>
        </div>
      ) : null}
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
    return "加载中";
  }
  if (!status || status === "idle") {
    return "空闲";
  }
  if (status === "running") {
    return "运行中";
  }
  if (status === "stale") {
    return "锁已过期";
  }
  return status;
}

function lockHint(lock: SyncLock | null): string {
  if (!lock || lock.status === "idle") {
    return "当前没有写入任务持锁";
  }
  if (lock.status === "stale") {
    return `超过 ${lock.stale_after_seconds}s 未更新`;
  }
  return profileLabelByKey(lock.profile_key);
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

function profileDescription(profile: SyncProfileSummary): string {
  return PROFILE_PRESENTATION[profile.profile_key]?.description ?? profile.description;
}

function profileLabel(profile: SyncProfileSummary): string {
  return PROFILE_PRESENTATION[profile.profile_key]?.label ?? profile.display_name;
}

function profileLabelByKey(profileKey: string | null | undefined): string {
  if (!profileKey) {
    return "任务运行中";
  }
  return PROFILE_PRESENTATION[profileKey]?.label ?? "未知同步配置";
}

function profileStatusLabel(status: string): string {
  const mapping: Record<string, string> = {
    disabled: "已停用",
    enabled: "已启用",
    planned: "计划中",
  };
  return mapping[status] ?? status;
}

function runTone(status: string): BadgeTone {
  if (status === "success") {
    return "success";
  }
  if (status.includes("failed")) {
    return "error";
  }
  if (status === "waiting_confirmation" || status === "backup_completed") {
    return "warning";
  }
  if (status === "running" || status === "planned" || status === "lock_acquired") {
    return "processing";
  }
  return "muted";
}

function isFinishedRunStatus(status: string): boolean {
  return ["success", "failed", "backup_failed", "cancelled", "stopped_after_stage"].includes(status);
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

function stageTone(status: string): BadgeTone {
  if (status === "passed") {
    return "success";
  }
  if (status === "failed") {
    return "error";
  }
  if (status === "running") {
    return "processing";
  }
  if (status === "waiting_confirmation") {
    return "warning";
  }
  if (status === "skipped" || status === "cancelled") {
    return "muted";
  }
  return "neutral";
}

function stageRowTone(status: string): "default" | "selected" | "warning" | "error" {
  if (status === "failed") {
    return "error";
  }
  if (status === "waiting_confirmation") {
    return "warning";
  }
  return "default";
}

function isRunnableProfile(profile: SyncProfileSummary): boolean {
  return profile.profile_status === "enabled" && RUNNABLE_PROFILE_KEYS.has(profile.profile_key);
}

function shouldUseTargetDate(profileKey: string): boolean {
  return profileKey === "prod_db_daily";
}

function shouldUseDateRange(profileKey: string): boolean {
  return profileKey === "prod_db_manual_backfill" || profileKey === STK_MINS_PROFILE_KEY;
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

function stageMetricLine(metrics: Record<string, unknown>): string {
  const entries = Object.entries(metrics).slice(0, 3);
  if (!entries.length) {
    return "无阶段指标";
  }
  return entries.map(([key, value]) => `${key}=${formatUnknown(value)}`).join(" · ");
}

function formatUnknown(value: unknown): string {
  if (value === null || value === undefined) {
    return "-";
  }
  if (Array.isArray(value)) {
    return value.length ? value.map((item) => String(item)).join(", ") : "-";
  }
  if (typeof value === "object") {
    return compactJson(value);
  }
  if (typeof value === "number") {
    return value.toLocaleString("zh-CN");
  }
  return String(value);
}

function todayInputValue(): string {
  return new Date().toISOString().slice(0, 10);
}
