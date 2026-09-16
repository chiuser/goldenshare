import type { StockRef } from "../api/generatedContracts";
import type { RuleKind } from "../api/rulesApi";
import { useTradingAccounts } from "../model/useTradingAccounts";
import { RuleCreateDialog } from "./RuleCreateDialog";
import { TradingAssistantAction, TradingAssistantDialog } from "./TradingAssistantForm";
import { useState } from "react";
import { useRobot } from "../model/useRobot";
import { RobotConfigurationDialog } from "./RobotConfigurationDialog";

export function StockRuleEntry({ stock, kind, onClose }: { stock: StockRef; kind: RuleKind; onClose: () => void }) {
  const accounts = useTradingAccounts();
  const robot = useRobot();
  const [configure, setConfigure] = useState(false);
  if (accounts.loading || accounts.error) return <TradingAssistantDialog title="读取规则录入信息" onClose={onClose}
    footer={<><TradingAssistantAction onClick={onClose}>取消</TradingAssistantAction><TradingAssistantAction disabled={accounts.loading} onClick={() => void accounts.refresh().catch(() => undefined)}>重新读取</TradingAssistantAction></>}>
    <p role={accounts.error ? "alert" : "status"}>{accounts.error ? "账户信息暂时无法读取" : "正在读取…"}</p></TradingAssistantDialog>;
  return <><RuleCreateDialog kind={kind} stock={stock} source="STOCK_DETAIL" accounts={accounts.state?.accounts ?? []} selected={accounts.state?.selected ?? null} robot={robot.robot} onSelectRobot={() => robot.error ? robot.refresh() : !robot.loading && setConfigure(true)} onClose={onClose} onSaved={async () => {}} />
    {configure && <RobotConfigurationDialog current={robot.robot} onClose={() => { setConfigure(false); robot.refresh(); }} onSaved={value => { robot.setRobot(value); setConfigure(false); }} />}</>;
}
