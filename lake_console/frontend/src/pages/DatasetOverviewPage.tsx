import { useMemo } from "react";
import { DatasetGroup } from "../components/DatasetGroup";
import { EmptyState } from "../components/EmptyState";
import { Metric } from "../components/Metric";
import { PageHeader } from "../components/PageHeader";
import { Panel } from "../components/Panel";
import type { DatasetSummary, LakeStatus } from "../types";
import { formatBytes } from "../utils/format";
import { groupDatasets } from "../utils/datasetGrouping";

type DatasetOverviewPageProps = {
  datasets: DatasetSummary[];
  readyDatasets: number;
  riskCount: number;
  status: LakeStatus | null;
  totalBytes: number;
  totalFiles: number;
  onOpenDetail: (datasetKey: string) => void;
};

export function DatasetOverviewPage({
  datasets,
  readyDatasets,
  riskCount,
  status,
  totalBytes,
  totalFiles,
  onOpenDetail,
}: DatasetOverviewPageProps) {
  const groupedDatasets = useMemo(() => groupDatasets(datasets), [datasets]);

  return (
    <>
      <PageHeader
        eyebrow="Dataset catalog"
        title="数据集文件概览"
        description="查看本地 Parquet 文件的覆盖范围、文件体量、落盘层级和风险提示。"
        helpTitle="按 Lake Dataset Catalog 展示 raw、manifest、derived、research，不连接远程 goldenshare-db。"
        right={<code>{status?.path.lake_root ?? "正在读取数据湖根目录..."}</code>}
      />

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
              <DatasetGroup group={group} key={group.groupKey} onOpenDetail={onOpenDetail} />
            ))}
          </div>
        ) : (
          <EmptyState
            title={status ? "暂无数据集" : "正在读取数据湖文件事实"}
            description={status ? "请先确认本地数据集目录已加载。" : "正在从本地 Lake Console API 获取数据集目录。"}
          />
        )}
      </Panel>
    </>
  );
}
