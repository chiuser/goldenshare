import { useEffect, useState } from "react";
import type { AlertDetail, PlanDetail, FieldErrorDto, Conditions } from "../api/generatedContracts";
import type { RuleKind } from "../api/rulesApi";
import { conditionErrors } from "../model/ruleInput";
import { ruleTime } from "../model/rulePresentation";
import type { AccountingWriteSession } from "./AccountingWriteFlow";
import { TradingAssistantAction, TradingAssistantDialog } from "./TradingAssistantForm";
import { RuleConditionEditor } from "./RuleConditionEditor";

export function RuleMaintenanceDialog({ kind, detail, action, onClose, session, restored }: {
  kind: RuleKind; detail: PlanDetail | AlertDetail; action: "EDIT" | "CLOSE"; onClose: () => void;
  session: AccountingWriteSession; restored?: Conditions | null;
}) {
  const [conditions, setConditions] = useState(detail.conditions);
  const current = detail;
  const [errors, setErrors] = useState<FieldErrorDto[]>([]);
  useEffect(() => { if (restored) { setConditions(restored); setErrors([]); } }, [restored]);
  const editable = action === "EDIT" ? current.maintenance.canEditConditions : current.maintenance.canClose;
  return <TradingAssistantDialog variant={action === "EDIT" ? "rule" : "rule-close"} showClose={action === "EDIT"} title={action === "EDIT" ? "修改条件" : kind === "PLAN" ? "关闭这个交易计划？" : "关闭这个独立提醒？"}
      subtitle={action === "EDIT" ? "新条件保存后生效，之前的行情仍按当时条件检查" : "关闭后不再检查，不删除历史记录"} onClose={onClose}
      footer={<><TradingAssistantAction onClick={onClose}>取消</TradingAssistantAction><TradingAssistantAction primary={action === "EDIT"} danger={action === "CLOSE"} disabled={!session.canSave || !editable} onClick={() => {
        const invalid = action === "EDIT" ? conditionErrors(conditions) : []; setErrors(invalid);
        if (!invalid.length) void session.save(action === "EDIT" ? "RULE_CONDITIONS_UPDATE" : "RULE_CLOSE", { expectedStateVersion: current.stateVersion, ...(action === "EDIT" ? conditions : {}) });
      }}>{action === "EDIT" ? "保存修改" : "确认关闭"}</TradingAssistantAction></>}>
      <p>{detail.stockRef.name} · {detail.stockRef.tsCode}{"direction" in detail ? ` · ${detail.direction === "BUY" ? "买入" : "卖出"} · ${detail.accountRef.name}` : " · 独立提醒"}</p>
      <p className="ta-note">创建：{ruleTime(detail.createdAt)} · 截止：{ruleTime(detail.deadlineAt)}</p>
      {action === "EDIT" ? <RuleConditionEditor value={conditions} onChange={setConditions} disabled={!session.canSave || !editable} errors={[...errors, ...session.fieldErrors]} /> : <div className="ta-rule-evidence"><p>{detail.conditionSummary}</p><p>仅停止后续检查，不会产生买卖、改变持仓或现金；关闭后不可重新开启。</p></div>}
      {!editable && <p role="alert" className="ta-form-error">{action === "EDIT" ? current.maintenance.editUnavailableReason : current.maintenance.closeUnavailableReason}</p>}
      {action === "EDIT" && <p className="ta-note">本次仅修改价格和累计成交量条件。旧版仍负责修改前的行情；全规则只记录一次首次触发。</p>}
    </TradingAssistantDialog>;
}
