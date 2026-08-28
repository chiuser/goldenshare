import type {
  SectorRelativeRotationMetaViewModel,
  SectorRelativeRotationPeriod,
  SectorRelativeRotationTrailLength,
  SectorRelativeRotationUrlScope,
  SectorRelativeRotationUrlState,
} from "../model/sectorRelativeRotationTypes";

interface RelativeRotationToolbarProps {
  meta: SectorRelativeRotationMetaViewModel;
  state: SectorRelativeRotationUrlState;
  statusLabel: string;
  statusTone: "ready" | "delayed";
  onScopeChange: (scope: SectorRelativeRotationUrlScope) => void;
  onLevel1Change: (code: string) => void;
  onLevel2Change: (code: string) => void;
  onTradeDateChange: (date: string | null) => void;
  onPeriodChange: (period: SectorRelativeRotationPeriod) => void;
  onTrailLengthChange: (length: SectorRelativeRotationTrailLength) => void;
}

const SCOPES: ReadonlyArray<{ value: SectorRelativeRotationUrlScope; label: string }> = [
  { value: "level1", label: "一级总榜" },
  { value: "level2", label: "二级总榜" },
  { value: "level3", label: "三级总榜" },
  { value: "level1-children", label: "一级内二级" },
  { value: "level2-children", label: "二级内三级" },
];

export function RelativeRotationToolbar(props: RelativeRotationToolbarProps) {
  const level2Nodes = props.meta.level2Nodes.filter((node) => node.parentSectorCode === props.state.level1Code);
  return (
    <section className="relative-rotation-toolbar" aria-label="相对轮动筛选条件">
      <div className="relative-toolbar-row">
        <ControlGroup label="比较范围">
          <div className="relative-segmented-control relative-scope-control">
            {SCOPES.map((item) => <button aria-pressed={props.state.scope === item.value} className={props.state.scope === item.value ? "active" : ""} key={item.value} type="button" onClick={() => props.onScopeChange(item.value)}>{item.label}</button>)}
          </div>
        </ControlGroup>
        {(props.state.scope === "level1-children" || props.state.scope === "level2-children") ? (
          <label className="relative-select-control"><span>一级行业</span><select aria-label="一级行业" value={props.state.level1Code ?? ""} onChange={(event) => props.onLevel1Change(event.target.value)}>{props.meta.level1Nodes.map((node) => <option key={node.sectorCode} value={node.sectorCode}>{node.sectorName}</option>)}</select></label>
        ) : null}
        {props.state.scope === "level2-children" ? (
          <label className="relative-select-control"><span>二级行业</span><select aria-label="二级行业" value={props.state.level2Code ?? ""} onChange={(event) => props.onLevel2Change(event.target.value)}>{level2Nodes.map((node) => <option key={node.sectorCode} value={node.sectorCode}>{node.sectorName}</option>)}</select></label>
        ) : null}
        <label className="relative-select-control relative-date-select"><span>分析日期</span><select aria-label="分析日期" value={props.state.tradeDate ?? ""} onChange={(event) => props.onTradeDateChange(event.target.value || null)}><option value="">按公共行情日期</option>{props.meta.tradeDates.map((item) => <option key={item.tradeDate} value={item.tradeDate}>{item.tradeDate} · {availabilityLabel(item.availability)} · {item.validSectorCount}/{item.expectedSectorCount}</option>)}</select></label>
      </div>
      <div className="relative-toolbar-row relative-toolbar-row-secondary">
        <ControlGroup label="强度周期"><div className="relative-segmented-control">{([5, 10, 20, 30] as const).map((period) => <button aria-pressed={props.state.period === period} className={props.state.period === period ? "active" : ""} key={period} type="button" onClick={() => props.onPeriodChange(period)}>{period}日</button>)}</div></ControlGroup>
        <ControlGroup label="轨迹长度"><div className="relative-segmented-control">{([20, 30, 60] as const).map((length) => <button aria-pressed={props.state.trailLength === length} className={props.state.trailLength === length ? "active" : ""} key={length} type="button" onClick={() => props.onTrailLengthChange(length)}>{length}日</button>)}</div></ControlGroup>
        <span className={`relative-data-status ${props.statusTone}`} role="status"><i aria-hidden="true" />{props.statusLabel}</span>
      </div>
    </section>
  );
}

function ControlGroup({ label, children }: { label: string; children: React.ReactNode }) { return <div className="relative-control-group"><span>{label}</span>{children}</div>; }
function availabilityLabel(value: "COMPLETE" | "PARTIAL" | "MISSING") { if (value === "COMPLETE") return "完整"; if (value === "PARTIAL") return "部分缺失"; return "无数据"; }
