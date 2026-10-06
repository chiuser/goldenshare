import { useEffect, useRef } from "react";
import type { Task } from "../api/contracts";
import { numberText } from "../model/presentation";
import { Button } from "./primitives";
export function StopDialog({ task, busy, onCancel, onConfirm }: { task: Task; busy: boolean; onCancel: () => void; onConfirm: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { const node = dialog.current!; const previous = document.activeElement as HTMLElement | null; node.showModal(); return () => { node.close(); previous?.focus(); }; }, []);
  return <dialog ref={dialog} className="dc-dialog" aria-labelledby="dc-stop-title" onCancel={e => { if (busy) e.preventDefault(); else onCancel(); }}>
    <h2 id="dc-stop-title">停止当前下载任务？</h2><p>已完成的文件会保留。停止后可继续原任务未完成的文件，失败项可单独重试。</p>
    <p className="dc-muted num">已处理 {numberText(task.processed)} / {numberText(task.total)} 个文件 · 剩余 {numberText(task.remaining)}</p>
    <div className="dc-actions"><Button disabled={busy} autoFocus onClick={onCancel}>继续下载</Button><Button tone="danger" disabled={busy} onClick={onConfirm}>确认停止</Button></div>
  </dialog>;
}
