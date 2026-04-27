import type { QuoteAdjustment, QuotePeriod, QuoteSecurityType } from "../../shared/api/quote-types";

export interface QuotePageState {
  tsCode: string;
  securityType: QuoteSecurityType;
  period: QuotePeriod;
  adjustment: QuoteAdjustment;
}
