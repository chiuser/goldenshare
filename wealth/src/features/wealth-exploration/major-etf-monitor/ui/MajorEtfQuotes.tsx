import { Panel } from "../../../../shared/ui/Panel";
import { formatEtfPrice, formatEtfPriceChange, formatTurnover } from "../../etf-activity/model/etfActivityFormatters";
import type { MajorEtfQuote } from "../api/majorEtfMonitorApi";
import type { MajorEtfMonitorState } from "../model/useMajorEtfMonitor";

const TITLE = "主要ETF（国家队）行情";
const COLUMNS = ["ETF 代码", "ETF 名称", "现价（元）", "涨跌幅", "成交额（亿元）"];

function QuoteRow({ quote }: { quote: MajorEtfQuote }) {
  const { tsCode, name, closePrice, priceChangePct, amountYuan } = quote;
  const change = priceChangePct === null ? { text: "—", className: "flat" } : formatEtfPriceChange(priceChangePct);
  return (
    <tr>
      <td className="num etf-code">{tsCode}</td>
      <td className="major-etf-name" title={name ?? undefined}>{name ?? "—"}</td>
      <td className="num">{closePrice === null ? "—" : formatEtfPrice(closePrice)}</td>
      <td className={`num ${change.className}`}>{change.text}</td>
      <td className="num">{formatTurnover(amountYuan)}</td>
    </tr>
  );
}

export function MajorEtfQuotes({ state, onRetry }: { state: MajorEtfMonitorState; onRetry: () => void }) {
  const { data, status } = state;
  const quotes = data?.quotes ?? [];
  const hasQuotes = quotes.length > 0;
  const tradeDate = hasQuotes ? data?.tradeDate : null;
  const loading = status === "loading";
  const failed = status === "error" || status === "timeout";
  let message = "暂无可用的主要ETF行情";
  if (status === "error") message = "主要ETF行情暂不可读取";
  if (status === "timeout") message = "主要ETF行情请求超时";

  return (
    <Panel title={TITLE} className="etf-activity-panel major-etf-quotes"
      meta={hasQuotes && <span className="etf-panel-meta">14 只 ETF</span>}>
      <div className="etf-rank-dates" role={loading ? "status" : undefined}>
        {loading ? "正在读取主要ETF行情…" : (
          <span>日线收盘 <time className="num" dateTime={tradeDate ?? undefined}>{tradeDate ?? "—"}</time></span>
        )}
      </div>
      <div className="major-etf-quotes-scroll" role="region" aria-label="主要ETF 行情表体"
        tabIndex={hasQuotes ? 0 : undefined} aria-busy={loading}>
        <table aria-label={TITLE}>
          <colgroup>{COLUMNS.map((label) => <col key={label} />)}</colgroup>
          <thead><tr>{COLUMNS.map((label) => <th key={label} scope="col">{label}</th>)}</tr></thead>
          <tbody>
            {quotes.map((quote) => <QuoteRow key={quote.tsCode} quote={quote} />)}
            {loading && Array.from({ length: 10 }, (_, index) => (
              <tr key={index} aria-hidden="true">{COLUMNS.map((label) => <td key={label}><i /></td>)}</tr>
            ))}
          </tbody>
        </table>
        {!hasQuotes && !loading && (
          <div className="etf-state major-etf-quotes-state" role={failed ? "alert" : "status"}>
            {message}
            {failed && <button className="tab-btn" type="button" onClick={onRetry}>重试</button>}
          </div>
        )}
      </div>
    </Panel>
  );
}
