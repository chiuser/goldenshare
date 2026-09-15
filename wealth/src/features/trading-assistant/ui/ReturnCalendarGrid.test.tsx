import { cleanup,fireEvent,render,screen } from "@testing-library/react";
import { afterEach,expect,it,vi } from "vitest";
import type { CalendarResponse } from "../api/generatedContracts";
import { ReturnCalendarGrid } from "./ReturnCalendarGrid";
afterEach(cleanup);
it("renders server dates, real zero, pending past and date-only future without changing amounts",()=>{
  const calendar = { calculatedThrough:"2026-09-11",days:[
    { date:"2026-09-10",inSelectedMonth:true,temporalState:"PAST",profitAmount:"0.00",returnPct:"0.00",reason:null },
    { date:"2026-09-11",inSelectedMonth:true,temporalState:"TODAY",profitAmount:null,returnPct:null,reason:"缺行情" },
    { date:"2026-09-14",inSelectedMonth:true,temporalState:"FUTURE",profitAmount:null,returnPct:null,reason:null },
  ] } as CalendarResponse;
  const onDay=vi.fn(), onMetric=vi.fn(), onMonth=vi.fn();
  render(<ReturnCalendarGrid calendar={calendar} month="2026-09" metric="AMOUNT" selectedDay={null} onDay={onDay} onMetric={onMetric} onMonth={onMonth} />);
  expect(screen.getByRole("button",{name:"2026-09-10"})).toHaveTextContent("0.00");
  expect(screen.getByRole("button",{name:"2026-09-11"})).toHaveTextContent("待计算");
  expect(screen.getByRole("button",{name:"2026-09-14"}).textContent).toBe("14");
  expect(screen.getByRole("button",{name:"2026-09-14"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button",{name:"2026-09-10"}));expect(onDay).toHaveBeenCalledWith("2026-09-10");
  fireEvent.click(screen.getByRole("button",{name:"收益率"}));expect(onMetric).toHaveBeenCalledWith("RATE");
  fireEvent.click(screen.getByRole("button",{name:"上个月"}));expect(onMonth).toHaveBeenCalledWith("2026-08");
});
