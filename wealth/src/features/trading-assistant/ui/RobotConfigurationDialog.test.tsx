import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RobotConfigurationDialog } from "./RobotConfigurationDialog";
import * as api from "../api/robotApi";

vi.mock("../api/robotApi", () => ({ createRobotCandidate: vi.fn(), testRobot: vi.fn(), getRobotTest: vi.fn(), confirmRobot: vi.fn() }));
const candidate = { candidateId: crypto.randomUUID(), candidateVersion:"1", name:"我的提醒", maskedWebhook:"https://open.feishu.cn/…",hasSigningSecret:false,keywords:[] };
const test = { testId:crypto.randomUUID(),state:"SUCCEEDED" as const, startedAt:"2026-09-16T10:00:00+08:00",completedAt:"2026-09-16T10:00:01+08:00",reason:null };
function fill() {
  fireEvent.change(screen.getByLabelText(/自定义名称/), { target:{value:"我的提醒"} });
  fireEvent.change(screen.getByLabelText(/飞书机器人地址/), { target:{value:"https://open.feishu.cn/open-apis/bot/v2/hook/isolated"} });
}
beforeEach(() => { vi.resetAllMocks(); vi.mocked(api.createRobotCandidate).mockResolvedValue(candidate); vi.mocked(api.testRobot).mockResolvedValue(test); });
describe("robot configuration without save recovery", () => {
  it("shows required name and address errors inline without a request", () => {
    render(<RobotConfigurationDialog current={null} onClose={vi.fn()} onSaved={vi.fn()} />);
    fireEvent.click(screen.getByRole("button",{name:"发送测试通知"}));
    expect(screen.getByRole("alert")).toHaveTextContent("请填写自定义名称");
    fireEvent.change(screen.getByLabelText(/自定义名称/),{target:{value:"我的提醒"}});
    fireEvent.click(screen.getByRole("button",{name:"发送测试通知"}));
    expect(screen.getByRole("alert")).toHaveTextContent("请输入完整的飞书机器人 Webhook 地址");
    expect(api.createRobotCandidate).not.toHaveBeenCalled();
  });
  it("returning to edit requires a new candidate and test before confirmation", async () => {
    render(<RobotConfigurationDialog current={null} onClose={vi.fn()} onSaved={vi.fn()} />); fill();
    fireEvent.click(screen.getByRole("button",{name:"发送测试通知"}));
    await screen.findByRole("button",{name:"已收到，保存并使用"});
    fireEvent.click(screen.getByRole("button",{name:"返回修改"}));
    fireEvent.change(screen.getByLabelText(/自定义名称/),{target:{value:"修改后名称"}});
    fireEvent.click(screen.getByRole("button",{name:"发送测试通知"}));
    await screen.findByRole("button",{name:"已收到，保存并使用"});
    expect(api.createRobotCandidate).toHaveBeenCalledTimes(2);
    expect(api.testRobot).toHaveBeenCalledTimes(2); expect(api.confirmRobot).not.toHaveBeenCalled();
  });
  it("blocks 11 keywords inline without truncating input or sending", () => {
    render(<RobotConfigurationDialog current={null} onClose={vi.fn()} onSaved={vi.fn()} />); fill();
    const input = screen.getByLabelText(/自定义关键词/), value = Array.from({length:11},(_,i)=>`词${i}`).join(",");
    fireEvent.change(input, { target:{value} });
    expect(input).toHaveValue(value); expect(screen.getByRole("alert")).toHaveTextContent("最多填写 10 个关键词。");
    expect(screen.getByRole("button",{name:"发送测试通知"})).toBeDisabled(); expect(api.createRobotCandidate).not.toHaveBeenCalled();
  });
  it("requires successful test and explicit receipt, then ends a failed save without retaining fields", async () => {
    vi.mocked(api.confirmRobot).mockRejectedValue(new Error("private secret"));
    render(<RobotConfigurationDialog current={null} onClose={vi.fn()} onSaved={vi.fn()} />); fill();
    fireEvent.click(screen.getByRole("button",{name:"发送测试通知"}));
    await screen.findByRole("button",{name:"已收到，保存并使用"});
    expect(api.confirmRobot).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button",{name:"已收到，保存并使用"}));
    await waitFor(()=>expect(screen.getByRole("alert")).toHaveTextContent("本次保存未完成"));
    expect(screen.queryByLabelText(/自定义名称/)).not.toBeInTheDocument();
    expect(screen.queryByText(/继续保存|private secret/)).not.toBeInTheDocument();
    expect(api.confirmRobot).toHaveBeenCalledTimes(1);
  });
  it("does not resend unknown test; failure permits an explicit retry or editing", async () => {
    vi.mocked(api.testRobot).mockResolvedValue({...test,state:"UNKNOWN"});
    render(<RobotConfigurationDialog current={null} onClose={vi.fn()} onSaved={vi.fn()} />); fill();
    fireEvent.click(screen.getByRole("button",{name:"发送测试通知"}));
    await screen.findByRole("heading",{name:"测试结果待核对"});
    expect(screen.getByRole("button",{name:"发送测试通知"})).toBeDisabled();
    expect(api.testRobot).toHaveBeenCalledTimes(1); expect(api.confirmRobot).not.toHaveBeenCalled();
  });
});
