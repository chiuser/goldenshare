import { buildIndexDetailPath, navigateWealth } from "../../app/routes/routerState";
import { fetchIndexDetailKline, fetchIndexDetailPageInit, fetchIndexDetailWeights } from "../../features/index-detail/api/indexDetailApiClient";
import { loadIndexNineTurnSeries } from "../../features/index-detail/api/indexNineTurnLoader";
import { normalizeIndexTsCode } from "../../features/index-detail/model/indexDetailState";
import { XxmForecastCard } from "../../features/index-detail/xxm-forecast/XxmForecastCard";
import { useXxmForecast } from "../../features/index-detail/xxm-forecast/useXxmForecast";
import { IndexDetailPageView, type IndexForecastProps } from "./IndexDetailPageView";

export interface IndexDetailPageProps { search: string; tsCode: string; }

export function showRecentIndexDay(tsCode: string, search: string) {
  const params = new URLSearchParams(search);
  params.delete("tradeDate");
  const query = params.toString();
  navigateWealth(`${buildIndexDetailPath(normalizeIndexTsCode(tsCode))}${query ? `?${query}` : ""}`, { replace: true });
}

function Forecast(props: IndexForecastProps) {
  return <XxmForecastCard {...useXxmForecast(props)} />;
}

export function IndexDetailPage({ search, tsCode }: IndexDetailPageProps) {
  return <IndexDetailPageView tsCode={tsCode} tradeDate={new URLSearchParams(search).get("tradeDate") ?? undefined}
    onRecentDay={() => showRecentIndexDay(tsCode, search)}
    loadPageInit={fetchIndexDetailPageInit} loadDailyKline={fetchIndexDetailKline}
    loadWeights={fetchIndexDetailWeights} weightsEndpoint="weights" loadNineTurn={loadIndexNineTurnSeries}
    Forecast={Forecast} />;
}
