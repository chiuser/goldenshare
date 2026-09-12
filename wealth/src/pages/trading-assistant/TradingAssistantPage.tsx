import { useEffect, useRef, useState } from "react";
import { buildIndexDetailPath, DEFAULT_WEALTH_PATH, navigateWealth, resolveTopMarketNavPath } from "../../app/routes/routerState";
import { getAuthEpoch } from "../../features/auth/model/authStorage";
import type { FeeSettingsDto, InitializationDefaults, InitializationDetail } from "../../features/trading-assistant/api/generatedContracts";
import { getDefaults, getFees, getInitialization } from "../../features/trading-assistant/api/tradingAssistantApi";
import { useTradingAccounts } from "../../features/trading-assistant/model/useTradingAccounts";
import { useAssistantMarketShell } from "../../features/trading-assistant/model/useAssistantMarketShell";
import { NewAccountFlow } from "../../features/trading-assistant/ui/NewAccountFlow";
import { FeeSettingsDialog } from "../../features/trading-assistant/ui/FeeSettingsDialog";
import { AccountLedgerFlow } from "../../features/trading-assistant/ui/AccountLedgerFlow";
import { TradingAssistantAction, TradingAssistantDialog } from "../../features/trading-assistant/ui/TradingAssistantForm";
import { PageBreadcrumb } from "../../shared/ui/page-breadcrumb/PageBreadcrumb";
import { TopMarketBar } from "../../shared/ui/top-market-bar/TopMarketBar";
import "./trading-assistant-page.css";

type Overlay = { kind: "create"; defaults: InitializationDefaults } | { kind: "settings"; accountId: string }
  | { kind: "fees"; accountId: string; fees: FeeSettingsDto } | { kind: "initial"; accountId: string; initial: InitializationDetail }
  | { kind: "entry"; accountId: string; direction: "BUY" | "SELL" | "IN" };
export function TradingAssistantPage() {
  const [, changed] = useState(0);
  useEffect(() => {
    const storageChanged = () => changed(v => v + 1);
    window.addEventListener("storage", storageChanged);
    return () => window.removeEventListener("storage", storageChanged);
  }, []);
  return <TradingAssistantWorkspace key={getAuthEpoch()} />;
}
function TradingAssistantWorkspace() {
  const accounts = useTradingAccounts();
  const shell = useAssistantMarketShell();
  const [overlay, setOverlay] = useState<Overlay | null>(null);
  const [opening, setOpening] = useState(false);
  const [feedback, setFeedback] = useState("");
  const requestNo = useRef(0);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => { ++requestNo.current; controller.current?.abort(); }, []);
  const current = accounts.state?.accounts.find(account => account.accountId === accounts.state?.selected);
  const overlayAccount = overlay && "accountId" in overlay ? accounts.state?.accounts.find(a => a.accountId === overlay.accountId) : null;
  const close = () => { ++requestNo.current; controller.current?.abort(); setOpening(false); setOverlay(null); };
  async function open(kind: "create" | "fees" | "initial") {
    if (opening || (kind !== "create" && !current)) return;
    const number = ++requestNo.current, epoch = getAuthEpoch();
    const abort = new AbortController(); controller.current?.abort(); controller.current = abort;
    setOpening(true); setFeedback("");
    try {
      const next: Overlay = kind === "create" ? { kind, defaults: await getDefaults(abort.signal) }
        : kind === "fees" ? { kind, accountId: current!.accountId, fees: await getFees(current!.accountId, abort.signal) }
          : { kind, accountId: current!.accountId, initial: await getInitialization(current!.accountId, abort.signal) };
      if (number === requestNo.current && epoch === getAuthEpoch()) setOverlay(next);
    } catch { if (number === requestNo.current && epoch === getAuthEpoch()) setFeedback("暂时无法读取表单信息，请重试。"); }
    finally { if (number === requestNo.current && epoch === getAuthEpoch()) setOpening(false); }
  }
  return <div className="ta-page">
    <TopMarketBar activeNav="assistant" tickers={shell?.tickers ?? []} onTickerSelect={code => navigateWealth(buildIndexDetailPath(code))}
      onNavigate={target => { const path = resolveTopMarketNavPath(target); if (path) navigateWealth(path); else setFeedback("该模块暂未开放"); }} />
    <main className="ta-page-main">
      {shell && <PageBreadcrumb items={[{ label: "财势乾坤", path: DEFAULT_WEALTH_PATH }, { label: "交易助手" }]} sessionStatus={shell.sessionStatus} onNavigate={navigateWealth} />}
      <div className="ta-page-heading">
        <div><h1>持仓列表</h1><p>查看每一笔当前持仓及其动态摊薄成本、收益和可卖数量</p></div>
        <div className="ta-segments ta-module-tabs" role="group" aria-label="交易助手模块">
          <button type="button" aria-pressed="true">持仓股</button><button type="button" disabled>收益分析</button><button type="button" disabled>计划与监控</button>
        </div>
        <select aria-label="交易账户" value={accounts.state?.selected ?? ""} disabled={accounts.loading || !accounts.state?.accounts.length}
          onChange={event => { close(); accounts.select(event.target.value); }}>
          {!accounts.state?.accounts.length && <option value="">{accounts.loading ? "读取账户中…" : "暂无账户"}</option>}
          {accounts.state?.accounts.map(account => <option key={account.accountId} value={account.accountId}>{account.brokerName} · {account.name}</option>)}
          {!!accounts.state?.accounts.length && <option value="ALL">全部账户</option>}
        </select>
      </div>
      <div className="ta-page-actions">
        <TradingAssistantAction disabled={accounts.loading || accounts.error || opening} onClick={() => void open("create")}>新增账户</TradingAssistantAction>
        <span className="ta-action-spacer" />
        {(["BUY", "SELL", "IN"] as const).map(direction => <TradingAssistantAction key={direction} primary={direction === "BUY"}
          disabled={!current || accounts.error || accounts.loading || opening} onClick={() => current && setOverlay({ kind: "entry", accountId: current.accountId, direction })}>
          {direction === "BUY" ? "记录买入" : direction === "SELL" ? "记录卖出" : "资金转入/转出"}</TradingAssistantAction>)}
        <TradingAssistantAction disabled={!current || accounts.error || accounts.loading || opening} onClick={() => current && setOverlay({ kind: "settings", accountId: current.accountId })}>账户设置</TradingAssistantAction>
      </div>
      {accounts.error ? <section className="ta-page-status" role="alert">账户信息暂时无法读取。<TradingAssistantAction onClick={() => void accounts.refresh().catch(() => undefined)}>重新读取</TradingAssistantAction></section>
        : accounts.loading ? <section className="ta-page-status" role="status">正在读取账户…</section>
          : !accounts.state?.accounts.length ? <section className="ta-page-status"><h2>创建交易账户</h2><p>填写账户、费用和当前资产，开始记录交易。</p>
            <TradingAssistantAction primary disabled={opening} onClick={() => void open("create")}>创建账户</TradingAssistantAction></section>
            : <section className="ta-page-status"><p>{accounts.state.selected === "ALL" ? "全部账户仅供汇总查看，记账请先选择具体账户。" : "账户录入已接入；持仓与收益视图尚未接入。"}</p></section>}
      {feedback && <p className="ta-form-error" role="status">{feedback}</p>}
    </main>
    {overlay?.kind === "create" && <NewAccountFlow defaults={overlay.defaults} onClose={close} onCreated={accounts.refresh} />}
    {overlay?.kind === "settings" && overlayAccount && <TradingAssistantDialog title="账户设置" subtitle={`${overlayAccount.brokerName} · ${overlayAccount.name}`} onClose={close}
      footer={<><TradingAssistantAction disabled={opening} onClick={() => void open("fees")}>交易费率</TradingAssistantAction>
        <TradingAssistantAction primary disabled={opening} onClick={() => void open("initial")}>更正期初资产</TradingAssistantAction></>}>
      <div className="ta-recovery-summary">交易费率与期初资产分别维护</div><p className="ta-note">费率调整仅影响新录入交易。<br />更正期初资产会从初始化日起重新计算。</p>
      {feedback && <p role="alert" className="ta-form-error">{feedback}</p>}
    </TradingAssistantDialog>}
    {overlay?.kind === "fees" && overlayAccount && <FeeSettingsDialog key={overlayAccount.accountId} account={overlayAccount} initial={overlay.fees} onClose={close} onUpdated={accounts.refresh} />}
    {overlay?.kind === "initial" && overlayAccount && <AccountLedgerFlow key={overlayAccount.accountId} account={overlayAccount} initial={overlay.initial} onClose={close} onUpdated={accounts.refresh} />}
    {overlay?.kind === "entry" && overlayAccount && <AccountLedgerFlow key={overlayAccount.accountId} account={overlayAccount} direction={overlay.direction} onClose={close} onUpdated={accounts.refresh} />}
  </div>;
}
