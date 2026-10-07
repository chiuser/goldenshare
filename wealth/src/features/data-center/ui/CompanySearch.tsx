import { useCallback, useEffect, useMemo, useState } from "react";
import type { Company, Conditions } from "../api/contracts";
import { ANNOUNCEMENT_SEARCH_INTERACTION, companyCandidates } from "../api/companyCandidates";
import { clientPolicy } from "../api/clientPolicy";
import { useStockSearchController } from "../../stock-search/model/useStockSearchController";
export function CompanySearch({ text, selected, dates, onText, onSelect }: {
  text: string; selected: Company | null; dates: Pick<Conditions, "startDate" | "endDate">; onText: (v: string) => void; onSelect: (c: Company) => void;
}) {
  const [hasMore, setHasMore] = useState(false);
  const loadCandidates = useMemo(() => companyCandidates(dates, setHasMore), [dates.startDate, dates.endDate]);
  const select = useCallback((company: Company) => onSelect({ tsCode: company.tsCode, name: company.name, initials: company.initials, matchedAlias: company.matchedAlias, nameSource: company.nameSource, matchKind: company.matchKind }), [onSelect]);
  const c = useStockSearchController({ onSelectOption: select, loadCandidates, interaction: ANNOUNCEMENT_SEARCH_INTERACTION });
  useEffect(() => { c.resetInput(text); }, [dates.startDate, dates.endDate]);
  useEffect(() => { if (text !== c.inputValue) c.resetInput(text); }, [text, selected]);
  const options = c.state.kind === "ready" ? c.state.options : [];
  const message = c.state.kind === "error" ? c.state.message : c.state.kind === "empty" ? "未找到匹配公司"
    : c.state.kind === "loading" ? "正在读取公司候选…" : hasMore ? "有更多匹配，请输入更完整的代码或名称" : "选中完整代码后，点击查询应用。";
  return <div className="dc-company"><input ref={c.inputRef} aria-label="公司名称 / 代码 / 首字母" role="combobox" autoComplete="off" maxLength={clientPolicy.companyKeywordLimit} value={text}
    placeholder="例如：平安银行 / 000001 / PAYH" aria-expanded={c.menuOpen && !selected} aria-controls={c.listboxId}
    aria-autocomplete="list" aria-activedescendant={c.activeOptionId}
    onFocus={() => { c.handleFocus(); if (!selected && text.trim()) c.handleInputChange(text); }} onBlur={c.handleBlur}
    onChange={e => { c.handleInputChange(e.target.value); onText(e.target.value); }}
    onKeyDown={e => { if (c.handleKeyDown(e.key)) e.preventDefault(); }} />
    {c.menuOpen && !selected && text.trim() && <div className="dc-company-menu"><p>按名称、代码及首字母匹配</p><div role="listbox" id={c.listboxId} aria-label="公司搜索候选">
      {options.map((company, i) => <button type="button" role="option" aria-selected={c.state.kind === "ready" && i === c.state.activeIndex} id={`${c.listboxId}-option-${i}`} key={company.tsCode}
        ref={el => c.setOptionElement(i, el)} onMouseDown={e => e.preventDefault()} onMouseEnter={() => c.setActiveIndex(i)} onClick={() => c.selectIndex(i)}>
        <span>{company.name} <span className="num">{company.tsCode}</span></span>
        <small>{company.matchedAlias ? `历史简称：${company.matchedAlias}` : company.nameSource === "master" ? "当前简称" : company.nameSource === "announcement" ? "公告名称" : "暂无名称"}{company.initials ? ` · 首字母 ${company.initials}` : ""}</small>
      </button>)}
    </div><p role="status">{message}</p></div>}
  </div>;
}
