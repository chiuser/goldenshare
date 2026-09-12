import { useState } from "react";
import type { AccountSummary, FeeInputs, FeeSettingsDto, FieldErrorDto } from "../api/generatedContracts";
import { validInputField } from "../api/contractValidation";
import { getFees } from "../api/tradingAssistantApi";
import { AccountingWriteFlow } from "./AccountingWriteFlow";
import { TradingAssistantAction, TradingAssistantDialog } from "./TradingAssistantForm";
import { FeeFields } from "./FeeFields";

export function FeeSettingsDialog({ account, initial, onClose, onUpdated }: {
  account: AccountSummary; initial: FeeSettingsDto; onClose: () => void; onUpdated: () => Promise<void>;
}) {
  const [fees, setFees] = useState<FeeInputs>({ commissionRateWan: initial.commissionRateWan,
    minimumCommission: initial.minimumCommission, stampTaxRatePct: initial.stampTaxRatePct });
  const [version, setVersion] = useState(initial.feeVersionId);
  const [errors, setErrors] = useState<FieldErrorDto[]>([]);
  return <AccountingWriteFlow scope={{ scopeType: "ACCOUNT_FEES", accountId: account.accountId }} onClose={onClose}
    onRestore={async recovered => {
      if (recovered.operationType !== "FEES_UPDATE") throw new Error("Unexpected recovered operation");
      const current = await getFees(account.accountId);
      setFees({ commissionRateWan: recovered.input.commissionRateWan, minimumCommission: recovered.input.minimumCommission,
        stampTaxRatePct: recovered.input.stampTaxRatePct });
      setVersion(current.feeVersionId); setErrors([]);
    }} onSaved={async () => { await getFees(account.accountId); await onUpdated(); }}>
    {session => <TradingAssistantDialog variant="fees" title="交易费用设置" subtitle="仅作用于保存后新录入的交易" onClose={onClose}
      footer={<><TradingAssistantAction onClick={onClose}>{session.busy && session.recovery ? "稍后查看" : "取消"}</TradingAssistantAction>
        <TradingAssistantAction primary disabled={!session.canSave} onClick={() => {
          const invalid = Object.entries(fees).filter(([field, value]) => !validInputField("FeesUpdateInput", field, value))
            .map(([field]) => ({ field, clientRowId: null, message: "请检查必填项、格式和取值范围", affectedOn: null }));
          setErrors(invalid);
          if (!invalid.length) void session.save("FEES_UPDATE", { ...fees, expectedFeeVersionId: version });
        }}>{session.busy && session.recovery ? "保存中…" : "保存设置"}</TradingAssistantAction></>}>
      <div className="ta-recovery-summary">{account.name} · {account.brokerName}</div>
      <FeeFields value={fees} onChange={setFees} disabled={!session.canSave} errors={[...errors, ...session.fieldErrors]} />
    </TradingAssistantDialog>}
  </AccountingWriteFlow>;
}
