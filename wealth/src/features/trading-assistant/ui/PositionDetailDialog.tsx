import { useEffect, useState } from "react";
import { getAuthEpoch } from "../../auth/model/authStorage";
import type { PositionDetail, PositionRow, StockRef } from "../api/generatedContracts";
import { getPositionDetail } from "../api/positionsApi";
import { TradingAssistantApiError } from "../api/tradingAssistantApi";
import { positionNumber as number, positionPercent as percent, positionQuantity as quantity, profitTone } from "../model/positionPresentation";
import { PositionFees } from "./PositionsSummary";
import { TradingAssistantAction, TradingAssistantDialog } from "./TradingAssistantForm";

export function PositionDetailDialog({ selected, row, token, onClose, onRefresh, onSell, expectedRoundId, onRecords }: {
  selected: string; row: Pick<PositionRow,"stockRef">; token: string; onClose: () => void; onRefresh: () => void;
  onSell?: (accountId: string, stock: StockRef) => void; expectedRoundId?: string; onRecords?: () => void;
}) {
  const [detail, setDetail] = useState<PositionDetail | null>(null);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [account, setAccount] = useState("");
  useEffect(() => {
    const abort = new AbortController(), epoch = getAuthEpoch();
    setDetail(null); setError(false); setAccount("");
    void getPositionDetail(selected, row.stockRef.tsCode, token, abort.signal).then(value => {
      if (!abort.signal.aborted && epoch === getAuthEpoch()) {
        if (expectedRoundId && value.accountRounds.length && !value.accountRounds.some(item => item.accountRef.accountId === selected && item.roundRef.roundId === expectedRoundId)) { onClose(); onRefresh(); return; }
        setDetail(value); if (value.accountRounds.length === 1) setAccount(value.accountRounds[0].accountRef.accountId);
      }
    }).catch(reason => {
      if (abort.signal.aborted || epoch !== getAuthEpoch()) return;
      if (reason instanceof TradingAssistantApiError && reason.details.code === "TA_READ_CONTEXT_CHANGED") { onClose(); onRefresh(); }
      else setError(true);
    });
    return () => abort.abort();
  }, [selected, row.stockRef.tsCode, token, retry, expectedRoundId]); // callbacks do not define a read identity
  const chosen = detail?.accountRounds.find(item => item.accountRef.accountId === account);
  return <TradingAssistantDialog variant="drawer" title={`${row.stockRef.name} ${row.stockRef.tsCode}`} subtitle="当前持仓 · 分账户核对" onClose={onClose}
    footer={<><TradingAssistantAction onClick={onClose}>关闭</TradingAssistantAction><TradingAssistantAction primary disabled={!onSell || !chosen || chosen.availableQuantity === null || BigInt(chosen.availableQuantity) === 0n}
      onClick={() => chosen && onSell?.(chosen.accountRef.accountId, row.stockRef)}>记录卖出</TradingAssistantAction></>}>
    {error ? <div role="alert"><p>持仓详情暂时无法读取，未更改账户状态。</p><TradingAssistantAction onClick={() => setRetry(value => value + 1)}>重新读取</TradingAssistantAction></div>
      : !detail ? <p role="status">正在读取持仓详情…</p> : <>
        {detail.coverage.reason && <p className="ta-note">{detail.coverage.reason}</p>}
        {!detail.accountRounds.length && <p>当前轮次尚不能确认，暂不展示成本和交易定位。</p>}
        {detail.accountRounds.length > 1 && <label className="ta-field">卖出账户<select value={account} onChange={event => setAccount(event.target.value)}><option value="">请选择具体账户</option>
          {detail.accountRounds.map(item => <option key={item.accountRef.accountId} value={item.accountRef.accountId}>{item.accountRef.brokerName} · {item.accountRef.name} · 可卖 {quantity(item.availableQuantity)}</option>)}</select></label>}
        {detail.accountRounds.map(item => <section className="ta-position-round" key={item.roundRef.roundId}>
          <h3>{item.accountRef.brokerName} · {item.accountRef.name}</h3><p className="ta-note">第 {item.roundRef.roundNumber} 轮 · {item.openedOn} · {item.openingSource === "INITIALIZATION" ? "期初录入" : "买入建仓"}</p>
          {item.valuationMethod === "CONFIRMED_SUSPENSION_CARRY" && <p className="ta-position-coverage">停牌 · 沿用最后有效收盘价<br />估值日期 {item.valuationDate} · 价格日期 {item.priceDate}</p>}
          <div className="ta-position-detail-highlight"><span>当前持仓 {quantity(item.quantity)} 股 · 可卖 {quantity(item.availableQuantity)} 股</span>
            <strong className={`ta-profit--${profitTone(item.holdingProfitAmount)}`}>{number(item.holdingProfitAmount, true)}</strong><span>收益率 {percent(item.holdingReturnPct, true)}</span></div>
          <dl className="ta-position-facts">{[["动态成本价", item.dynamicCostPrice], ["动态总成本", item.dynamicCostAmount], ["持仓市值", item.marketValue], ["累计卖出净回款", item.sellNetProceedsAmount], ["累计买入投入", item.buyInvestmentAmount]].map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{number(value)}</dd></div>)}</dl>
          <PositionFees row={item} />{item.reason && <p className="ta-note">{item.reason}</p>}
        </section>)}
        {onRecords && <TradingAssistantAction onClick={onRecords}>查看本轮闭环记录</TradingAssistantAction>}
      </>}
  </TradingAssistantDialog>;
}
