import { useEffect, useRef, useState } from "react";
import { WatchlistGroupDialog, WatchlistPalette, type WatchlistDialogProps } from "./CreateWatchlistGroupDialog";
export function ChangeWatchlistGroupColorDialog(props: WatchlistDialogProps & {
  name: string;
  color: string | null;
  palette: string[];
  onConfirm: (color: string) => void;
}) {
  const [color, setColor] = useState(props.color ?? "");
  const wasOpen = useRef(false);
  useEffect(() => {
    if (props.open && !wasOpen.current) setColor(props.color ?? "");
    wasOpen.current = props.open;
  }, [props.open, props.color]);
  return <WatchlistGroupDialog {...props} variant="color" title="修改分组颜色" onConfirm={() => props.onConfirm(color)}>
    <p>修改「{props.name}」的颜色，不改变分组成员。</p>
    <WatchlistPalette palette={props.palette} value={color} onChange={setColor} disabled={props.locked} />
    <p>颜色允许重复；股票左侧色条仍按分组创建顺序排列。</p>
  </WatchlistGroupDialog>;
}
