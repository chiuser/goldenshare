import { Panel } from "../../../../shared/ui/Panel";
import type { EtfActivityResponse } from "../api/etfActivityApi";
import { formatEtfPrice, formatEtfPriceChange, formatEtfRankChange, formatTurnover } from "../model/etfActivityFormatters";

const COLUMNS = ["今日排名", "ETF 代码", "ETF 名称", "现价（元）", "涨跌幅", "成交额（亿元）", "较前一交易日"];

export function EtfActivityRanking({ data, pending, failed, onRetry }: {
  data: EtfActivityResponse | null;
  pending: boolean;
  failed: boolean;
  onRetry: () => void;
}) {
  const ranking = data?.ranking;
  const hasRanks = ranking?.status === "ready" || ranking?.status === "partial";
  const isLoading = pending && !data;
  const error = ranking?.status === "error";
  return (
    <Panel title="ETF 成交额排行榜" className="etf-activity-panel etf-rank-panel" meta={hasRanks ? <span className="etf-panel-meta">前 50 名</span> : undefined}>
      {hasRanks && (
        <div className="etf-rank-dates">
          <span>日线收盘 <time className="num" dateTime={data?.tradeDate ?? undefined}>{data?.tradeDate}</time></span>
          {ranking.status === "ready" && data?.previousTradeDate && <span>对比日 <time className="num" dateTime={data.previousTradeDate}>{data.previousTradeDate}</time></span>}
        </div>
      )}
      {ranking?.status === "partial" && (
        <p className="etf-rank-note">
          {data?.previousTradeDate ? `前一交易日（${data.previousTradeDate}）日线暂缺，名次变化显示 —。` : "暂无前一交易日可供比较"}
        </p>
      )}
      {isLoading && <div className="etf-rank-dates" role="status">正在读取 ETF 榜单…</div>}
      {failed || error ? (
        <div className="etf-state" role={error ? "alert" : undefined}>
          {error ? ranking.error?.message : "ETF 排行榜暂不可读取"}
          {error && <button className="tab-btn" type="button" disabled={pending} onClick={onRetry}>{pending ? "正在重试…" : "重试"}</button>}
        </div>
      ) : (
        <div className={`etf-rank-scroll${hasRanks || isLoading ? "" : " etf-rank-scroll--empty"}`} role="region" aria-label="ETF 排行表体"
          tabIndex={hasRanks ? 0 : undefined} aria-busy={isLoading}>
          <table aria-label="ETF 成交额排行榜">
            <colgroup>{COLUMNS.map((label) => <col key={label} />)}</colgroup>
            <thead><tr>{COLUMNS.map((label) => <th key={label} scope="col">{label}</th>)}</tr></thead>
            <tbody>
              {ranking?.rows.map((row) => {
                const priceChange = formatEtfPriceChange(row.priceChangePct);
                const rankChange = formatEtfRankChange(row.rankChange);
                return (
                  <tr key={row.tsCode}>
                    <td className="num">{row.rank}</td>
                    <td className="num etf-code">{row.tsCode}</td>
                    <td className="etf-name">{row.name ?? "—"}</td>
                    <td className="num">{formatEtfPrice(row.closePrice)}</td>
                    <td className={`num ${priceChange.className}`}>{priceChange.text}</td>
                    <td className="num">{formatTurnover(row.amountYuan)}</td>
                    <td className={`num ${rankChange.className}`}>{rankChange.text}</td>
                  </tr>
                );
              })}
              {isLoading && Array.from({ length: 10 }, (_, index) => (
                <tr key={index} aria-hidden="true"><td><i /></td><td colSpan={2}><i /><i /></td><td colSpan={4} /></tr>
              ))}
            </tbody>
          </table>
          {!hasRanks && !isLoading && <div className="etf-state etf-rank-empty" role="status">暂无成交额排行</div>}
        </div>
      )}
    </Panel>
  );
}
