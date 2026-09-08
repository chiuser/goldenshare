import { useEffect, useId, useState } from "react";
import type { WatchlistGroupDto } from "../api/watchlistApiTypes";
import { WatchlistGroupDialog, type WatchlistDialogProps } from "./CreateWatchlistGroupDialog";
export function WatchlistGroupTargetDialog(props: WatchlistDialogProps & {
  mode: "move" | "add";
  currentGroupId: number;
  groups: WatchlistGroupDto[];
  onConfirm: (ids: number[]) => void;
}) {
  const [ids, setIds] = useState<number[]>([]);
  const name = useId();
  useEffect(() => {
    setIds([]);
  }, [props.open, props.mode, props.currentGroupId]);
  const targets = props.groups.filter(group => group.id !== props.currentGroupId);
  return <WatchlistGroupDialog {...props} variant={props.mode} title={props.mode === "move" ? "移动分组" : "添加到分组"} disabled={!ids.length || ids.some(id => !targets.some(group => group.id === id))} onConfirm={() => props.onConfirm(ids)}>
    <p>{props.mode === "move" ? "移入目标组，同时从当前组移出。" : "加入目标分组，保留当前组关系。"}</p>
    {!targets.length && <p>暂无可选目标分组</p>}
    <div className="watchlist-group-options">{targets.map(group => <label key={group.id}>
      <input type={props.mode === "move" ? "radio" : "checkbox"} name={name} disabled={props.locked} checked={ids.includes(group.id)} onChange={() => setIds(previous => props.mode === "move" ? [group.id] : previous.includes(group.id) ? previous.filter(id => id !== group.id) : [...previous, group.id])} />
      <span>{group.color && <i className="watchlist-group-dot" style={{
            backgroundColor: group.color
          }} />}{group.name}</span>
    </label>)}</div>
  </WatchlistGroupDialog>;
}
