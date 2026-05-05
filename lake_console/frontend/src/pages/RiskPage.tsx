import { Badge } from "../components/Badge";
import { DataTableCard } from "../components/DataTableCard";
import type { DataTableColumn } from "../components/DataTableCard";
import { EmptyState } from "../components/EmptyState";
import { LoadingBlock } from "../components/LoadingBlock";
import { Metric } from "../components/Metric";
import { PageHeader } from "../components/PageHeader";
import { SectionCard } from "../components/SectionCard";
import type { DatasetRiskItem, LakeStatus, RiskItem } from "../types";

type RiskPageProps = {
  datasetRisks: DatasetRiskItem[];
  status: LakeStatus | null;
};

export function RiskPage({ datasetRisks, status }: RiskPageProps) {
  const isLoading = status === null;
  const rootRiskCount = status?.risks.length ?? 0;
  const datasetRiskCount = datasetRisks.length;
  const totalRiskCount = rootRiskCount + datasetRiskCount;
  return (
    <>
      <PageHeader
        eyebrow="Local risk review"
        title="风险"
        description="只展示数据湖根目录与数据集文件风险，不接入生产 Ops 状态。"
        helpTitle="这里展示的是本地文件事实和 Lake Root 检查结果，不读取远程 goldenshare-db。"
        variant="subtle"
        right={(
          <div className="risk-header-summary">
            <strong>{isLoading ? "..." : totalRiskCount}</strong>
            <span>{isLoading ? "正在读取" : "当前风险"}</span>
          </div>
        )}
      />

      <section className="risk-posture-panel">
        <div className="risk-posture-main">
          <span>{isLoading ? "正在读取" : totalRiskCount > 0 ? "需要关注" : "检查通过"}</span>
          <strong>{isLoading ? "..." : totalRiskCount}</strong>
          <p>{isLoading ? "正在读取本地数据湖风险。" : "根目录与数据集文件风险合计。"}</p>
        </div>
        <div className="risk-summary-grid">
          <Metric label="根目录风险" value={isLoading ? "读取中" : String(rootRiskCount)} hint="路径、初始化、读写权限" variant={rootRiskCount ? "warning" : "subtle"} />
          <Metric label="数据集风险" value={isLoading ? "读取中" : String(datasetRiskCount)} hint="来自文件扫描和 catalog" variant={datasetRiskCount ? "warning" : "subtle"} />
        </div>
      </section>

      <section className="risk-page-grid">
        <SectionCard
          description="移动盘路径、初始化状态、读写权限等本地风险。"
          side={<span>{isLoading ? "读取中" : `${rootRiskCount} 项`}</span>}
          title="数据湖根目录风险"
          variant="subtle"
        >
          {isLoading ? (
            <LoadingBlock title="正在读取数据湖根目录风险" description="正在从本地 Lake Console API 获取路径、权限和初始化状态。" />
          ) : status?.risks.length ? (
            <DataTableCard
              columns={rootRiskColumns}
              empty={<EmptyState title="暂无数据湖根目录风险" description="当前未发现路径或权限风险。" />}
              getRowKey={(risk) => `${risk.code}-${risk.path ?? ""}`}
              label="数据湖根目录风险"
              rows={status.risks}
              rowTone={riskRowTone}
            />
          ) : (
            <EmptyState title="数据湖根目录检查通过" description="当前未发现路径、初始化状态或读写权限风险。" tone="info" />
          )}
        </SectionCard>

        <SectionCard
          description="来自本地文件扫描和 Lake Dataset Catalog 的风险。"
          side={<span>{isLoading ? "读取中" : `${datasetRiskCount} 项`}</span>}
          title="数据集风险"
          variant="subtle"
        >
          {isLoading ? (
            <LoadingBlock title="正在读取数据集风险" description="正在扫描本地数据集文件事实和 catalog 风险。" />
          ) : datasetRisks.length ? (
            <DataTableCard
              columns={datasetRiskColumns}
              empty={<EmptyState title="暂无数据集风险" description="当前数据集没有暴露文件风险。" />}
              getRowKey={(risk) => `${risk.datasetKey}-${risk.code}-${risk.path ?? ""}`}
              label="数据集风险"
              rows={datasetRisks}
              rowTone={riskRowTone}
            />
          ) : (
            <EmptyState title="数据集检查通过" description="当前数据集文件扫描和 catalog 检查没有暴露风险。" tone="info" />
          )}
        </SectionCard>
      </section>
    </>
  );
}

const rootRiskColumns: DataTableColumn<RiskItem>[] = [
  {
    header: "级别",
    key: "severity",
    className: "risk-col-severity",
    render: (risk) => <RiskSeverityBadge severity={risk.severity} />,
  },
  {
    header: "原因码",
    key: "code",
    className: "risk-col-code",
    render: (risk) => <code>{risk.code}</code>,
  },
  {
    header: "说明",
    key: "message",
    className: "risk-col-message",
    render: (risk) => risk.message,
  },
  {
    header: "路径",
    key: "path",
    className: "risk-col-path",
    render: (risk) => risk.path ? <code>{risk.path}</code> : "-",
  },
];

const datasetRiskColumns: DataTableColumn<DatasetRiskItem>[] = [
  {
    header: "数据集",
    key: "dataset",
    className: "risk-col-dataset",
    render: (risk) => (
      <div className="risk-dataset-cell">
        <strong>{risk.datasetName}</strong>
        <span>{risk.datasetKey}</span>
      </div>
    ),
  },
  {
    header: "级别",
    key: "severity",
    className: "risk-col-severity",
    render: (risk) => <RiskSeverityBadge severity={risk.severity} />,
  },
  {
    header: "原因码",
    key: "code",
    className: "risk-col-code",
    render: (risk) => <code>{risk.code}</code>,
  },
  {
    header: "说明",
    key: "message",
    className: "risk-col-message",
    render: (risk) => risk.message,
  },
];

function RiskSeverityBadge({ severity }: { severity: string }) {
  return <Badge tone={riskSeverityTone(severity)}>{riskSeverityLabel(severity)}</Badge>;
}

function riskRowTone(risk: RiskItem): "warning" | "error" | "default" {
  const normalized = risk.severity.toLowerCase();
  if (normalized === "critical" || normalized === "error") {
    return "error";
  }
  if (normalized === "warning") {
    return "warning";
  }
  return "default";
}

function riskSeverityLabel(severity: string): string {
  const labels: Record<string, string> = {
    critical: "严重",
    error: "错误",
    warning: "警告",
    info: "提示",
  };
  return labels[severity.toLowerCase()] ?? severity;
}

function riskSeverityTone(severity: string): "info" | "warning" | "error" | "neutral" {
  const normalized = severity.toLowerCase();
  if (normalized === "critical" || normalized === "error") {
    return "error";
  }
  if (normalized === "warning") {
    return "warning";
  }
  if (normalized === "info") {
    return "info";
  }
  return "neutral";
}
