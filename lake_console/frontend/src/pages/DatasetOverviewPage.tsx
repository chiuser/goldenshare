import { useMemo, useState } from "react";
import { Badge } from "../components/Badge";
import { DataTableCard, type DataTableColumn } from "../components/DataTableCard";
import { EmptyState } from "../components/EmptyState";
import { HealthBadge } from "../components/HealthBadge";
import { Metric } from "../components/Metric";
import { PageHeader } from "../components/PageHeader";
import { SectionCard } from "../components/SectionCard";
import type { DatasetSummary, LakeStatus } from "../types";
import { formatBytes, formatDateOrMonthRange, formatDateTime, formatRange } from "../utils/format";

type DatasetOverviewPageProps = {
  datasets: DatasetSummary[];
  readyDatasets: number;
  riskCount: number;
  status: LakeStatus | null;
  totalBytes: number;
  totalFiles: number;
  onOpenDetail: (datasetKey: string) => void;
};

type LayerAggregate = {
  key: string;
  label: string;
  datasetCount: number;
  fileCount: number;
  partitionCount: number;
  totalBytes: number;
  freqs: number[];
  layouts: string[];
  samplePath: string;
  coverage: string;
};

type CountSummary = {
  key: string;
  label: string;
  count: number;
};

const LAYER_ORDER = ["raw_tushare", "manifest", "derived", "research"];

const ARCHITECTURE_FLOW = [
  {
    code: "LakeDatasetDefinition",
    title: "静态数据集契约",
    description: "定义数据集 key、展示名、分组、主存储形态、写入策略和层级。",
  },
  {
    code: "LakeLayerDefinition",
    title: "层级契约",
    description: "定义每一层的存储形态、路径、用途和推荐使用方式。",
  },
  {
    code: "FilesystemScanner",
    title: "文件扫描器",
    description: "读取本地 Lake 真实目录与 Parquet 文件，不读取业务数据库。",
  },
  {
    code: "LakeDatasetSummary",
    title: "数据集级事实",
    description: "汇总层级、文件数、分区数、容量、覆盖范围和风险。",
  },
  {
    code: "Backend API",
    title: "控制台 API",
    description: "当前首页只消费 /api/lake/status 和 /api/datasets。",
  },
  {
    code: "Frontend View",
    title: "页面投影",
    description: "只做展示 view model，不解析 path，不假算未落地字段。",
  },
];

const DATA_DOMAIN_ROWS = [
  {
    domain: "Lake 文件事实",
    source: "catalog + filesystem scanner",
    objects: "LakeDatasetSummary / LakeLayerSummary / LakePartitionSummary",
    scope: "数据湖总览、数据集详情、后续 Storage",
  },
  {
    domain: "Lake 根目录状态",
    source: "LakeRootService",
    objects: "LakeStatusResponse / LakePathInfo / DiskUsageInfo",
    scope: "根目录状态、磁盘状态",
  },
  {
    domain: "命令示例",
    source: "catalog command examples",
    objects: "LakeCommandExampleResponse",
    scope: "命令页，不在总览页反推同步来源",
  },
  {
    domain: "Kopia 恢复事实",
    source: "Kopia CLI JSON",
    objects: "LakeRecoverySnapshotSummary",
    scope: "Recovery 独立领域",
  },
];

export function DatasetOverviewPage({
  datasets,
  readyDatasets,
  riskCount,
  status,
  totalBytes,
  totalFiles,
  onOpenDetail,
}: DatasetOverviewPageProps) {
  const [query, setQuery] = useState("");
  const [groupFilter, setGroupFilter] = useState("");
  const [layerFilter, setLayerFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const totalPartitions = useMemo(() => datasets.reduce((sum, dataset) => sum + dataset.partition_count, 0), [datasets]);
  const layerAggregates = useMemo(() => buildLayerAggregates(datasets), [datasets]);
  const sourceSummaries = useMemo(() => buildCountSummaries(datasets, (dataset) => dataset.source, sourceLabel), [datasets]);
  const updateModeSummaries = useMemo(() => buildCountSummaries(datasets, (dataset) => dataset.update_mode ?? "unknown", updateModeLabel), [datasets]);
  const writePolicySummaries = useMemo(() => buildCountSummaries(datasets, (dataset) => dataset.write_policy ?? "unknown", writePolicyLabel), [datasets]);
  const groupOptions = useMemo(() => sortedUnique(datasets.map((dataset) => dataset.group_label ?? dataset.category ?? "未分组")), [datasets]);
  const layerOptions = useMemo(() => layerAggregates.map((layer) => ({ key: layer.key, label: layer.label })), [layerAggregates]);
  const filteredDatasets = useMemo(
    () => filterDatasets(datasets, { groupFilter, layerFilter, query, statusFilter }),
    [datasets, groupFilter, layerFilter, query, statusFilter],
  );
  const timeRange = useMemo(() => buildDatasetTimeRange(datasets), [datasets]);
  const rootState = status?.path.initialized ? "已初始化" : status ? "未初始化" : "读取中";
  const rootHint = status ? [status.path.exists ? "存在" : "不存在", status.path.readable ? "可读" : "不可读", status.path.writable ? "可写" : "不可写"].join(" / ") : "-";

  const columns: DataTableColumn<DatasetSummary>[] = [
    {
      key: "dataset",
      header: "数据集",
      className: "lake-inventory-dataset-col",
      render: (dataset) => (
        <div className="lake-inventory-name">
          <div>
            <strong>{dataset.display_name}</strong>
            <code>{dataset.dataset_key}</code>
          </div>
          <HealthBadge status={dataset.health_status} />
        </div>
      ),
    },
    {
      key: "group",
      header: "分组 / 来源",
      render: (dataset) => (
        <div className="lake-inventory-stack">
          <strong>{dataset.group_label ?? dataset.category ?? "未分组"}</strong>
          <span>{sourceLabel(dataset.source)}</span>
        </div>
      ),
    },
    {
      key: "storage",
      header: "湖内位置",
      className: "lake-inventory-path-col",
      render: (dataset) => (
        <div className="lake-inventory-stack">
          <code>{dataset.storage_root ?? "-"}</code>
          <span>{layoutLabel(dataset.primary_layout)}</span>
        </div>
      ),
    },
    {
      key: "layers",
      header: "层级 / 频率",
      render: (dataset) => (
        <div className="lake-chip-stack">
          <div className="lake-chip-row">
            {dataset.layers.map((layer) => (
              <Badge tone="brand" key={`${dataset.dataset_key}-${layer}`}>
                {layerLabel(layer)}
              </Badge>
            ))}
          </div>
          <span>{freqLabel(dataset.freqs)}</span>
        </div>
      ),
    },
    {
      key: "scale",
      header: "规模",
      className: "lake-inventory-number-col",
      render: (dataset) => (
        <div className="lake-inventory-stack lake-inventory-numeric">
          <strong>{formatBytes(dataset.total_bytes)}</strong>
          <span>
            {formatCount(dataset.file_count)} 文件 / {formatCount(dataset.partition_count)} 分区
          </span>
        </div>
      ),
    },
    {
      key: "coverage",
      header: "覆盖范围",
      render: (dataset) => (
        <div className="lake-inventory-stack">
          <strong>{formatDateOrMonthRange(dataset)}</strong>
          <span>{formatDateTime(dataset.latest_modified_at)}</span>
        </div>
      ),
    },
    {
      key: "policy",
      header: "写入 / 更新",
      render: (dataset) => (
        <div className="lake-inventory-stack">
          <strong>{writePolicyLabel(dataset.write_policy ?? "unknown")}</strong>
          <span>{updateModeLabel(dataset.update_mode ?? "unknown")}</span>
        </div>
      ),
    },
  ];

  return (
    <div className="lake-overview-page">
      <PageHeader
        eyebrow="Local Lake"
        title="数据湖总览"
        description="基于统一文件事实模型展示本地数据湖：数据集、层级、存储形态、来源口径和当前落盘规模。"
        helpTitle="字段和对象关系遵守 Local Lake Console 数据模型关系图 v1；首页只做现有 API 的页面投影。"
        right={<code>{status?.path.lake_root ?? "正在读取数据湖根目录..."}</code>}
        variant="accent"
      />

      <SectionCard title="总览" description="数字来自 LakeDatasetSummary 与 LakeStatusResponse，不包含未登记为数据集的临时目录。">
        <section className="metric-grid lake-overview-metrics">
          <Metric label="数据集" value={formatCount(datasets.length)} hint={`${formatCount(readyDatasets)} 个已有文件落盘`} />
          <Metric label="已登记容量" value={formatBytes(totalBytes)} hint="catalog + filesystem scanner" />
          <Metric label="文件 / 分区" value={`${formatCount(totalFiles)} / ${formatCount(totalPartitions)}`} hint="所有已登记层级合计" />
          <Metric label="风险提示" value={formatCount(riskCount)} hint="Lake 根目录与数据集风险合计" variant={riskCount ? "warning" : "success"} />
        </section>
        <div className="lake-overview-summary-grid">
          <FactTile label="Lake Root" value={status?.path.lake_root ?? "-"} hint={`${rootState} · ${rootHint}`} mono />
          <FactTile label="数据时间范围" value={timeRange} hint="按数据集扫描聚合" />
          <FactTile label="湖内层级" value={formatCount(layerAggregates.length)} hint={layerAggregates.map((layer) => layer.label).join(" / ") || "-"} />
        </div>
      </SectionCard>

      <SectionCard title="事实口径" description="总览页只展示已经进入统一模型的事实；Recovery 和命令示例属于独立或辅助领域。">
        <div className="lake-overview-domain-table">
          <table>
            <thead>
              <tr>
                <th>领域</th>
                <th>主事实源</th>
                <th>核心对象</th>
                <th>页面范围</th>
              </tr>
            </thead>
            <tbody>
              {DATA_DOMAIN_ROWS.map((row) => (
                <tr key={row.domain}>
                  <td>{row.domain}</td>
                  <td>{row.source}</td>
                  <td>
                    <code>{row.objects}</code>
                  </td>
                  <td>{row.scope}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>

      <SectionCard title="架构链路" description="从 catalog 静态契约到前端展示，事实沿一条链路流动。">
        <div className="lake-overview-flow">
          {ARCHITECTURE_FLOW.map((item, index) => (
            <article className="lake-overview-flow-node" key={item.code}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <strong>{item.title}</strong>
              <code>{item.code}</code>
              <p>{item.description}</p>
            </article>
          ))}
        </div>
      </SectionCard>

      <SectionCard title="湖内层级" description="层级来自每个数据集的 LakeLayerSummary，页面展示中文名，路径保留真实目录。">
        {layerAggregates.length ? (
          <div className="lake-overview-domain-table">
            <table>
              <thead>
                <tr>
                  <th>层级</th>
                  <th>数据集</th>
                  <th>存储形态</th>
                  <th>典型路径</th>
                  <th>规模</th>
                  <th>覆盖范围</th>
                  <th>频率</th>
                </tr>
              </thead>
              <tbody>
                {layerAggregates.map((layer) => (
                  <tr key={layer.key}>
                    <td>
                      <strong>{layer.label}</strong>
                      <span className="lake-table-muted">{layer.key}</span>
                    </td>
                    <td>{formatCount(layer.datasetCount)}</td>
                    <td>{layer.layouts.join(" / ") || "-"}</td>
                    <td>
                      <code>{layer.samplePath}</code>
                    </td>
                    <td>
                      <strong>{formatBytes(layer.totalBytes)}</strong>
                      <span className="lake-table-muted">
                        {formatCount(layer.fileCount)} 文件 / {formatCount(layer.partitionCount)} 分区
                      </span>
                    </td>
                    <td>{layer.coverage}</td>
                    <td>{freqLabel(layer.freqs)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title="暂无层级事实" description="当前 API 还没有返回可展示的 LakeLayerSummary。" />
        )}
      </SectionCard>

      <SectionCard title="来源与同步方式" description="只展示当前模型中已落地的 source、update_mode、write_policy；不从路径或命令字符串反推同步来源。">
        <div className="lake-overview-source-grid">
          <CountSummaryCard title="事实来源" rows={sourceSummaries} />
          <CountSummaryCard title="更新模式" rows={updateModeSummaries} />
          <CountSummaryCard title="写入策略" rows={writePolicySummaries} />
        </div>
      </SectionCard>

      <SectionCard
        className="lake-overview-inventory"
        side={<span>{formatCount(filteredDatasets.length)} / {formatCount(datasets.length)} 项</span>}
        title="数据集清单"
        description="清单来自 /api/datasets；点击行进入数据集详情。"
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
          <select aria-label="按层级过滤" value={layerFilter} onChange={(event) => setLayerFilter(event.target.value)}>
            <option value="">全部层级</option>
            {layerOptions.map((layer) => (
              <option key={layer.key} value={layer.key}>
                {layer.label}
              </option>
            ))}
          </select>
          <select aria-label="按状态过滤" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="">全部状态</option>
            <option value="ok">已落盘</option>
            <option value="warning">有风险</option>
            <option value="error">异常</option>
            <option value="empty">未落盘</option>
          </select>
        </div>
        <DataTableCard
          columns={columns}
          empty={<EmptyState title="没有匹配的数据集" description="可以清空筛选条件后再查看。" />}
          getRowKey={(dataset) => dataset.dataset_key}
          label="数据湖数据集清单"
          onRowClick={(dataset) => onOpenDetail(dataset.dataset_key)}
          rowTone={(dataset) => (dataset.health_status === "warning" ? "warning" : dataset.health_status === "error" ? "error" : "default")}
          rows={filteredDatasets}
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

function buildLayerAggregates(datasets: DatasetSummary[]): LayerAggregate[] {
  const drafts = new Map<
    string,
    {
      datasetKeys: Set<string>;
      fileCount: number;
      partitionCount: number;
      totalBytes: number;
      freqs: Set<number>;
      layouts: Set<string>;
      paths: string[];
      earliestDates: string[];
      latestDates: string[];
      earliestMonths: string[];
      latestMonths: string[];
    }
  >();

  for (const dataset of datasets) {
    for (const layer of dataset.layer_summaries) {
      const draft = drafts.get(layer.layer) ?? {
        datasetKeys: new Set<string>(),
        fileCount: 0,
        partitionCount: 0,
        totalBytes: 0,
        freqs: new Set<number>(),
        layouts: new Set<string>(),
        paths: [],
        earliestDates: [],
        latestDates: [],
        earliestMonths: [],
        latestMonths: [],
      };
      draft.datasetKeys.add(dataset.dataset_key);
      draft.fileCount += layer.file_count;
      draft.partitionCount += layer.partition_count;
      draft.totalBytes += layer.total_bytes;
      for (const freq of layer.freqs) draft.freqs.add(freq);
      draft.layouts.add(layoutLabel(layer.layout));
      if (layer.path) draft.paths.push(layer.path);
      if (layer.earliest_trade_date) draft.earliestDates.push(layer.earliest_trade_date);
      if (layer.latest_trade_date) draft.latestDates.push(layer.latest_trade_date);
      if (layer.earliest_trade_month) draft.earliestMonths.push(layer.earliest_trade_month);
      if (layer.latest_trade_month) draft.latestMonths.push(layer.latest_trade_month);
      drafts.set(layer.layer, draft);
    }
  }

  return Array.from(drafts.entries())
    .map(([key, draft]) => ({
      key,
      label: layerLabel(key),
      datasetCount: draft.datasetKeys.size,
      fileCount: draft.fileCount,
      partitionCount: draft.partitionCount,
      totalBytes: draft.totalBytes,
      freqs: Array.from(draft.freqs).sort((left, right) => left - right),
      layouts: Array.from(draft.layouts).sort((left, right) => left.localeCompare(right, "zh-CN")),
      samplePath: draft.paths[0] ?? "-",
      coverage: formatRange(
        minText(draft.earliestDates) ?? minText(draft.earliestMonths),
        maxText(draft.latestDates) ?? maxText(draft.latestMonths),
      ),
    }))
    .sort((left, right) => layerOrder(left.key) - layerOrder(right.key));
}

function buildCountSummaries(datasets: DatasetSummary[], getKey: (dataset: DatasetSummary) => string, getLabel: (key: string) => string): CountSummary[] {
  const counts = new Map<string, number>();
  for (const dataset of datasets) {
    const key = getKey(dataset);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .map(([key, count]) => ({ key, label: getLabel(key), count }))
    .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label, "zh-CN"));
}

function filterDatasets(
  datasets: DatasetSummary[],
  filters: { groupFilter: string; layerFilter: string; query: string; statusFilter: string },
): DatasetSummary[] {
  const normalizedQuery = filters.query.trim().toLowerCase();
  return datasets.filter((dataset) => {
    const group = dataset.group_label ?? dataset.category ?? "未分组";
    const haystack = [
      dataset.dataset_key,
      dataset.display_name,
      dataset.description ?? "",
      dataset.storage_root ?? "",
      dataset.source,
      group,
      dataset.layers.join(" "),
    ]
      .join(" ")
      .toLowerCase();
    return (
      (!normalizedQuery || haystack.includes(normalizedQuery)) &&
      (!filters.groupFilter || group === filters.groupFilter) &&
      (!filters.layerFilter || dataset.layers.includes(filters.layerFilter)) &&
      (!filters.statusFilter || dataset.health_status === filters.statusFilter)
    );
  });
}

function buildDatasetTimeRange(datasets: DatasetSummary[]): string {
  const earliestDates = datasets.map((dataset) => dataset.earliest_trade_date).filter((value): value is string => Boolean(value));
  const latestDates = datasets.map((dataset) => dataset.latest_trade_date).filter((value): value is string => Boolean(value));
  if (earliestDates.length || latestDates.length) {
    return formatRange(minText(earliestDates), maxText(latestDates));
  }
  return formatRange(
    minText(datasets.map((dataset) => dataset.earliest_trade_month).filter((value): value is string => Boolean(value))),
    maxText(datasets.map((dataset) => dataset.latest_trade_month).filter((value): value is string => Boolean(value))),
  );
}

function sortedUnique(values: string[]): string[] {
  return Array.from(new Set(values)).sort((left, right) => left.localeCompare(right, "zh-CN"));
}

function layerOrder(layer: string): number {
  const index = LAYER_ORDER.indexOf(layer);
  return index === -1 ? LAYER_ORDER.length : index;
}

function minText(values: string[]): string | null {
  return values.length ? values.reduce((min, value) => (value < min ? value : min), values[0]) : null;
}

function maxText(values: string[]): string | null {
  return values.length ? values.reduce((max, value) => (value > max ? value : max), values[0]) : null;
}

function layerLabel(layer: string): string {
  const labels: Record<string, string> = {
    raw_tushare: "原始层",
    manifest: "辅助清单层",
    derived: "派生层",
    research: "研究层",
  };
  return labels[layer] ?? layer;
}

function layoutLabel(layout: string | null): string {
  const labels: Record<string, string> = {
    current_file: "当前版本单文件",
    manifest_file: "辅助清单文件",
    by_date: "按交易日期分区",
    by_symbol_month: "按月份分桶",
  };
  return layout ? labels[layout] ?? layout : "-";
}

function sourceLabel(source: string): string {
  const labels: Record<string, string> = {
    tushare: "Tushare 口径",
  };
  return labels[source] ?? source;
}

function writePolicyLabel(value: string): string {
  const labels: Record<string, string> = {
    replace_file: "替换当前文件",
    replace_partition: "替换分区",
    append: "追加写入",
    unknown: "未声明",
  };
  return labels[value] ?? value;
}

function updateModeLabel(value: string): string {
  const labels: Record<string, string> = {
    manual_cli: "手动命令",
    scheduled: "定时任务",
    derived_local: "本地计算",
    unknown: "未声明",
  };
  return labels[value] ?? value;
}

function freqLabel(freqs: number[]): string {
  return freqs.length ? freqs.map((freq) => `${freq}min`).join(" / ") : "-";
}

function formatCount(value: number): string {
  return value.toLocaleString("zh-CN");
}
