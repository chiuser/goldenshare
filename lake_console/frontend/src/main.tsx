import { StrictMode, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type RiskItem = {
  severity: string;
  code: string;
  message: string;
  path?: string | null;
};

type LakeStatus = {
  path: {
    lake_root: string;
    exists: boolean;
    readable: boolean;
    writable: boolean;
    initialized: boolean;
    layout_version: number | null;
  };
  disk: {
    total_bytes: number;
    used_bytes: number;
    free_bytes: number;
    usage_percent: number;
  } | null;
  risks: RiskItem[];
};

type LayerSummary = {
  layer: string;
  layer_name: string;
  purpose: string;
  layout: string;
  path: string;
  partition_count: number;
  file_count: number;
  total_bytes: number;
  row_count: number | null;
  freqs: number[];
  earliest_trade_date: string | null;
  latest_trade_date: string | null;
  earliest_trade_month: string | null;
  latest_trade_month: string | null;
  recommended_usage: string;
  risks: RiskItem[];
};

type DatasetSummary = {
  dataset_key: string;
  display_name: string;
  source: string;
  category: string | null;
  group_key: string | null;
  group_label: string | null;
  group_order: number | null;
  description: string | null;
  dataset_role: string;
  storage_root: string | null;
  layers: string[];
  layer_summaries: LayerSummary[];
  freqs: number[];
  supported_freqs: number[];
  raw_freqs: number[];
  derived_freqs: number[];
  partition_count: number;
  file_count: number;
  total_bytes: number;
  row_count: number | null;
  earliest_trade_date: string | null;
  latest_trade_date: string | null;
  earliest_trade_month: string | null;
  latest_trade_month: string | null;
  primary_layout: string | null;
  available_layouts: string[];
  write_policy: string | null;
  update_mode: string | null;
  health_status: "ok" | "warning" | "error" | "empty" | string;
  risks: RiskItem[];
};

type PartitionSummary = {
  dataset_key: string;
  layer: string;
  layout: string;
  freq: number | null;
  trade_date: string | null;
  trade_month: string | null;
  bucket: number | null;
  path: string;
  file_count: number;
  total_bytes: number;
};

function App() {
  const [status, setStatus] = useState<LakeStatus | null>(null);
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [partitions, setPartitions] = useState<PartitionSummary[]>([]);
  const [selectedDatasetKey, setSelectedDatasetKey] = useState<string>("stk_mins");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [statusResponse, datasetResponse] = await Promise.all([
          fetch("/api/lake/status"),
          fetch("/api/datasets"),
        ]);
        if (!statusResponse.ok || !datasetResponse.ok) {
          throw new Error("Lake Console API 请求失败。");
        }
        const statusPayload = (await statusResponse.json()) as LakeStatus;
        const datasetPayload = (await datasetResponse.json()) as { items: DatasetSummary[] };
        if (!cancelled) {
          setStatus(statusPayload);
          setDatasets(datasetPayload.items);
          const preferred = datasetPayload.items.find((dataset) => dataset.dataset_key === selectedDatasetKey);
          if (!preferred && datasetPayload.items[0]) {
            setSelectedDatasetKey(datasetPayload.items[0].dataset_key);
          }
        }
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "未知错误");
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function loadPartitions() {
      if (!selectedDatasetKey) {
        setPartitions([]);
        return;
      }
      try {
        const partitionResponse = await fetch(`/api/partitions?dataset_key=${encodeURIComponent(selectedDatasetKey)}`);
        if (!partitionResponse.ok) {
          throw new Error("分区 API 请求失败。");
        }
        const partitionPayload = (await partitionResponse.json()) as { items: PartitionSummary[] };
        if (!cancelled) {
          setPartitions(partitionPayload.items.slice(0, 24));
        }
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "未知错误");
        }
      }
    }
    void loadPartitions();
    return () => {
      cancelled = true;
    };
  }, [selectedDatasetKey]);

  const groupedDatasets = useMemo(() => groupDatasets(datasets), [datasets]);
  const selectedDataset = datasets.find((dataset) => dataset.dataset_key === selectedDatasetKey) ?? datasets[0] ?? null;
  const readyDatasets = datasets.filter((dataset) => dataset.file_count > 0).length;
  const totalFiles = datasets.reduce((sum, dataset) => sum + dataset.file_count, 0);
  const totalBytes = datasets.reduce((sum, dataset) => sum + dataset.total_bytes, 0);
  const riskCount = datasets.reduce((sum, dataset) => sum + dataset.risks.length, 0) + (status?.risks.length ?? 0);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <span className="sidebar-logo-mark">L</span>
          <span>Lake Console</span>
        </div>
        <div className="sidebar-section-label">本地数据湖</div>
        <a className="sidebar-link active">数据集总览</a>
        <a className="sidebar-link">层级与分区</a>
        <a className="sidebar-link">命令示例</a>
        <a className="sidebar-link">风险</a>
        <div className="sidebar-section-label">边界</div>
        <a className="sidebar-link">不接远程 DB</a>
        <a className="sidebar-link">不进生产部署</a>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <div className="breadcrumb">Goldenshare / Local Lake / Dataset Catalog</div>
            <h1>本地 Tushare Parquet Lake 管理台</h1>
          </div>
          <span className={status?.path.initialized ? "status-badge success" : "status-badge warning"}>
            {status?.path.initialized ? "Lake 已初始化" : "等待初始化"}
          </span>
        </header>

        <section className="content">
          <div className="page-intro">
            <div>
              <h2>数据集文件事实</h2>
              <p>按 Lake Dataset Catalog 展示 raw、manifest、derived、research，不连接远程 goldenshare-db。</p>
            </div>
            <code>{status?.path.lake_root ?? "正在读取 Lake Root..."}</code>
          </div>

          {error ? <div className="alert error">API 加载失败：{error}</div> : null}

          <section className="metric-grid">
            <Metric label="Catalog 数据集" value={String(datasets.length)} hint={`${readyDatasets} 个已有文件落盘`} />
            <Metric label="文件总数" value={String(totalFiles)} hint="所有层级合计 Parquet 文件" />
            <Metric label="数据总量" value={formatBytes(totalBytes)} hint="列表页不默认读取 row count" />
            <Metric label="风险提示" value={String(riskCount)} hint="Lake Root 与数据集风险合计" />
          </section>

          <section className="two-column wide-left">
            <Panel title="数据集目录" description="展示分组参考 Ops 默认目录；代码维护分包不作为用户可见分组。">
              {datasets.length ? (
                <div className="dataset-groups">
                  {groupedDatasets.map((group) => (
                    <DatasetGroup
                      group={group}
                      key={group.groupKey}
                      selectedDatasetKey={selectedDataset?.dataset_key ?? null}
                      onSelect={setSelectedDatasetKey}
                    />
                  ))}
                </div>
              ) : (
                <EmptyState title="暂无 Catalog 数据集" description="请先确认 Lake Dataset Catalog 已加载。" />
              )}
            </Panel>

            <Panel title="选中数据集" description="详情来自后端模型字段，前端不自行拼路径或猜层级用途。">
              {selectedDataset ? <DatasetDetail dataset={selectedDataset} /> : <EmptyState title="未选择数据集" description="请选择左侧数据集。" />}
            </Panel>
          </section>

          <Panel title="层级概览" description="manifest 不隐藏；derived/research 作为数据集子层展示。">
            {selectedDataset ? (
              <div className="layer-grid dynamic">
                {selectedDataset.layer_summaries.map((layer) => (
                  <LayerCard layer={layer} key={`${selectedDataset.dataset_key}-${layer.layer}-${layer.layout}`} />
                ))}
              </div>
            ) : null}
          </Panel>

          <Panel title="最近分区 / 文件" description="这里只展示选中数据集的最近分区；row_count 留到详情或显式刷新。">
            {partitions.length ? (
              <div className="partition-groups">
                {Object.entries(groupPartitionsByLayer(partitions)).map(([layer, items]) => (
                  <div className="partition-group" key={layer}>
                    <div className="partition-group-title">
                      <strong>{layer}</strong>
                      <span>{layerDescription(layer)}</span>
                    </div>
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Layout</th>
                          <th>Freq</th>
                          <th>日期/月</th>
                          <th className="num-cell">文件</th>
                          <th className="num-cell">大小</th>
                        </tr>
                      </thead>
                      <tbody>
                        {items.map((partition) => (
                          <tr key={partition.path}>
                            <td>{partition.layout}</td>
                            <td>{partition.freq ?? "-"}</td>
                            <td>{partition.trade_date ?? partition.trade_month ?? "-"}</td>
                            <td className="num-cell">{partition.file_count}</td>
                            <td className="num-cell">{formatBytes(partition.total_bytes)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState title="暂无分区文件" description="该数据集还没有落盘，或当前层级是未写入状态。" />
            )}
          </Panel>

          <Panel title="命令示例 / 操作提示" description="本页只展示命令，不触发写入；真实写入继续通过 CLI 执行。">
            {selectedDataset ? <CommandHints dataset={selectedDataset} /> : null}
          </Panel>

          {status?.risks.length ? (
            <Panel title="Lake Root 风险" description="这里展示 Lake Root 与 _tmp 等本地文件风险。">
              <div className="risk-list">
                {status.risks.map((risk) => (
                  <div className="alert warning" key={risk.code}>
                    <strong>{risk.code}</strong>
                    <span>{risk.message}</span>
                  </div>
                ))}
              </div>
            </Panel>
          ) : null}
        </section>
      </main>
    </div>
  );
}

function Panel({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return (
    <section className="panel">
      <div className="panel-header">
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
      {children}
    </section>
  );
}

function Metric({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <article className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
      <em>{hint}</em>
    </article>
  );
}

function DatasetGroup({
  group,
  selectedDatasetKey,
  onSelect,
}: {
  group: DatasetGroupView;
  selectedDatasetKey: string | null;
  onSelect: (datasetKey: string) => void;
}) {
  return (
    <section className="dataset-group">
      <div className="dataset-group-header">
        <div>
          <strong>{group.groupLabel}</strong>
          <span>{group.groupKey}</span>
        </div>
        <em>{group.items.length} 个数据集</em>
      </div>
      <div className="dataset-list">
        {group.items.map((dataset) => (
          <DatasetCard
            dataset={dataset}
            isSelected={dataset.dataset_key === selectedDatasetKey}
            key={dataset.dataset_key}
            onSelect={() => onSelect(dataset.dataset_key)}
          />
        ))}
      </div>
    </section>
  );
}

function DatasetCard({ dataset, isSelected, onSelect }: { dataset: DatasetSummary; isSelected: boolean; onSelect: () => void }) {
  return (
    <button className={isSelected ? "dataset-card selected" : "dataset-card"} onClick={onSelect} type="button">
      <div className="dataset-title">
        <div>
          <strong>{dataset.display_name}</strong>
          <span>{dataset.dataset_key}</span>
        </div>
        <HealthBadge status={dataset.health_status} />
      </div>
      <p>{dataset.description ?? "本地 Lake 数据集"}</p>
      <dl>
        <div>
          <dt>层级</dt>
          <dd>{dataset.layers.length}</dd>
        </div>
        <div>
          <dt>文件</dt>
          <dd>{dataset.file_count}</dd>
        </div>
        <div>
          <dt>大小</dt>
          <dd>{formatBytes(dataset.total_bytes)}</dd>
        </div>
        <div>
          <dt>日期</dt>
          <dd>{formatRange(dataset.earliest_trade_date, dataset.latest_trade_date)}</dd>
        </div>
      </dl>
    </button>
  );
}

function DatasetDetail({ dataset }: { dataset: DatasetSummary }) {
  return (
    <div className="dataset-detail">
      <div className="dataset-detail-title">
        <div>
          <strong>{dataset.display_name}</strong>
          <span>{dataset.dataset_key}</span>
        </div>
        <HealthBadge status={dataset.health_status} />
      </div>
      <p>{dataset.description}</p>
      <div className="detail-grid">
        <DetailItem label="展示分组" value={dataset.group_label ?? "-"} />
        <DetailItem label="数据来源" value={dataset.source} />
        <DetailItem label="角色" value={dataset.dataset_role} />
        <DetailItem label="主布局" value={dataset.primary_layout ?? "-"} />
        <DetailItem label="写入策略" value={dataset.write_policy ?? "-"} />
        <DetailItem label="更新方式" value={dataset.update_mode ?? "-"} />
        <DetailItem label="存储根" value={dataset.storage_root ?? "-"} wide />
        <DetailItem label="可用布局" value={dataset.available_layouts.join(", ") || "-"} wide />
        <DetailItem label="频度" value={dataset.supported_freqs.join(", ") || "-"} wide />
      </div>
      {dataset.risks.length ? (
        <div className="risk-list compact">
          {dataset.risks.map((risk) => (
            <div className="alert warning" key={risk.code}>
              <strong>{risk.code}</strong>
              <span>{risk.message}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function DetailItem({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={wide ? "detail-item wide" : "detail-item"}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function LayerCard({ layer }: { layer: LayerSummary }) {
  return (
    <article className="layer-card">
      <div className="layer-card-title">
        <div>
          <strong>{layer.layer_name}</strong>
          <span>{layer.layer}</span>
        </div>
        <span className="tag">{layer.layout}</span>
      </div>
      <p>{layer.purpose}</p>
      <p>{layer.recommended_usage}</p>
      <code>{layer.path}</code>
      <dl>
        <div>
          <dt>分区</dt>
          <dd>{layer.partition_count}</dd>
        </div>
        <div>
          <dt>文件</dt>
          <dd>{layer.file_count}</dd>
        </div>
        <div>
          <dt>大小</dt>
          <dd>{formatBytes(layer.total_bytes)}</dd>
        </div>
        <div>
          <dt>日期</dt>
          <dd>{formatRange(layer.earliest_trade_date, layer.latest_trade_date)}</dd>
        </div>
      </dl>
    </article>
  );
}

function CommandHints({ dataset }: { dataset: DatasetSummary }) {
  const commands = commandExamples(dataset);
  return (
    <div className="command-list">
      {commands.map((command) => (
        <code key={command}>{command}</code>
      ))}
    </div>
  );
}

function HealthBadge({ status }: { status: string }) {
  const label = status === "ok" ? "已落盘" : status === "warning" ? "有风险" : status === "error" ? "异常" : "未落盘";
  return <span className={`health-badge ${status}`}>{label}</span>;
}

function EmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <p>{description}</p>
    </div>
  );
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value)) {
    return "-";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

function formatRange(start: string | null, end: string | null): string {
  if (!start && !end) {
    return "-";
  }
  if (start === end) {
    return start ?? "-";
  }
  return `${start ?? "-"} ~ ${end ?? "-"}`;
}

type DatasetGroupView = {
  groupKey: string;
  groupLabel: string;
  groupOrder: number;
  items: DatasetSummary[];
};

function groupDatasets(datasets: DatasetSummary[]): DatasetGroupView[] {
  const grouped = new Map<string, DatasetGroupView>();
  for (const dataset of datasets) {
    const groupKey = dataset.group_key ?? "unknown";
    const group = grouped.get(groupKey) ?? {
      groupKey,
      groupLabel: dataset.group_label ?? "未分组",
      groupOrder: dataset.group_order ?? 999,
      items: [],
    };
    group.items.push(dataset);
    grouped.set(groupKey, group);
  }
  return [...grouped.values()]
    .map((group) => ({ ...group, items: group.items.sort((a, b) => a.dataset_key.localeCompare(b.dataset_key)) }))
    .sort((a, b) => a.groupOrder - b.groupOrder || a.groupKey.localeCompare(b.groupKey));
}

function groupPartitionsByLayer(partitions: PartitionSummary[]): Record<string, PartitionSummary[]> {
  return partitions.reduce<Record<string, PartitionSummary[]>>((result, partition) => {
    result[partition.layer] = [...(result[partition.layer] ?? []), partition];
    return result;
  }, {});
}

function layerDescription(layer: string): string {
  if (layer === "raw_tushare") {
    return "源站事实层。";
  }
  if (layer === "manifest") {
    return "执行辅助清单层。";
  }
  if (layer === "derived") {
    return "本地派生层。";
  }
  if (layer === "research") {
    return "研究查询优化层。";
  }
  return "本地文件层。";
}

function commandExamples(dataset: DatasetSummary): string[] {
  if (dataset.dataset_key === "stock_basic") {
    return ["lake-console sync-stock-basic"];
  }
  if (dataset.dataset_key === "trade_cal") {
    return ["lake-console sync-trade-cal --start-date 2020-01-01 --end-date 2026-12-31"];
  }
  if (dataset.dataset_key === "stk_mins") {
    return [
      "lake-console sync-stk-mins --ts-code 600000.SH --freq 30 --trade-date 2026-04-24",
      "lake-console sync-stk-mins-range --all-market --freqs 1,5,15,30,60 --start-date 2026-04-01 --end-date 2026-04-30",
      "lake-console rebuild-stk-mins-derived --freq 90 --trade-date 2026-04-24",
      "lake-console rebuild-stk-mins-research --freq 30 --trade-month 2026-04",
    ];
  }
  return [
    `lake-console plan-sync ${dataset.dataset_key} --help`,
    `lake-console sync-dataset ${dataset.dataset_key} --help`,
  ];
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
