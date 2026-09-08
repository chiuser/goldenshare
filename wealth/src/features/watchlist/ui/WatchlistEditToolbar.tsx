import type { WatchlistEditDialog } from "../model/useWatchlistEditController";
export function WatchlistEditToolbar({
  count,
  maxSelection,
  isDefault,
  locked,
  onDialog,
  onPin,
  onDone
}: {
  count: number;
  maxSelection: number;
  isDefault: boolean;
  locked: boolean;
  onDialog: (dialog: WatchlistEditDialog) => void;
  onPin: (pin: boolean) => void;
  onDone: () => void;
}) {
  return <div className="watchlist-edit-toolbar" role="toolbar" aria-label="自选编辑操作">
    <span className="watchlist-selection-count" title={count >= maxSelection ? `单次最多选择 ${maxSelection} 只` : undefined}>已选择 {count} 只</span>
    <button type="button" disabled={locked || !count} onClick={() => onDialog("move")}>移动分组</button>
    <button type="button" disabled={locked || !count} onClick={() => onDialog("add")}>添加到分组</button>
    <button type="button" className="watchlist-danger" disabled={locked || !count} onClick={() => onDialog("remove")}>移出本组</button>
    <button type="button" disabled={locked || !count} onClick={() => onPin(true)}>置顶</button>
    <button type="button" disabled={locked || !count} onClick={() => onPin(false)}>取消置顶</button>
    <button type="button" disabled={locked || isDefault} onClick={() => onDialog("color")}>修改颜色</button>
    <button type="button" className="watchlist-danger" disabled={locked || isDefault} onClick={() => onDialog("delete")}>删除分组</button>
    <button type="button" className="watchlist-done" disabled={locked} onClick={onDone}>完成</button>
  </div>;
}
