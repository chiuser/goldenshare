"""The single initialization-only default, design §4.3.2; never overrides saved fees."""
from src.biz.schemas.wealth.market.trading_assistant.accounts import InitializationDefaults

INITIALIZATION_DEFAULTS = InitializationDefaults(stampTaxRatePct="0.05", commissionRateUnit="WAN",
    stampTaxRateUnit="PERCENT", currency="CNY")
