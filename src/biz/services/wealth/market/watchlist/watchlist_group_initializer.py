from sqlalchemy.orm import Session

from src.biz.models.wealth.watchlist_group import WealthWatchlistGroup
from src.biz.services.wealth.market.watchlist.watchlist_policy import DEFAULT_GROUP_NAME


class WatchlistGroupInitializer:
    def initialize_default_group(
        self, session: Session, *, user_id: int
    ) -> WealthWatchlistGroup:
        group = WealthWatchlistGroup(
            user_id=user_id, name=DEFAULT_GROUP_NAME, is_default=True, color=None
        )
        session.add(group)
        session.flush()
        return group
