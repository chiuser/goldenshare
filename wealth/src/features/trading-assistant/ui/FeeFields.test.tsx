import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { FeeFields } from "./FeeFields";

it("explains current sell estimates without changing required fee inputs", () => {
  render(<FeeFields value={{ commissionRateWan: "2.50", minimumCommission: "5.00", stampTaxRatePct: "0.05" }} onChange={vi.fn()} />);
  expect(screen.getByText("新交易与当前卖出估算使用当前费率。历史费用、历史快照不变；买入不收印花税。")).toBeInTheDocument();
  expect(screen.queryByText(/仅影响保存后新录入/)).not.toBeInTheDocument();
  for (const label of ["交易佣金率", "单笔最低佣金", "卖出印花税率"]) {
    expect(screen.getByLabelText(label, { exact: false })).toBeRequired();
  }
});
