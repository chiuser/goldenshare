import { directionClass } from "../../../shared/lib/marketDirection";
import { formatSignedPercent } from "../../../shared/lib/formatters";
import { Panel } from "../../../shared/ui/Panel";
import { SkeletonBlock } from "../../../shared/ui/SkeletonBlock";
import type {
  ConceptRankMetric,
  ConceptWorkspace,
  IndustryRankMetric,
  IndustryWorkspace,
  RegionRankMetric,
  RegionWorkspace,
  SectorDetail,
  SectorOverviewPanelData,
  SectorOverviewView,
  SectorRankItem,
} from "./api/marketSectorOverviewApi";
import type { SectorRequestState } from "./useSectorOverviewController";

const VIEW_LABELS: Record<SectorOverviewView, string> = { INDUSTRY: "行业", CONCEPT: "概念", REGION: "地域" };
const RANK_OPTIONS = {
  INDUSTRY: [
    ["CHANGE_PCT", "涨跌幅"],
    ["MAIN_NET_INFLOW", "主力净流入"],
    ["UP_COUNT", "上涨家数"],
  ],
  CONCEPT: [
    ["HEAT_SCORE", "综合热度"],
    ["HEAT_DELTA_1D", "日度热度变化"],
    ["CHANGE_PCT", "涨跌幅"],
    ["MAIN_NET_INFLOW", "主力净流入"],
  ],
  REGION: [
    ["CHANGE_PCT", "涨跌幅"],
    ["MAIN_NET_INFLOW", "主力净流入"],
    ["UP_COUNT", "上涨家数"],
  ],
} as const;

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
  const data = "data" in requestState && requestState.data.sectorOverview.view === view
    ? requestState.data.sectorOverview
    : null;
  return (
    <Panel
      className="sector-overview-v2"
      title="板块速览"
      help="盘后数据。行业按三级层级联动，概念按热度与行情排行，地域返回固定生产枚举。"
      meta={data ? <span className="sector-asof">数据日 {data.tradeDate}</span> : undefined}
    >
      <div className="sector-overview-shell">
        <div className="sector-toolbar">
          <div aria-label="板块分类" className="sector-tabs" role="tablist">
            {(Object.keys(VIEW_LABELS) as SectorOverviewView[]).map((item) => (
              <button
                aria-selected={view === item}
                className={view === item ? "active" : ""}
                key={item}
                role="tab"
                tabIndex={view === item ? 0 : -1}
                type="button"
                onClick={() => onViewChange(item)}
                onKeyDown={(event) => {
                  const views = Object.keys(VIEW_LABELS) as SectorOverviewView[];
                  const currentIndex = views.indexOf(item);
                  const nextIndex = event.key === "ArrowRight"
                    ? (currentIndex + 1) % views.length
                    : event.key === "ArrowLeft"
                      ? (currentIndex - 1 + views.length) % views.length
                      : event.key === "Home"
                        ? 0
                        : event.key === "End"
                          ? views.length - 1
                          : null;
                  if (nextIndex == null) return;
                  event.preventDefault();
                  const nextView = views[nextIndex];
                  onViewChange(nextView);
                  event.currentTarget.parentElement
                    ?.querySelectorAll<HTMLButtonElement>('[role="tab"]')
                    [nextIndex]?.focus();
                }}
              >
                {VIEW_LABELS[item]}
              </button>
            ))}
          </div>
          {data ? (
            <div aria-label="排行维度" className="sector-rank-options">
              {RANK_OPTIONS[data.view].map(([key, label]) => (
                <button
                  className={currentRank(data) === key ? "active" : ""}
                  key={key}
                  type="button"
                  onClick={() => onRankChange(key)}
                >
                  {label}
                </button>
              ))}
            </div>
          ) : null}
        </div>

        {requestState.kind === "loading" || (requestState.kind === "refreshing" && !data) ? <SkeletonBlock /> : null}
        {requestState.kind === "forbidden" ? <SectorState title="无查看权限" text="当前账号没有行情查看权限。" /> : null}
        {requestState.kind === "error" ? (
          <SectorState title="加载失败" text={requestState.message} action="重试" onAction={onRetry} />
        ) : null}
        {requestState.kind === "empty" ? <SectorState title="暂无数据" text="所选交易日没有完整的板块盘后事实。" /> : null}

        {data && requestState.kind !== "empty" ? (
          <>
            {requestState.kind === "partial" || requestState.kind === "delayed" ? (
              <div className={`sector-quality-banner ${requestState.kind}`}>
                {requestState.kind === "delayed" ? "当前展示最近完成交易日数据" : "部分指标或热度暂不可用，已保留可用事实"}
              </div>
            ) : null}
            {requestState.kind === "refreshing" ? <div className="sector-refreshing">正在更新…</div> : null}
            <Workspace
              data={data}
              onSectorSelect={onSectorSelect}
              onStockSelect={onStockSelect}
            />
          </>
        ) : null}
      </div>
    </Panel>
  );
}

function currentRank(data: SectorOverviewPanelData): string {
  if (data.view === "INDUSTRY") return data.industry.rankMetric;
  if (data.view === "CONCEPT") return data.concept.rankMetric;
  return data.region.rankMetric;
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
    return <IndustryWorkspaceView workspace={data.industry} onSectorSelect={onSectorSelect} onStockSelect={onStockSelect} />;
  }
  if (data.view === "CONCEPT") {
    return <ConceptWorkspaceView workspace={data.concept} onSectorSelect={onSectorSelect} onStockSelect={onStockSelect} />;
  }
  return <RegionWorkspaceView workspace={data.region} onSectorSelect={onSectorSelect} onStockSelect={onStockSelect} />;
}

function IndustryWorkspaceView({
  workspace,
  onSectorSelect,
  onStockSelect,
}: {
  workspace: IndustryWorkspace;
  onSectorSelect: (sectorCode: string) => void;
  onStockSelect: (stockCode: string) => void;
}) {
  return (
    <div className="sector-workspace industry-workspace">
      <div className="industry-columns">
        {workspace.columns.map((column) => (
          <section className="industry-level-column" key={column.level}>
            <header>
              <strong>Level {column.level}</strong>
              <span>{column.level === 1 ? "一级行业" : column.level === 2 ? "二级行业" : "三级行业"}</span>
            </header>
            <div className="sector-ranking-list">
              {column.rows.map((row) => <SectorRankCard key={row.sectorCode} row={row} onSelect={onSectorSelect} />)}
              {!column.rows.length ? <div className="sector-list-empty">暂无下级行业</div> : null}
            </div>
          </section>
        ))}
      </div>
      <SectorDetailPanel detail={workspace.detail} onStockSelect={onStockSelect} />
    </div>
  );
}

function ConceptWorkspaceView({
  workspace,
  onSectorSelect,
  onStockSelect,
}: {
  workspace: ConceptWorkspace;
  onSectorSelect: (sectorCode: string) => void;
  onStockSelect: (stockCode: string) => void;
}) {
  return (
    <div className="sector-workspace flat-workspace">
      <div className="flat-ranking-list" aria-label="概念板块排行">
        {workspace.rows.map((row) => <SectorRankCard key={row.sectorCode} row={row} onSelect={onSectorSelect} />)}
      </div>
      <SectorDetailPanel detail={workspace.detail} onStockSelect={onStockSelect} />
    </div>
  );
}

function RegionWorkspaceView({
  workspace,
  onSectorSelect,
  onStockSelect,
}: {
  workspace: RegionWorkspace;
  onSectorSelect: (sectorCode: string) => void;
  onStockSelect: (stockCode: string) => void;
}) {
  return (
    <div className="sector-workspace flat-workspace">
      <div className="flat-ranking-list" aria-label="地域板块排行">
        {workspace.rows.map((row) => <SectorRankCard key={row.sectorCode} row={row} onSelect={onSectorSelect} />)}
      </div>
      <SectorDetailPanel detail={workspace.detail} onStockSelect={onStockSelect} showBreadthDistribution />
    </div>
  );
}

function SectorRankCard({ row, onSelect }: { row: SectorRankItem; onSelect: (sectorCode: string) => void }) {
  const leaderName = row.leader?.stockName || row.leader?.stockCode || "--";
  return (
    <button className={`sector-rank-card ${row.selected ? "selected" : ""}`} type="button" onClick={() => onSelect(row.sectorCode)}>
      <span className="sector-rank-number">{row.rank}</span>
      <span className="sector-rank-main">
        <strong title={row.sectorName}>{row.sectorName}</strong>
        <span title={leaderName}>领涨 {leaderName}</span>
      </span>
      {row.heat ? <HeatBadge heat={row.heat} /> : null}
      <span className={`sector-rank-metric ${directionClass(row.primaryMetric.direction)}`}>
        {row.primaryMetric.displayText}
      </span>
    </button>
  );
}

function HeatBadge({ heat }: { heat: NonNullable<SectorRankItem["heat"]> }) {
  const level = { BOILING: "沸腾", HOT: "高热", ACTIVE: "活跃", NONE: "--" }[heat.heatLevel];
  const trend = { HEATING: "升温", STABLE: "稳定", COOLING: "降温", UNKNOWN: "" }[heat.heatTrend];
  return <span className={`heat-badge ${heat.heatStatus.toLowerCase()}`}>{heat.heatStatus === "INVALID" ? "待计算" : `${level}${trend ? ` · ${trend}` : ""}`}</span>;
}

function SectorDetailPanel({
  detail,
  onStockSelect,
  showBreadthDistribution = false,
}: {
  detail: SectorDetail | null;
  onStockSelect: (stockCode: string) => void;
  showBreadthDistribution?: boolean;
}) {
  if (!detail) return <aside className="sector-detail-panel"><div className="sector-list-empty">请选择板块</div></aside>;
  const metrics = detail.metrics;
  return (
    <aside className="sector-detail-panel">
      <div className="sector-detail-heading">
        <div>
          <strong>{detail.sectorName}</strong>
          {detail.hierarchyPath ? <span title={detail.hierarchyPath}>{detail.hierarchyPath}</span> : <span>{detail.sectorCode}</span>}
        </div>
        {detail.heat ? <HeatBadge heat={detail.heat} /> : null}
      </div>
      <div className="sector-detail-metrics">
        <MetricCard label="涨跌幅" value={metrics.changePct == null ? "--" : formatSignedPercent(metrics.changePct)} />
        <MetricCard label="主力净流入" value={formatAmount(metrics.mainNetInflow)} />
        <MetricCard label="上涨 / 下跌" value={`${metrics.upCount ?? "--"} / ${metrics.downCount ?? "--"}`} />
        <MetricCard label="有效成分" value={`${metrics.memberCount}`} />
        <MetricCard label="停牌" value={`${metrics.suspendedCount}`} />
        <MetricCard label="行情覆盖" value={metrics.quoteCoverage == null ? "--" : `${(metrics.quoteCoverage * 100).toFixed(1)}%`} />
      </div>
      {showBreadthDistribution ? <SectorBreadthDistribution metrics={metrics} /> : null}
      <div className="sector-leader-card">
        <span>领涨股</span>
        <strong>{detail.leader?.stockName || detail.leader?.stockCode || "--"}</strong>
        <em>{detail.leader?.changePct == null ? "--" : formatSignedPercent(detail.leader.changePct)}</em>
      </div>
      {detail.heatHistory?.length ? <HeatHistory points={detail.heatHistory} /> : null}
      <div className="sector-members">
        <header><strong>板块成分</strong><span>涨幅前 5</span></header>
        {detail.members.map((member) => (
          <button key={member.stockCode} type="button" onClick={() => onStockSelect(member.stockCode)}>
            <span title={member.stockName || member.stockCode}>{member.stockName || member.stockCode}</span>
            <span className={directionClass(member.direction)}>{member.changePct == null ? "--" : formatSignedPercent(member.changePct)}</span>
          </button>
        ))}
        {!detail.members.length ? <div className="sector-list-empty">暂无有效成分行情</div> : null}
      </div>
    </aside>
  );
}

function SectorBreadthDistribution({ metrics }: { metrics: SectorDetail["metrics"] }) {
  const upCount = metrics.upCount ?? 0;
  const downCount = metrics.downCount ?? 0;
  const total = upCount + downCount;
  return (
    <div className="sector-breadth-distribution" aria-label="地域成分涨跌分布">
      <div>
        <span>上涨 {metrics.upCount ?? "--"}</span>
        <span>下跌 {metrics.downCount ?? "--"}</span>
      </div>
      <div className="sector-breadth-track" aria-hidden="true">
        <span className="up" style={{ flexGrow: total ? upCount : 0 }} />
        <span className="down" style={{ flexGrow: total ? downCount : 0 }} />
      </div>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

function HeatHistory({ points }: { points: NonNullable<SectorDetail["heatHistory"]> }) {
  return (
    <div className="heat-history" aria-label="最近20日热度">
      {points.map((point) => (
        <span
          key={point.tradeDate}
          style={{ height: `${Math.max(4, point.heatScore ?? 0)}%` }}
          title={`${point.tradeDate} · ${point.heatScore ?? "--"}`}
        />
      ))}
    </div>
  );
}

function SectorState({ title, text, action, onAction }: { title: string; text: string; action?: string; onAction?: () => void }) {
  return (
    <div className="sector-state-overlay">
      <strong>{title}</strong>
      <span>{text}</span>
      {action && onAction ? <button type="button" onClick={onAction}>{action}</button> : null}
    </div>
  );
}

function formatAmount(value: number | null): string {
  return value == null ? "--" : `${value >= 0 ? "+" : ""}${(value / 100_000_000).toFixed(1)}亿`;
}
