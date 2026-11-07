import {render,screen,waitFor} from "@testing-library/react";
import {afterEach,expect,it,vi} from "vitest";
import {IndexDetailPage} from "./IndexDetailPage";
import {makeOrdinaryKline,makePageInit,makeTrendPayload} from "../../features/index-detail/testing/indexDetailTestFixtures";
vi.mock("../../shared/charts/detail-workspace/DetailChartWorkspace",()=>({DetailChartWorkspace:()=>null}));
vi.mock("../../features/index-detail/xxm/useIndexXxmLayer",()=>({useIndexXxmLayer:()=>({phase:"unsupported",data:null,errorMessage:"",requestKey:"",retry:()=>{},macdPrimitives:[]})}));
afterEach(()=>vi.unstubAllGlobals());
it("ordinary Page never mounts or requests research, including before P4 dynamic URL wiring",async()=>{
 const fetcher=vi.fn(async(input:RequestInfo|URL)=>{const url=String(input);const value=url.includes("/page-init")?makePageInit():url.includes("/kline")?makeOrdinaryKline():url.includes("/trend-channel")?makeTrendPayload():{};return new Response(JSON.stringify(value),{status:url.includes("/daily-waves")?500:200});});vi.stubGlobal("fetch",fetcher);
 render(<IndexDetailPage search="" tsCode="000001.SH"/>);await screen.findByLabelText("IndexHeader");await waitFor(()=>expect(fetcher.mock.calls.some(([url])=>String(url).includes("/kline"))).toBe(true));expect(screen.queryByRole("button",{name:"波段核对"})).not.toBeInTheDocument();expect(fetcher.mock.calls.some(([url])=>String(url).includes("/daily-waves"))).toBe(false);
});
