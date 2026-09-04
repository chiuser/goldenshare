import { DataStatusBadge } from "../../../../../shared/ui/DataStatusBadge";
import { DAILY_LEVEL_LABELS } from "../api/sectorDailyInsightAdapter";
import type { SectorDailyInsightController } from "../model/useSectorDailyInsightController";

export function DailyInsightToolbar({ controller }: { controller: SectorDailyInsightController }) {
  const { urlState, viewState } = controller;
  const { meta, snapshot, kind } = viewState;
  const date = snapshot?.facts.observedTradeDate ?? urlState?.tradeDate ?? meta?.defaultTradeDate;
  const previous = snapshot?.facts.previousTradeDate ?? (urlState?.tradeDate === null ? meta?.dateContext.previousTradeDate : null);
  const status = kind === "delayed" ? `当前展示 ${date} 盘后数据` : kind === "loading" ? "正在加载" : kind === "error" ? "读取失败" : kind === "empty" ? "暂无数据" : "盘后事实已准备";
  return <section className="daily-insight-toolbar" aria-label="每日洞察筛选条件">
    <div className="daily-insight-toolbar-primary">
      <span>洞察层级</span>
      <div className="daily-insight-levels" aria-label="洞察层级">
        {([1, 2, 3] as const).map((level) => <button key={level} type="button" disabled={!urlState} aria-pressed={urlState?.level === level} className={urlState?.level === level ? "active" : ""} onClick={() => controller.selectLevel(level)}>{DAILY_LEVEL_LABELS[level]}</button>)}
      </div>
      <label className="daily-insight-date"><span>分析日期</span><select aria-label="分析日期" disabled={!meta || !urlState} value={urlState?.tradeDate ?? ""} onChange={(event) => controller.selectTradeDate(event.target.value || null)}>
        <option value="">按公共行情日期</option>
        {urlState?.tradeDate && !meta?.tradeDates.some((day) => day.tradeDate === urlState.tradeDate) ? <option value={urlState.tradeDate}>{urlState.tradeDate}</option> : null}
        {meta?.tradeDates.map((day) => <option key={day.tradeDate} value={day.tradeDate}>{day.tradeDate}{day.availability === "MISSING" ? " · 未发布" : ""}</option>)}
      </select></label>
    </div>
    <div className="daily-insight-toolbar-context">
      <span>当前：<span className="num">{date ?? "--"}</span></span>
      <span className="daily-insight-previous">上一交易日：<span className="num">{previous ?? "--"}</span></span>
      <span className={`daily-insight-status ${kind}`} role="status" title={kind === "delayed" ? meta?.dateContext.delayReason ?? undefined : undefined}><DataStatusBadge tone={kind === "delayed" ? "delayed" : "ready"} label={status} /></span>
    </div>
  </section>;
}
