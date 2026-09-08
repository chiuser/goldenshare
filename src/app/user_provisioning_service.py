from sqlalchemy.orm import Session

from src.app.models.app_user import AppUser
from src.biz.services.wealth.market.watchlist.watchlist_group_initializer import (
    WatchlistGroupInitializer,
)


class UserProvisioningService:
    """Compose account creation and its default group in the caller's transaction."""

    def create_user(
        self,
        session: Session,
        *,
        username: str,
        password_hash: str,
        display_name: str | None = None,
        email: str | None = None,
        account_state: str = "active",
        is_admin: bool = False,
        is_active: bool = True,
    ) -> AppUser:
        user = AppUser(
            username=username,
            password_hash=password_hash,
            display_name=display_name,
            email=email,
            account_state=account_state,
            is_admin=is_admin,
            is_active=is_active,
        )
        session.add(user)
        session.flush()
        WatchlistGroupInitializer().initialize_default_group(session, user_id=user.id)
        return user
