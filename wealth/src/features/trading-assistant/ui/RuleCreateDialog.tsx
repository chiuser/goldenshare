import { useState } from "react";
import type { AccountSummary, Conditions, FieldErrorDto, StockRef } from "../api/generatedContracts";
import type { RuleKind } from "../api/rulesApi";
import { getRule } from "../api/rulesApi";
import { validInputField } from "../api/contractValidation";
import { conditionErrors } from "../model/ruleInput";
import { AccountingWriteFlow, type AccountingWriteSession } from "./AccountingWriteFlow";
import { TradingAssistantAction, TradingAssistantDialog, TradingAssistantField } from "./TradingAssistantForm";
import { TradingAssistantStockPicker } from "./TradingAssistantStockPicker";
import { RuleConditionEditor } from "./RuleConditionEditor";

// An ID never bypasses server qualification.
export function RuleCreateDialog({ kind, accounts, selected, stock: initialStock = null, source = "TRADING_ASSISTANT", robot = null, onSelectRobot, onClose, onSaved }: {
  kind: RuleKind; accounts: AccountSummary[]; selected: string | null; stock?: StockRef | null;
  source?: "TRADING_ASSISTANT" | "STOCK_DETAIL"; robot?: { robotId: string; name: string } | null;
  onSelectRobot?: () => void; onClose: () => void; onSaved: () => Promise<void>;
}) {
  const [stock, setStock] = useState(initialStock);
  const [account, setAccount] = useState(accounts.find(a => a.accountId === selected)?.accountId ?? "");
  const [direction, setDirection] = useState<"BUY" | "SELL">("BUY");
  const [day, setDay] = useState(""), [time, setTime] = useState("15:00");
  const [notify, setNotify] = useState(false);
  const [savedSource, setSavedSource] = useState(source);
  const [retainedRobot, setRetainedRobot] = useState<string | null>(null);
  const robotId = robot?.robotId ?? retainedRobot;
  const [conditions, setConditions] = useState<Conditions>({ priceCondition: { operator: "LTE", upper: "" }, volumeCondition: null });
  const [errors, setErrors] = useState<FieldErrorDto[]>([]);
  function render(session: AccountingWriteSession | null) {
    const disabled = !!session && !session.canSave;
    const allErrors = [...errors, ...(session?.fieldErrors ?? [])];
    const fieldError = (field: string) => allErrors.find(e => e.field === field)?.message;
    async function save() {
      const invalid = conditionErrors(conditions);
      const add = (field: string, message: string) => invalid.push({ field, message, clientRowId: null, affectedOn: null });
      if (!stock) add("stockCode", "请选择股票");
      if (kind === "PLAN" && !account) add("accountId", "请选择账户");
      const deadlineAt = `${day}T${time}:00+08:00`;
      if (!validInputField("CreatePlanInput", "deadlineAt", deadlineAt)) add("deadlineAt", "请选择有效的截止日期与时间");
      if ((kind === "ALERT" || notify) && !robotId) add("robotId", "请先配置并验证飞书机器人");
      setErrors(invalid);
      if (invalid.length || !session || !stock) return;
      const common = { ...conditions, stockCode: stock.tsCode, deadlineAt, source: savedSource };
      await session.save(kind === "PLAN" ? "PLAN_CREATE" : "ALERT_CREATE", kind === "PLAN"
        ? { ...common, accountId: account, direction, notifyEnabled: notify, robotId: notify ? robotId : null }
        : { ...common, robotId });
    }
    return <TradingAssistantDialog variant="rule" title={kind === "PLAN" ? "新建交易计划" : "新建独立提醒"} subtitle="盘后验证条件 · 不会自动买卖" onClose={onClose}
      footer={<><TradingAssistantAction onClick={onClose}>{session?.busy ? "稍后查看" : "取消"}</TradingAssistantAction><TradingAssistantAction primary disabled={disabled} onClick={() => void save()}>{kind === "PLAN" ? "创建计划" : "创建提醒"}</TradingAssistantAction></>}>
      <div className="ta-rule-two-fields"><TradingAssistantStockPicker value={stock} onChange={setStock} disabled={disabled || !!initialStock} error={fieldError("stockCode")} />
        {kind === "PLAN" && <div className="ta-field"><label htmlFor="ta-rule-account">账户 *</label><select id="ta-rule-account" value={account} disabled={disabled} onChange={e => setAccount(e.target.value)}><option value="">选择账户</option>{accounts.map(a => <option key={a.accountId} value={a.accountId}>{a.name} · {a.brokerName}</option>)}</select>{fieldError("accountId") && <p className="ta-field-error" role="alert">{fieldError("accountId")}</p>}</div>}
      </div>
      <div className="ta-rule-time-fields">
        {kind === "PLAN" && <div className="ta-field"><label htmlFor="ta-rule-direction">计划方向 *</label><select id="ta-rule-direction" disabled={disabled} value={direction} onChange={e => setDirection(e.target.value as typeof direction)}><option value="BUY">买入</option><option value="SELL">卖出</option></select></div>}
        <TradingAssistantField label="截止日期" type="date" required disabled={disabled} value={day} error={fieldError("deadlineAt")} onChange={e => setDay(e.target.value)} />
        <TradingAssistantField label="截止时间（北京时间）" type="time" step={60} required disabled={disabled} value={time} onChange={e => setTime(e.target.value)} />
      </div>
      <RuleConditionEditor value={conditions} onChange={setConditions} disabled={disabled} errors={allErrors} />
      {kind === "PLAN" && <label className="ta-rule-enable"><input type="checkbox" disabled={disabled} checked={notify} onChange={e => setNotify(e.target.checked)} />计划触发后通过飞书通知我</label>}
      <div className="ta-field ta-rule-robot"><label>接收机器人</label><TradingAssistantAction disabled={disabled || !onSelectRobot} onClick={onSelectRobot}>{robot?.name ?? "选择"}</TradingAssistantAction>
        {fieldError("robotId") && <p className="ta-field-error" role="alert">{fieldError("robotId")}</p>}
        <p className="ta-note">选择并配置飞书机器人，经测试确认后用于盘后通知。</p></div>
      <div className="ta-rule-evidence"><p>从保存生效起，到所选截止时间，逐个完整分钟检查全部启用条件，登记第一次同时满足的结果。</p><p className="ta-note">创建时间由系统记录；不回溯生效前的行情。触发不代表成交。</p></div>
    </TradingAssistantDialog>;
  }
  if (!stock || (kind === "PLAN" && !account)) return render(null);
  return <AccountingWriteFlow scope={{ scopeType: "RULE_CREATE", ruleType: kind, tsCode: stock.tsCode, accountId: kind === "PLAN" ? account : null }} onClose={onClose} onSaved={async receipt => {
      if (receipt.operationType !== "PLAN_CREATE" && receipt.operationType !== "ALERT_CREATE") throw new Error("Unexpected rule receipt");
      await getRule(kind, receipt.result.ruleId); await onSaved();
    }}
    onRestore={async recovered => {
      if (recovered.operationType !== "PLAN_CREATE" && recovered.operationType !== "ALERT_CREATE") throw new Error("Unexpected rule input");
      const input = recovered.input;
      setSavedSource(input.source); setRetainedRobot(input.robotId ?? null);
      setConditions({ priceCondition: input.priceCondition, volumeCondition: input.volumeCondition });
      setDay(input.deadlineAt.slice(0, 10)); setTime(input.deadlineAt.slice(11, 16));
      if ("direction" in input) { setDirection(input.direction); setNotify(input.notifyEnabled ?? false); }
      setErrors([]);
    }}>{render}</AccountingWriteFlow>;
}
