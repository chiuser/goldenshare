import type { StockSearchResponseDto } from "./stockSearchApiTypes";

export interface StockSearchOption {
  tsCode: string;
  name: string;
  codeText: string;
}

export function buildStockSearchOptions(
  payload: StockSearchResponseDto,
): StockSearchOption[] {
  return payload.items.map((item) => ({
    tsCode: item.tsCode,
    name: item.name,
    codeText: item.tsCode,
  }));
}
