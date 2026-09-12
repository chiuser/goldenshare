import { useEffect, useState } from "react";
import type { CreateAccountInput, FieldErrorDto } from "../api/generatedContracts";
import { parseContract, validInputField } from "../api/contractValidation";
import { FeeFields } from "./FeeFields";
import { TradingAssistantAction, TradingAssistantDialog, TradingAssistantField } from "./TradingAssistantForm";
import { InitialPositionFields } from "./InitialPositionFields";
import { positionDrafts, validateInitialPositions, type PositionDraft } from "../model/initialPositionDraft";

export function AccountSetupDialog({ stampTaxRatePct, saving, errors = [], onClose, onSubmit, saveDisabled = false, restoredInput }: {
  stampTaxRatePct: string; saving: boolean; errors?: FieldErrorDto[]; saveDisabled?: boolean;
  onClose: () => void; onSubmit: (input: CreateAccountInput) => void;
  restoredInput?: CreateAccountInput | null;
}) {
  const [step, setStep] = useState(1);
  const [input, setInput] = useState({ name: "", brokerName: "", commissionRateWan: "", minimumCommission: "", stampTaxRatePct, initialCash: "" });
  const [positions, setPositions] = useState<PositionDraft[]>([]);
  const [localErrors, setLocalErrors] = useState<FieldErrorDto[]>([]);
  useEffect(() => {
    if (!restoredInput) return;
    const { initialPositions, ...fields } = restoredInput;
    setInput(fields);
    setPositions(positionDrafts(initialPositions));
    setLocalErrors([]); setStep(3);
  }, [restoredInput]);
  const shownErrors = [...localErrors, ...errors];
  const errorFor = (field: string, row?: string) => shownErrors.find(error => error.field === field && (error.clientRowId ?? undefined) === row)?.message;

  function advance() {
    if (saving || (step === 3 && saveDisabled)) return;
    const found: FieldErrorDto[] = [];
    const invalid = (field: string, clientRowId: string | null = null, message = "请检查必填项、格式和取值范围") => found.push({ field, clientRowId, message, affectedOn: null });
    const fields = step === 1 ? ["name", "brokerName"] : step === 2 ? ["commissionRateWan", "minimumCommission", "stampTaxRatePct"] : Object.keys(input);
    for (const field of fields) if (!validInputField("CreateAccountInput", field, input[field as keyof typeof input])) invalid(field);
    const checked = validateInitialPositions(step === 3 ? positions : []);
    const initialPositions = checked.values;
    found.push(...checked.errors);
    setLocalErrors(found);
    if (found.length) {
      if (found.some(error => ["name", "brokerName"].includes(error.field))) setStep(1);
      else if (found.some(error => ["commissionRateWan", "minimumCommission", "stampTaxRatePct"].includes(error.field))) setStep(2);
      return;
    }
    if (step < 3) { setStep(step + 1); return; }
    onSubmit(parseContract("CreateAccountInput", { ...input, initialPositions }));
  }

  return <TradingAssistantDialog title={step === 1 ? "创建交易账户" : step === 2 ? "设置交易费用" : "录入当前资产"}
    subtitle={`首次使用 · ${step} / 3`} variant={step === 3 ? "assets" : "onboarding"} onClose={onClose}
    footer={<>
      {step > 1 && <TradingAssistantAction disabled={saving} onClick={() => setStep(step - 1)}>上一步</TradingAssistantAction>}
      <TradingAssistantAction primary disabled={saving || (step === 3 && saveDisabled)} onClick={advance}>{saving ? "保存中…" : step === 3 ? "完成初始化" : "下一步"}</TradingAssistantAction>
    </>}>
    <div className="ta-setup-progress" aria-label={`第 ${step} 步，共 3 步`}><span style={{ width: `${step / 3 * 100}%` }} /></div>
    {step === 1 && <>
      <TradingAssistantField required label="账户名称" value={input.name} disabled={saving} error={errorFor("name")}
        onChange={event => setInput({ ...input, name: event.target.value })} />
      <TradingAssistantField required label="券商名称" value={input.brokerName} disabled={saving} error={errorFor("brokerName")}
        onChange={event => setInput({ ...input, brokerName: event.target.value })} />
      <div className="ta-notice"><strong>只记录资产，不连接券商</strong>无需填写资金账号。交易助手用于手动登记持仓及交易。</div>
    </>}
    {step === 2 && <FeeFields value={input} disabled={saving} errors={shownErrors} onChange={fees => setInput({ ...input, ...fees })} />}
    {step === 3 && <>
      <TradingAssistantField required label="当前现金余额（元）" inputMode="decimal" value={input.initialCash} disabled={saving} error={errorFor("initialCash")}
        onChange={event => setInput({ ...input, initialCash: event.target.value })} />
      <InitialPositionFields rows={positions} onChange={setPositions} disabled={saving} errors={shownErrors} />
      <p className="ta-note">从初始化当天开始记录，不需要补录此前的买卖历史。当前没有持仓时可以只填写现金。</p>
    </>}
    {saving && <p className="ta-note" role="status">正在保存，输入暂不可改，请勿重复提交。输入尚未安全保留，请勿刷新或关闭页面。</p>}
  </TradingAssistantDialog>;
}
