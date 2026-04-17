from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, delete, desc, func, select
from sqlalchemy.orm import Session

from src.platform.auth.constants import ACCOUNT_STATE_ACTIVE, ACCOUNT_STATE_SUSPENDED, ROLE_ADMIN, ROLE_VIEWER
from src.platform.auth.password_service import PasswordService
from src.platform.auth.security_utils import generate_raw_token, hash_raw_token, normalize_email, normalize_username
from src.platform.auth.user_repository import UserRepository
from src.platform.exceptions import WebAppError
from src.platform.models.app.auth_action_token import AuthActionToken
from src.platform.models.app.auth_audit_log import AuthAuditLog
from src.platform.models.app.auth_invite_code import AuthInviteCode
from src.platform.models.app.auth_refresh_token import AuthRefreshToken
from src.platform.models.app.auth_user_role import AuthUserRole
from src.platform.models.app.app_user import AppUser
from src.platform.services.auth_service import AuthService


class AdminUserService:
    def __init__(self) -> None:
        self.user_repository = UserRepository()
        self.password_service = PasswordService()
        self.auth_service = AuthService()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def list_users(self, session: Session, *, keyword: str | None, limit: int, offset: int) -> tuple[list[AppUser], dict[int, list[str]], int]:
        safe_limit = max(1, min(limit, 500))
        stmt = select(AppUser)
        count_stmt = select(func.count()).select_from(AppUser)
        if keyword:
            q = f"%{keyword.strip()}%"
            stmt = stmt.where((AppUser.username.ilike(q)) | (AppUser.display_name.ilike(q)) | (AppUser.email.ilike(q)))
            count_stmt = count_stmt.where((AppUser.username.ilike(q)) | (AppUser.display_name.ilike(q)) | (AppUser.email.ilike(q)))
        total = int(session.scalar(count_stmt) or 0)
        rows = list(
            session.scalars(
                stmt.order_by(desc(AppUser.created_at), desc(AppUser.id)).limit(safe_limit).offset(max(0, offset))
            )
        )
        role_map = self._role_map(session, [item.id for item in rows])
        return rows, role_map, total

    def create_user(
        self,
        session: Session,
        *,
        username: str,
        password: str,
        display_name: str | None,
        email: str | None,
        is_admin: bool,
        is_active: bool,
        account_state: str,
        roles: list[str],
        actor_user_id: int | None,
    ) -> AppUser:
        self.auth_service.ensure_authorization_seed(session)
        normalized_username = normalize_username(username)
        normalized_email = normalize_email(email)
        self.auth_service.validate_password(password)
        if self.user_repository.get_by_username(session, normalized_username):
            raise WebAppError(status_code=409, code="conflict", message="Username already exists")
        if normalized_email and self.user_repository.get_by_email(session, normalized_email):
            raise WebAppError(status_code=409, code="conflict", message="Email already exists")

        role_keys = sorted(set(roles)) if roles else [ROLE_ADMIN if is_admin else ROLE_VIEWER]
        if ROLE_ADMIN in role_keys:
            is_admin = True
        user = self.user_repository.create_user(
            session,
            username=normalized_username,
            password_hash=self.password_service.hash_password(password),
            display_name=display_name.strip() if display_name else None,
            email=normalized_email,
            account_state=account_state or ACCOUNT_STATE_ACTIVE,
            is_admin=is_admin,
            is_active=is_active,
        )
        if user.account_state == ACCOUNT_STATE_ACTIVE and normalized_email:
            user.email_verified_at = self._now()
        self.auth_service.replace_roles(
            session,
            user_id=user.id,
            role_keys=role_keys,
            assigned_by_user_id=actor_user_id,
        )
        self._audit(
            session,
            event_type="admin.user.create",
            user_id=user.id,
            username_snapshot=user.username,
            detail={"roles": role_keys, "is_admin": user.is_admin},
        )
        session.commit()
        session.refresh(user)
        return user

    def update_user(
        self,
        session: Session,
        *,
        user_id: int,
        display_name: str | None,
        email: str | None,
        is_admin: bool | None,
        is_active: bool | None,
        account_state: str | None,
    ) -> AppUser:
        user = self.user_repository.get_by_id(session, user_id)
        if user is None:
            raise WebAppError(status_code=404, code="not_found", message="User does not exist")
        if display_name is not None:
            user.display_name = display_name.strip() or None
        if email is not None:
            normalized_email = normalize_email(email)
            if normalized_email and normalized_email != (user.email or ""):
                exists = self.user_repository.get_by_email(session, normalized_email)
                if exists is not None and exists.id != user.id:
                    raise WebAppError(status_code=409, code="conflict", message="Email already exists")
            user.email = normalized_email
        if is_admin is not None:
            user.is_admin = is_admin
        if is_active is not None:
            user.is_active = is_active
        if account_state is not None:
            user.account_state = account_state
        self._audit(session, event_type="admin.user.update", user_id=user.id, username_snapshot=user.username, detail={})
        session.commit()
        session.refresh(user)
        return user

    def replace_user_roles(
        self,
        session: Session,
        *,
        user_id: int,
        role_keys: list[str],
        actor_user_id: int | None,
    ) -> list[str]:
        user = self.user_repository.get_by_id(session, user_id)
        if user is None:
            raise WebAppError(status_code=404, code="not_found", message="User does not exist")
        final_roles = self.auth_service.replace_roles(
            session,
            user_id=user_id,
            role_keys=role_keys,
            assigned_by_user_id=actor_user_id,
        )
        user.is_admin = ROLE_ADMIN in final_roles
        self._audit(
            session,
            event_type="admin.user.roles",
            user_id=user.id,
            username_snapshot=user.username,
            detail={"roles": final_roles},
        )
        session.commit()
        return final_roles

    def suspend_user(self, session: Session, *, user_id: int) -> AppUser:
        user = self.user_repository.get_by_id(session, user_id)
        if user is None:
            raise WebAppError(status_code=404, code="not_found", message="User does not exist")
        user.is_active = False
        user.account_state = ACCOUNT_STATE_SUSPENDED
        self._audit(session, event_type="admin.user.suspend", user_id=user.id, username_snapshot=user.username, detail={})
        session.commit()
        session.refresh(user)
        return user

    def activate_user(self, session: Session, *, user_id: int) -> AppUser:
        user = self.user_repository.get_by_id(session, user_id)
        if user is None:
            raise WebAppError(status_code=404, code="not_found", message="User does not exist")
        user.is_active = True
        user.account_state = ACCOUNT_STATE_ACTIVE
        self._audit(session, event_type="admin.user.activate", user_id=user.id, username_snapshot=user.username, detail={})
        session.commit()
        session.refresh(user)
        return user

    def admin_reset_password(self, session: Session, *, user_id: int, password: str) -> AppUser:
        user = self.user_repository.get_by_id(session, user_id)
        if user is None:
            raise WebAppError(status_code=404, code="not_found", message="User does not exist")
        self.auth_service.validate_password(password)
        user.password_hash = self.password_service.hash_password(password)
        user.password_changed_at = self._now()
        user.failed_login_count = 0
        user.last_failed_login_at = None
        user.locked_until = None
        user.account_state = ACCOUNT_STATE_ACTIVE if user.is_active else user.account_state
        self.auth_service.revoke_all_refresh_tokens(session, user_id=user.id, reason="admin_reset_password")
        self._audit(session, event_type="admin.user.reset_password", user_id=user.id, username_snapshot=user.username, detail={})
        session.commit()
        session.refresh(user)
        return user

    def delete_user(self, session: Session, *, user_id: int, actor_user_id: int | None) -> int:
        user = self.user_repository.get_by_id(session, user_id)
        if user is None:
            raise WebAppError(status_code=404, code="not_found", message="User does not exist")
        if actor_user_id is not None and actor_user_id == user.id:
            raise WebAppError(status_code=422, code="validation_error", message="Can not delete current user")

        if user.is_admin:
            remaining_admins = int(
                session.scalar(
                    select(func.count())
                    .select_from(AppUser)
                    .where(and_(AppUser.is_admin.is_(True), AppUser.id != user.id))
                ) or 0
            )
            if remaining_admins <= 0:
                raise WebAppError(status_code=422, code="validation_error", message="Can not delete last admin user")

        session.execute(delete(AuthUserRole).where(AuthUserRole.user_id == user.id))
        session.execute(delete(AuthRefreshToken).where(AuthRefreshToken.user_id == user.id))
        session.execute(delete(AuthActionToken).where(AuthActionToken.user_id == user.id))
        session.delete(user)
        self._audit(
            session,
            event_type="admin.user.delete",
            user_id=actor_user_id,
            username_snapshot=user.username,
            detail={"deleted_user_id": user_id},
        )
        session.commit()
        return user_id

    def create_invite(
        self,
        session: Session,
        *,
        role_key: str,
        assigned_email: str | None,
        max_uses: int,
        expires_at: datetime | None,
        note: str | None,
        actor_user_id: int | None,
        code: str | None,
    ) -> tuple[AuthInviteCode, str]:
        self.auth_service.ensure_authorization_seed(session)
        raw_code = (code.strip() if code else "") or generate_raw_token()[:20]
        normalized_email = normalize_email(assigned_email)
        now = self._now()
        row = AuthInviteCode(
            code_hash=hash_raw_token(raw_code),
            code_hint=raw_code,
            role_key=(role_key or ROLE_VIEWER).strip().lower(),
            assigned_email=normalized_email,
            max_uses=max(1, max_uses),
            used_count=0,
            expires_at=expires_at,
            disabled_at=None,
            last_used_at=None,
            created_by_user_id=actor_user_id,
            note=note.strip() if note else None,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
        self._audit(
            session,
            event_type="admin.invite.create",
            user_id=actor_user_id,
            detail={"invite_id": row.id, "role_key": row.role_key},
        )
        session.commit()
        session.refresh(row)
        return row, raw_code

    def list_invites(self, session: Session, *, include_disabled: bool, limit: int, offset: int) -> tuple[list[AuthInviteCode], int]:
        safe_limit = max(1, min(limit, 500))
        filters = []
        if not include_disabled:
            filters.append(AuthInviteCode.disabled_at.is_(None))
        stmt = select(AuthInviteCode)
        count_stmt = select(func.count()).select_from(AuthInviteCode)
        if filters:
            stmt = stmt.where(and_(*filters))
            count_stmt = count_stmt.where(and_(*filters))
        total = int(session.scalar(count_stmt) or 0)
        rows = list(
            session.scalars(
                stmt.order_by(desc(AuthInviteCode.created_at), desc(AuthInviteCode.id)).limit(safe_limit).offset(max(0, offset))
            )
        )
        return rows, total

    def disable_invite(self, session: Session, *, invite_id: int, actor_user_id: int | None) -> int:
        row = session.get(AuthInviteCode, invite_id)
        if row is None:
            raise WebAppError(status_code=404, code="not_found", message="Invite does not exist")
        row.disabled_at = self._now()
        self._audit(session, event_type="admin.invite.disable", user_id=actor_user_id, detail={"invite_id": invite_id})
        session.commit()
        return row.id

    def delete_invite(self, session: Session, *, invite_id: int, actor_user_id: int | None) -> int:
        row = session.get(AuthInviteCode, invite_id)
        if row is None:
            raise WebAppError(status_code=404, code="not_found", message="Invite does not exist")
        session.delete(row)
        self._audit(session, event_type="admin.invite.delete", user_id=actor_user_id, detail={"invite_id": invite_id})
        session.commit()
        return invite_id

    def list_auth_audit(
        self,
        session: Session,
        *,
        user_id: int | None,
        event_type: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AuthAuditLog], int]:
        safe_limit = max(1, min(limit, 1000))
        filters = []
        if user_id is not None:
            filters.append(AuthAuditLog.user_id == user_id)
        if event_type:
            filters.append(AuthAuditLog.event_type == event_type.strip())
        stmt = select(AuthAuditLog)
        count_stmt = select(func.count()).select_from(AuthAuditLog)
        if filters:
            stmt = stmt.where(and_(*filters))
            count_stmt = count_stmt.where(and_(*filters))
        total = int(session.scalar(count_stmt) or 0)
        rows = list(
            session.scalars(
                stmt.order_by(desc(AuthAuditLog.occurred_at), desc(AuthAuditLog.id)).limit(safe_limit).offset(max(0, offset))
            )
        )
        return rows, total

    def _role_map(self, session: Session, user_ids: list[int]) -> dict[int, list[str]]:
        if not user_ids:
            return {}
        rows = session.execute(
            select(AuthUserRole.user_id, AuthUserRole.role_key).where(AuthUserRole.user_id.in_(user_ids))
        ).all()
        role_map: dict[int, list[str]] = {}
        for uid, role_key in rows:
            if not role_key:
                continue
            role_map.setdefault(int(uid), []).append(role_key)
        for uid in role_map:
            role_map[uid] = sorted(set(role_map[uid]))
        return role_map

    def _audit(
        self,
        session: Session,
        *,
        event_type: str,
        user_id: int | None = None,
        username_snapshot: str | None = None,
        detail: dict | None = None,
    ) -> None:
        session.add(
            AuthAuditLog(
                user_id=user_id,
                username_snapshot=username_snapshot,
                event_type=event_type,
                event_status="success",
                detail_json=detail or {},
                occurred_at=self._now(),
            )
        )
        session.flush()
