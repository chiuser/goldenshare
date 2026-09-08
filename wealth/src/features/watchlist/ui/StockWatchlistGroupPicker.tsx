import { useEffect, useId, useRef } from "react";
import type { useStockWatchlistGroups } from "../model/useStockWatchlistGroups";
import { mutationLocked } from "../model/watchlistTypes";
import "./watchlist.css";
export function StockWatchlistGroupPicker({
  controller
}: {
  controller: ReturnType<typeof useStockWatchlistGroups>;
}) {
  const anchor = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const popup = useRef<HTMLDivElement>(null);
  const wasOpen = useRef(false);
  const id = useId();
  const latest = useRef(controller);
  latest.current = controller;
  const locked = mutationLocked(controller.mutation);
  useEffect(() => {
    if (controller.open) {
      const target = popup.current?.querySelector<HTMLElement>(controller.status === "ready" ? "input" : "button");
      (target ?? popup.current)?.focus();
    } else if (wasOpen.current) trigger.current?.focus();
    wasOpen.current = controller.open;
  }, [controller.open, controller.status]);
  useEffect(() => {
    if (!controller.open) return;
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !anchor.current?.contains(event.target)) latest.current.cancel();
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        latest.current.cancel();
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [controller.open]);
  return <div className="stock-watchlist-anchor" ref={anchor}>
    <button ref={trigger} className="stock-header-action" type="button" aria-haspopup="dialog" aria-expanded={controller.open} aria-controls={id} disabled={controller.status === "idle" || locked || !controller.open && controller.status === "loading"} onClick={controller.open ? controller.cancel : controller.show}>
      {controller.saving ? "处理中" : controller.isAdded ? "已添加" : "+自选"}
    </button>
    {controller.open && <div ref={popup} id={id} className="stock-watchlist-picker" role="dialog" aria-label="选择自选分组" tabIndex={-1}>
      <h3>选择分组</h3><p>至少选择一个分组</p>
      {controller.status === "loading" && <p role="status">正在读取分组…</p>}
      {controller.status === "error" && <div role="alert">{controller.error}<button type="button" onClick={() => void controller.retry()}>重试读取</button></div>}
      {controller.mutation.kind === "unknown" && <p role="status">提交结果待确认，正在读取最新归属。</p>}
      {controller.mutation.kind === "failed" && <p role="alert">{controller.mutation.error.message}</p>}
      {controller.status === "ready" && <div className="watchlist-group-options">{controller.groups.map(group => <label key={group.groupId}>
        <input type="checkbox" checked={controller.draftIds.has(group.groupId)} disabled={locked} onChange={() => controller.toggle(group.groupId)} />
        <span>{group.color && <i className="watchlist-group-dot" style={{
              backgroundColor: group.color
            }} />}{group.name}</span>
      </label>)}</div>}
      <footer><button type="button" disabled={locked} onClick={controller.cancel}>取消</button><button type="button" disabled={locked || controller.status !== "ready" || !controller.draftIds.size} onClick={() => void controller.confirm()}>确认</button></footer>
    </div>}
  </div>;
}
