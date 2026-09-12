import { mayReturnToEditing, type WriteRecoveryState } from "../model/writeRecovery";
import { TradingAssistantAction, TradingAssistantDialog } from "./TradingAssistantForm";

export function WriteRecoveryDialog({ state, checking, detailsFailed = false, confirmedSaved = false, failureMessage, onCheck, onClose, onEdit, onLoadDetails }: {
  state: WriteRecoveryState; checking: boolean; detailsFailed?: boolean; confirmedSaved?: boolean; failureMessage?: string | null;
  onCheck: () => void; onClose: () => void; onEdit: () => void; onLoadDetails: () => void;
}) {
  const saved = confirmedSaved || state.status?.outcome === "SAVED";
  const editable = mayReturnToEditing(state);
  const retained = state.status?.inputRetained === true;
  const title = saved ? (detailsFailed ? "已保存，最新信息加载失败" : "已保存")
    : editable ? (retained ? "本次未保存，输入已保留" : "本次未保存") : "暂时无法确认保存结果";
  const subtitle = saved ? (detailsFailed ? "保存已经成功，无需再次提交" : "无需重复提交")
    : editable ? "已确认本次操作没有生效" : "请先核对，不要重复保存";
  return <TradingAssistantDialog title={title} subtitle={subtitle} variant="recovery" showClose={false} onClose={onClose}
    footer={<>
      <TradingAssistantAction onClick={onClose}>{saved || editable ? "关闭提示" : "稍后查看"}</TradingAssistantAction>
      <TradingAssistantAction primary disabled={checking} onClick={saved ? onLoadDetails : editable ? onEdit : onCheck}>
        {checking ? "核对中…" : saved ? (detailsFailed ? "重新加载" : "查看最新详情") : editable ? "返回编辑" : "重新核对"}
      </TradingAssistantAction>
    </>}>
    {state.status && <div className="ta-recovery-summary">
      <p>{state.status.summary.title}</p>
      {state.status.summary.lines.map((line, index) => <p key={index}>{line}</p>)}
    </div>}
    {saved ? <p className="ta-note">{detailsFailed ? "仅重新加载最新详情，不会重复保存或产生新版本。" : "请查看最新详情。"}</p>
      : editable ? <>
        {state.status?.rejection && <p className="ta-note">{state.status.rejection.message}</p>}
        <p className="ta-note">可以返回表单继续编辑。<br />再次保存时，会重新检查当前条件和状态。</p>
      </> : <p className="ta-note">{retained ? "输入已保留。" : "输入尚未安全保留，请勿刷新或关闭页面。"}重新核对只查询结果，不会再保存一次。</p>}
    {state.queryUnavailable && <p className="ta-form-error" role="alert">暂时无法核对，请稍后重新核对。已有的保存结论不变。</p>}
    {failureMessage && <p className="ta-form-error" role="alert">{failureMessage}</p>}
  </TradingAssistantDialog>;
}
