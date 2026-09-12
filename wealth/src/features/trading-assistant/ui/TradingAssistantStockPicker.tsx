import { useId, useRef } from "react";
import { useStockSearchController } from "../../stock-search/model/useStockSearchController";
import type { StockSearchOption } from "../../stock-search/api/stockSearchAdapter";
import type { StockRef } from "../api/generatedContracts";

export function TradingAssistantStockPicker({ value, onChange, error, disabled = false }: {
  value: StockRef | null; onChange: (value: StockRef | null) => void; error?: string; disabled?: boolean;
}) {
  const id = useId();
  const options = useRef<StockSearchOption[]>([]);
  const controller = useStockSearchController({ onSelect: code => {
    const option = options.current.find(item => item.tsCode === code);
    if (option) onChange({ tsCode: option.tsCode, name: option.name });
  } });
  if (controller.state.kind === "ready") options.current = controller.state.options;
  return <div className="ta-field ta-stock-picker">
    <label htmlFor={value ? `${id}-change` : id}>股票 *</label>
    {value ? <div className="ta-stock-selected"><span>{value.name ? `${value.name} · ` : ""}{value.tsCode}</span>
      <button id={`${id}-change`} type="button" className="ta-close" disabled={disabled} aria-label="重新选择股票" onClick={() => onChange(null)}>×</button>
    </div> : <>
      <input id={id} ref={controller.inputRef} role="combobox" autoComplete="off" type="search" maxLength={32} disabled={disabled}
        placeholder="股票代码 / 拼音首字母" value={controller.inputValue} aria-expanded={controller.menuOpen}
        aria-controls={controller.listboxId} aria-activedescendant={controller.activeOptionId} aria-autocomplete="list"
        aria-invalid={!!error} aria-describedby={error ? `${id}-error` : undefined}
        onChange={event => controller.handleInputChange(event.target.value)} onBlur={controller.handleBlur}
        onFocus={controller.handleFocus} onKeyDown={event => { if (controller.handleKeyDown(event.key)) event.preventDefault(); }} />
      {controller.menuOpen && controller.state.kind === "ready" && <div className="ta-stock-options" role="listbox" id={controller.listboxId} aria-label="股票搜索结果">
        {controller.state.options.map((option, index) => <button type="button" key={option.tsCode} role="option"
          id={`${controller.listboxId}-option-${index}`} aria-selected={index === (controller.state.kind === "ready" ? controller.state.activeIndex : -1)}
          ref={node => controller.setOptionElement(index, node)} onPointerDown={event => { event.preventDefault(); controller.selectIndex(index); }}>
          <span>{option.name}</span><span>{option.tsCode}</span>
        </button>)}
      </div>}
      {controller.state.kind === "loading" && <p className="ta-field-hint" role="status">搜索中…</p>}
      {controller.state.kind === "empty" && <p className="ta-field-hint" role="status">未找到匹配的当前上市 A 股</p>}
      {controller.state.kind === "error" && <p className="ta-field-error" role="alert">搜索暂不可用，请稍后重试</p>}
    </>}
    {error && <p className="ta-field-error" id={`${id}-error`} role="alert">{error}</p>}
  </div>;
}
