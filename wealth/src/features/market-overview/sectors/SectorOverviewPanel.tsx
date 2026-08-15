import type {
  ConceptRankMetric,
  IndustryRankMetric,
  RegionRankMetric,
  SectorOverviewPanelData,
  SectorOverviewView,
  SectorRankMetric,
} from "./api/marketSectorOverviewApi";
import { ConceptWorkspace } from "./concept/ConceptWorkspace";
import { IndustryWorkspace } from "./industry/IndustryWorkspace";
import { RegionWorkspace } from "./region/RegionWorkspace";
import { SectorOverviewTabs } from "./SectorOverviewTabs";
import { SectorRankingToolbar } from "./SectorRankingToolbar";
import type { SectorRequestState } from "./useSectorOverviewController";

const VIEW_BADGES: Record<SectorOverviewView, string> = {
  INDUSTRY: "行业层级",
  CONCEPT: "概念热度",
  REGION: "地域排行",
};

interface SectorOverviewPanelProps {
  view: SectorOverviewView;
  requestState: SectorRequestState;
  onViewChange: (view: SectorOverviewView) => void;
  onRankChange: (rankMetric: IndustryRankMetric | ConceptRankMetric | RegionRankMetric) => void;
  onSectorSelect: (sectorCode: string) => void;
  onRetry: () => void;
  onStockSelect: (stockCode: string) => void;
}

export function SectorOverviewPanel({
  view,
  requestState,
  onViewChange,
  onRankChange,
  onSectorSelect,
  onRetry,
  onStockSelect,
}: SectorOverviewPanelProps) {
  const data = "data" in requestState
    && requestState.data?.sectorOverview.view === view
    ? requestState.data.sectorOverview
    : null;
  const rankMetric = data ? currentRank(data) : defaultRank(view);
  const overlay = stateOverlay(requestState);

  return (
    <section aria-label="板块速览" className={`sector-overview-v2 view-${view.toLowerCase()}`}>
      <header className="sector-overview-header">
        <div className="sector-overview-title">
          <h2>板块速览 V2</h2>
          <span>{VIEW_BADGES[view]}</span>
        </div>
        <SectorOverviewTabs view={view} onViewChange={onViewChange} />
        <div className="sector-asof">{data ? `数据日期 ${data.tradeDate}` : "数据日期 --"}</div>
      </header>
      <SectorRankingToolbar
        rankMetric={rankMetric}
        view={view}
        onRankChange={(metric: SectorRankMetric) => onRankChange(metric)}
      />
      <div className="sector-workspace-stage">
        {data && requestState.kind !== "empty"
          ? <Workspace data={data} onSectorSelect={onSectorSelect} onStockSelect={onStockSelect} />
          : <SectorWorkspaceSkeleton view={view} />}
        {requestState.kind === "refreshing" ? <div className="sector-refreshing">正在更新…</div> : null}
        {requestState.kind === "partial" || requestState.kind === "delayed" ? (
          <div className={`sector-quality-banner ${requestState.kind}`}>
            {requestState.kind === "delayed"
              ? `当前展示 ${requestState.data.sectorOverview.tradeDate} 盘后数据`
              : "部分指标或热度暂不可用，已保留可用事实"}
          </div>
        ) : null}
        {overlay ? <SectorStateOverlay {...overlay} onRetry={onRetry} /> : null}
      </div>
    </section>
  );
}

function Workspace({
  data,
  onSectorSelect,
  onStockSelect,
}: {
  data: SectorOverviewPanelData;
  onSectorSelect: (sectorCode: string) => void;
  onStockSelect: (stockCode: string) => void;
}) {
  if (data.view === "INDUSTRY") {
    return <IndustryWorkspace workspace={data.industry} onSectorSelect={onSectorSelect} onStockSelect={onStockSelect} />;
  }
  if (data.view === "CONCEPT") {
    return <ConceptWorkspace workspace={data.concept} onSectorSelect={onSectorSelect} onStockSelect={onStockSelect} />;
  }
  return <RegionWorkspace workspace={data.region} onSectorSelect={onSectorSelect} onStockSelect={onStockSelect} />;
}

function currentRank(data: SectorOverviewPanelData): SectorRankMetric {
  if (data.view === "INDUSTRY") return data.industry.rankMetric;
  if (data.view === "CONCEPT") return data.concept.rankMetric;
  return data.region.rankMetric;
}

function defaultRank(view: SectorOverviewView): SectorRankMetric {
  if (view === "CONCEPT") return "HEAT_SCORE";
  return view === "INDUSTRY" ? "CHANGE_PCT_UP" : "CHANGE_PCT";
}

function stateOverlay(requestState: SectorRequestState): { title: string; text: string; retry?: boolean } | null {
  switch (requestState.kind) {
    case "initial-loading":
      return { title: "正在加载", text: "正在读取板块盘后事实。" };
    case "empty":
      return { title: "暂无数据", text: "所选交易日没有完整的板块盘后事实。" };
    case "forbidden":
      return { title: "无查看权限", text: "当前账号没有行情查看权限。" };
    case "error":
      return { title: "加载失败", text: requestState.message, retry: true };
    case "refreshing":
    case "ready":
    case "partial":
    case "delayed":
      return null;
  }
}

function SectorWorkspaceSkeleton({ view }: { view: SectorOverviewView }) {
  return (
    <div aria-label={`${view === "INDUSTRY" ? "行业" : view === "CONCEPT" ? "概念" : "地域"}工作台骨架`} className={`sector-workspace sector-workspace-skeleton ${view.toLowerCase()}`}>
      <div className="sector-skeleton-ranking">
        <div className="sector-skeleton-head" />
        {Array.from({ length: view === "INDUSTRY" ? 15 : 7 }, (_, index) => <div className="sector-skeleton-row" key={index} />)}
      </div>
      <div className="sector-skeleton-detail">
        <div className="sector-skeleton-title" />
        <div className="sector-skeleton-metrics">
          {Array.from({ length: 4 }, (_, index) => <span key={index} />)}
        </div>
        <div className="sector-skeleton-card" />
        <div className="sector-skeleton-list" />
      </div>
    </div>
  );
}

function SectorStateOverlay({
  title,
  text,
  retry,
  onRetry,
}: {
  title: string;
  text: string;
  retry?: boolean;
  onRetry: () => void;
}) {
  return (
    <div className="sector-state-overlay">
      <strong>{title}</strong>
      <span>{text}</span>
      {retry ? <button type="button" onClick={onRetry}>重试</button> : null}
    </div>
  );
}
