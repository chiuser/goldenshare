import { useEffect, useId, useState } from "react";
import type { Company, Conditions } from "../api/contracts";
import { dataCenterApi, errorMessage } from "../api/dataCenterApi";
import { clientPolicy } from "../api/clientPolicy";
export function CompanySearch({ text, selected, dates, onText, onSelect }: {
  text: string; selected: Company | null; dates: Pick<Conditions, "startDate" | "endDate">; onText: (v: string) => void; onSelect: (c: Company) => void;
}) {
  const id = useId(); const [open, setOpen] = useState(false); const [items, setItems] = useState<Company[]>([]);
  const [index, setIndex] = useState(-1); const [message, setMessage] = useState("");
  useEffect(() => {
    setItems([]); setIndex(-1);
    if (!open || selected || !text.trim()) { setMessage(""); return; }
    const controller = new AbortController(); let poll: number | undefined;
    const search = async () => {
      setMessage("搜索中…");
      try {
        const r = await dataCenterApi.companies(text.trim(), dates, controller.signal);
        if (controller.signal.aborted) return;
        setItems(r.items); setIndex(-1);
        setMessage(r.pageState?.status === "preparing" ? "正在准备公司候选…" : r.pageState?.status === "error" ? r.pageState.message ?? "候选暂不可获取" : r.hasMore ? "有更多匹配，请输入更完整的代码或名称" : r.items.length ? "选中完整代码后，点击查询应用。" : "未找到匹配公司");
        if (r.pageState?.status === "preparing") poll = window.setTimeout(search, clientPolicy.defaultPollSeconds * 1000);
      } catch (e) { if (!controller.signal.aborted) setMessage(errorMessage(e)); }
    };
    const timer = window.setTimeout(search, clientPolicy.companyDebounceMs);
    return () => { controller.abort(); window.clearTimeout(timer); window.clearTimeout(poll); };
  }, [text, selected, open, dates.startDate, dates.endDate]);
  const choose = (c: Company) => { onSelect(c); setOpen(false); };
  return <div className="dc-company"><input aria-label="公司名称 / 代码 / 首字母" role="combobox" autoComplete="off" maxLength={clientPolicy.companyKeywordLimit} value={text}
    placeholder="例如：平安银行 / 000001 / PAYH" aria-expanded={open && !selected && !!text.trim()} aria-controls={id}
    aria-autocomplete="list" aria-activedescendant={index >= 0 ? `${id}-${index}` : undefined}
    onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} onChange={e => { onText(e.target.value); setOpen(true); }}
    onKeyDown={e => {
      if (e.key === "Escape") { setOpen(false); return; }
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); setOpen(true); setIndex(i => items.length ? (i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length : -1); }
      if (e.key === "Enter" && open && index >= 0 && items[index]) { e.preventDefault(); choose(items[index]); }
    }} />
    {open && !selected && text.trim() && <div className="dc-company-menu"><p>按名称、代码及首字母匹配</p><div role="listbox" id={id} aria-label="公司搜索候选">
      {items.map((c, i) => <button type="button" role="option" aria-selected={i === index} id={`${id}-${i}`} key={c.tsCode}
        onMouseDown={e => e.preventDefault()} onClick={() => choose(c)}><span>{c.name} <span className="num">{c.tsCode}</span></span>
        <small>{c.matchedAlias ? `历史简称：${c.matchedAlias}` : c.nameSource === "master" ? "当前简称" : c.nameSource === "announcement" ? "公告名称" : "暂无名称"}{c.initials ? ` · 首字母 ${c.initials}` : ""}</small></button>)}
    </div><p role="status">{message}</p></div>}
  </div>;
}
