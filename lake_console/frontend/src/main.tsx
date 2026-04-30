import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

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
  risks: Array<{ severity: string; code: string; message: string; path?: string | null }>;
};

type DatasetSummary = {
  dataset_key: string;
  display_name: string;
  layers: string[];
  freqs: number[];
  partition_count: number;
  file_count: number;
  total_bytes: number;
  earliest_trade_date: string | null;
  latest_trade_date: string | null;
  risks: Array<{ severity: string; code: string; message: string }>;
};

type PartitionSummary = {
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
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [statusResponse, datasetResponse, partitionResponse] = await Promise.all([
          fetch("/api/lake/status"),
          fetch("/api/datasets"),
          fetch("/api/partitions?dataset_key=stk_mins"),
        ]);
        if (!statusResponse.ok || !datasetResponse.ok || !partitionResponse.ok) {
          throw new Error("Lake Console API 请求失败。");
        }
        const statusPayload = (await statusResponse.json()) as LakeStatus;
        const datasetPayload = (await datasetResponse.json()) as { items: DatasetSummary[] };
        const partitionPayload = (await partitionResponse.json()) as { items: PartitionSummary[] };
        if (!cancelled) {
          setStatus(statusPayload);
          setDatasets(datasetPayload.items);
          setPartitions(partitionPayload.items.slice(0, 16));
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

  const stkMins = datasets.find((dataset) => dataset.dataset_key === "stk_mins");
  const stockBasic = datasets.find((dataset) => dataset.dataset_key === "stock_basic");
  const layerSummaries = buildLayerSummaries(partitions);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <span className="sidebar-logo-mark">L</span>
          <span>Lake Console</span>
        </div>
        <div className="sidebar-section-label">本地数据湖</div>
        <a className="sidebar-link active">总览</a>
        <a className="sidebar-link">数据集</a>
        <a className="sidebar-link">分区</a>
        <a className="sidebar-link">风险</a>
        <div className="sidebar-section-label">边界</div>
        <a className="sidebar-link">不接远程 DB</a>
        <a className="sidebar-link">不进生产部署</a>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <div className="breadcrumb">Goldenshare / Local Lake</div>
            <h1>本地 Tushare Parquet Lake 管理台</h1>
          </div>
          <span className={status?.path.initialized ? "status-badge success" : "status-badge warning"}>
            {status?.path.initialized ? "Lake 已初始化" : "等待初始化"}
          </span>
        </header>

        <section className="content">
          <div className="page-intro">
            <div>
              <h2>文件事实总览</h2>
              <p>只读取移动盘上的 Parquet 与 manifest，不连接远程 goldenshare-db，不依赖生产 Ops 状态。</p>
            </div>
            <code>{status?.path.lake_root ?? "正在读取 Lake Root..."}</code>
          </div>

          {error ? <div className="alert error">API 加载失败：{error}</div> : null}

          <section className="metric-grid">
            <Metric label="磁盘剩余" value={status?.disk ? formatBytes(status.disk.free_bytes) : "-"} hint="移动盘可用空间" />
            <Metric label="空间使用率" value={status?.disk ? `${status.disk.usage_percent}%` : "-"} hint="来自 Lake Root 所在卷" />
            <Metric label="数据集数量" value={String(datasets.length)} hint="基于文件事实扫描" />
            <Metric label="分区数量" value={String(partitions.length)} hint="当前展示 stk_mins 最近分区" />
          </section>

          <section className="two-column">
            <Panel title="数据集清单" description="正式数据集与本地执行股票池分离展示，避免把 manifest 当研究表使用。">
              {datasets.length ? (
                <div className="dataset-list">
                  {datasets.map((dataset) => (
                    <DatasetCard dataset={dataset} key={dataset.dataset_key} />
                  ))}
                </div>
              ) : (
                <EmptyState title="暂无正式数据集" description="先执行 lake-console sync-stock-basic，再执行 stk_mins 小样本或全市场同步。" />
              )}
            </Panel>

            <Panel title="当前能力" description="第一阶段能力保持本地独立，不进入生产链路。">
              <div className="capability-list">
                <Capability name="stock_basic" status={stockBasic ? "ready" : "pending"} text="正式维表 + 执行股票池双落盘" />
                <Capability name="stk_mins 单股票单日" status={stkMins ? "ready" : "pending"} text="写入 raw_tushare/stk_mins_by_date" />
                <Capability name="stk_mins 全市场" status="ready" text="读取本地股票池，按 freq / trade_date 扇出" />
                <Capability name="_tmp 清理" status="ready" text="clean-tmp dry-run 与按年龄清理" />
              </div>
            </Panel>
          </section>

          <Panel title="Lake 分层概览" description="三层数据服务不同查询场景，页面按文件事实展示当前覆盖情况。">
            <div className="layer-grid">
              <LayerCard
                name="Raw 原始层"
                layer="raw_tushare"
                source="Tushare API 原始落盘"
                usage="适合单日全市场排名、横截面统计、作为派生计算来源。"
                summary={layerSummaries.raw_tushare}
              />
              <LayerCard
                name="Derived 派生层"
                layer="derived"
                source="由 raw 本地计算生成"
                usage="适合 90/120 分钟线等本地派生周期。"
                summary={layerSummaries.derived}
              />
              <LayerCard
                name="Research 研究层"
                layer="research"
                source="由 raw / derived 重排生成"
                usage="适合单股多年回测、少数股票多月相似性分析。"
                summary={layerSummaries.research}
              />
            </div>
          </Panel>

          <Panel title="最近 stk_mins 分区" description="按 layer 分组展示本地文件事实，避免混用原始层、派生层和研究层。">
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
              <EmptyState title="暂无分钟线分区" description="执行 sync-stk-mins 后，这里会展示 by_date 分区。" />
            )}
          </Panel>

          {status?.risks.length ? (
            <Panel title="风险提示" description="这里展示 Lake Root 与 _tmp 等本地文件风险。">
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

function DatasetCard({ dataset }: { dataset: DatasetSummary }) {
  return (
    <article className="dataset-card">
      <div className="dataset-title">
        <div>
          <strong>{dataset.display_name}</strong>
          <span>{dataset.dataset_key}</span>
        </div>
        <span className="tag">{dataset.layers.join(", ")}</span>
      </div>
      <dl>
        <div>
          <dt>分区</dt>
          <dd>{dataset.partition_count}</dd>
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
          <dd>
            {dataset.earliest_trade_date ?? "-"} ~ {dataset.latest_trade_date ?? "-"}
          </dd>
        </div>
      </dl>
    </article>
  );
}

function LayerCard({
  name,
  layer,
  source,
  usage,
  summary,
}: {
  name: string;
  layer: string;
  source: string;
  usage: string;
  summary: LayerSummary;
}) {
  return (
    <article className="layer-card">
      <div className="layer-card-title">
        <strong>{name}</strong>
        <span>{layer}</span>
      </div>
      <p>{source}</p>
      <p>{usage}</p>
      <dl>
        <div>
          <dt>分区</dt>
          <dd>{summary.partitionCount}</dd>
        </div>
        <div>
          <dt>文件</dt>
          <dd>{summary.fileCount}</dd>
        </div>
        <div>
          <dt>大小</dt>
          <dd>{formatBytes(summary.totalBytes)}</dd>
        </div>
      </dl>
    </article>
  );
}

function Capability({ name, status, text }: { name: string; status: "ready" | "pending"; text: string }) {
  return (
    <div className="capability-row">
      <span className={status === "ready" ? "dot success" : "dot muted"} />
      <div>
        <strong>{name}</strong>
        <p>{text}</p>
      </div>
    </div>
  );
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

type LayerSummary = {
  partitionCount: number;
  fileCount: number;
  totalBytes: number;
};

function buildLayerSummaries(partitions: PartitionSummary[]): Record<string, LayerSummary> {
  const result: Record<string, LayerSummary> = {
    raw_tushare: { partitionCount: 0, fileCount: 0, totalBytes: 0 },
    derived: { partitionCount: 0, fileCount: 0, totalBytes: 0 },
    research: { partitionCount: 0, fileCount: 0, totalBytes: 0 },
  };
  for (const partition of partitions) {
    const summary = result[partition.layer] ?? { partitionCount: 0, fileCount: 0, totalBytes: 0 };
    summary.partitionCount += 1;
    summary.fileCount += partition.file_count;
    summary.totalBytes += partition.total_bytes;
    result[partition.layer] = summary;
  }
  return result;
}

function groupPartitionsByLayer(partitions: PartitionSummary[]): Record<string, PartitionSummary[]> {
  return partitions.reduce<Record<string, PartitionSummary[]>>((result, partition) => {
    result[partition.layer] = [...(result[partition.layer] ?? []), partition];
    return result;
  }, {});
}

function layerDescription(layer: string): string {
  if (layer === "raw_tushare") {
    return "原始接口落盘，适合单日全市场横截面。";
  }
  if (layer === "derived") {
    return "本地派生周期，适合 90/120 分钟线。";
  }
  if (layer === "research") {
    return "研究重排，适合单股长周期查询。";
  }
  return "本地文件层。";
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
