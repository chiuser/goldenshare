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
  latest_modified_at: string | null;
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
  latest_modified_at: string | null;
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

type CommandExample = {
  example_key: string;
  title: string;
  scenario: string;
  description: string;
  command: string;
  argv: string[];
  prerequisites: string[];
  notes: string[];
};

type CommandExampleItem = {
  item_key: string;
  item_type: "dataset" | "command_set" | string;
  display_name: string;
  description: string | null;
  examples: CommandExample[];
};

type CommandExampleGroup = {
  group_key: string;
  group_label: string;
  group_order: number;
  items: CommandExampleItem[];
};

type ActivePage = "datasets" | "datasetDetail" | "commands" | "risks";

function App() {
  const [status, setStatus] = useState<LakeStatus | null>(null);
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [partitions, setPartitions] = useState<PartitionSummary[]>([]);
  const [commandGroups, setCommandGroups] = useState<CommandExampleGroup[]>([]);
  const [selectedDatasetKey, setSelectedDatasetKey] = useState<string>("stk_mins");
  const [activePage, setActivePage] = useState<ActivePage>("datasets");
  const [selectedCommandGroupKey, setSelectedCommandGroupKey] = useState<string>("");
  const [selectedCommandItemKey, setSelectedCommandItemKey] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [commandError, setCommandError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [statusResponse, datasetResponse] = await Promise.all([
          fetch("/api/lake/status"),
          fetch("/api/datasets"),
        ]);
        if (!statusResponse.ok || !datasetResponse.ok) {
          throw new Error("数据湖控制台 API 请求失败。");
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
    async function loadCommandExamples() {
      try {
        const response = await fetch("/api/lake/command-examples");
        if (!response.ok) {
          throw new Error("命令示例 API 请求失败。");
        }
        const payload = (await response.json()) as { groups: CommandExampleGroup[] };
        if (!cancelled) {
          const groups = payload.groups;
          const firstGroup = groups[0] ?? null;
          setCommandGroups(groups);
          setSelectedCommandGroupKey((current) => (groups.some((group) => group.group_key === current) ? current : firstGroup?.group_key ?? ""));
          setSelectedCommandItemKey((current) => {
            const allItems = groups.flatMap((group) => group.items);
            if (allItems.some((item) => item.item_key === current)) {
              return current;
            }
            return allItems.find((item) => item.item_key === selectedDatasetKey)?.item_key ?? firstGroup?.items[0]?.item_key ?? "";
          });
        }
      } catch (caught) {
        if (!cancelled) {
          setCommandError(caught instanceof Error ? caught.message : "未知错误");
        }
      }
    }
    void loadCommandExamples();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const matchedGroup = commandGroups.find((group) => group.items.some((item) => item.item_key === selectedDatasetKey));
    if (!matchedGroup) {
      return;
    }
    setSelectedCommandGroupKey(matchedGroup.group_key);
    setSelectedCommandItemKey(selectedDatasetKey);
  }, [commandGroups, selectedDatasetKey]);

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
  const allDatasetRisks = datasets.flatMap((dataset) =>
    dataset.risks.map((risk) => ({ ...risk, datasetKey: dataset.dataset_key, datasetName: dataset.display_name })),
  );

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-brand">
          <LogoMark />
          <div>
            <strong>数据湖控制台</strong>
            <span>本地 Tushare Parquet 数据湖</span>
          </div>
        </div>
        <span className={status?.path.initialized ? "status-badge success" : "status-badge warning"}>
          {status?.path.initialized ? "数据湖已初始化" : "等待初始化"}
        </span>
      </header>

      <div className="app-body">
        <aside className="sidebar">
          <div className="sidebar-section-label">本地数据湖</div>
          <button className={activePage === "datasets" || activePage === "datasetDetail" ? "sidebar-link active" : "sidebar-link"} onClick={() => setActivePage("datasets")} type="button">
            数据集总览
          </button>
          <button className={activePage === "commands" ? "sidebar-link active" : "sidebar-link"} onClick={() => setActivePage("commands")} type="button">
            命令示例
          </button>
          <button className={activePage === "risks" ? "sidebar-link active" : "sidebar-link"} onClick={() => setActivePage("risks")} type="button">
            风险
          </button>
          <div className="sidebar-section-label">边界</div>
          <span className="sidebar-link static">不接远程 DB</span>
          <span className="sidebar-link static">不进生产部署</span>
        </aside>

        <main className="main">
          <section className="content">
          {error ? <div className="alert error">API 加载失败：{error}</div> : null}

          {activePage === "datasets" ? (
            <DatasetOverviewPage
              datasets={datasets}
              groupedDatasets={groupedDatasets}
              readyDatasets={readyDatasets}
              riskCount={riskCount}
              status={status}
              totalBytes={totalBytes}
              totalFiles={totalFiles}
              onOpenDetail={(datasetKey) => {
                setSelectedDatasetKey(datasetKey);
                setActivePage("datasetDetail");
              }}
            />
          ) : null}

          {activePage === "datasetDetail" ? (
            selectedDataset ? (
              <DatasetDetailPage
                dataset={selectedDataset}
                partitions={partitions}
                onBack={() => setActivePage("datasets")}
              />
            ) : (
              <EmptyState title="未选择数据集" description="请先返回数据集总览选择数据集。" />
            )
          ) : null}

          {activePage === "commands" ? (
            <CommandExamplesPage
              commandError={commandError}
              commandGroups={commandGroups}
              selectedCommandGroupKey={selectedCommandGroupKey}
              selectedCommandItemKey={selectedCommandItemKey}
              onSelectGroup={(groupKey) => {
                setSelectedCommandGroupKey(groupKey);
                const group = commandGroups.find((item) => item.group_key === groupKey);
                setSelectedCommandItemKey(group?.items[0]?.item_key ?? "");
              }}
              onSelectItem={setSelectedCommandItemKey}
            />
          ) : null}

          {activePage === "risks" ? (
            <RiskPage datasetRisks={allDatasetRisks} status={status} />
          ) : null}
          </section>
        </main>
      </div>
    </div>
  );
}

function LogoMark() {
  const [logoAvailable, setLogoAvailable] = useState(true);
  if (logoAvailable) {
    return (
      <span className="logo-mark">
        <img alt="数据湖控制台" onError={() => setLogoAvailable(false)} src="/lake-console-logo.png" />
      </span>
    );
  }
  return <span className="logo-mark fallback">湖</span>;
}

function DatasetOverviewPage({
  datasets,
  groupedDatasets,
  readyDatasets,
  riskCount,
  status,
  totalBytes,
  totalFiles,
  onOpenDetail,
}: {
  datasets: DatasetSummary[];
  groupedDatasets: DatasetGroupView[];
  readyDatasets: number;
  riskCount: number;
  status: LakeStatus | null;
  totalBytes: number;
  totalFiles: number;
  onOpenDetail: (datasetKey: string) => void;
}) {
  return (
    <>
      <div className="page-intro">
        <div>
          <h2>
            数据集文件概览
            <span
              className="help-mark"
              title="按 Lake Dataset Catalog 展示 raw、manifest、derived、research，不连接远程 goldenshare-db。"
              aria-label="页面说明"
            >
              ?
            </span>
          </h2>
        </div>
        <code>{status?.path.lake_root ?? "正在读取数据湖根目录..."}</code>
      </div>

      <section className="metric-grid">
        <Metric label="数据集数量" value={String(datasets.length)} hint={`${readyDatasets} 个已有文件落盘`} />
        <Metric label="文件总数" value={String(totalFiles)} hint="所有层级合计 Parquet 文件" />
        <Metric label="数据总量" value={formatBytes(totalBytes)} hint="按本地文件大小汇总" />
        <Metric label="风险提示" value={String(riskCount)} hint="数据湖根目录与数据集风险合计" />
      </section>

      <Panel title="数据集目录">
        {datasets.length ? (
          <div className="dataset-groups">
            {groupedDatasets.map((group) => (
              <DatasetGroup
                group={group}
                key={group.groupKey}
                onOpenDetail={onOpenDetail}
              />
            ))}
          </div>
        ) : (
          <EmptyState title="暂无数据集" description="请先确认本地数据集目录已加载。" />
        )}
      </Panel>
    </>
  );
}

function DatasetDetailPage({
  dataset,
  partitions,
  onBack,
}: {
  dataset: DatasetSummary;
  partitions: PartitionSummary[];
  onBack: () => void;
}) {
  const latestPartition = latestPartitionLabel(dataset);
  const earliestPartition = earliestPartitionLabel(dataset);
  const averageFileSize = dataset.file_count > 0 ? Math.round(dataset.total_bytes / dataset.file_count) : 0;
  const layerRisks = dataset.layer_summaries.flatMap((layer) => layer.risks);
  const riskTotal = dataset.risks.length + layerRisks.length;
  const latestFile = partitions[0] ?? null;

  return (
    <div className="detail-page">
      <button className="back-button" onClick={onBack} type="button">
        ← 返回数据集总览
      </button>

      <section className="detail-hero">
        <div>
          <div className="detail-hero-title">
            <h2>{dataset.display_name}</h2>
            <HealthBadge status={dataset.health_status} />
          </div>
          <code>{dataset.dataset_key}</code>
          <p>{dataset.description ?? "本地数据湖数据集。"}</p>
        </div>
      </section>

      <section className="detail-section">
        <h3>核心概览</h3>
        <div className="metric-grid detail-metrics">
          <Metric label="文件数" value={String(dataset.file_count)} hint="全部层级合计" />
          <Metric label="总大小" value={formatBytes(dataset.total_bytes)} hint="按本地文件大小汇总" />
          <Metric label="层级数" value={String(dataset.layers.length)} hint={dataset.layers.join(", ") || "-"} />
          <Metric label="分区数" value={String(dataset.partition_count)} hint="全部层级合计" />
          <Metric label="行数" value={formatRowCount(dataset.row_count)} hint="详情页字段，未计算时不展示估值" />
          <Metric label="日期范围" value={formatDateOrMonthRange(dataset)} hint="按文件分区事实汇总" />
          <Metric label="最近更新" value={formatDateTime(dataset.latest_modified_at)} hint="本地文件修改时间" />
          <Metric label="风险" value={riskTotal ? String(riskTotal) : "无"} hint="数据集与层级风险合计" />
        </div>
      </section>

      <section className="detail-section">
        <h3>基础信息</h3>
        <div className="detail-grid">
          <DetailItem label="数据源" value={dataset.source} />
          <DetailItem label="数据集 key" value={dataset.dataset_key} />
          <DetailItem label="分组" value={dataset.group_label ?? "-"} />
          <DetailItem label="角色" value={dataset.dataset_role} />
          <DetailItem label="存储根" value={dataset.storage_root ?? "-"} wide />
          <DetailItem label="主布局" value={dataset.primary_layout ?? "-"} />
          <DetailItem label="写入策略" value={dataset.write_policy ?? "-"} />
          <DetailItem label="更新方式" value={dataset.update_mode ?? "-"} />
          <DetailItem label="可用布局" value={dataset.available_layouts.join(", ") || "-"} wide />
          <DetailItem label="支持频度" value={dataset.supported_freqs.join(", ") || "-"} wide />
        </div>
      </section>

      <section className="detail-section">
        <h3>数据层级</h3>
        <div className="layer-stack">
          {dataset.layer_summaries.map((layer) => (
            <LayerRow layer={layer} key={`${dataset.dataset_key}-${layer.layer}-${layer.layout}`} />
          ))}
        </div>
      </section>

      <section className="detail-section">
        <h3>分区概况</h3>
        <div className="partition-summary-grid">
          <DetailItem label="最新分区" value={latestPartition} />
          <DetailItem label="最早分区" value={earliestPartition} />
          <DetailItem label="分区数量" value={String(dataset.partition_count)} />
          <DetailItem label="平均文件大小" value={dataset.file_count ? formatBytes(averageFileSize) : "-"} />
          <DetailItem label="最近文件样本" value={latestFile?.path ?? "暂无文件"} wide />
          <DetailItem label="风险提示" value={riskTotal ? `${riskTotal} 项风险` : "无"} wide />
        </div>
      </section>
    </div>
  );
}

function CommandExamplesPage({
  commandError,
  commandGroups,
  selectedCommandGroupKey,
  selectedCommandItemKey,
  onSelectGroup,
  onSelectItem,
}: {
  commandError: string | null;
  commandGroups: CommandExampleGroup[];
  selectedCommandGroupKey: string;
  selectedCommandItemKey: string;
  onSelectGroup: (groupKey: string) => void;
  onSelectItem: (itemKey: string) => void;
}) {
  return (
    <>
      <div className="page-intro">
        <div>
          <h2>命令示例 / 操作提示</h2>
          <p>本页只展示命令，不触发写入；真实写入继续通过 CLI 执行。</p>
        </div>
      </div>
      <Panel title="命令示例" description="命令来自后端 Lake catalog，前端不自行拼接。">
        <CommandExamplesPanel
          error={commandError}
          groups={commandGroups}
          selectedGroupKey={selectedCommandGroupKey}
          selectedItemKey={selectedCommandItemKey}
          onSelectGroup={onSelectGroup}
          onSelectItem={onSelectItem}
        />
      </Panel>
    </>
  );
}

function RiskPage({
  datasetRisks,
  status,
}: {
  datasetRisks: Array<RiskItem & { datasetKey: string; datasetName: string }>;
  status: LakeStatus | null;
}) {
  return (
    <>
      <div className="page-intro">
        <div>
          <h2>风险</h2>
          <p>只展示数据湖根目录与数据集文件风险，不接入生产 Ops 状态。</p>
        </div>
      </div>

      <section className="two-column">
        <Panel title="数据湖根目录风险" description="移动盘路径、初始化状态、读写权限等本地风险。">
          {status?.risks.length ? (
            <div className="risk-list">
              {status.risks.map((risk) => (
                <RiskCard risk={risk} key={`${risk.code}-${risk.path ?? ""}`} />
              ))}
            </div>
          ) : (
            <EmptyState title="暂无数据湖根目录风险" description="当前未发现路径或权限风险。" />
          )}
        </Panel>

        <Panel title="数据集风险" description="来自本地文件扫描和 Lake Dataset Catalog 的风险。">
          {datasetRisks.length ? (
            <div className="risk-list">
              {datasetRisks.map((risk) => (
                <RiskCard
                  context={`${risk.datasetName} / ${risk.datasetKey}`}
                  risk={risk}
                  key={`${risk.datasetKey}-${risk.code}-${risk.path ?? ""}`}
                />
              ))}
            </div>
          ) : (
            <EmptyState title="暂无数据集风险" description="当前数据集没有暴露文件风险。" />
          )}
        </Panel>
      </section>
    </>
  );
}

function RiskCard({ risk, context }: { risk: RiskItem; context?: string }) {
  return (
    <div className="alert warning">
      <div>
        <strong>{risk.code}</strong>
        {context ? <em>{context}</em> : null}
        <span>{risk.message}</span>
        {risk.path ? <code>{risk.path}</code> : null}
      </div>
    </div>
  );
}

function Panel({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <section className="panel">
      <div className="panel-header">
        <h2>{title}</h2>
        {description ? <p>{description}</p> : null}
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
  onOpenDetail,
}: {
  group: DatasetGroupView;
  onOpenDetail: (datasetKey: string) => void;
}) {
  return (
    <section className="dataset-group">
      <div className="dataset-group-header">
        <div>
          <strong>{group.groupLabel}</strong>
        </div>
        <em>{group.items.length} 个数据集</em>
      </div>
      <div className="dataset-list">
        {group.items.map((dataset) => (
          <DatasetCard
            dataset={dataset}
            key={dataset.dataset_key}
            onOpenDetail={() => onOpenDetail(dataset.dataset_key)}
          />
        ))}
      </div>
    </section>
  );
}

function DatasetCard({ dataset, onOpenDetail }: { dataset: DatasetSummary; onOpenDetail: () => void }) {
  return (
    <article className="dataset-card">
      <div className="dataset-title">
        <div>
          <strong>{dataset.display_name}</strong>
          <span>{dataset.dataset_key}</span>
        </div>
        <HealthBadge status={dataset.health_status} />
      </div>
      <p>{dataset.description ?? "本地数据湖数据集"}</p>
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
          <dd>{formatDateOrMonthRange(dataset)}</dd>
        </div>
      </dl>
      <div className="dataset-card-actions">
        <button onClick={onOpenDetail} type="button">查看详情</button>
      </div>
    </article>
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

function LayerRow({ layer }: { layer: LayerSummary }) {
  return (
    <article className="layer-row">
      <div className="layer-row-main">
        <div>
          <strong>{layerDisplayName(layer)}</strong>
          <span>{layer.layer}</span>
        </div>
        <span className="tag">{layer.layout}</span>
      </div>
      <p>{humanizeLayerPurpose(layer)}</p>
      <p>{humanizeLayerUsage(layer)}</p>
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
          <dt>行数</dt>
          <dd>{formatRowCount(layer.row_count)}</dd>
        </div>
        <div>
          <dt>日期/月</dt>
          <dd>{formatLayerDateOrMonthRange(layer)}</dd>
        </div>
        <div>
          <dt>最近更新</dt>
          <dd>{formatDateTime(layer.latest_modified_at)}</dd>
        </div>
      </dl>
    </article>
  );
}

function CommandExamplesPanel({
  groups,
  selectedGroupKey,
  selectedItemKey,
  error,
  onSelectGroup,
  onSelectItem,
}: {
  groups: CommandExampleGroup[];
  selectedGroupKey: string;
  selectedItemKey: string;
  error: string | null;
  onSelectGroup: (groupKey: string) => void;
  onSelectItem: (itemKey: string) => void;
}) {
  if (error) {
    return <div className="alert error">命令示例加载失败：{error}</div>;
  }
  if (!groups.length) {
    return <EmptyState title="正在加载命令示例" description="命令来自后端 Lake catalog，前端不会自行拼接。" />;
  }

  const selectedGroup = groups.find((group) => group.group_key === selectedGroupKey) ?? groups[0];
  const selectedItem = selectedGroup.items.find((item) => item.item_key === selectedItemKey) ?? selectedGroup.items[0] ?? null;

  return (
    <div className="command-examples">
      <div className="command-notice">
        <strong>只读提示</strong>
        <span>本页只展示命令，不会执行写入。请在本地终端确认参数后执行。</span>
      </div>
      <div className="command-toolbar">
        <label>
          <span>展示分组</span>
          <select value={selectedGroup.group_key} onChange={(event) => onSelectGroup(event.target.value)}>
            {groups.map((group) => (
              <option key={group.group_key} value={group.group_key}>
                {group.group_label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>数据集 / 命令集合</span>
          <select value={selectedItem?.item_key ?? ""} onChange={(event) => onSelectItem(event.target.value)}>
            {selectedGroup.items.map((item) => (
              <option key={item.item_key} value={item.item_key}>
                {item.display_name}
              </option>
            ))}
          </select>
        </label>
      </div>
      {selectedItem ? <CommandExampleItemDetail item={selectedItem} /> : <EmptyState title="暂无命令示例" description="当前分组没有可展示命令。" />}
    </div>
  );
}

function CommandExampleItemDetail({ item }: { item: CommandExampleItem }) {
  return (
    <div className="command-item-detail">
      <div className="command-item-title">
        <div>
          <strong>{item.display_name}</strong>
          <span>{item.item_key}</span>
        </div>
        <span className="tag">{item.item_type === "dataset" ? "数据集" : "命令集合"}</span>
      </div>
      {item.description ? <p>{item.description}</p> : null}
      <div className="command-card-list">
        {item.examples.map((example) => (
          <CommandExampleCard example={example} key={example.example_key} />
        ))}
      </div>
    </div>
  );
}

function CommandExampleCard({ example }: { example: CommandExample }) {
  const [copied, setCopied] = useState(false);

  async function copyCommand() {
    try {
      await navigator.clipboard.writeText(example.command);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }

  return (
    <article className="command-card">
      <div className="command-card-header">
        <div>
          <strong>{example.title}</strong>
          <span>{example.description}</span>
        </div>
        <span className="tag">{scenarioLabel(example.scenario)}</span>
      </div>
      <div className="command-code-row">
        <code>{example.command}</code>
        <button type="button" onClick={copyCommand}>
          {copied ? "已复制" : "复制"}
        </button>
      </div>
      {example.prerequisites.length || example.notes.length ? (
        <div className="command-meta">
          {example.prerequisites.length ? <span>前置：{example.prerequisites.join("；")}</span> : null}
          {example.notes.length ? <span>备注：{example.notes.join("；")}</span> : null}
        </div>
      ) : null}
    </article>
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

function formatDateOrMonthRange(dataset: DatasetSummary): string {
  const dateRange = formatRange(dataset.earliest_trade_date, dataset.latest_trade_date);
  if (dateRange !== "-") {
    return dateRange;
  }
  return formatRange(dataset.earliest_trade_month, dataset.latest_trade_month);
}

function formatLayerDateOrMonthRange(layer: LayerSummary): string {
  const dateRange = formatRange(layer.earliest_trade_date, layer.latest_trade_date);
  if (dateRange !== "-") {
    return dateRange;
  }
  return formatRange(layer.earliest_trade_month, layer.latest_trade_month);
}

function latestPartitionLabel(dataset: DatasetSummary): string {
  return dataset.latest_trade_date ?? dataset.latest_trade_month ?? "-";
}

function earliestPartitionLabel(dataset: DatasetSummary): string {
  return dataset.earliest_trade_date ?? dataset.earliest_trade_month ?? "-";
}

function formatRowCount(value: number | null): string {
  return value === null ? "未计算" : value.toLocaleString("zh-CN");
}

function formatDateTime(value: string | null): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN", { hour12: false });
}

function layerDisplayName(layer: LayerSummary): string {
  const labels: Record<string, string> = {
    raw_tushare: "原始数据",
    manifest: "同步用清单",
    derived: "本地计算结果",
    research: "查询优化数据",
  };
  return labels[layer.layer] ?? layer.layer_name;
}

function humanizeLayerPurpose(layer: LayerSummary): string {
  const descriptions: Record<string, string> = {
    raw_tushare: "从 Tushare 拉取后直接保存的数据。",
    manifest: "给同步任务使用的本地清单，例如股票池、指数池或交易日历。",
    derived: "由本地已有数据计算出来的结果。",
    research: "为了让本地研究和回测查询更快而重新整理的数据。",
  };
  return descriptions[layer.layer] ?? cleanTechnicalCopy(layer.purpose);
}

function humanizeLayerUsage(layer: LayerSummary): string {
  if (layer.layer === "raw_tushare") {
    return "适合查看原始落盘范围，也可以作为后续计算的数据来源。";
  }
  if (layer.layer === "manifest") {
    return "适合确认同步任务会使用哪些标的、日期或基础清单。";
  }
  if (layer.layer === "derived") {
    return "适合查看本地派生周期或计算结果是否已经生成。";
  }
  if (layer.layer === "research") {
    return "适合单标的长周期查询、回测和相似性分析。";
  }
  return cleanTechnicalCopy(layer.recommended_usage);
}

function cleanTechnicalCopy(value: string): string {
  return value
    .replaceAll("源站事实层", "原始数据")
    .replaceAll("源站事实", "原始数据")
    .replaceAll("执行辅助清单层", "同步用清单")
    .replaceAll("本地派生层", "本地计算结果")
    .replaceAll("研究查询优化层", "查询优化数据")
    .replaceAll("原始落盘层", "直接保存的数据");
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

function scenarioLabel(scenario: string): string {
  const labels: Record<string, string> = {
    init: "初始化",
    status: "状态",
    plan: "预览",
    sync_point: "单点同步",
    sync_range: "区间同步",
    sync_snapshot: "快照刷新",
    derive: "派生",
    research: "Research",
    maintenance: "维护",
    diagnostic: "诊断",
  };
  return labels[scenario] ?? scenario;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
