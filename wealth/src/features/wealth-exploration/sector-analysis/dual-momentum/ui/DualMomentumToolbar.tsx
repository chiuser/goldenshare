import type {
  SectorDualMomentumMetaViewModel,
  SectorDualMomentumPeriod,
  SectorDualMomentumThreshold,
  SectorDualMomentumUrlScope,
  SectorDualMomentumUrlState,
} from "../model/sectorDualMomentumTypes";

interface DualMomentumToolbarProps {
  meta: SectorDualMomentumMetaViewModel;
  state: SectorDualMomentumUrlState;
  statusLabel: string;
  statusTone: "ready" | "delayed";
  onScopeChange: (scope: SectorDualMomentumUrlScope) => void;
  onLevel1Change: (sectorCode: string) => void;
  onLevel2Change: (sectorCode: string) => void;
  onTradeDateChange: (tradeDate: string | null) => void;
  onPeriodChange: (period: SectorDualMomentumPeriod) => void;
  onThresholdChange: (threshold: SectorDualMomentumThreshold) => void;
}

const SCOPES: ReadonlyArray<{ value: SectorDualMomentumUrlScope; label: string }> = [
  { value: "level1", label: "一级总榜" },
  { value: "level2", label: "二级总榜" },
  { value: "level3", label: "三级总榜" },
  { value: "level1-children", label: "一级内二级" },
  { value: "level2-children", label: "二级内三级" },
];

export function DualMomentumToolbar(props: DualMomentumToolbarProps) {
  const level2Nodes = props.meta.level2Nodes.filter((node) => node.parentSectorCode === props.state.level1Code);
  return (
    <section className="dual-momentum-toolbar" aria-label="双动量筛选条件">
      <div className="dual-toolbar-row">
        <ControlGroup label="比较范围">
          <div className="dual-segmented-control dual-scope-control">
            {SCOPES.map((item) => (
              <button
                aria-pressed={props.state.scope === item.value}
                className={props.state.scope === item.value ? "active" : ""}
                key={item.value}
                type="button"
                onClick={() => props.onScopeChange(item.value)}
              >{item.label}</button>
            ))}
          </div>
        </ControlGroup>
        {(props.state.scope === "level1-children" || props.state.scope === "level2-children") ? (
          <label className="dual-select-control">
            <span>一级行业</span>
            <select value={props.state.level1Code ?? ""} onChange={(event) => props.onLevel1Change(event.target.value)}>
              {props.meta.level1Nodes.map((node) => <option key={node.sectorCode} value={node.sectorCode}>{node.sectorName}</option>)}
            </select>
          </label>
        ) : null}
        {props.state.scope === "level2-children" ? (
          <label className="dual-select-control">
            <span>二级行业</span>
            <select value={props.state.level2Code ?? ""} onChange={(event) => props.onLevel2Change(event.target.value)}>
              {level2Nodes.map((node) => <option key={node.sectorCode} value={node.sectorCode}>{node.sectorName}</option>)}
            </select>
          </label>
        ) : null}
        <label className="dual-select-control dual-date-select">
          <span>分析日期</span>
          <select value={props.state.tradeDate ?? ""} onChange={(event) => props.onTradeDateChange(event.target.value || null)}>
            <option value="">按公共行情日期</option>
            {props.meta.tradeDates.map((item) => (
              <option key={item.tradeDate} value={item.tradeDate}>
                {item.tradeDate} · {availabilityLabel(item.availability)} · {item.validSectorCount}/{item.expectedSectorCount}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="dual-toolbar-row dual-toolbar-row-secondary">
        <ControlGroup label="观察周期">
          <div className="dual-segmented-control">
            {([5, 10, 20, 30] as const).map((period) => (
              <button aria-pressed={props.state.period === period} className={props.state.period === period ? "active" : ""} key={period} type="button" onClick={() => props.onPeriodChange(period)}>{period}日</button>
            ))}
          </div>
        </ControlGroup>
        <ControlGroup label="领先阈值">
          <div className="dual-segmented-control">
            {([70, 80, 90] as const).map((threshold) => (
              <button aria-pressed={props.state.threshold === threshold} className={props.state.threshold === threshold ? "active" : ""} key={threshold} type="button" onClick={() => props.onThresholdChange(threshold)}>{threshold}%</button>
            ))}
          </div>
        </ControlGroup>
        <span className={`dual-data-status ${props.statusTone}`} role="status"><i aria-hidden="true" />{props.statusLabel}</span>
      </div>
    </section>
  );
}

function ControlGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="dual-control-group"><span>{label}</span>{children}</div>;
}

function availabilityLabel(value: "COMPLETE" | "PARTIAL" | "MISSING") {
  if (value === "COMPLETE") return "完整";
  if (value === "PARTIAL") return "部分缺失";
  return "无数据";
}
