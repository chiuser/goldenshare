import { WatchlistGroupDialog, type WatchlistDialogProps } from "./CreateWatchlistGroupDialog";
export function ConfirmWatchlistGroupDeleteDialog(props: WatchlistDialogProps & {
  name: string;
  memberCount: number;
  onConfirm: () => void;
}) {
  return <WatchlistGroupDialog {...props} variant="delete" title="删除分组" danger confirmLabel="确认删除">
    <p>删除「{props.name}」及其 {props.memberCount} 只股票的组内关系？</p><p>其他分组中的股票保持不变。</p>
  </WatchlistGroupDialog>;
}
