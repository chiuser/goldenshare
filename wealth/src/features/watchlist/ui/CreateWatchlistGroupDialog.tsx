import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { WatchlistGroupDto, WatchlistGroupRulesDto } from "../api/watchlistApiTypes";
import { validateWatchlistGroupName } from "../model/watchlistGroupName";
import { useWatchlistDialog } from "./useWatchlistDialog";
import "./watchlist.css";
export interface WatchlistDialogProps {
  open: boolean;
  locked: boolean;
  error?: string;
  onCancel: () => void;
  onRetryRead?: () => void;
  available?: boolean;
}
export function WatchlistGroupDialog({
  open,
  available = true,
  locked,
  error,
  onCancel,
  onRetryRead,
  title,
  children,
  onConfirm,
  confirmLabel = "确认",
  disabled = false,
  danger = false,
  variant = "add"
}: WatchlistDialogProps & {
  title: string;
  children: ReactNode;
  onConfirm: () => void;
  confirmLabel?: string;
  disabled?: boolean;
  danger?: boolean;
  variant?: "create" | "move" | "add" | "remove" | "delete" | "color";
}) {
  const ref = useWatchlistDialog(open && available);
  const titleId = useId();
  return createPortal(<dialog ref={ref} className={`watchlist-dialog watchlist-group-dialog watchlist-group-dialog-${variant}`} aria-modal="true" aria-labelledby={titleId} onCancel={event => {
    event.preventDefault();
    if (!locked) onCancel();
  }} onClick={event => {
    event.stopPropagation();
    if (event.currentTarget === event.target && !locked) onCancel();
  }}>
    <div className="watchlist-dialog-shell" onClick={event => event.stopPropagation()}>
      <h2 id={titleId}>{title}</h2>{danger && <span className="watchlist-warning" aria-hidden="true">!</span>}{children}
      {error && <p role="alert" className="watchlist-error">{error}</p>}
      {onRetryRead && <button type="button" onClick={onRetryRead}>重试读取</button>}
      <footer><button type="button" disabled={locked} onClick={onCancel}>取消</button>
        <button type="button" className={danger ? "watchlist-remove-confirm" : "watchlist-confirm"} disabled={locked || disabled} onClick={onConfirm}>{locked ? "处理中" : confirmLabel}</button>
      </footer>
    </div>
  </dialog>, document.body);
}
export function WatchlistPalette({
  palette,
  value,
  onChange,
  disabled
}: {
  palette: string[];
  value: string;
  onChange: (color: string) => void;
  disabled: boolean;
}) {
  const name = useId();
  return <div className="watchlist-palette" role="radiogroup" aria-label="分组颜色">
    {palette.map(color => <label key={color} style={{
      backgroundColor: color
    }} title={color}>
      <input type="radio" name={name} aria-label={color} value={color} checked={value === color} disabled={disabled} onChange={() => onChange(color)} />
      <span aria-hidden="true" />
    </label>)}
  </div>;
}
export function CreateWatchlistGroupDialog(props: WatchlistDialogProps & {
  groups: WatchlistGroupDto[];
  rules?: WatchlistGroupRulesDto;
  onConfirm: (name: string, color: string) => void;
}) {
  const [name, setName] = useState("");
  const [color, setColor] = useState(props.rules?.palette[0] ?? "");
  const wasOpen = useRef(false);
  useEffect(() => {
    if (props.open && !wasOpen.current) {
      setName("");
      setColor(props.rules?.palette[0] ?? "");
    }
    wasOpen.current = props.open;
  }, [props.open, props.rules]);
  // Keep the draft owner mounted if a required groups/rules reread fails.
  if (!props.rules) return null;
  const validation = validateWatchlistGroupName(name, props.rules, props.groups.map(group => group.name));
  const atLimit = props.groups.length >= props.rules.maxGroups || props.groups.filter(group => !group.isDefault).length >= props.rules.maxCustomGroups;
  return <WatchlistGroupDialog {...props} variant="create" title="新建分组" confirmLabel="创建" disabled={!!validation.error || atLimit || !color} onConfirm={() => props.onConfirm(validation.name, color)}>
    <label>分组名称<input autoFocus className="watchlist-search-input" value={name} aria-label="分组名称" disabled={props.locked} onChange={event => setName(event.target.value)} /></label>
    <p>{atLimit ? "分组数量已达上限" : name && validation.error ? validation.error : `最多 ${props.rules.nameMaxVisibleChars} 个可见字符，创建后不能改名`}</p>
    <span>分组颜色</span><WatchlistPalette palette={props.rules.palette} value={color} onChange={setColor} disabled={props.locked} />
    <p>固定色板，允许不同分组使用相同颜色</p>
  </WatchlistGroupDialog>;
}
