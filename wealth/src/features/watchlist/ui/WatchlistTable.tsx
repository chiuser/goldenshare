import { useEffect, useRef } from "react";
import type { WatchlistRowViewModel } from "../model/watchlistTypes";
import type { WatchlistDirection, WatchlistSort, WatchlistSortField } from "../api/watchlistApiTypes";
import { WatchlistColorMarks } from "./WatchlistColorMarks";
import "./watchlist.css";
const columns = [["stock-code-column", "股票代码"], ["stock-name-column", "股票名称"], ["price-column", "最新价（元）"], ["change-column", "涨跌幅（%）"], ["volume-column", "成交量（万手）"], ["pe-column", "市盈率（PE TTM）"], ["pb-column", "市净率（PB）"], ["ratio-column", "量比"], ["turnover-column", "换手率（%）"], ["money-column", "资金净流入（万）"], ["sector-column", "所属板块"]] as const;
const sortFields: Record<string, WatchlistSortField> = {
  "price-column": "price",
  "change-column": "changePct",
  "volume-column": "vol",
  "pe-column": "peTtm",
  "pb-column": "pb",
  "ratio-column": "volumeRatio",
  "turnover-column": "turnoverRate",
  "money-column": "netAmount"
};
const direction = (value: WatchlistDirection) => value === "UNKNOWN" ? "watchlist-missing" : value.toLowerCase();
interface Props {
  rows: WatchlistRowViewModel[];
  editing: boolean;
  selectedIds: Set<number>;
  maxSelection: number;
  locked: boolean;
  sort: WatchlistSort | null;
  onSort: (field: WatchlistSortField) => void;
  onToggle: (id: number) => void;
  hasMore: boolean;
  loadingMore: boolean;
  loadMoreError: string | null;
  scrollResetKey: number;
  onLoadMore: () => void;
  onRetryMore: () => void;
  onSelect: (code: string) => void;
}
export function WatchlistTable({
  rows,
  editing,
  selectedIds,
  maxSelection,
  locked,
  sort,
  onSort,
  onToggle,
  hasMore,
  loadingMore,
  loadMoreError,
  scrollResetKey,
  onLoadMore,
  onRetryMore,
  onSelect
}: Props) {
  const viewport = useRef<HTMLDivElement>(null);
  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (viewport.current) viewport.current.scrollTop = 0;
  }, [scrollResetKey]);
  useEffect(() => {
    if (!hasMore || loadingMore || loadMoreError || locked || !sentinel.current) return;
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) onLoadMore();
    }, {
      root: viewport.current,
      rootMargin: "120px 0px"
    });
    observer.observe(sentinel.current);
    return () => observer.disconnect();
  }, [hasMore, loadingMore, loadMoreError, onLoadMore, locked]);
  const clickRow = (row: WatchlistRowViewModel) => {
    if (locked) return;
    if (editing) onToggle(row.membershipId);else onSelect(row.tsCode);
  };
  return <div ref={viewport} className={`watchlist-table-scroll${editing ? " is-editing" : ""}`} aria-label="自选股票滚动区域" tabIndex={0}>
      <table className="watchlist-table" aria-label="自选股票列表">
        <colgroup>
          <col className="color-marks-column" />
          {editing && <col className="selection-column" />}
          {columns.map(([key]) => <col className={key} key={key} />)}
        </colgroup>
        <thead>
          <tr>
            <th scope="col" className="color-marks-column" aria-label="所属分组颜色" />
            {editing && <th scope="col" className="selection-column">选择</th>}
            {columns.map(([key, label]) => <th scope="col" className={key} key={key} aria-sort={sortFields[key] ? sort?.sortBy === sortFields[key] ? sort.direction === "desc" ? "descending" : "ascending" : "none" : undefined}>
                {sortFields[key] ? <button type="button" className="watchlist-sort" disabled={locked} onClick={() => onSort(sortFields[key])}>{label} <span aria-hidden="true">{sort?.sortBy === sortFields[key] ? sort.direction === "desc" ? "↓" : "↑" : "↕"}</span></button> : <span>{label}</span>}
              </th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map(row => <tr key={row.membershipId} className={selectedIds.has(row.membershipId) ? "is-selected" : undefined} onClick={() => clickRow(row)}>
              <td className="color-marks-column"><WatchlistColorMarks marks={row.groupMarks} /></td>
              {editing && <td className="selection-column"><input type="checkbox" aria-label={`选择 ${row.name} ${row.tsCode}`} checked={selectedIds.has(row.membershipId)} disabled={locked || !selectedIds.has(row.membershipId) && selectedIds.size >= maxSelection} onClick={event => event.stopPropagation()} onChange={() => onToggle(row.membershipId)} /></td>}
              <td className="stock-code-column">
                <button className="watchlist-stock-link num" type="button" onClick={event => {
              event.stopPropagation();
              clickRow(row);
            }}>
                  {row.tsCode}
                </button>
              </td>
              <td className="stock-name-column">
                <span>{row.name}</span>
              </td>
              <td className={`price-column num ${direction(row.price === "--" ? "UNKNOWN" : row.priceDirection)}`}>
                <span>{row.price}</span>
              </td>
              <td className={`change-column num ${direction(row.priceDirection)}`}>
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
              <td className={`money-column num ${direction(row.moneyFlowDirection)}`}>
                <span>{row.netAmount}</span>
              </td>
              <td className="sector-column">
                <span className="watchlist-sector-wrap">
                  {row.industry === "--" ? <span className="watchlist-sector-empty">--</span> : <span className="watchlist-sector-tag" title={row.industry}>
                      {row.industry}
                    </span>}
                </span>
              </td>
            </tr>)}
        </tbody>
      </table>
      {hasMore && !loadMoreError && <div ref={sentinel} className="watchlist-load-more" role="status">
          {loadingMore ? "正在加载更多…" : "向下滚动加载更多"}
        </div>}
      {loadMoreError && <div className="watchlist-load-more" role="alert">
          {loadMoreError}
          <button type="button" onClick={onRetryMore}>
            重试
          </button>
        </div>}
    </div>;
}
