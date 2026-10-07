import type { CandidateLoader, SearchInteraction } from "../../stock-search/model/useStockSearchController";
import { clientPolicy } from "./clientPolicy";
import type { Company, Conditions } from "./contracts";
import { dataCenterApi } from "./dataCenterApi";
import type { StockSearchOption } from "../../stock-search/api/stockSearchAdapter";
export type CompanyOption = Company & StockSearchOption;
export const ANNOUNCEMENT_SEARCH_INTERACTION: SearchInteraction = {
  debounceMs: clientPolicy.companyDebounceMs, timeoutMs: clientPolicy.requestSeconds * 1000,
  maxKeyword: clientPolicy.companyKeywordLimit, enterFirst: false,
};
function observeDelay(signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => { window.clearTimeout(timer); signal.removeEventListener("abort", abort); reject(new DOMException("Aborted", "AbortError")); };
    const timer = window.setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, clientPolicy.defaultPollSeconds * 1000);
    signal.addEventListener("abort", abort, { once: true }); if (signal.aborted) abort();
  });
}
export function companyCandidates(dates: Pick<Conditions, "startDate" | "endDate">, onHasMore: (value: boolean) => void): CandidateLoader<CompanyOption> {
  return async ({ keyword, signal }) => {
    let result = await dataCenterApi.companies(keyword, dates, signal);
    while (result.pageState?.status === "preparing") {
      await observeDelay(signal);
      const query = await dataCenterApi.query(result.queryId!, 1, signal);
      if (query.pageState.status === "error") throw new Error(query.pageState.message ?? "候选暂不可获取");
      if (query.pageState.status !== "preparing") result = await dataCenterApi.companies(keyword, dates, signal);
    }
    if (result.pageState?.status === "error") throw new Error(result.pageState.message ?? "候选暂不可获取");
    if (signal.aborted) throw new DOMException("Aborted", "AbortError");
    onHasMore(result.hasMore === true);
    return result.items.map(company => ({ ...company, codeText: company.tsCode }));
  };
}
