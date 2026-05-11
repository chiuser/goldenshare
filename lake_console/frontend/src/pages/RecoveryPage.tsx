import { Badge } from "../components/Badge";
import { CopyButton } from "../components/CopyButton";
import { DataTableCard, type DataTableColumn } from "../components/DataTableCard";
import { DenseToolbar } from "../components/DenseToolbar";
import { EmptyState } from "../components/EmptyState";
import { ErrorStateBlock } from "../components/ErrorStateBlock";
import { LoadingBlock } from "../components/LoadingBlock";
import { PageHeader } from "../components/PageHeader";
import { SectionCard } from "../components/SectionCard";
import type { RecoveryRepositorySummary, RecoverySnapshotDetail, RecoverySnapshotSummary, DatasetSummary } from "../types";
import type { RecoveryFilters } from "../hooks/useRecoveryData";
import { formatBytes, formatDateTime } from "../utils/format";

type RecoveryPageProps = {
  datasets: DatasetSummary[];
  detail: RecoverySnapshotDetail | null;
  detailError: string | null;
  detailLoading: boolean;
  filters: RecoveryFilters;
  onCloseDetail: () => void;
  onOpenRecord: (recordId: string) => void;
  onRefresh: () => void;
  onUpdateFilters: (filters: Partial<RecoveryFilters>) => void;
  records: RecoverySnapshotSummary[];
  recordsError: string | null;
  recordsLoading: boolean;
  selectedRecordId: string;
  summary: RecoveryRepositorySummary | null;
  summaryError: string | null;
  summaryLoading: boolean;
  total: number;
};

export function RecoveryPage({
  datasets,
  detail,
  detailError,
  detailLoading,
  filters,
  onCloseDetail,
  onOpenRecord,
  onRefresh,
  onUpdateFilters,
  records,
  recordsError,
  recordsLoading,
  selectedRecordId,
  summary,
  summaryError,
  summaryLoading,
  total,
}: RecoveryPageProps) {
  const activeFilterCount = [
    filters.scope,
    filters.datasetKey,
    filters.query.trim(),
    filters.pinnedOnly ? "pinned" : "",
    filters.baselineOnly ? "baseline" : "",
  ].filter(Boolean).length;

  const columns: DataTableColumn<RecoverySnapshotSummary>[] = [
    {
      key: "time",
      header: "时间",
      className: "recovery-time-column",
      render: (row) => (
        <div className="recovery-cell-stack recovery-cell-stack-compact">
          <strong>{formatDateTime(row.finished_at ?? row.started_at)}</strong>
          <span>{row.is_baseline ? "baseline snapshot" : "regular snapshot"}</span>
        </div>
      ),
    },
    {
      key: "target",
      header: "对象",
      className: "recovery-object-column",
      render: (row) => (
        <div className="recovery-cell-stack recovery-cell-stack-compact">
          <strong className="recovery-ellipsis" title={targetLabel(row)}>{targetLabel(row)}</strong>
          <div className="recovery-inline-badges">
            <Badge tone={scopeTone(row.scope)}>{row.scope}</Badge>
            {row.is_baseline ? <Badge tone="brand">baseline</Badge> : null}
            {row.pins.length ? <Badge tone="info">{row.pins.length} pin</Badge> : null}
          </div>
        </div>
      ),
    },
    {
      key: "snapshot",
      header: "Snapshot",
      className: "recovery-snapshot-column",
      render: (row) => (
        <div className="recovery-cell-stack recovery-cell-stack-compact">
          <strong className="recovery-ellipsis" title={snapshotLabel(row)}>{snapshotLabel(row)}</strong>
          <span className="recovery-mono-line">{shortSnapshotId(row.snapshot_id)}</span>
        </div>
      ),
    },
    {
      key: "size",
      header: "大小",
      className: "recovery-size-column",
      render: (row) => (
        <div className="recovery-cell-stack recovery-cell-stack-compact">
          <strong>{formatBytes(row.total_size)}</strong>
          <span className="recovery-nowrap">{compactCount(row.file_count)} 文件 · {compactCount(row.dir_count)} 目录</span>
        </div>
      ),
    },
    {
      key: "retention",
      header: "Retention",
      className: "recovery-retention-column",
      render: (row) => (
        <div className="recovery-cell-stack recovery-cell-stack-compact">
          <strong>{retentionSummary(row.retention_reasons)}</strong>
          <span>{row.pins.length ? `${row.pins.length} pin` : "retained"}</span>
        </div>
      ),
    },
    {
      key: "actions",
      header: "操作",
      className: "recovery-action-column",
      render: (row) => (
        <button className="recovery-inline-button recovery-inline-button-quiet" onClick={() => onOpenRecord(row.snapshot_id)} type="button">
          详情
        </button>
      ),
    },
  ];

  const repositoryDisconnected = Boolean(summary && !summary.connected);

  return (
    <div className={selectedRecordId ? "recovery-layout recovery-layout-with-detail" : "recovery-layout"}>
      <div className="recovery-main">
        <PageHeader
          eyebrow="Recovery / Write Safety"
          title="Recovery / Write Safety"
          right={(
            <div className="recovery-header-side">
              <strong>{summary?.connected ? "Connected" : summaryLoading ? "Loading" : "Disconnected"}</strong>
              <span>{summary?.repository_type ?? "repository"}</span>
            </div>
          )}
        />

        {summaryError ? <ErrorStateBlock title="Repository 摘要加载失败" description={summaryError} /> : null}
        {repositoryDisconnected ? (
          <ErrorStateBlock
            title="Kopia repository 未就绪"
            description={summary?.repository_error ?? "当前会话无法读取 Kopia repository，请先确认命令行能无交互访问。"}
          />
        ) : null}
        {recordsError ? <ErrorStateBlock title="Snapshot 列表加载失败" description={recordsError} /> : null}

        <section className="recovery-status-strip">
          <div className="recovery-status-item">
            <span>Repository</span>
            <strong>{summary?.repository_path ?? "—"}</strong>
          </div>
          <div className="recovery-status-item">
            <span>Lake Root</span>
            <strong>{summary?.lake_root ?? "—"}</strong>
          </div>
        </section>

        <section className="recovery-mini-stats">
          <RecoveryMiniStat label="Snapshots" value={summary ? String(summary.snapshot_count) : "..."} />
          <RecoveryMiniStat label="Pinned" value={summary ? String(summary.pinned_snapshot_count) : "..."} tone={summary && summary.pinned_snapshot_count > 0 ? "accent" : "muted"} />
          <RecoveryMiniStat label="Latest Snapshot" value={summary?.latest_snapshot_at ? formatDateTime(summary.latest_snapshot_at) : "—"} wide />
          <RecoveryMiniStat label="Latest Baseline" value={summary?.latest_baseline_at ? formatDateTime(summary.latest_baseline_at) : "—"} wide={Boolean(summary?.latest_baseline_at)} />
        </section>

        <SectionCard
          title="Snapshots"
          side={(
            <div className="recovery-table-side">
              <span>{recordsLoading ? "读取中" : `${total} 条`}</span>
              {activeFilterCount ? <Badge tone="muted">{activeFilterCount} filters</Badge> : null}
              <button className="recovery-inline-button recovery-inline-button-muted" onClick={onRefresh} type="button">
                刷新
              </button>
            </div>
          )}
        >
          <DenseToolbar className="recovery-toolbar">
            <label className="recovery-field">
              <span>Scope</span>
              <select value={filters.scope} onChange={(event) => onUpdateFilters({ scope: event.target.value })}>
                <option value="">全部</option>
                <option value="whole_lake">whole_lake</option>
                <option value="manifest">manifest</option>
                <option value="raw">raw</option>
                <option value="derived">derived</option>
                <option value="research">research</option>
                <option value="indicators">indicators</option>
              </select>
            </label>
            <label className="recovery-field">
              <span>数据集</span>
              <select value={filters.datasetKey} onChange={(event) => onUpdateFilters({ datasetKey: event.target.value })}>
                <option value="">全部</option>
                {datasets.map((dataset) => (
                  <option key={dataset.dataset_key} value={dataset.dataset_key}>
                    {dataset.display_name}
                  </option>
                ))}
              </select>
            </label>
            <label className="recovery-field recovery-field-query">
              <span>检索</span>
              <input
                placeholder="snapshot id / description / path / pin"
                type="search"
                value={filters.query}
                onChange={(event) => onUpdateFilters({ query: event.target.value })}
              />
            </label>
            <div className="recovery-toggle-row">
              <button
                className={filters.pinnedOnly ? "recovery-toggle active" : "recovery-toggle"}
                onClick={() => onUpdateFilters({ pinnedOnly: !filters.pinnedOnly })}
                type="button"
              >
                仅看已 pin
              </button>
              <button
                className={filters.baselineOnly ? "recovery-toggle active" : "recovery-toggle"}
                onClick={() => onUpdateFilters({ baselineOnly: !filters.baselineOnly })}
                type="button"
              >
                仅看 baseline
              </button>
              <button
                className="recovery-toggle"
                onClick={() => onUpdateFilters({ scope: "", datasetKey: "", pinnedOnly: false, baselineOnly: false, query: "" })}
                type="button"
              >
                重置
              </button>
            </div>
          </DenseToolbar>

          {recordsLoading ? (
            <LoadingBlock title="正在读取快照清单" description="正在从 Kopia inventory 加载 snapshot 列表。" />
          ) : (
            <DataTableCard
              columns={columns}
              empty={<EmptyState title="当前筛选条件下无快照" description="调整 scope、数据集或 pin / baseline 条件后重试。" />}
              getRowKey={(row) => row.snapshot_id}
              label="Kopia 快照清单"
              onRowClick={(row) => onOpenRecord(row.snapshot_id)}
              rowTone={(row) => {
                if (row.snapshot_id === selectedRecordId) return "selected";
                if (row.is_baseline) return "warning";
                return "default";
              }}
              rows={records}
            />
          )}
        </SectionCard>
      </div>

      {selectedRecordId ? (
        <aside className="recovery-detail-drawer">
          {detailLoading ? (
            <LoadingBlock title="正在读取快照详情" description="正在加载选中快照的 metadata 与命令预览。" />
          ) : detailError ? (
            <ErrorStateBlock title="Snapshot 明细加载失败" description={detailError} />
          ) : detail ? (
            <>
              <div className="recovery-detail-header">
                <div className="recovery-cell-stack">
                  <Badge tone="brand">{detail.scope}</Badge>
                  <h3>{detail.dataset_key ?? detail.display_path}</h3>
                  <span>{detail.snapshot_id}</span>
                </div>
                <button className="recovery-inline-button" onClick={onCloseDetail} type="button">
                  关闭
                </button>
              </div>

              <SectionCard title="概览">
                <div className="recovery-kv-grid">
                  <DetailItem label="Description" value={detail.description ?? "—"} wide />
                  <DetailItem label="Source Path" value={detail.source_path} wide />
                  <DetailItem label="Repository Path" value={detail.repository_path ?? "—"} wide />
                  <DetailItem label="Manifest ID" value={detail.manifest_id ?? "—"} />
                  <DetailItem label="Host / User" value={detail.host && detail.user_name ? `${detail.user_name}@${detail.host}` : "—"} />
                  <DetailItem label="Baseline" value={detail.is_baseline ? "Yes" : "No"} />
                  <DetailItem label="Pins" value={detail.pins.length ? detail.pins.join(", ") : "—"} wide />
                </div>
              </SectionCard>

              <SectionCard title="统计">
                <div className="recovery-kv-grid">
                  <DetailItem label="大小" value={formatBytes(detail.total_size)} />
                  <DetailItem label="文件数" value={detail.file_count.toLocaleString("zh-CN")} />
                  <DetailItem label="目录数" value={detail.dir_count.toLocaleString("zh-CN")} />
                  <DetailItem label="完成时间" value={formatDateTime(detail.finished_at ?? detail.started_at)} />
                  <DetailItem label="Retention" value={detail.retention_reasons.length ? detail.retention_reasons.join(", ") : "—"} wide />
                </div>
              </SectionCard>

              <SectionCard title="命令预览">
                <div className="recovery-command-list">
                  {detail.command_hints.map((item) => (
                    <article className="recovery-command-card" key={item.command_key}>
                      <div className="recovery-command-header">
                        <div className="recovery-cell-stack">
                          <strong>{item.title}</strong>
                          <span>{item.scenario}</span>
                        </div>
                        <CopyButton idleLabel="复制命令" value={item.command} />
                      </div>
                      <code>{item.command}</code>
                    </article>
                  ))}
                </div>
              </SectionCard>
            </>
          ) : (
            <EmptyState title="未选择快照" description="点击主表中的行，查看 snapshot 详情与恢复命令。" />
          )}
        </aside>
      ) : null}
    </div>
  );
}

function shortSnapshotId(value: string) {
  return value.slice(0, 12);
}

function targetLabel(row: RecoverySnapshotSummary) {
  if (row.scope === "whole_lake") {
    return "whole_lake";
  }
  return row.dataset_key ?? row.display_path;
}

function snapshotLabel(row: RecoverySnapshotSummary) {
  return row.description ?? row.snapshot_id;
}

function retentionSummary(reasons: string[]) {
  if (!reasons.length) return "—";
  if (reasons.length === 1) return reasons[0];
  return `${reasons[0]} +${reasons.length - 1}`;
}

function compactCount(value: number) {
  return new Intl.NumberFormat("zh-CN", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

function RecoveryMiniStat({
  label,
  value,
  tone = "default",
  wide = false,
}: {
  label: string;
  value: string;
  tone?: "default" | "accent" | "muted";
  wide?: boolean;
}) {
  const className = [
    "recovery-mini-stat",
    `recovery-mini-stat-${tone}`,
    wide ? "recovery-mini-stat-wide" : undefined,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <article className={className}>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function DetailItem({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={wide ? "recovery-detail-item recovery-detail-item-wide" : "recovery-detail-item"}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function scopeTone(scope: string) {
  switch (scope) {
    case "whole_lake":
      return "brand";
    case "raw":
      return "success";
    case "derived":
      return "warning";
    case "research":
      return "info";
    case "manifest":
      return "muted";
    default:
      return "muted";
  }
}
