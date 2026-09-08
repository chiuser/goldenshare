import { useEffect, useRef, type RefObject } from "react";
import { fetchStockWatchlistGroups } from "../api/watchlistApi";
import type { useWatchlistItemsController } from "../model/useWatchlistItemsController";
import { mutationLocked } from "../model/watchlistTypes";
import type { WatchlistAddResponseDto } from "../api/watchlistApiTypes";
import { createPortal } from "react-dom";
import { useWatchlistSearchController } from "../model/useWatchlistSearchController";
import { useWatchlistDialog } from "./useWatchlistDialog";
import "./watchlist.css";
interface Props {
  open: boolean;
  onClose: () => void;
  groupId: number;
  groupName: string;
  onAdd: (tsCode: string) => Promise<WatchlistAddResponseDto | null>;
  mutation: ReturnType<typeof useWatchlistItemsController>["mutation"];
  onRetryRead: () => Promise<boolean>;
  membershipReader?: RefObject<((tsCode: string) => Promise<boolean>) | null>;
}
export function AddWatchlistDialog({
  open,
  onClose,
  onAdd,
  groupId,
  groupName,
  mutation,
  onRetryRead,
  membershipReader
}: Props) {
  const dialogRef = useWatchlistDialog(open);
  const search = useWatchlistSearchController(groupId, open);
  useEffect(() => {
    if (!membershipReader) return;
    membershipReader.current = async tsCode => {
      if (open && search.items.some(item => item.tsCode === tsCode)) {
        const response = await search.refresh();
        if (!response) return false;
        if (response.items.some(item => item.tsCode === tsCode)) return true;
      }
      try {
        await fetchStockWatchlistGroups(tsCode);
        return true;
      } catch {
        return false;
      }
    };
    return () => {
      membershipReader.current = null;
    };
  }, [membershipReader, open, search.refresh, search.items]);
  const locked = mutationLocked(mutation);
  const close = () => {
    if (!locked) onClose();
  };
  const feedback = mutation.kind === "unknown" ? "提交结果待确认，请先读取最新状态" : mutation.kind === "failed" ? mutation.error.message : mutation.kind === "succeeded" && mutation.action.groupId === groupId ? `已添加到「${groupName}」` : "";
  const epoch = useRef(0);
  useEffect(() => {
    epoch.current += 1;
    return () => {
      epoch.current += 1;
    };
  }, [open, groupId]);
  async function add(tsCode: string) {
    const currentEpoch = epoch.current;
    try {
      const result = await onAdd(tsCode);
      if (result && epoch.current === currentEpoch) search.retry();
    } catch {/* The Items controller owns the write outcome. */}
  }
  return createPortal(<dialog ref={dialogRef} className="watchlist-dialog watchlist-add-dialog" aria-modal="true" aria-labelledby="watchlist-add-title" onCancel={event => {
    event.preventDefault();
    close();
  }} onClick={event => {
    event.stopPropagation();
    if (event.target === event.currentTarget) close();
  }}>
      <div className="watchlist-dialog-shell" onClick={event => event.stopPropagation()}>
        <header>
          <h2 id="watchlist-add-title">添加自选</h2>
          <p>添加到「{groupName}」 · 仅支持当前上市 A 股</p>
          <button className="watchlist-dialog-close" type="button" aria-label="关闭添加自选" disabled={locked} onClick={close}>
            ×
          </button>
        </header>
        <input autoFocus className="watchlist-search-input" aria-label="搜索股票" placeholder="输入名称首字母或代码" value={search.keyword} disabled={locked} onChange={event => {
        search.setKeyword(event.target.value);
      }} onCompositionStart={() => search.setComposing(true)} onCompositionEnd={() => search.setComposing(false)} />
        <div className="watchlist-search-results" role="table" aria-label="搜索结果">
          <div role="row" className="watchlist-search-header">
            <span role="columnheader">代码</span>
            <span role="columnheader">名称</span>
            <span role="columnheader" className="watchlist-search-status">
              状态
            </span>
          </div>
          <div role="rowgroup" className="watchlist-search-body" aria-busy={search.status === "loading"}>
            {search.status === "loading" && <p className="watchlist-search-message" role="status">
                正在搜索…
              </p>}
            {search.status === "empty" && <p className="watchlist-search-message">
                未找到匹配的当前上市 A 股
              </p>}
            {search.status === "error" && <div className="watchlist-search-message" role="alert">
                {search.error}
                {search.canRetry && <button type="button" onClick={search.retry}>
                    重试
                  </button>}
              </div>}
            {search.items.map(item => {
            const isAdded = item.status === "ADDED" || mutation.kind === "succeeded" && mutation.action.groupId === groupId && mutation.result.tsCode === item.tsCode;
            const pending = mutation.kind === "pending" && mutation.action.tsCode === item.tsCode;
            return <div role="row" className="watchlist-search-row" key={item.tsCode}>
                  <span role="cell" className="num">
                    {item.tsCode}
                  </span>
                  <span role="cell">{item.name}</span>
                  <span role="cell" className="watchlist-search-status">
                    {isAdded ? <span className="watchlist-added">已添加</span> : <button type="button" className="watchlist-plus" aria-label={`添加 ${item.name} ${item.tsCode}`} disabled={locked} onClick={() => void add(item.tsCode)}>
                        {pending ? <span aria-hidden="true">…</span> : <svg className="watchlist-plus-icon" viewBox="0 0 16 16" aria-hidden="true">
                            <path d="M8 2v12M2 8h12" />
                          </svg>}
                      </button>}
                  </span>
                </div>;
          })}
          </div>
        </div>
        <footer>
          <span role="status">{feedback || "输入后停顿 0.5s 自动搜索"}</span>
          {mutation.kind === "unknown" && <button type="button" onClick={() => void onRetryRead()}>重试读取</button>}
          <button type="button" disabled={locked} onClick={close}>
            完成
          </button>
        </footer>
      </div>
    </dialog>, document.body);
}
