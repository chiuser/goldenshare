import { createPortal } from "react-dom";
import { useWatchlistDialog } from "./useWatchlistDialog";
import "./watchlist.css";

interface Props {
  stock: { tsCode: string; name: string } | null;
  open: boolean;
  pending: boolean;
  error?: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}
export function RemoveWatchlistDialog({
  stock,
  open,
  pending,
  error,
  onCancel,
  onConfirm,
}: Props) {
  const dialogRef = useWatchlistDialog(open);
  return createPortal(
    <dialog
      ref={dialogRef}
      className="watchlist-dialog watchlist-remove-dialog"
      aria-modal="true"
      aria-labelledby="watchlist-remove-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!pending) onCancel();
      }}
      onClick={(event) => {
        event.stopPropagation();
        if (event.target === event.currentTarget && !pending) onCancel();
      }}
    >
      <div
        className="watchlist-dialog-shell"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="watchlist-remove-title">确认移除「{stock?.name}」？</h2>
        <p>移除后可再次通过搜索添加。</p>
        {error && (
          <p role="alert" className="watchlist-error">
            {error}
          </p>
        )}
        <footer>
          <button autoFocus type="button" disabled={pending} onClick={onCancel}>
            取消
          </button>
          <button
            type="button"
            className="watchlist-remove-confirm"
            disabled={pending}
            onClick={onConfirm}
          >
            {pending ? "处理中" : "确认移除"}
          </button>
        </footer>
      </div>
    </dialog>,
    document.body,
  );
}
