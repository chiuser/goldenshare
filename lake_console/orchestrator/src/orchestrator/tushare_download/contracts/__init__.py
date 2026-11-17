"""Local, verified source contracts are registered during approved dataset onboarding.

No existing dataset is migrated or declared verified by the component's tests.
"""

from .index_monthly import INDEX_MONTHLY_CONTRACT
from .index_weekly import INDEX_WEEKLY_CONTRACT
from .moneyflow_ths import MONEYFLOW_THS_CONTRACT
from .stk_factor_pro import STK_FACTOR_PRO_CONTRACT

CONTRACTS = (
    STK_FACTOR_PRO_CONTRACT, MONEYFLOW_THS_CONTRACT,
    INDEX_WEEKLY_CONTRACT, INDEX_MONTHLY_CONTRACT,
)
