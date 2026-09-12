import { useEffect, useRef, useState } from "react";
import type { AccountSummary, FieldErrorDto, InitializationCorrectionInput, InitializationCorrectionPreview, InitializationDetail } from "../api/generatedContracts";
import { parseContract, validInputField } from "../api/contractValidation";
import { accountPath, request, TradingAssistantApiError } from "../api/tradingAssistantApi";
import { positionDrafts, validateInitialPositions, type PositionDraft } from "../model/initialPositionDraft";
import type { AccountingWriteSession } from "./AccountingWriteFlow";
import { InitialPositionFields } from "./InitialPositionFields";
import { TradingAssistantAction, TradingAssistantDialog, TradingAssistantField } from "./TradingAssistantForm";

export function InitializationCorrectionForm({ account, initial, restored, session, onClose }: {
  account: AccountSummary; initial: InitializationDetail; restored?: InitializationCorrectionInput;
  session: AccountingWriteSession; onClose: () => void;
}) {
  const [cash, setCash] = useState(restored?.initialCash ?? initial.initialCash);
  const [rows, setRows] = useState<PositionDraft[]>(() => restored ? positionDrafts(restored.initialPositions)
    : positionDrafts(initial.initialPositions).map((row, i) => ({ ...row, stock: initial.initialPositions[i].stockRef })));
  const revision = initial.initializationRevision;
  const [errors, setErrors] = useState<FieldErrorDto[]>([]);
  const [failure, setFailure] = useState<string | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [review, setReview] = useState<{ input: InitializationCorrectionInput; result: InitializationCorrectionPreview } | null>(null);
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  async function preview() {
    if (reviewing) return;
    const checked = validateInitialPositions(rows, initial.initializedOn);
    if (!validInputField("InitializationCorrectionInput", "initialCash", cash)) checked.errors.push({
      field: "initialCash", clientRowId: null, message: "请填写有效的初始现金金额", affectedOn: null });
    setErrors(checked.errors); setFailure(null);
    if (checked.errors.length) return;
    const input = parseContract("InitializationCorrectionInput", { initialCash: cash, initialPositions: checked.values, expectedRevision: revision });
    const controller = new AbortController(); active.current = controller; setReviewing(true);
    try {
      const result = await request(accountPath(account.accountId) + "/initialization/correction-preview", "InitializationCorrectionPreview",
        { method: "POST", body: input, signal: controller.signal });
      if (controller.signal.aborted) return;
      if (result.expectedRevision !== input.expectedRevision) throw new Error("Preview revision mismatch");
      setErrors(result.fieldErrors);
      if (!result.fieldErrors.length) setReview({ input, result });
    } catch (error) {
      if (!controller.signal.aborted) {
        if (error instanceof TradingAssistantApiError) setErrors(error.details.fieldErrors);
        setFailure("暂时无法核对更正，请重试；当前填写内容仍保留。");
      }
    } finally { if (!controller.signal.aborted) setReviewing(false); }
  }
  const disabled = !session.canSave || reviewing;
  const shown = [...errors, ...session.fieldErrors];
  return <>
        <TradingAssistantDialog variant="assets" title="更正期初资产" subtitle={`${account.name} · 初始化日期 ${initial.initializedOn}（只读）`} onClose={onClose}
          footer={<><TradingAssistantAction onClick={onClose}>取消</TradingAssistantAction>
            <TradingAssistantAction primary disabled={disabled} onClick={() => void preview()}>{reviewing ? "核对中…" : "核对更正"}</TradingAssistantAction></>}>
          <p className="ta-note">更正初始化当日资产，不是今天的持仓。</p>
          <div className="ta-setup-progress"><span style={{ width: "100%" }} /></div>
          <TradingAssistantField required label="初始现金" inputMode="decimal" value={cash} disabled={disabled}
            error={shown.find(e => e.field === "initialCash")?.message} onChange={e => setCash(e.target.value)} />
          <InitialPositionFields rows={rows} onChange={setRows} disabled={disabled} errors={shown} initializedOn={initial.initializedOn} />
          <div className="ta-notice"><strong>确认后重新计算受影响的持仓与收益</strong>
            系统会检查全部后续流水；有冲突时不会保存。下一步核对变更内容，尚未保存。</div>
          {failure && <p role="alert" className="ta-form-error">{failure}</p>}
        </TradingAssistantDialog>
        {review && (!session.recovery || session.editing) && <TradingAssistantDialog variant="fees" title="确认期初资产更正" subtitle="请核对发生变化的内容" onClose={() => setReview(null)}
          footer={<><TradingAssistantAction onClick={() => setReview(null)}>返回修改</TradingAssistantAction>
            <TradingAssistantAction primary disabled={!session.canSave} onClick={() => void session.save("INITIALIZATION_CORRECT", review.input)}>确认更正</TradingAssistantAction></>}>
          <div className="ta-recovery-summary">{account.name} · {review.result.affectedFromDate}</div>
          <dl className="ta-change-comparison"><dt>初始现金</dt><dd>{comparison(review.result.before.initialCash, review.result.after.initialCash)}</dd></dl>
          {review.result.after.initialPositions.map((after, index) => {
            const before = review.result.before.initialPositions[index];
            const stock = after ?? before;
            if (!stock) return null;
            return <section key={stock.tsCode}>
              <h3>{stock.stockRef.name} <span className="num">{stock.tsCode}</span>{!before ? " · 新增" : !after ? " · 移除" : ""}</h3>
              <dl className="ta-change-comparison">
                <dt>建仓日期</dt><dd>{comparison(before?.openedOn, after?.openedOn)}</dd>
                <dt>总持仓数量</dt><dd>{comparison(before?.quantity, after?.quantity)}</dd>
                <dt>期初可卖数量</dt><dd>{comparison(before?.availableQuantity, after?.availableQuantity)}</dd>
                <dt>含费成本价</dt><dd>{comparison(before?.costPrice, after?.costPrice)}</dd>
                <dt>期初持仓成本</dt><dd>{comparison(before?.costAmount, after?.costAmount)}</dd>
              </dl>
            </section>;
          })}
          <p className="ta-note">确认后从 {review.result.affectedFromDate} 起重算受影响的持仓与收益，现金仍按原现金基线核验。保存时再次检查后续历史；重算完成前相关收益暂不可用。</p>
        </TradingAssistantDialog>}
      </>;
}
function comparison(before: string | number | undefined, after: string | number | undefined) {
  if (before === after) return `${before ?? "—"}（未变）`;
  return `${before ?? "—"} → ${after ?? "—"}`;
}
