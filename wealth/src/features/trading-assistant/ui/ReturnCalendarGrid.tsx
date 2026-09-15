import type { CalendarResponse } from "../api/generatedContracts";
import { positionNumber as money, positionPercent as percent, profitTone } from "../model/positionPresentation";
import { shiftReturnMonth, type ReturnMetric } from "../model/returnSelection";
import { ReturnMetricTabs } from "./ReturnMetricTabs";
import previousIcon from "../assets/calendar-previous.svg";
import nextIcon from "../assets/calendar-next.svg";

export function ReturnCalendarGrid({ calendar, month, metric, selectedDay, onMonth, onMetric, onDay }: {
  calendar: CalendarResponse | null; month: string; metric: ReturnMetric; selectedDay: string | null;
  onMonth: (month: string) => void; onMetric: (metric: ReturnMetric) => void; onDay: (day: string) => void;
}) {
  return <section className="ta-return-calendar" aria-label="收益日历">
    <div className="ta-return-calendar-toolbar"><div className="ta-return-month">
      <button type="button" aria-label="上个月" disabled={month === "0001-01"} onClick={() => onMonth(shiftReturnMonth(month + "-01", -1).slice(0,7))}><img src={previousIcon} alt="" /></button>
      <h2>{month.slice(0,4)} 年 {Number(month.slice(5))} 月</h2>
      <button type="button" aria-label="下个月" disabled={month === "9999-12"} onClick={() => onMonth(shiftReturnMonth(month + "-01", 1).slice(0,7))}><img src={nextIcon} alt="" /></button>
    </div><ReturnMetricTabs value={metric} onChange={onMetric} /></div>
    <p className="ta-note">{calendar?.calculatedThrough ? `数据截至 ${calendar.calculatedThrough}` : "尚无完整收益截止日期"}</p>
    <div className="ta-return-weekdays" aria-hidden="true">{["周一","周二","周三","周四","周五"].map(day => <span key={day}>{day}</span>)}</div>
    <div className="ta-return-days">{calendar?.days.map(day => {
      const future = day.temporalState === "FUTURE", hasResult = day.profitAmount !== null;
      return <button type="button" key={day.date} aria-label={day.date} disabled={future} aria-pressed={selectedDay === day.date}
        title={future ? day.date : hasResult ? `${money(day.profitAmount,true)} · ${percent(day.returnPct,true)}` : day.reason || "待计算"}
        className={`ta-return-day ${!day.inSelectedMonth || future ? "ta-return-day--muted" : ""}`} onClick={() => onDay(day.date)}>
        <span className="ta-return-day-date num">{Number(day.date.slice(8))}</span>
        {!future && (hasResult ? <span className="ta-return-day-values"><strong className={`num ${profitTone(day.profitAmount)}`}>{metric === "AMOUNT" ? money(day.profitAmount,true) : percent(day.returnPct,true)}</strong>
          <small className="num">{metric === "AMOUNT" ? percent(day.returnPct,true) : money(day.profitAmount,true)}</small></span> : <span className="ta-return-day-pending">待计算</span>)}
      </button>;
    })}</div>
  </section>;
}
