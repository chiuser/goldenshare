import { EmptyState } from "../components/EmptyState";
import { LoadingBlock } from "../components/LoadingBlock";
import { Metric } from "../components/Metric";
import { PageHeader } from "../components/PageHeader";
import { RiskCard } from "../components/RiskCard";
import { SectionCard } from "../components/SectionCard";
import type { DatasetRiskItem, LakeStatus } from "../types";

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
        right={(
          <div className="risk-header-summary">
            <strong>{isLoading ? "..." : totalRiskCount}</strong>
            <span>{isLoading ? "正在读取" : "当前风险"}</span>
          </div>
        )}
      />

      <section className="risk-summary-grid">
        <Metric label="总风险" value={isLoading ? "读取中" : String(totalRiskCount)} hint="根目录与数据集风险合计" />
        <Metric label="根目录风险" value={isLoading ? "读取中" : String(rootRiskCount)} hint="路径、初始化、读写权限" />
        <Metric label="数据集风险" value={isLoading ? "读取中" : String(datasetRiskCount)} hint="来自文件扫描和 catalog" />
      </section>

      <section className="risk-page-grid">
        <SectionCard
          description="移动盘路径、初始化状态、读写权限等本地风险。"
          side={<span>{isLoading ? "读取中" : `${rootRiskCount} 项`}</span>}
          title="数据湖根目录风险"
        >
          {isLoading ? (
            <LoadingBlock title="正在读取数据湖根目录风险" description="正在从本地 Lake Console API 获取路径、权限和初始化状态。" />
          ) : status?.risks.length ? (
            <div className="risk-list">
              {status.risks.map((risk) => (
                <RiskCard risk={risk} key={`${risk.code}-${risk.path ?? ""}`} />
              ))}
            </div>
          ) : (
            <EmptyState title="暂无数据湖根目录风险" description="当前未发现路径或权限风险。" />
          )}
        </SectionCard>

        <SectionCard
          description="来自本地文件扫描和 Lake Dataset Catalog 的风险。"
          side={<span>{isLoading ? "读取中" : `${datasetRiskCount} 项`}</span>}
          title="数据集风险"
        >
          {isLoading ? (
            <LoadingBlock title="正在读取数据集风险" description="正在扫描本地数据集文件事实和 catalog 风险。" />
          ) : datasetRisks.length ? (
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
        </SectionCard>
      </section>
    </>
  );
}
