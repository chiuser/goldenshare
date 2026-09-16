import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Conditions } from "../api/generatedContracts";
import { RuleConditionEditor } from "./RuleConditionEditor";
import { conditionErrors } from "../model/ruleInput";
import { parseContract } from "../api/contractValidation";

describe("shared price and cumulative volume editor", () => {
  it("uses inclusive buttons, removes disabled fields and keeps operators exclusive", () => {
    function Form() {
      const [value, setValue] = useState<Conditions>({ priceCondition: { operator: "LTE", upper: "10.00" }, volumeCondition: { operator: "GTE", thresholdLots: "200.00" } });
      return <><RuleConditionEditor value={value} onChange={setValue} /><output>{JSON.stringify(value)}</output></>;
    }
    render(<Form />);
    fireEvent.click(screen.getByRole("button", { name: "区间（含边界）" }));
    fireEvent.change(screen.getByLabelText("价格下限（元）"), { target: { value: "9.00" } });
    expect(screen.getByRole("button", { name: "区间（含边界）" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("checkbox", { name: "价格条件" }));
    expect(screen.queryByLabelText("价格上限（元）")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "不高于 ≤" }));
    expect(screen.getByRole("status")).toHaveTextContent('"priceCondition":null');
    expect(screen.getByRole("status")).toHaveTextContent('"operator":"LTE"');
  });
  it("validates exact large thresholds, range order and at least one condition", () => {
    expect(conditionErrors({ priceCondition: { operator:"BETWEEN",lower:"999999999999999998.99",upper:"999999999999999999.00" },volumeCondition:null })).toEqual([]);
    expect(conditionErrors({ priceCondition: { operator:"BETWEEN",lower:"10.00",upper:"9.99" },volumeCondition:null })).toHaveLength(1);
    expect(conditionErrors({ priceCondition:null,volumeCondition:null })).toHaveLength(1);
    expect(() => parseContract("CreatePlanInput", { accountId: crypto.randomUUID(), stockCode:"000001.SZ", direction:"BUY", source:"TRADING_ASSISTANT", deadlineAt:"2026-09-15T15:00:00+08:00", priceCondition:{operator:"LTE",upper:"10.00"},volumeCondition:null,notifyEnabled:true,robotId:null })).toThrow();
  });
});
