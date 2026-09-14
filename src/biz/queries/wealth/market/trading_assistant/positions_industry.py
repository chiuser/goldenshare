"""One dated Eastmoney third-level membership, shared with future analysis reads."""
from dataclasses import dataclass

from sqlalchemy import and_, select

from src.foundation.models.core_serving.dc_index import DcIndex
from src.foundation.models.core_serving.dc_member import DcMember
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget


@dataclass(frozen=True, slots=True)
class IndustryMembership:
    name: str | None
    reason: str | None = None


class PositionsIndustryQuery:
    def __init__(self, policy):
        self.policy = policy

    def read(self, session, *, codes, trade_date, deadline):
        result = {code: IndustryMembership(None) for code in codes}
        if trade_date is None:
            return result
        for offset in range(0, len(codes), self.policy.page_rows):
            batch = codes[offset:offset + self.policy.page_rows]
            # Same date is deliberately enforced in the join, not independently
            # selected as MAX(date) in each source. No future/upper-level fallback.
            apply_sql_budget(session, deadline, self.policy)
            query = select(DcMember.con_code, DcIndex.ts_code, DcIndex.name).join(DcIndex,
                and_(DcIndex.ts_code == DcMember.ts_code, DcIndex.trade_date == DcMember.trade_date)).where(
                    DcMember.trade_date == trade_date, DcMember.con_code.in_(batch),
                    DcIndex.idx_type == "行业板块", DcIndex.level == "东财三级行业")
            seen = set()
            for code, _, name in session.execute(query):
                if code in seen:
                    result[code] = IndustryMembership(None, "东财三级行业存在多重归属，分类待核验")
                else:
                    result[code] = IndustryMembership(name)
                    seen.add(code)
            deadline.remaining_ms()
        return result
