import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { DAILY_LEVEL_LABELS } from "../api/sectorDailyInsightAdapter";
import type { DailyInsightRowViewModel } from "../api/sectorDailyInsightTypes";
import { DAILY_EVIDENCE_LABELS, dailyInsightDestination, type DailyInsightDestination } from "../model/sectorDailyInsightNavigation";

interface Props { row: DailyInsightRowViewModel; tradeDate: string; trigger: HTMLButtonElement; onClose: () => void; onNavigate: (destination: DailyInsightDestination) => void }
export function DailyInsightExplanationDialog({ row, tradeDate, trigger, onClose, onNavigate }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    dialog.showModal();
    const dismissOnBackgroundScroll = (event: Event) => {
      if (!(event.target instanceof Node) || !dialog.contains(event.target)) onClose();
    };
    window.addEventListener("scroll", dismissOnBackgroundScroll, true);
    return () => {
      window.removeEventListener("scroll", dismissOnBackgroundScroll, true);
      if (dialog.open) dialog.close();
      if (trigger.isConnected) trigger.focus({ preventScroll: true });
    };
  }, [onClose, trigger]);
  return createPortal(<dialog className="daily-insight-explanation" ref={ref} aria-labelledby={titleId} onCancel={(event) => { event.preventDefault(); onClose(); }} onClick={(event) => {
    const box = event.currentTarget.getBoundingClientRect();
    if (event.target === event.currentTarget && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) onClose();
  }}>
    <div className="daily-insight-explanation-header"><h3 id={titleId}>{row.sectorName} · 说明</h3><button type="button" onClick={onClose}>关闭</button></div>
    <p className="daily-insight-explanation-context">{DAILY_LEVEL_LABELS[row.industryLevel]} · {tradeDate}</p>
    <p className="daily-insight-explanation-text">{row.renderedText}</p>
    {row.evidence.length ? <div className="daily-insight-related"><p>查看相关分析</p><div>{row.evidence.map((evidence) => <button key={evidence} type="button" onClick={() => onNavigate(dailyInsightDestination(row, tradeDate, evidence))}>{DAILY_EVIDENCE_LABELS[evidence]}</button>)}</div></div> : null}
  </dialog>, document.body);
}
