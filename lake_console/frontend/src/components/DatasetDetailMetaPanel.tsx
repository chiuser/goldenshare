import type { ReactNode } from "react";
import type { DatasetSummary } from "../types";
import { buildDatasetDetailViewModel } from "../utils/datasetDetailViewModel";
import { DetailItem } from "./DetailItem";
import { SectionCard } from "./SectionCard";

type DatasetDetailMetaPanelProps = {
  dataset: DatasetSummary;
  detailView: ReturnType<typeof buildDatasetDetailViewModel>;
};

export function DatasetDetailMetaPanel({ dataset, detailView }: DatasetDetailMetaPanelProps) {
  return (
    <SectionCard
      className="detail-meta-section"
      description="展示这个数据集在本地数据湖中的身份、写入策略和分区概况。"
      title="数据集画像"
    >
      <div className="detail-meta-stack">
        <DetailGroup title="身份">
          <div className="detail-grid">
            <DetailItem label="数据源" value={dataset.source} />
            <DetailItem label="数据集 key" value={dataset.dataset_key} />
            <DetailItem label="分组" value={dataset.group_label ?? "-"} />
            <DetailItem label="角色" value={dataset.dataset_role} />
          </div>
        </DetailGroup>

        <DetailGroup title="存储与写入">
          <div className="detail-grid">
            <DetailItem label="存储根" value={dataset.storage_root ?? "-"} wide />
            <DetailItem label="主布局" value={dataset.primary_layout ?? "-"} />
            <DetailItem label="写入策略" value={dataset.write_policy ?? "-"} />
            <DetailItem label="更新方式" value={dataset.update_mode ?? "-"} />
            <DetailItem label="可用布局" value={dataset.available_layouts.join(", ") || "-"} wide />
            <DetailItem label="支持频度" value={dataset.supported_freqs.join(", ") || "-"} wide />
          </div>
        </DetailGroup>

        <DetailGroup title="分区概况">
          <div className="partition-summary-grid">
            <DetailItem label="最新分区" value={detailView.latestPartition} />
            <DetailItem label="最早分区" value={detailView.earliestPartition} />
            <DetailItem label="分区数量" value={String(dataset.partition_count)} />
            <DetailItem label="平均文件大小" value={detailView.averageFileSize} />
            <DetailItem label="最近文件样本" value={detailView.latestFilePath} wide />
            <DetailItem label="风险提示" value={detailView.riskTotal ? `${detailView.riskTotal} 项风险` : "无"} wide />
          </div>
        </DetailGroup>
      </div>
    </SectionCard>
  );
}

function DetailGroup({ children, title }: { children: ReactNode; title: string }) {
  return (
    <div className="detail-meta-group">
      <h4>{title}</h4>
      {children}
    </div>
  );
}
