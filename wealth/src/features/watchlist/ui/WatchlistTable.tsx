import { useEffect, useRef } from "react";
import type { WatchlistRowViewModel } from "../model/watchlistTypes";
import type { WatchlistDirection } from "../api/watchlistApiTypes";
import "./watchlist.css";

const columns = [
  ["stock-code-column", "股票代码"],
  ["stock-name-column", "股票名称"],
  ["price-column", "最新价（元）"],
  ["change-column", "涨跌幅（%）"],
  ["volume-column", "成交量（万手）"],
  ["pe-column", "市盈率（PE TTM）"],
  ["pb-column", "市净率（PB）"],
  ["ratio-column", "量比"],
  ["turnover-column", "换手率（%）"],
  ["money-column", "资金净流入（千万）"],
  ["sector-column", "所属板块"],
  ["action-column", "操作"],
] as const;
const direction = (value: WatchlistDirection) =>
  value === "UNKNOWN" ? "watchlist-missing" : value.toLowerCase();
interface Props {
  rows: WatchlistRowViewModel[];
  pendingCodes: string[];
  hasMore: boolean;
  loadingMore: boolean;
  loadMoreError: string | null;
  scrollResetKey: number;
  onLoadMore: () => void;
  onRetryMore: () => void;
  onSelect: (code: string) => void;
  onRemove: (row: WatchlistRowViewModel) => void;
}
export function WatchlistTable({
  rows,
  pendingCodes,
  hasMore,
  loadingMore,
  loadMoreError,
  scrollResetKey,
  onLoadMore,
  onRetryMore,
  onSelect,
  onRemove,
}: Props) {
  const viewport = useRef<HTMLDivElement>(null);
  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (viewport.current) viewport.current.scrollTop = 0;
  }, [scrollResetKey]);
  useEffect(() => {
    if (
      !hasMore ||
      loadingMore ||
      loadMoreError ||
      pendingCodes.length ||
      !sentinel.current
    )
      return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) onLoadMore();
      },
      { root: viewport.current, rootMargin: "120px 0px" },
    );
    observer.observe(sentinel.current);
    return () => observer.disconnect();
  }, [hasMore, loadingMore, loadMoreError, onLoadMore, pendingCodes.length]);
  return (
    <div
      ref={viewport}
      className="watchlist-table-scroll"
      aria-label="自选股票滚动区域"
      tabIndex={0}
    >
      <table className="watchlist-table" aria-label="自选股票列表">
        <colgroup>
          {columns.map(([key]) => (
            <col className={key} key={key} />
          ))}
        </colgroup>
        <thead>
          <tr>
            {columns.map(([key, label]) => (
              <th scope="col" className={key} key={key}>
                <span>{label}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} onClick={() => onSelect(row.tsCode)}>
              <td className="stock-code-column">
                <button
                  className="watchlist-stock-link num"
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    onSelect(row.tsCode);
                  }}
                >
                  {row.tsCode}
                </button>
              </td>
              <td className="stock-name-column">
                <span>{row.name}</span>
              </td>
              <td
                className={`price-column num ${direction(row.price === "--" ? "UNKNOWN" : row.priceDirection)}`}
              >
                <span>{row.price}</span>
              </td>
              <td
                className={`change-column num ${direction(row.priceDirection)}`}
              >
                <span>{row.changePct}</span>
              </td>
              <td className="volume-column num">
                <span>{row.vol}</span>
              </td>
              <td className="pe-column num">
                <span>{row.peTtm}</span>
              </td>
              <td className="pb-column num">
                <span>{row.pb}</span>
              </td>
              <td className="ratio-column num">
                <span>{row.volumeRatio}</span>
              </td>
              <td className="turnover-column num">
                <span>{row.turnoverRate}</span>
              </td>
              <td
                className={`money-column num ${direction(row.moneyFlowDirection)}`}
              >
                <span>{row.netAmount}</span>
              </td>
              <td className="sector-column">
                <span className="watchlist-sector-wrap">
                  <span className="watchlist-sector-tag">{row.industry}</span>
                </span>
              </td>
              <td className="action-column">
                <button
                  type="button"
                  className="watchlist-remove"
                  aria-label={`移除 ${row.name} ${row.tsCode}`}
                  disabled={pendingCodes.includes(row.tsCode)}
                  onClick={(event) => {
                    event.stopPropagation();
                    onRemove(row);
                  }}
                >
                  <span>移除</span>
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {hasMore && !loadMoreError && (
        <div ref={sentinel} className="watchlist-load-more" role="status">
          {loadingMore ? "正在加载更多…" : "向下滚动加载更多"}
        </div>
      )}
      {loadMoreError && (
        <div className="watchlist-load-more" role="alert">
          {loadMoreError}
          <button type="button" onClick={onRetryMore}>
            重试
          </button>
        </div>
      )}
    </div>
  );
}
