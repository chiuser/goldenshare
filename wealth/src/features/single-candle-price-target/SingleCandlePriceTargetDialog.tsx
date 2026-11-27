import { useId, useLayoutEffect, useRef } from "react";

import { formatSignedPercent } from "../../shared/lib/formatters";
import { directionClass, directionFromNumber } from "../../shared/lib/marketDirection";
import {
  formatPriceTargetNumber, priceTargetTitles, type PriceTargetAsset, type PriceTargetQuote,
} from "./singleCandlePriceTarget";
import { useSingleCandlePriceTarget } from "./useSingleCandlePriceTarget";
import "./single-candle-price-target.css";

interface PriceTargetDialogProps {
  asset: PriceTargetAsset;
  trigger: HTMLButtonElement;
  onClose: () => void;
}

const quoteMessages = {
  idle: "选择交易日后查看行情",
  loading: "正在读取日线行情…",
  empty: "所选交易日暂无日线行情",
  error: "日线行情读取失败",
};

export function SingleCandlePriceTargetDialog({ asset, trigger, onClose }: PriceTargetDialogProps) {
  const titleId = useId();
  const quoteTitleId = useId();
  const coefficientErrorId = useId();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const dateRef = useRef<HTMLInputElement>(null);
  const form = useSingleCandlePriceTarget(asset);
  const { quoteState } = form;
  const isStock = asset.kind === "stock";

  useLayoutEffect(() => {
    const dialog = dialogRef.current!;
    dialog.showModal();
    dateRef.current?.focus();
    return () => {
      dialog.close();
      if (trigger.isConnected) trigger.focus();
    };
  }, [trigger]);

  function close() {
    form.cancelRequest();
    onClose();
  }

  return (
    <dialog className="price-target-dialog" aria-labelledby={titleId} ref={dialogRef}
      onCancel={(event) => { event.preventDefault(); close(); }}>
      <div className="price-target-content">
        <header className="price-target-header">
          <h2 id={titleId}>{priceTargetTitles[form.target]}</h2>
          <div className="price-target-asset">
            <span title={asset.name}>{asset.name}</span>
            <span>{asset.tsCode}</span>
          </div>
          <button type="button" className="price-target-close" aria-label="关闭" onClick={close}>
            <svg aria-hidden="true" focusable="false" viewBox="0 -960 960 960">
              <path d="M256-213.85 213.85-256l224-224-224-224L256-746.15l224 224 224-224L746.15-704l-224 224 224 224L704-213.85l-224-224-224 224Z" />
            </svg>
          </button>
        </header>
        <div className="price-target-form">
          <fieldset>
            <legend>测算目标</legend>
            <div className="price-target-options">
              <button type="button" aria-pressed={form.target === "top"} onClick={() => form.selectTarget("top")}>单阳测顶</button>
              <button type="button" aria-pressed={form.target === "bottom"} onClick={() => form.selectTarget("bottom")}>单阴测底</button>
            </div>
          </fieldset>
          <div className="price-target-fields">
            <label>
              交易日
              <input type="date" ref={dateRef} value={form.date} onChange={(event) => form.selectDate(event.target.value)} />
            </label>
            <label>
              测算系数
              <input type="number" step="any" value={form.coefficientText}
                aria-invalid={!form.validCoefficient || undefined}
                aria-describedby={form.validCoefficient ? undefined : coefficientErrorId}
                onChange={(event) => form.editCoefficient(event.target.value)} />
            </label>
            {!form.validCoefficient && <p className="price-target-error" id={coefficientErrorId} role="alert">请输入大于 0 的有效系数</p>}
          </div>
        </div>
        <section className="price-target-quote" aria-labelledby={quoteTitleId}>
          <header><h3 id={quoteTitleId}>日线行情</h3>{isStock && <span>前复权</span>}</header>
          {quoteState.phase === "ready" ? (
            <>
              <DailyQuoteFields quote={quoteState.quote} />
              {form.missingPrice && <p className="price-target-error" role="status">{form.missingPrice}</p>}
            </>
          ) : (
            <div className="price-target-quote-status" role="status">
              {quoteMessages[quoteState.phase]}
              {quoteState.phase === "error" && <button type="button" onClick={form.retry}>重试</button>}
            </div>
          )}
        </section>
        <footer className="price-target-footer">
          <button type="button" className="price-target-calculate" disabled={!form.canCalculate} onClick={form.calculate}>计算</button>
          <output className="price-target-result">
            <span>{isStock ? "前复权目标价：" : "目标点位："}</span>
            <strong className={form.result === null ? undefined : form.target === "top" ? "up" : "down"}>
              {form.result === null ? "—" : formatPriceTargetNumber(form.result)}
            </strong>
            {form.result !== null && <span className="price-target-unit">{isStock ? "元" : "点"}</span>}
          </output>
        </footer>
        {form.resultOutOfRange && <p className="price-target-error" role="alert">测算结果超出可显示范围</p>}
      </div>
    </dialog>
  );
}

function DailyQuoteFields({ quote: { current, previous } }: { quote: PriceTargetQuote }) {
  const changePct = current.changePct;
  const fields = [
    { name: "开盘价", value: formatPriceTargetNumber(current.open) },
    { name: "最高价", value: formatPriceTargetNumber(current.high) },
    { name: "最低价", value: formatPriceTargetNumber(current.low) },
    { name: "收盘价", value: formatPriceTargetNumber(current.close) },
    {
      name: "涨跌幅", className: directionClass(directionFromNumber(changePct)),
      value: changePct == null ? "--" : formatSignedPercent(changePct),
    },
    { name: "前一交易日收盘", value: formatPriceTargetNumber(previous?.close) },
  ];
  return (
    <>
      <dl className="price-target-quote-grid">
        {fields.map(({ name, value, className }) => (
          <div key={name}><dt>{name}</dt><dd className={className}>{value}</dd></div>
        ))}
      </dl>
      <p className="price-target-previous-date">前一交易日 <time dateTime={previous?.tradeDate}>{previous?.tradeDate ?? "--"}</time></p>
    </>
  );
}
