import type { QuoteRelatedInfoResponse } from "../../../shared/api/quote-types";
import type { QuoteRelatedItemVM } from "../quote-view-model";

export function mapRelatedInfo(input: QuoteRelatedInfoResponse): QuoteRelatedItemVM[] {
  return input.items.map((item) => ({
    type: item.type,
    title: item.title,
    value: item.value,
  }));
}
