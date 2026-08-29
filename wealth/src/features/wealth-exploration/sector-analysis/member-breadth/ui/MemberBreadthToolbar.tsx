import type { SectorMemberBreadthController } from "../model/useSectorMemberBreadthController";
import type { SectorMemberBreadthMetaViewModel, SectorMemberBreadthUrlScope, SectorMemberBreadthUrlState } from "../model/sectorMemberBreadthTypes";

const SCOPES: ReadonlyArray<{ value: SectorMemberBreadthUrlScope; label: string }> = [
  { value: "level1", label: "一级总榜" }, { value: "level2", label: "二级总榜" }, { value: "level3", label: "三级总榜" },
  { value: "level1-children", label: "一级内二级" }, { value: "level2-children", label: "二级内三级" },
];

export function MemberBreadthToolbar({ controller, meta, state, statusLabel, delayed }: { controller: SectorMemberBreadthController; meta: SectorMemberBreadthMetaViewModel; state: SectorMemberBreadthUrlState; statusLabel: string; delayed: boolean }) {
  const level2Nodes = meta.level2Nodes.filter((node) => node.parentSectorCode === state.level1Code);
  return <section className="member-breadth-toolbar" aria-label="成员广度筛选条件">
    <div className="member-breadth-toolbar-row">
      <Control label="比较范围"><Segmented>{SCOPES.map((item) => <button aria-pressed={state.scope === item.value} className={state.scope === item.value ? "active" : ""} key={item.value} type="button" onClick={() => controller.selectScope(item.value)}>{item.label}</button>)}</Segmented></Control>
      {state.scope === "level1-children" || state.scope === "level2-children" ? <Select label="一级行业" value={state.level1Code ?? ""} onChange={controller.selectLevel1} options={meta.level1Nodes.map((node) => [node.sectorCode, node.sectorName])} /> : null}
      {state.scope === "level2-children" ? <Select label="二级行业" value={state.level2Code ?? ""} onChange={controller.selectLevel2} options={level2Nodes.map((node) => [node.sectorCode, node.sectorName])} /> : null}
      <label className="member-breadth-select member-breadth-date"><span>分析日期</span><select aria-label="分析日期" value={state.tradeDate ?? ""} onChange={(event) => controller.selectTradeDate(event.target.value || null)}><option value="">按公共行情日期</option>{meta.tradeDates.map((item) => <option key={item.tradeDate} value={item.tradeDate}>{item.tradeDate} · {availabilityLabel(item.availability)} · {item.validSectorCount}/{item.expectedSectorCount}</option>)}</select></label>
    </div>
    <div className="member-breadth-toolbar-row member-breadth-toolbar-secondary">
      <Control label="广度方向"><Segmented><button aria-pressed={state.direction === "up"} className={state.direction === "up" ? "active" : ""} type="button" onClick={() => controller.selectDirection("up")}>上涨广度</button><button aria-pressed={state.direction === "down"} className={state.direction === "down" ? "active" : ""} type="button" onClick={() => controller.selectDirection("down")}>下跌广度</button></Segmented></Control>
      <Control label="排名指标"><Segmented><button aria-pressed={state.metric === "member-count"} className={state.metric === "member-count" ? "active" : ""} type="button" onClick={() => controller.selectMetric("member-count")}>成分股占比</button><button aria-pressed={state.metric === "turnover"} className={state.metric === "turnover" ? "active" : ""} type="button" onClick={() => controller.selectMetric("turnover")}>成交额占比</button><button aria-pressed={state.metric === "ma-position"} className={state.metric === "ma-position" ? "active" : ""} type="button" onClick={() => controller.selectMetric("ma-position")}>均线位置占比</button></Segmented></Control>
      <Control label="均线周期"><Segmented>{([5, 10, 15, 20, 30, 60] as const).map((period) => <button aria-pressed={state.maPeriod === period} className={state.maPeriod === period ? "active" : ""} key={period} type="button" onClick={() => controller.selectMaPeriod(period)}>MA{period}</button>)}</Segmented></Control>
      <Control label="历史范围"><Segmented>{([20, 30, 60] as const).map((range) => <button aria-pressed={state.historyRange === range} className={state.historyRange === range ? "active" : ""} key={range} type="button" onClick={() => controller.selectHistoryRange(range)}>{range}日</button>)}</Segmented></Control>
      <span className={`member-breadth-status ${delayed ? "delayed" : ""}`} role="status"><i aria-hidden="true" />{statusLabel}</span>
    </div>
  </section>;
}

function Control({ label, children }: { label: string; children: React.ReactNode }) { return <div className="member-breadth-control"><span>{label}</span>{children}</div>; }
function Segmented({ children }: { children: React.ReactNode }) { return <div className="member-breadth-segmented">{children}</div>; }
function Select({ label, value, options, onChange }: { label: string; value: string; options: Array<[string, string]>; onChange: (value: string) => void }) { return <label className="member-breadth-select"><span>{label}</span><select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>{options.map(([code, name]) => <option key={code} value={code}>{name}</option>)}</select></label>; }
function availabilityLabel(value: "COMPLETE" | "PARTIAL" | "MISSING") { return value === "COMPLETE" ? "完整" : value === "PARTIAL" ? "部分缺失" : "无数据"; }
