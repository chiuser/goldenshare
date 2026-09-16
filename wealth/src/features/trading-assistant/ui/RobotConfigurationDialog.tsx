import { useEffect, useRef, useState } from "react";
import type { CandidateResult, RobotConfig, TestResult } from "../api/generatedContracts";
import { confirmRobot, createRobotCandidate, getRobotTest, testRobot } from "../api/robotApi";
import { TradingAssistantApiError } from "../api/tradingAssistantApi";
import { getAuthEpoch } from "../../auth/model/authStorage";
import { TradingAssistantAction, TradingAssistantDialog, TradingAssistantField } from "./TradingAssistantForm";

// Credentials exist only in this mounted form. No storage, recovery flow or automatic resend.
export function RobotConfigurationDialog({ current, onClose, onSaved }: {
  current: RobotConfig | null; onClose: () => void; onSaved: (robot: RobotConfig) => void;
}) {
  const [name, setName] = useState(current?.name ?? ""), [webhook, setWebhook] = useState("");
  const [secret, setSecret] = useState(""), [clearSecret, setClearSecret] = useState(false);
  const [keywords, setKeywords] = useState(current?.keywords.join("，") ?? "");
  const [candidate, setCandidate] = useState<CandidateResult | null>(null), [test, setTest] = useState<TestResult | null>(null);
  const [busy, setBusy] = useState(false), [failure, setFailure] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | undefined>();
  const [readFailed, setReadFailed] = useState(false), [pollGeneration, setPollGeneration] = useState(0);
  const [fieldError, setFieldError] = useState<string | undefined>();
  const controller = useRef(new AbortController()), epoch = useRef(getAuthEpoch());
  const alive = () => !controller.current.signal.aborted && epoch.current === getAuthEpoch();
  useEffect(() => { controller.current = new AbortController(); const value = controller.current; return () => value.abort(); }, []);
  const values = keywords.split(/[,，\n]/).map(v => v.trim()).filter(Boolean);
  const keywordError = values.length > 10 ? "最多填写 10 个关键词。" : undefined;
  const locked = busy || !!candidate;
  useEffect(() => {
    if (!candidate || !test || test.state !== "IN_FLIGHT") return;
    const read = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const value = await getRobotTest(candidate.candidateId, test.testId, read.signal);
        if (read.signal.aborted || !alive()) return;
        setReadFailed(false); setTest(value);
        if (value.state === "IN_FLIGHT") timer = setTimeout(poll, 1000);
      } catch { if (!read.signal.aborted && alive()) setReadFailed(true); }
    };
    void poll(); return () => { read.abort(); clearTimeout(timer); };
  }, [candidate, test?.testId, test?.state, pollGeneration]);
  async function sendTest() {
    if (busy || keywordError) return;
    if (!name.trim()) { setNameError("请填写自定义名称。"); return; }
    setNameError(undefined);
    if ((!current && !webhook.trim()) || (webhook && !/^https:\/\/open\.feishu\.cn\/open-apis\/bot\/v2\/hook\/[A-Za-z0-9_-]+$/.test(webhook.trim()))) {
      setFieldError("请输入完整的飞书机器人 Webhook 地址。"); return;
    }
    setFieldError(undefined);
    setBusy(true); setFailure(null);
    try {
      const c = candidate ?? await createRobotCandidate({ name: name.trim(), keywords: values,
        expectedConfigVersionId: current?.configVersionId ?? null,
        webhook: webhook ? { action: "REPLACE", value: webhook.trim() } : { action: "KEEP" },
        signingSecret: clearSecret ? { action: "CLEAR" } : secret ? { action: "REPLACE", value: secret } : current ? { action: "KEEP" } : { action: "CLEAR" },
      }, controller.current.signal);
      if (!alive()) return;
      setCandidate(c);
      const result = await testRobot(c, controller.current.signal);
      if (alive()) setTest(result);
    } catch (error) {
      if (alive()) { setName(""); setWebhook(""); setSecret(""); setKeywords(""); setCandidate(null); setTest(null);
        setFailure(error instanceof TradingAssistantApiError ? error.message : "本次操作未完成，请关闭后重新填写；不会自动继续保存或重发测试。"); }
    } finally { if (alive()) setBusy(false); }
  }
  async function save() {
    if (!candidate || test?.state !== "SUCCEEDED" || busy) return;
    setBusy(true);
    try { const robot = await confirmRobot(candidate.candidateId, test.testId, current, controller.current.signal); if (alive()) onSaved(robot); }
    catch { if (alive()) { setCandidate(null); setTest(null); setName(""); setKeywords(""); setWebhook(""); setSecret(""); setFailure("本次保存未完成，请关闭后重新填写。重新打开将读取实际有效配置。"); } }
    finally { if (alive()) setBusy(false); }
  }
  return <TradingAssistantDialog variant="robot" title="配置飞书机器人" subtitle="修改经测试并保存后，后续通知统一使用新配置，已有计划无需重建。" onClose={onClose}
    footer={<><TradingAssistantAction disabled={busy} onClick={test?.state === "SUCCEEDED" ? () => { setCandidate(null); setTest(null); } : onClose}>{test?.state === "SUCCEEDED" ? "返回修改" : "取消"}</TradingAssistantAction>{!failure && <TradingAssistantAction primary disabled={busy || !!keywordError || test?.state === "IN_FLIGHT" || test?.state === "UNKNOWN"} onClick={() => void (test?.state === "SUCCEEDED" ? save() : sendTest())}>{busy ? "处理中…" : test?.state === "SUCCEEDED" ? "已收到，保存并使用" : test?.state === "FAILED" ? "重新发送测试" : "发送测试通知"}</TradingAssistantAction>}</>}>
    {failure ? <p className="ta-form-error" role="alert">{failure}</p> : <>
      <TradingAssistantField label="自定义名称" required value={name} disabled={locked} error={nameError} onChange={e => setName(e.target.value)} placeholder="例如：我的交易提醒" />
      <TradingAssistantField label="飞书机器人地址（Webhook）" required={!current} type="password" autoComplete="off" value={webhook} disabled={locked} error={fieldError} onChange={e => setWebhook(e.target.value)} placeholder={current ? "已保存地址；留空保持不变" : "粘贴完整 Webhook 地址"} />
      <p className="ta-note">从飞书机器人的配置复制地址。地址与密钥不会展示在通知正文中。</p>
      <h3>安全配置</h3>
      <TradingAssistantField label="签名密钥" type="password" autoComplete="new-password" value={secret} disabled={locked || clearSecret} onChange={e => setSecret(e.target.value)} placeholder={current?.hasSigningSecret ? "已设置；留空保持不变" : "若开启签名校验，请粘贴对应密钥"} />
      {current?.hasSigningSecret && <label className="ta-rule-enable"><input type="checkbox" disabled={locked} checked={clearSecret} onChange={e => setClearSecret(e.target.checked)} />清除已保存的签名密钥</label>}
      <TradingAssistantField label="自定义关键词（选填，最多 10 个）" value={keywords} disabled={locked} error={keywordError} onChange={e => setKeywords(e.target.value)} hint="多个关键词用逗号分隔，会包含在测试及正式通知中。" />
      <p className="ta-note">与飞书机器人的安全设置保持一致，推荐开启签名校验。若启用 IP 白名单，请在飞书侧放行系统发送出口。</p>
      {test && <section className="ta-rule-evidence" aria-live="polite"><h3>{({ IN_FLIGHT: "测试发送中", SUCCEEDED: "测试发送成功", FAILED: "测试发送失败", UNKNOWN: "测试结果待核对" })[test.state]}</h3><p>{test.reason}</p>
        {test.state === "SUCCEEDED" && <p>请到飞书确认收到测试通知，再点击“已收到，保存并使用”。</p>}
        {test.state === "UNKNOWN" && <p>不会自动重发，也不能再次发送这次测试。请核对飞书中的实际消息。</p>}
        {test.state === "FAILED" && <TradingAssistantAction onClick={() => { setCandidate(null); setTest(null); }}>返回修改配置</TradingAssistantAction>}
        {readFailed && <><p role="alert">暂时无法读取测试结果，不代表发送失败。</p><TradingAssistantAction onClick={() => setPollGeneration(v => v + 1)}>重新读取测试结果</TradingAssistantAction></>}
      </section>}
    </>}
  </TradingAssistantDialog>;
}
