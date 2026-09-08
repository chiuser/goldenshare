import { WatchlistGroupDialog, type WatchlistDialogProps } from "./CreateWatchlistGroupDialog";
export function ConfirmWatchlistRemoveDialog(props: WatchlistDialogProps & {
  name: string;
  count: number;
  onConfirm: () => void;
}) {
  return <WatchlistGroupDialog {...props} variant="remove" title="移出本组" danger confirmLabel="确认移出" disabled={!props.count}>
    <p>将 {props.count} 只股票移出「{props.name}」？</p><p>只影响当前组，其他分组归属保持不变。</p>
  </WatchlistGroupDialog>;
}
