export interface StockSearchItemDto {
  tsCode: string;
  name: string;
}

export interface StockSearchResponseDto {
  keyword: string;
  items: StockSearchItemDto[];
}
