import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PositionDetailDialog } from "./PositionDetailDialog";

const mock=vi.hoisted(()=>({ detail:vi.fn() }));
vi.mock("../api/positionsApi",()=>({ getPositionDetail:mock.detail }));
const stockRef={ tsCode:"000001.SZ",name:"平安银行" };
const detail=(roundId:string)=>({ coverage:{ reason:null },accountRounds:[{
  accountRef:{ accountId:"account",brokerName:"券商",name:"账户" },roundRef:{ roundId,roundNumber:1 },openedOn:"2026-09-10",openingSource:"INITIALIZATION",
  quantity:"600",availableQuantity:"600",holdingProfitAmount:"100.00",holdingReturnPct:"1.00",dynamicCostPrice:"9.00",dynamicCostAmount:"5400.00",marketValue:"6600.00",
  sellNetProceedsAmount:"4600.00",buyInvestmentAmount:"10000.00",estimatedSellCommission:"0.00",estimatedStampTax:"0.00",estimatedTotalFeeAmount:"0.00",estimatedNetProceeds:"6600.00",reason:null
}] });
describe("historical round to current position identity",()=>{
  beforeEach(()=>{ vi.clearAllMocks(); vi.spyOn(HTMLDialogElement.prototype,"showModal").mockImplementation(function(this:HTMLDialogElement){this.setAttribute("open","");});vi.spyOn(HTMLDialogElement.prototype,"close").mockImplementation(function(this:HTMLDialogElement){this.removeAttribute("open");}); });
  it("rejects the same stock's newer round instead of displaying its money",async()=>{
    mock.detail.mockResolvedValue(detail("new-round"));
    const close=vi.fn(),refresh=vi.fn();
    render(<PositionDetailDialog selected="account" row={{ stockRef }} token="context" expectedRoundId="old-round" onClose={close} onRefresh={refresh} onSell={vi.fn()} />);
    await waitFor(()=>expect(refresh).toHaveBeenCalledOnce());
    expect(close).toHaveBeenCalledOnce();
    expect(screen.queryByText("6,600.00")).not.toBeInTheDocument();
  });
  it("uses the concrete account and preserves sell and full-round-record actions",async()=>{
    mock.detail.mockResolvedValue(detail("round"));
    const sell=vi.fn(),records=vi.fn();
    render(<PositionDetailDialog selected="account" row={{ stockRef }} token="context" expectedRoundId="round" onClose={vi.fn()} onRefresh={vi.fn()} onSell={sell} onRecords={records} />);
    await waitFor(()=>expect(screen.getByRole("button",{ name:"记录卖出" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button",{ name:"记录卖出" }));
    expect(sell).toHaveBeenCalledWith("account",stockRef);
    fireEvent.click(screen.getByRole("button",{ name:"查看本轮闭环记录" }));
    expect(records).toHaveBeenCalledOnce();
    expect(mock.detail.mock.calls[0].slice(0,3)).toEqual(["account","000001.SZ","context"]);
  });
});
