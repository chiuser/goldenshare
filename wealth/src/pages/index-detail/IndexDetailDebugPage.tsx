import { makeIndexNineTurnLoader } from "../../features/index-detail/api/indexNineTurnLoader";
import { debugRequests, fetchDebugForecast, fetchDebugKline, fetchDebugPageInit, fetchDebugWeights } from "../../features/index-detail/debug/apiClient";
import { ForecastDebugDetails } from "../../features/index-detail/debug/ForecastDebugDetails";
import { IndexDebugXxmLayer } from "../../features/index-detail/debug/IndexDebugXxmLayer";
import { IndexRecognitionDebug } from "../../features/index-detail/debug/IndexRecognitionDebug";
import { XxmForecastCard } from "../../features/index-detail/xxm-forecast/XxmForecastCard";
import { useXxmForecast } from "../../features/index-detail/xxm-forecast/useXxmForecast";
import { showRecentIndexDay, type IndexDetailPageProps } from "./IndexDetailPage";
import { IndexDetailPageView, type IndexForecastProps } from "./IndexDetailPageView";
import type { ForecastDebugResponse } from "../../features/index-detail/xxm-forecast/types";

const loadNineTurn = makeIndexNineTurnLoader(debugRequests);

function Forecast(props: IndexForecastProps) {
  return <XxmForecastCard {...useXxmForecast(props, fetchDebugForecast)}
    renderDetails={response => "debug" in response ? <ForecastDebugDetails response={response as ForecastDebugResponse} /> : null} />;
}

export function IndexDetailDebugPage({ search, tsCode }: IndexDetailPageProps) {
  return <IndexDetailPageView tsCode={tsCode} tradeDate={new URLSearchParams(search).get("tradeDate") ?? undefined}
    onRecentDay={() => showRecentIndexDay(tsCode, search)}
    loadPageInit={fetchDebugPageInit} loadDailyKline={fetchDebugKline} loadWeights={fetchDebugWeights}
    weightsEndpoint="debug/weights" requests={debugRequests} loadNineTurn={loadNineTurn}
    SignalLayer={IndexDebugXxmLayer} MainChartAddon={IndexRecognitionDebug} Forecast={Forecast} showAlignmentDiagnostics />;
}
