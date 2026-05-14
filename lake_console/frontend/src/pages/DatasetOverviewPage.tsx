import { useMemo, useState } from "react";
import { DataTableCard, type DataTableColumn } from "../components/DataTableCard";
import { EmptyState } from "../components/EmptyState";
import { HealthBadge } from "../components/HealthBadge";
import { Metric } from "../components/Metric";
import { PageHeader } from "../components/PageHeader";
import { SectionCard } from "../components/SectionCard";
import type { LakeOverview, LakeOverviewDatasetRow, LakeStatus } from "../types";
import { formatBytes, formatDateTime } from "../utils/format";

type DatasetOverviewPageProps = {
  overview: LakeOverview | null;
  status: LakeStatus | null;
  onOpenDetail: (datasetKey: string) => void;
};

type CountSummary = {
  key: string;
  label: string;
  count: number;
};

export function DatasetOverviewPage({ overview, status, onOpenDetail }: DatasetOverviewPageProps) {
  const [query, setQuery] = useState("");
  const [groupFilter, setGroupFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const rows = overview?.dataset_rows ?? [];
  const filteredRows = useMemo(() => filterRows(rows, { groupFilter, query, statusFilter }), [rows, groupFilter, query, statusFilter]);
  const groupOptions = useMemo(() => sortedUnique(rows.map((row) => row.group_label)), [rows]);
  const statusOptions = useMemo(() => buildStatusOptions(rows), [rows]);
  const rootState = status?.path.initialized ? "已初始化" : status ? "未初始化" : "读取中";
  const rootHint = status ? [status.path.exists ? "存在" : "不存在", status.path.readable ? "可读" : "不可读", status.path.writable ? "可写" : "不可写"].join(" / ") : "-";
  const syncRows: CountSummary[] = overview?.sync_method_groups.map((item) => ({ key: item.key, label: item.label, count: item.count })) ?? [];

  const columns: DataTableColumn<LakeOverviewDatasetRow>[] = [
    {
      key: "dataset",
      header: "数据集",
      className: "lake-inventory-dataset-col",
      render: (row) => (
        <div className="lake-inventory-name">
          <div>
            <strong>{row.display_name}</strong>
            <code>{row.dataset_key}</code>
          </div>
          <HealthBadge label={row.health_label} status={row.health_status} />
        </div>
      ),
    },
    {
      key: "group",
      header: "分组 / 来源",
      render: (row) => (
        <div className="lake-inventory-stack">
          <strong>{row.group_label}</strong>
          <span>{row.source_label}</span>
        </div>
      ),
    },
    {
      key: "path",
      header: "主路径",
      className: "lake-inventory-path-col",
      render: (row) => <code>{row.primary_path ?? "-"}</code>,
    },
    {
      key: "nodes",
      header: "节点",
      render: (row) => (
        <div className="lake-inventory-stack">
          <strong>{formatCount(row.node_count)}</strong>
          <span>{row.health_label}</span>
        </div>
      ),
    },
    {
      key: "scale",
      header: "规模",
      className: "lake-inventory-number-col",
      render: (row) => (
        <div className="lake-inventory-stack lake-inventory-numeric">
          <strong>{formatBytes(row.total_bytes)}</strong>
          <span>
            {formatCount(row.file_count)} 文件 / {formatCount(row.partition_count)} 分区
          </span>
        </div>
      ),
    },
    {
      key: "coverage",
      header: "覆盖范围",
      render: (row) => <strong>{row.coverage_label}</strong>,
    },
  ];

  return (
    <div className="lake-overview-page">
      <PageHeader
        eyebrow="Local Lake"
        title="数据湖总览"
        description="展示后端数据湖模型已经输出的事实：总量、湖内层级、来源方式、数据集清单和硬盘资产样本。"
        helpTitle="前端不解析路径、不聚合节点、不猜后端实现；页面字段以后端 /api/lake/overview 和 /api/lake/datasets 输出为准。"
        right={<code>{overview?.lake_root ?? status?.path.lake_root ?? "正在读取数据湖根目录..."}</code>}
        variant="accent"
      />

      <SectionCard title="总览" description="数字来自后端 LakeOverviewResponse。">
        {overview ? (
          <section className="metric-grid lake-overview-metrics">
            {overview.summary_metrics.map((metric) => (
              <Metric
                hint={metric.hint}
                key={metric.key}
                label={metric.label}
                value={metric.value}
                variant={metric.tone === "warning" || metric.tone === "success" || metric.tone === "error" ? metric.tone : "subtle"}
              />
            ))}
          </section>
        ) : (
          <EmptyState title="正在读取总览" description="等待后端返回数据湖总览事实。" />
        )}
        <div className="lake-overview-summary-grid">
          <FactTile label="Lake Root" value={status?.path.lake_root ?? overview?.lake_root ?? "-"} hint={`${rootState} · ${rootHint}`} mono />
          <FactTile label="更新时间" value={formatDateTime(overview?.generated_at ?? null)} hint="后端生成时间" />
          <FactTile label="硬盘资产样本" value={formatCount(overview?.physical_assets.length ?? 0)} hint="后端返回的前 200 项资产样本" />
        </div>
      </SectionCard>

      <SectionCard title="湖内层级" description="层级汇总由后端按内容节点扫描后输出。">
        {overview?.layer_groups.length ? (
          <div className="lake-overview-domain-table">
            <table>
              <thead>
                <tr>
                  <th>层级</th>
                  <th>数据集 / 节点</th>
                  <th>典型路径</th>
                  <th>规模</th>
                  <th>覆盖范围</th>
                  <th>频率</th>
                </tr>
              </thead>
              <tbody>
                {overview.layer_groups.map((layer) => (
                  <tr key={layer.layer}>
                    <td>
                      <strong>{layer.layer_name}</strong>
                      <span className="lake-table-muted">{layer.layer}</span>
                    </td>
                    <td>
                      <strong>{formatCount(layer.dataset_count)}</strong>
                      <span className="lake-table-muted">{formatCount(layer.node_count)} 个节点</span>
                    </td>
                    <td>
                      <code>{layer.sample_path ?? "-"}</code>
                    </td>
                    <td>
                      <strong>{formatBytes(layer.total_bytes)}</strong>
                      <span className="lake-table-muted">
                        {formatCount(layer.file_count)} 文件 / {formatCount(layer.partition_count)} 分区
                      </span>
                    </td>
                    <td>{layer.coverage_label}</td>
                    <td>{freqLabel(layer.freqs)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title="暂无层级事实" description="后端暂未返回可展示的湖内层级汇总。" />
        )}
      </SectionCard>

      <SectionCard title="来源与同步方式" description="来源分组由后端输出，不从路径或命令字符串反推。">
        <div className="lake-overview-source-grid">
          <CountSummaryCard title="事实来源" rows={syncRows} />
        </div>
      </SectionCard>

      <SectionCard
        className="lake-overview-inventory"
        side={<span>{formatCount(filteredRows.length)} / {formatCount(rows.length)} 项</span>}
        title="数据集清单"
        description="清单行来自 /api/lake/overview 的 dataset_rows；点击行进入数据集详情。"
      >
        <div className="lake-overview-toolbar">
          <input aria-label="搜索数据集" placeholder="搜索数据集 / key / 路径" value={query} onChange={(event) => setQuery(event.target.value)} />
          <select aria-label="按分组过滤" value={groupFilter} onChange={(event) => setGroupFilter(event.target.value)}>
            <option value="">全部分组</option>
            {groupOptions.map((group) => (
              <option key={group} value={group}>
                {group}
              </option>
            ))}
          </select>
          <select aria-label="按状态过滤" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="">全部状态</option>
            {statusOptions.map((option) => (
              <option key={option.status} value={option.status}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <DataTableCard
          columns={columns}
          empty={<EmptyState title="没有匹配的数据集" description="可以清空筛选条件后再查看。" />}
          getRowKey={(row) => row.dataset_key}
          label="数据湖数据集清单"
          onRowClick={(row) => onOpenDetail(row.dataset_key)}
          rowTone={(row) => (row.health_status === "warning" ? "warning" : row.health_status === "error" ? "error" : "default")}
          rows={filteredRows}
        />
      </SectionCard>
    </div>
  );
}

function FactTile({ hint, label, mono = false, value }: { hint: string; label: string; mono?: boolean; value: string }) {
  return (
    <article className="lake-overview-fact-tile">
      <span>{label}</span>
      <strong className={mono ? "mono" : undefined}>{value}</strong>
      <em>{hint}</em>
    </article>
  );
}

function CountSummaryCard({ rows, title }: { rows: CountSummary[]; title: string }) {
  return (
    <article className="lake-overview-count-card">
      <h3>{title}</h3>
      <div className="lake-overview-count-list">
        {rows.length ? (
          rows.map((row) => (
            <div key={row.key}>
              <span>{row.label}</span>
              <strong>{formatCount(row.count)}</strong>
            </div>
          ))
        ) : (
          <span className="lake-table-muted">暂无</span>
        )}
      </div>
    </article>
  );
}

function filterRows(
  rows: LakeOverviewDatasetRow[],
  filters: { groupFilter: string; query: string; statusFilter: string },
): LakeOverviewDatasetRow[] {
  const normalizedQuery = filters.query.trim().toLowerCase();
  return rows.filter((row) => {
    const haystack = [row.dataset_key, row.display_name, row.group_label, row.source_label, row.primary_path ?? ""].join(" ").toLowerCase();
    return (
      (!normalizedQuery || haystack.includes(normalizedQuery)) &&
      (!filters.groupFilter || row.group_label === filters.groupFilter) &&
      (!filters.statusFilter || row.health_status === filters.statusFilter)
    );
  });
}

function sortedUnique(values: string[]): string[] {
  return Array.from(new Set(values)).sort((left, right) => left.localeCompare(right, "zh-CN"));
}

function buildStatusOptions(rows: LakeOverviewDatasetRow[]): Array<{ label: string; status: string }> {
  const order = new Map([
    ["ok", 0],
    ["warning", 1],
    ["error", 2],
    ["empty", 3],
  ]);
  const byStatus = new Map<string, string>();
  rows.forEach((row) => {
    if (!byStatus.has(row.health_status)) {
      byStatus.set(row.health_status, row.health_label);
    }
  });
  return Array.from(byStatus, ([status, label]) => ({ label, status })).sort(
    (left, right) => (order.get(left.status) ?? 99) - (order.get(right.status) ?? 99) || left.label.localeCompare(right.label, "zh-CN"),
  );
}

function freqLabel(freqs: number[]): string {
  return freqs.length ? freqs.map((freq) => `${freq}min`).join(" / ") : "-";
}

function formatCount(value: number): string {
  return value.toLocaleString("zh-CN");
}
