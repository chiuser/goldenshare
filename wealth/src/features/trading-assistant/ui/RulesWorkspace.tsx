import { useState } from "react";
import type { AccountSummary, AlertsQuery } from "../api/generatedContracts";
import type { RuleKind } from "../api/rulesApi";
import { useRules } from "../model/useRules";
import { checkLabel, notificationLabel, resultLabel, ruleTime } from "../model/rulePresentation";
import { TradingAssistantAction } from "./TradingAssistantForm";
import { RuleCreateDialog } from "./RuleCreateDialog";
import { RuleDetailDialog } from "./RuleDetailDialog";
import "./trading-assistant-rules.css";

export function RulesWorkspace({ accounts, selected }: { accounts: AccountSummary[]; selected: string | null }) {
  const [kind, setKind] = useState<RuleKind>("PLAN"), [status, setStatus] = useState<AlertsQuery["status"]>("ALL");
  const [search, setSearch] = useState(""), [keyword, setKeyword] = useState("");
  const [revision, setRevision] = useState(0);
  const [overlay, setOverlay] = useState<"CREATE" | { ruleId: string } | null>(null);
  const rules = useRules(kind, selected, status, keyword, revision);
  const changed = () => setRevision(v => v + 1);
  return <section className="ta-rule-workspace">
    <div className="ta-rule-toolbar"><div><h2>计划与监控</h2><p className="ta-note">条件是否成立，盘后给你一个可核验的结果。</p></div><div className="ta-rule-actions"><TradingAssistantAction disabled title="机器人配置与通知发送在后续阶段开放">通知设置</TradingAssistantAction><TradingAssistantAction primary disabled={kind === "PLAN" && !accounts.length} onClick={() => setOverlay("CREATE")}>{kind === "PLAN" ? "新建交易计划" : "新建独立提醒"}</TradingAssistantAction></div></div>
    <div className="ta-segments ta-rule-tabs" role="group" aria-label="规则类型">{([['PLAN','交易计划'],['ALERT','独立提醒']] as const).map(([key, label]) => <button type="button" key={key} aria-pressed={kind === key} onClick={() => { setOverlay(null); setKind(key); }}>{label}{rules.data ? ` ${key === "PLAN" ? rules.data.counts.planCount : rules.data.counts.alertCount}` : ""}</button>)}</div>
    <form className="ta-rule-filters" onSubmit={e => { e.preventDefault(); setKeyword(search); }}><select aria-label="规则状态" value={status} onChange={e => { setOverlay(null); setStatus(e.target.value as typeof status); }}>{([['ALL','全部状态'],['ACTIVE','进行中'],['TRIGGERED','已触发'],['NOT_TRIGGERED','未触发'],['CLOSED','已关闭']] as const).map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select><input type="search" aria-label="搜索规则股票" placeholder="搜索名称 / 代码" value={search} onChange={e => { setSearch(e.target.value); if (!e.target.value) setKeyword(""); }} /><TradingAssistantAction type="submit">搜索</TradingAssistantAction></form>
    <div className="ta-rule-table" role="table" aria-label={kind === "PLAN" ? "交易计划" : "独立提醒"}>
      <div role="row" className={`ta-rule-row ta-rule-row--header${kind === "ALERT" ? " ta-rule-row--alert" : ""}`}>{["股票", ...(kind === "PLAN" ? ["方向"] : []), "截止时间", "触发条件 · 全部满足", "验证状态", "触发结果", "飞书通知"].map(label => <span role="columnheader" key={label}>{label}</span>)}</div>
      {rules.data?.items.map(row => <button type="button" key={row.ruleId} className={`ta-rule-row${kind === "ALERT" ? " ta-rule-row--alert" : ""}`} onClick={() => setOverlay({ ruleId: row.ruleId })} aria-label={`查看${row.stockRef.name}详情`}>
        <span>{row.stockRef.name}<small className="num">{row.stockRef.tsCode}</small></span>{"direction" in row && <span>{row.direction === "BUY" ? "买入" : "卖出"}</span>}
        <span className="num">{ruleTime(row.deadlineAt)}<small>北京时间</small></span><span className="ta-rule-condition-summary" title={row.conditionSummary}>{row.conditionSummary}</span><span>{checkLabel(row.checkStatus)}</span><span>{resultLabel(row)}</span><span>{notificationLabel(row.notificationSummary)}</span>
      </button>)}
    </div>
    {rules.loading && <p role="status">正在读取规则…</p>}{rules.error && <div role="alert" className="ta-form-error">规则暂时无法读取。<TradingAssistantAction onClick={rules.data ? rules.more : rules.refresh}>重新读取</TradingAssistantAction></div>}
    {!rules.loading && !rules.error && !rules.data?.items.length && <p className="ta-note">暂无符合条件的{kind === "PLAN" ? "交易计划" : "独立提醒"}</p>}
    {rules.data?.nextCursor && <TradingAssistantAction disabled={rules.loading} onClick={rules.more}>加载更多</TradingAssistantAction>}
    <p className="ta-note">“已触发”仅表示条件成立，不代表成交。数据不完整时保留“待确认”，不会记为未触发。所有时间均为北京时间。</p>
    {overlay === "CREATE" && <RuleCreateDialog kind={kind} accounts={accounts} selected={selected} onClose={() => setOverlay(null)} onSaved={async () => { changed(); }} />}
    {overlay && overlay !== "CREATE" && <RuleDetailDialog kind={kind} ruleId={overlay.ruleId} onClose={() => setOverlay(null)} onUpdated={changed} />}
  </section>;
}
