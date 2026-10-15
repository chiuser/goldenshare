import { fetchIndexNineTurnSeries } from "../../nine-turn/api/nineTurnApiClient";
import type { NineTurnSeriesLoader } from "../../nine-turn/controller/useNineTurnSeriesRegistry";
import { indexDetailRequests } from "./indexDetailRequestScheduler";

export const loadIndexNineTurnSeries: NineTurnSeriesLoader = (request, options) => {
  if (request.subjectType !== "index") throw new Error("指数九转请求对象不符合产品合同。");
  return indexDetailRequests.run("nineTurn", () => fetchIndexNineTurnSeries({
    endDate: request.endDate, limit: request.limit, period: request.period, tsCode: request.tsCode,
  }, options), options.signal);
};
