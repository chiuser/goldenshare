import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AccountSetupDialog } from "./AccountSetupDialog";

vi.mock("./TradingAssistantStockPicker", () => ({ TradingAssistantStockPicker: ({ onChange }: { onChange: (value: unknown) => void }) =>
  <button onClick={() => onChange({ tsCode: "000001.SZ", name: "测试股票" })}>选择测试股票</button> }));

const fill = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label, { exact: false }), { target: { value } });
function reachAssets() {
  fill("账户名称", "主账户"); fill("券商名称", "测试券商");
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fill("交易佣金率", "2.50"); fill("单笔最低佣金", "5.00");
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
}

describe("three-step account initialization", () => {
  it("requires broker and fee settings; empty cash is not silently converted to zero", () => {
    const submit = vi.fn();
    render(<AccountSetupDialog stampTaxRatePct="0.05" saving={false} onClose={vi.fn()} onSubmit={submit} />);
    fireEvent.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.getAllByRole("alert")).toHaveLength(2);
    reachAssets();
    fireEvent.click(screen.getByRole("button", { name: "完成初始化" }));
    expect(submit).not.toHaveBeenCalled();
    fill("当前现金余额", "0.00");
    fireEvent.click(screen.getByRole("button", { name: "完成初始化" }));
    expect(submit).toHaveBeenCalledWith({ name: "主账户", brokerName: "测试券商", commissionRateWan: "2.50", minimumCommission: "5.00",
      stampTaxRatePct: "0.05", initialCash: "0.00", initialPositions: [] });
  });
  it("accepts odd lots and explicit zero sellable quantity, preserving stable row identity", () => {
    const submit = vi.fn();
    render(<AccountSetupDialog stampTaxRatePct="0.05" saving={false} onClose={vi.fn()} onSubmit={submit} />);
    reachAssets(); fill("当前现金余额", "10.00");
    fireEvent.click(screen.getByRole("button", { name: "添加持仓股票" }));
    fireEvent.click(screen.getByRole("button", { name: "选择测试股票" }));
    fill("持仓数量", "13"); fill("持仓成本价", "10.01");
    fireEvent.click(screen.getByRole("button", { name: "完成初始化" }));
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByText("请选择建仓日期。")).toBeInTheDocument();
    fill("建仓日期", "2026-09-11");
    fill("当日可卖数量", "14"); fireEvent.click(screen.getByRole("button", { name: "完成初始化" }));
    expect(screen.getByText("初始化当日可卖数量不能超过持仓数量")).toBeInTheDocument();
    fill("当日可卖数量", "0"); fireEvent.click(screen.getByRole("button", { name: "完成初始化" }));
    expect(submit.mock.calls[0][0].initialPositions).toEqual([{ clientRowId: expect.any(String), tsCode: "000001.SZ",
      openedOn: "2026-09-11", quantity: 13, availableQuantity: 0, costPrice: "10.01" }]);
  });
  it("keeps submitted inputs disabled while saving", () => {
    render(<AccountSetupDialog stampTaxRatePct="0.05" saving onClose={vi.fn()} onSubmit={vi.fn()} />);
    expect(screen.getByLabelText("账户名称", { exact: false })).toBeDisabled();
    expect(screen.getByRole("button", { name: "保存中…" })).toBeDisabled();
    expect(screen.queryByLabelText("资金账号")).not.toBeInTheDocument();
  });
});
