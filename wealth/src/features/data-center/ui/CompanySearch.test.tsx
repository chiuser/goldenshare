import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { dataCenterApi } from "../api/dataCenterApi";
import type { Company } from "../api/contracts";
import { CompanySearch } from "./CompanySearch";
import { useState } from "react";
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });
it("debounces candidates, requires keyboard selection and cancels observation on blur", async () => {
  vi.useFakeTimers();
  const company: Company = { tsCode: "000001.SZ", name: "平安银行", initials: "PAYH", matchedAlias: null, nameSource: "master", matchKind: "initials" };
  const read = vi.spyOn(dataCenterApi, "companies").mockResolvedValue({ keyword: "PAYH", items: [company], hasMore: false, pageState: null, preparation: null, queryId: null });
  const select = vi.fn(); render(<CompanySearch text="PAYH" selected={null} dates={{ startDate: "2026-09-30", endDate: "2026-09-30" }} onText={vi.fn()} onSelect={select} />);
  const input = screen.getByRole("combobox"); fireEvent.focus(input);
  await act(async () => { await vi.advanceTimersByTimeAsync(299); }); expect(read).not.toHaveBeenCalled();
  await act(async () => { await vi.advanceTimersByTimeAsync(1); }); expect(read).toHaveBeenCalledTimes(1); expect(select).not.toHaveBeenCalled();
  fireEvent.keyDown(input, { key: "ArrowDown" }); fireEvent.keyDown(input, { key: "Enter" }); expect(select).toHaveBeenCalledWith(company);
  fireEvent.focus(input); fireEvent.blur(input);
  await act(async () => { await vi.advanceTimersByTimeAsync(300); }); expect(read).toHaveBeenCalledTimes(1); expect(screen.queryByRole("listbox")).toBeNull();
});

it("controlled lowercase typing keeps the debounce alive and opens candidates without refocusing", async () => {
  vi.useFakeTimers();
  const company: Company = { tsCode: "000001.SZ", name: "平安银行", initials: "PAYH", matchedAlias: null, nameSource: "master", matchKind: "initials" };
  const read = vi.spyOn(dataCenterApi, "companies").mockResolvedValue({ keyword: "PAYH", items: [company], hasMore: false, pageState: null, preparation: null, queryId: null });
  function Controlled() {
    const [text, setText] = useState("");
    return <CompanySearch text={text} selected={null} dates={{ startDate: "2026-09-30", endDate: "2026-09-30" }} onText={setText} onSelect={vi.fn()} />;
  }
  render(<Controlled />);
  const input = screen.getByRole("combobox"); fireEvent.focus(input);
  for (const value of ["p", "pa", "pay", "payh"]) {
    fireEvent.change(input, { target: { value } });
    await act(async () => { await vi.advanceTimersByTimeAsync(50); });
  }
  await act(async () => { await vi.advanceTimersByTimeAsync(300); });
  expect(read).toHaveBeenCalledTimes(1);
  expect(read.mock.calls[0][0]).toBe("PAYH");
  expect(screen.getByRole("option", { name: /平安银行/ })).toBeVisible();
});
