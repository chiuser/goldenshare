import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { ReturnDates } from "./ReturnDates";

it("keeps every tied date available through expand and collapse",()=>{
  const dates=["2026-09-01","2026-09-02","2026-09-03"];
  render(<ReturnDates dates={dates} />);
  expect(screen.queryByText(dates.join("、"))).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{ name:"展开日期" }));
  expect(screen.getByText(dates.join("、"))).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{ name:"收起日期" }));
  expect(screen.queryByText(dates.join("、"))).not.toBeInTheDocument();
});
