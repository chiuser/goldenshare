import type { KeyboardEvent, PointerEvent } from "react";

import loadingIndicator from "../../../assets/stock-search/loading.svg";
import searchIconActive from "../../../assets/stock-search/search-active.svg";
import searchIcon from "../../../assets/stock-search/search.svg";
import { useStockSearchController } from "../model/useStockSearchController";
import "./stock-search.css";

export interface StockSearchProps {
  onSelect: (tsCode: string) => void;
}

export function StockSearch({ onSelect }: StockSearchProps) {
  const controller = useStockSearchController({ onSelect });
  const readyState = controller.state.kind === "ready" ? controller.state : null;
  const activeVisual =
    controller.isFocused
    || ["loading", "ready", "empty"].includes(controller.state.kind);
  const errorVisual = controller.state.kind === "error";

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (controller.handleKeyDown(event.key)) event.preventDefault();
  }

  function handleOptionPointerDown(
    event: PointerEvent<HTMLButtonElement>,
    index: number,
  ) {
    event.preventDefault();
    controller.selectIndex(index);
  }

  return (
    <div
      className={`stock-search${activeVisual ? " active" : ""}${errorVisual ? " error" : ""}`}
      data-state={controller.state.kind}
    >
      <div className="stock-search-field">
        <img
          alt=""
          aria-hidden="true"
          className="stock-search-icon"
          src={activeVisual ? searchIconActive : searchIcon}
        />
        <input
          ref={controller.inputRef}
          aria-activedescendant={controller.activeOptionId}
          aria-autocomplete="list"
          aria-controls={controller.listboxId}
          aria-expanded={controller.menuOpen}
          aria-label="搜索股票"
          autoComplete="off"
          maxLength={32}
          placeholder="搜索股票代码 / 拼音首字母"
          role="combobox"
          spellCheck={false}
          type="search"
          value={controller.inputValue}
          onBlur={controller.handleBlur}
          onChange={(event) => controller.handleInputChange(event.target.value)}
          onFocus={controller.handleFocus}
          onKeyDown={handleKeyDown}
        />
        {controller.state.kind === "loading" ? (
          <img
            alt=""
            aria-hidden="true"
            className="stock-search-loading-indicator"
            src={loadingIndicator}
          />
        ) : null}
      </div>

      {controller.state.kind === "loading" ? (
        <div
          id={controller.listboxId}
          aria-live="polite"
          className="stock-search-menu stock-search-status"
        >
          搜索中…
        </div>
      ) : null}

      {controller.state.kind === "empty" ? (
        <div
          id={controller.listboxId}
          aria-live="polite"
          className="stock-search-menu stock-search-status"
        >
          未找到匹配的当前上市 A 股
        </div>
      ) : null}

      {controller.state.kind === "error" ? (
        <div
          id={controller.listboxId}
          aria-live="polite"
          className="stock-search-menu stock-search-status error"
        >
          搜索暂不可用，请稍后重试
        </div>
      ) : null}

      {readyState ? (
        <div
          id={controller.listboxId}
          aria-label="股票搜索联想"
          className="stock-search-menu stock-search-results"
          role="listbox"
        >
          <div className="stock-search-options">
            {readyState.options.map((option, index) => {
              const selected = index === readyState.activeIndex;
              return (
                <button
                  key={option.tsCode}
                  ref={(element) => controller.setOptionElement(index, element)}
                  id={`${controller.listboxId}-option-${index}`}
                  aria-label={`${option.name} ${option.codeText}`}
                  aria-selected={selected}
                  className={`stock-search-option${selected ? " selected" : ""}`}
                  role="option"
                  type="button"
                  onMouseEnter={() => controller.setActiveIndex(index)}
                  onPointerDown={(event) => handleOptionPointerDown(event, index)}
                >
                  <span className="stock-search-option-name">{option.name}</span>
                  <span className="stock-search-option-code num">{option.codeText}</span>
                </button>
              );
            })}
          </div>
          <div aria-hidden="true" className="stock-search-footer num">
            ↑↓ 选择　Enter 打开　Esc 关闭
          </div>
        </div>
      ) : null}
    </div>
  );
}
