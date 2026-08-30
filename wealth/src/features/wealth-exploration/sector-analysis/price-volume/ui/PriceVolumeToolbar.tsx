import type {
  PriceVolumeMetaViewModel,
  PriceVolumePeriod,
  PriceVolumeStateFilter,
  PriceVolumeUrlScope,
  PriceVolumeUrlState,
} from "../api/sectorPriceVolumeTypes";

interface PriceVolumeToolbarProps {
  meta: PriceVolumeMetaViewModel;
  state: PriceVolumeUrlState;
  statusLabel: string;
  statusTone: "ready" | "delayed" | "loading" | "error";
  onScopeChange: (scope: PriceVolumeUrlScope) => void;
  onLevel1Change: (code: string) => void;
  onLevel2Change: (code: string) => void;
  onTradeDateChange: (date: string | null) => void;
  onPeriodChange: (period: PriceVolumePeriod) => void;
  onStateFilterChange: (filter: PriceVolumeStateFilter) => void;
}

const SCOPES: ReadonlyArray<{ value: PriceVolumeUrlScope; label: string }> = [
  { value: "level1", label: "一级总榜" }, { value: "level2", label: "二级总榜" }, { value: "level3", label: "三级总榜" },
  { value: "level1-children", label: "一级内二级" }, { value: "level2-children", label: "二级内三级" },
];
const FILTERS: ReadonlyArray<{ value: PriceVolumeStateFilter; label: string }> = [
  { value: "all", label: "全部" }, { value: "joint", label: "量价共同增强" }, { value: "price", label: "价格增强" },
  { value: "amount", label: "成交增强" }, { value: "neutral", label: "量价均不明显" },
];

export function PriceVolumeToolbar(props: PriceVolumeToolbarProps) {
  const level2Nodes = props.meta.level2Nodes.filter((node) => node.parentSectorCode === props.state.level1Code);
  return (
    <section className="price-volume-toolbar" aria-label="量价分布筛选条件">
      <div className="price-volume-toolbar-row">
        <ControlGroup label="比较范围"><Segmented>{SCOPES.map((item) => <button aria-pressed={props.state.scope === item.value} className={props.state.scope === item.value ? "active" : ""} key={item.value} type="button" onClick={() => props.onScopeChange(item.value)}>{item.label}</button>)}</Segmented></ControlGroup>
        {(props.state.scope === "level1-children" || props.state.scope === "level2-children") ? <SelectControl label="一级行业" value={props.state.level1Code ?? ""} onChange={props.onLevel1Change} options={props.meta.level1Nodes.map((node) => ({ value: node.sectorCode, label: node.sectorName }))} /> : null}
        {props.state.scope === "level2-children" ? <SelectControl label="二级行业" value={props.state.level2Code ?? ""} onChange={props.onLevel2Change} options={level2Nodes.map((node) => ({ value: node.sectorCode, label: node.sectorName }))} /> : null}
        <label className="price-volume-select price-volume-date-select"><span>分析日期</span><select aria-label="分析日期" value={props.state.tradeDate ?? ""} onChange={(event) => props.onTradeDateChange(event.target.value || null)}><option value="">按公共行情日期</option>{props.meta.tradeDates.map((item) => <option key={item.tradeDate} value={item.tradeDate}>{item.tradeDate} · {availabilityLabel(item.availability)} · {item.validSectorCount}/{item.expectedSectorCount}</option>)}</select></label>
      </div>
      <div className="price-volume-toolbar-row price-volume-toolbar-secondary">
        <ControlGroup label="统计周期"><Segmented>{([1, 5, 10, 20, 30] as const).map((period) => <button aria-pressed={props.state.period === period} className={props.state.period === period ? "active" : ""} key={period} type="button" onClick={() => props.onPeriodChange(period)}>{period}日</button>)}</Segmented></ControlGroup>
        <ControlGroup label="状态筛选"><Segmented>{FILTERS.map((item) => <button aria-pressed={props.state.stateFilter === item.value} className={props.state.stateFilter === item.value ? "active" : ""} key={item.value} type="button" onClick={() => props.onStateFilterChange(item.value)}>{item.label}</button>)}</Segmented></ControlGroup>
        <div className="price-volume-toolbar-spacer" />
        <span className={`price-volume-data-status ${props.statusTone}`} role="status"><i aria-hidden="true" />{props.statusLabel}</span>
      </div>
    </section>
  );
}

export function PriceVolumeToolbarSkeleton() { return <section aria-hidden="true" className="price-volume-toolbar price-volume-toolbar-skeleton"><i /><i /><i /><i /></section>; }
function ControlGroup({ label, children }: { label: string; children: React.ReactNode }) { return <div className="price-volume-control-group"><span>{label}</span>{children}</div>; }
function Segmented({ children }: { children: React.ReactNode }) { return <div className="price-volume-segmented">{children}</div>; }
function SelectControl({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: Array<{ value: string; label: string }> }) { return <label className="price-volume-select"><span>{label}</span><select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>; }
function availabilityLabel(value: "COMPLETE" | "PARTIAL" | "MISSING") { if (value === "COMPLETE") return "完整"; if (value === "PARTIAL") return "部分缺失"; return "无数据"; }
