import type {
  SectorMomentumMetaViewModel,
  SectorMomentumPeriod,
  SectorMomentumUrlDirection,
  SectorMomentumUrlScope,
  SectorMomentumUrlState,
} from "../model/sectorMomentumTypes";

interface MomentumControlBarProps {
  meta: SectorMomentumMetaViewModel;
  state: SectorMomentumUrlState;
  statusLabel: string;
  statusTone: "ready" | "delayed";
  onDirectionChange: (direction: SectorMomentumUrlDirection) => void;
  onLevel1Change: (sectorCode: string) => void;
  onLevel2Change: (sectorCode: string) => void;
  onPeriodChange: (period: SectorMomentumPeriod) => void;
  onScopeChange: (scope: SectorMomentumUrlScope) => void;
  onTradeDateChange: (tradeDate: string | null) => void;
}

const SCOPES: ReadonlyArray<{ value: SectorMomentumUrlScope; label: string }> = [
  { value: "level1", label: "一级总榜" },
  { value: "level2", label: "二级总榜" },
  { value: "level3", label: "三级总榜" },
  { value: "level1-children", label: "一级内二级" },
  { value: "level2-children", label: "二级内三级" },
];

export function MomentumControlBar({
  meta,
  state,
  statusLabel,
  statusTone,
  onDirectionChange,
  onLevel1Change,
  onLevel2Change,
  onPeriodChange,
  onScopeChange,
  onTradeDateChange,
}: MomentumControlBarProps) {
  const level2Nodes = meta.level2Nodes.filter((node) => node.parentSectorCode === state.level1Code);
  return (
    <section className="momentum-control-bar" aria-label="动量排名筛选条件">
      <div className="momentum-control-row">
        <ControlGroup label="比较范围">
          <div className="momentum-segmented-control momentum-scope-control">
            {SCOPES.map((item) => (
              <button
                aria-pressed={state.scope === item.value}
                className={state.scope === item.value ? "active" : ""}
                key={item.value}
                type="button"
                onClick={() => onScopeChange(item.value)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </ControlGroup>
        {(state.scope === "level1-children" || state.scope === "level2-children") ? (
          <label className="momentum-select-control">
            <span>一级行业</span>
            <select value={state.level1Code ?? ""} onChange={(event) => onLevel1Change(event.target.value)}>
              {meta.level1Nodes.map((node) => <option key={node.sectorCode} value={node.sectorCode}>{node.sectorName}</option>)}
            </select>
          </label>
        ) : null}
        {state.scope === "level2-children" ? (
          <label className="momentum-select-control">
            <span>二级行业</span>
            <select value={state.level2Code ?? ""} onChange={(event) => onLevel2Change(event.target.value)}>
              {level2Nodes.map((node) => <option key={node.sectorCode} value={node.sectorCode}>{node.sectorName}</option>)}
            </select>
          </label>
        ) : null}
        <label className="momentum-select-control momentum-date-select">
          <span>分析日期</span>
          <select value={state.tradeDate ?? ""} onChange={(event) => onTradeDateChange(event.target.value || null)}>
            <option value="">按公共行情日期</option>
            {meta.tradeDates.map((item) => (
              <option key={item.tradeDate} value={item.tradeDate}>
                {item.tradeDate} · {availabilityLabel(item.availability)} · {item.validSectorCount}/{item.expectedSectorCount}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="momentum-control-row momentum-control-row-secondary">
        <ControlGroup label="统计周期">
          <div className="momentum-segmented-control">
            {([1, 5, 10, 20, 30] as const).map((period) => (
              <button aria-pressed={state.period === period} className={state.period === period ? "active" : ""} key={period} type="button" onClick={() => onPeriodChange(period)}>
                {period}日
              </button>
            ))}
          </div>
        </ControlGroup>
        <ControlGroup label="排行方向">
          <div className="momentum-segmented-control">
            <button aria-pressed={state.direction === "gainers"} className={state.direction === "gainers" ? "active" : ""} type="button" onClick={() => onDirectionChange("gainers")}>涨幅榜</button>
            <button aria-pressed={state.direction === "losers"} className={state.direction === "losers" ? "active" : ""} type="button" onClick={() => onDirectionChange("losers")}>跌幅榜</button>
          </div>
        </ControlGroup>
        <span className={`momentum-data-status ${statusTone}`} role="status">
          <i aria-hidden="true" />
          {statusLabel}
        </span>
      </div>
    </section>
  );
}

function ControlGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="momentum-control-group">
      <span>{label}</span>
      {children}
    </div>
  );
}

function availabilityLabel(value: "COMPLETE" | "PARTIAL" | "MISSING"): string {
  if (value === "COMPLETE") return "完整";
  if (value === "PARTIAL") return "部分缺失";
  return "无数据";
}
