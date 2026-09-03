import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useWatchlistSearchController } from "../model/useWatchlistSearchController";
import { useWatchlistDialog } from "./useWatchlistDialog";
import "./watchlist.css";

interface Props {
  open: boolean;
  onClose: () => void;
  onAdd: (tsCode: string) => Promise<unknown>;
  pendingCodes: string[];
  memberships: Record<string, boolean>;
}
export function AddWatchlistDialog({
  open,
  onClose,
  onAdd,
  pendingCodes,
  memberships,
}: Props) {
  const dialogRef = useWatchlistDialog(open);
  const search = useWatchlistSearchController(open);
  const [feedback, setFeedback] = useState("");
  const epoch = useRef(0);
  useEffect(() => {
    epoch.current += 1;
    if (!open) setFeedback("");
    return () => {
      epoch.current += 1;
    };
  }, [open]);
  async function add(tsCode: string) {
    const currentEpoch = epoch.current;
    setFeedback("");
    try {
      await onAdd(tsCode);
      if (epoch.current === currentEpoch) setFeedback("已添加到列表末尾");
    } catch (error) {
      if (epoch.current === currentEpoch)
        setFeedback(
          error instanceof Error ? error.message : "添加失败，请重试",
        );
    }
  }
  return createPortal(
    <dialog
      ref={dialogRef}
      className="watchlist-dialog watchlist-add-dialog"
      aria-modal="true"
      aria-labelledby="watchlist-add-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        event.stopPropagation();
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="watchlist-dialog-shell"
        onClick={(event) => event.stopPropagation()}
      >
        <header>
          <h2 id="watchlist-add-title">添加自选</h2>
          <p>仅支持当前上市 A 股</p>
          <button
            className="watchlist-dialog-close"
            type="button"
            aria-label="关闭添加自选"
            onClick={onClose}
          >
            ×
          </button>
        </header>
        <input
          autoFocus
          className="watchlist-search-input"
          aria-label="搜索股票"
          placeholder="输入名称首字母或代码"
          value={search.keyword}
          onChange={(event) => {
            search.setKeyword(event.target.value);
            setFeedback("");
          }}
          onCompositionStart={() => search.setComposing(true)}
          onCompositionEnd={() => search.setComposing(false)}
        />
        <div
          className="watchlist-search-results"
          role="table"
          aria-label="搜索结果"
        >
          <div role="row" className="watchlist-search-header">
            <span role="columnheader">代码</span>
            <span role="columnheader">名称</span>
            <span role="columnheader" className="watchlist-search-status">
              状态
            </span>
          </div>
          <div
            role="rowgroup"
            className="watchlist-search-body"
            aria-busy={search.status === "loading"}
          >
            {search.status === "loading" && (
              <p className="watchlist-search-message" role="status">
                正在搜索…
              </p>
            )}
            {search.status === "empty" && (
              <p className="watchlist-search-message">
                未找到匹配的当前上市 A 股
              </p>
            )}
            {search.status === "error" && (
              <div className="watchlist-search-message" role="alert">
                {search.error}
                {search.canRetry && (
                  <button type="button" onClick={search.retry}>
                    重试
                  </button>
                )}
              </div>
            )}
            {search.items.map((item) => {
              const isAdded =
                memberships[item.tsCode] ?? item.status === "ADDED";
              const pending = pendingCodes.includes(item.tsCode);
              return (
                <div
                  role="row"
                  className="watchlist-search-row"
                  key={item.tsCode}
                >
                  <span role="cell" className="num">
                    {item.tsCode}
                  </span>
                  <span role="cell">{item.name}</span>
                  <span role="cell" className="watchlist-search-status">
                    {isAdded ? (
                      <span className="watchlist-added">已添加</span>
                    ) : (
                      <button
                        type="button"
                        className="watchlist-plus"
                        aria-label={`添加 ${item.name} ${item.tsCode}`}
                        disabled={pending}
                        onClick={() => void add(item.tsCode)}
                      >
                        {pending ? (
                          <span aria-hidden="true">…</span>
                        ) : (
                          <svg
                            className="watchlist-plus-icon"
                            viewBox="0 0 16 16"
                            aria-hidden="true"
                          >
                            <path d="M8 2v12M2 8h12" />
                          </svg>
                        )}
                      </button>
                    )}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
        <footer>
          <span role="status">{feedback || "输入后停顿 0.5s 自动搜索"}</span>
          <button type="button" onClick={onClose}>
            完成
          </button>
        </footer>
      </div>
    </dialog>,
    document.body,
  );
}
