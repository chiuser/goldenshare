from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, desc, func, select, update
from sqlalchemy.orm import Session

from src.app.auth import JWTService, PasswordService
from src.app.auth.constants import (
    ACCOUNT_STATE_ACTIVE,
    ACCOUNT_STATE_LOCKED,
    ACCOUNT_STATE_PENDING_VERIFICATION,
    ACCOUNT_STATE_SUSPENDED,
    AUTH_ACTION_RESET_PASSWORD,
    AUTH_ACTION_VERIFY_EMAIL,
    DEFAULT_PERMISSIONS,
    DEFAULT_ROLE_PERMISSIONS,
    DEFAULT_ROLES,
    ROLE_ADMIN,
    ROLE_VIEWER,
)
from src.app.auth.domain import AuthenticatedUser
from src.app.auth.security_utils import generate_raw_token, hash_raw_token, normalize_email, normalize_username
from src.app.auth.user_repository import UserRepository
from src.app.exceptions import WebAppError
from src.app.models.app_user import AppUser
from src.app.models.auth_action_token import AuthActionToken
from src.app.models.auth_audit_log import AuthAuditLog
from src.app.models.auth_invite_code import AuthInviteCode
from src.app.models.auth_permission import AuthPermission
from src.app.models.auth_refresh_token import AuthRefreshToken
from src.app.models.auth_role import AuthRole
from src.app.models.auth_role_permission import AuthRolePermission
from src.app.models.auth_user_role import AuthUserRole
from src.app.web.settings import get_web_settings


class AuthService:
    def __init__(self) -> None:
        self.user_repository = UserRepository()
        self.password_service = PasswordService()
        self.jwt_service = JWTService()
        self.settings = get_web_settings()

    def login(
        self,
        session: Session,
        *,
        username: str,
        password: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[str, str, datetime, AuthenticatedUser]:
        normalized_username = normalize_username(username)
        user = self.user_repository.get_by_username(session, normalized_username)
        now = self._now()
        if user is None:
            self._audit(
                session,
                event_type="auth.login",
                event_status="failure",
                username_snapshot=normalized_username,
                ip_address=ip_address,
                user_agent=user_agent,
                detail={"reason": "user_not_found"},
            )
            session.commit()
            raise WebAppError(status_code=401, code="unauthorized", message="Username or password is incorrect")

        if self._is_locked(user, now):
            self._audit(
                session,
                event_type="auth.login",
                event_status="failure",
                user=user,
                ip_address=ip_address,
                user_agent=user_agent,
                detail={"reason": "locked", "locked_until": self._iso(user.locked_until)},
            )
            session.commit()
            raise WebAppError(status_code=401, code="unauthorized", message="Account is temporarily locked")

        if not self.password_service.verify_password(password, user.password_hash):
            self._record_failed_login(session, user=user, now=now)
            self._audit(
                session,
                event_type="auth.login",
                event_status="failure",
                user=user,
                ip_address=ip_address,
                user_agent=user_agent,
                detail={"reason": "bad_password", "failed_login_count": user.failed_login_count},
            )
            session.commit()
            raise WebAppError(status_code=401, code="unauthorized", message="Username or password is incorrect")

        if not user.is_active:
            self._audit(
                session,
                event_type="auth.login",
                event_status="failure",
                user=user,
                ip_address=ip_address,
                user_agent=user_agent,
                detail={"reason": "inactive"},
            )
            session.commit()
            raise WebAppError(status_code=401, code="unauthorized", message="User is inactive")

        if user.account_state == ACCOUNT_STATE_PENDING_VERIFICATION:
            self._audit(
                session,
                event_type="auth.login",
                event_status="failure",
                user=user,
                ip_address=ip_address,
                user_agent=user_agent,
                detail={"reason": "pending_verification"},
            )
            session.commit()
            raise WebAppError(
                status_code=403,
                code="email_verification_required",
                message="Email verification is required before login",
            )
        if user.account_state == ACCOUNT_STATE_SUSPENDED:
            self._audit(
                session,
                event_type="auth.login",
                event_status="failure",
                user=user,
                ip_address=ip_address,
                user_agent=user_agent,
                detail={"reason": "suspended"},
            )
            session.commit()
            raise WebAppError(status_code=403, code="account_suspended", message="User account is suspended")

        self._ensure_authorization_seed(session)
        user.failed_login_count = 0
        user.last_failed_login_at = None
        user.locked_until = None
        if user.account_state == ACCOUNT_STATE_LOCKED:
            user.account_state = ACCOUNT_STATE_ACTIVE

        self.user_repository.update_last_login(session, user, now)
        role_keys = self._list_role_keys_for_user(session, user.id)
        if not role_keys:
            self._assign_roles(session, user.id, [ROLE_ADMIN if user.is_admin else self._default_role()], assigned_by_user_id=None)
            role_keys = self._list_role_keys_for_user(session, user.id)
        permission_keys = self._list_permission_keys_for_roles(session, role_keys)

        access_token, access_expire_at = self._issue_access_token(user)
        refresh_token = self._issue_refresh_token(
            session,
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        self._audit(
            session,
            event_type="auth.login",
            event_status="success",
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
            detail={"roles": role_keys},
        )
        session.commit()

        return access_token, refresh_token, access_expire_at, self._build_authenticated_user(user, role_keys, permission_keys)

    def register(
        self,
        session: Session,
        *,
        username: str,
        password: str,
        display_name: str | None,
        email: str | None,
        invite_code: str | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[AppUser, str | None, str | None, str | None, datetime | None]:
        register_mode = (self.settings.auth_register_mode or "closed").strip().lower()
        if register_mode not in {"public", "invite_only", "closed"}:
            register_mode = "closed"
        if register_mode == "closed":
            raise WebAppError(status_code=403, code="registration_closed", message="User registration is disabled")

        normalized_username = normalize_username(username)
        normalized_email = normalize_email(email)
        self._validate_password(password)
        self._ensure_authorization_seed(session)

        if self.user_repository.get_by_username(session, normalized_username):
            raise WebAppError(status_code=409, code="conflict", message="Username already exists")
        if normalized_email and self.user_repository.get_by_email(session, normalized_email):
            raise WebAppError(status_code=409, code="conflict", message="Email already exists")

        invite = None
        if register_mode == "invite_only":
            if not invite_code:
                raise WebAppError(status_code=422, code="validation_error", message="Invite code is required")
            invite = self._require_valid_invite(session, invite_code=invite_code, email=normalized_email)

        require_verify = bool(self.settings.auth_require_email_verification)
        if require_verify and not normalized_email:
            raise WebAppError(status_code=422, code="validation_error", message="Email is required for registration")

        role_key = invite.role_key if invite else self._default_role()
        is_admin = role_key == ROLE_ADMIN
        account_state = ACCOUNT_STATE_PENDING_VERIFICATION if require_verify else ACCOUNT_STATE_ACTIVE
        user = self.user_repository.create_user(
            session,
            username=normalized_username,
            password_hash=self.password_service.hash_password(password),
            display_name=display_name.strip() if display_name else None,
            email=normalized_email,
            account_state=account_state,
            is_admin=is_admin,
            is_active=True,
        )
        self._assign_roles(session, user.id, [role_key], assigned_by_user_id=None)

        if invite is not None:
            invite.used_count += 1
            invite.last_used_at = self._now()

        verify_debug_token = None
        if require_verify:
            verify_debug_token = self._create_action_token(
                session,
                user_id=user.id,
                action_type=AUTH_ACTION_VERIFY_EMAIL,
                expire_minutes=self.settings.auth_verify_email_expire_minutes,
            )
        else:
            user.email_verified_at = self._now()

        self._audit(
            session,
            event_type="auth.register",
            event_status="success",
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
            detail={"register_mode": register_mode, "role_key": role_key},
        )
        access_token = None
        refresh_token = None
        access_expire_at = None
        if account_state == ACCOUNT_STATE_ACTIVE:
            access_token, access_expire_at = self._issue_access_token(user)
            refresh_token = self._issue_refresh_token(
                session,
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        session.commit()
        return user, verify_debug_token, access_token, refresh_token, access_expire_at

    def resend_verification(
        self,
        session: Session,
        *,
        username_or_email: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> str | None:
        user = self._find_user_by_identifier(session, username_or_email)
        if user is None:
            self._audit(
                session,
                event_type="auth.resend_verification",
                event_status="success",
                username_snapshot=username_or_email.strip(),
                ip_address=ip_address,
                user_agent=user_agent,
                detail={"reason": "no_user"},
            )
            session.commit()
            return None
        if user.account_state != ACCOUNT_STATE_PENDING_VERIFICATION:
            self._audit(
                session,
                event_type="auth.resend_verification",
                event_status="success",
                user=user,
                ip_address=ip_address,
                user_agent=user_agent,
                detail={"reason": "already_verified_or_inactive"},
            )
            session.commit()
            return None
        token = self._create_action_token(
            session,
            user_id=user.id,
            action_type=AUTH_ACTION_VERIFY_EMAIL,
            expire_minutes=self.settings.auth_verify_email_expire_minutes,
        )
        self._audit(
            session,
            event_type="auth.resend_verification",
            event_status="success",
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
            detail={},
        )
        session.commit()
        return token

    def verify_email(
        self,
        session: Session,
        *,
        token: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[str, str, datetime, AuthenticatedUser]:
        action_token, user = self._consume_action_token(session, token=token, action_type=AUTH_ACTION_VERIFY_EMAIL)
        now = self._now()
        user.email_verified_at = now
        user.account_state = ACCOUNT_STATE_ACTIVE
        user.is_active = True
        if user.failed_login_count:
            user.failed_login_count = 0
            user.last_failed_login_at = None
        user.locked_until = None
        action_token.used_at = now

        self._ensure_authorization_seed(session)
        role_keys = self._list_role_keys_for_user(session, user.id)
        if not role_keys:
            self._assign_roles(session, user.id, [ROLE_VIEWER], assigned_by_user_id=None)
            role_keys = self._list_role_keys_for_user(session, user.id)
        permission_keys = self._list_permission_keys_for_roles(session, role_keys)
        access_token, access_expire_at = self._issue_access_token(user)
        refresh_token = self._issue_refresh_token(session, user_id=user.id, ip_address=ip_address, user_agent=user_agent)

        self._audit(
            session,
            event_type="auth.verify_email",
            event_status="success",
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
            detail={},
        )
        session.commit()
        return access_token, refresh_token, access_expire_at, self._build_authenticated_user(user, role_keys, permission_keys)

    def forgot_password(
        self,
        session: Session,
        *,
        username_or_email: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> str | None:
        user = self._find_user_by_identifier(session, username_or_email)
        if user is None:
            self._audit(
                session,
                event_type="auth.forgot_password",
                event_status="success",
                username_snapshot=username_or_email.strip(),
                ip_address=ip_address,
                user_agent=user_agent,
                detail={"reason": "no_user"},
            )
            session.commit()
            return None
        token = self._create_action_token(
            session,
            user_id=user.id,
            action_type=AUTH_ACTION_RESET_PASSWORD,
            expire_minutes=self.settings.auth_reset_password_expire_minutes,
        )
        self._audit(
            session,
            event_type="auth.forgot_password",
            event_status="success",
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
            detail={},
        )
        session.commit()
        return token

    def reset_password(
        self,
        session: Session,
        *,
        token: str,
        new_password: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[str, str, datetime, AuthenticatedUser]:
        self._validate_password(new_password)
        action_token, user = self._consume_action_token(session, token=token, action_type=AUTH_ACTION_RESET_PASSWORD)
        now = self._now()
        user.password_hash = self.password_service.hash_password(new_password)
        user.password_changed_at = now
        user.failed_login_count = 0
        user.last_failed_login_at = None
        user.locked_until = None
        user.account_state = ACCOUNT_STATE_ACTIVE
        user.is_active = True
        action_token.used_at = now
        self._revoke_all_refresh_tokens(session, user_id=user.id, reason="password_reset")

        self._ensure_authorization_seed(session)
        role_keys = self._list_role_keys_for_user(session, user.id)
        if not role_keys:
            self._assign_roles(session, user.id, [ROLE_VIEWER], assigned_by_user_id=None)
            role_keys = self._list_role_keys_for_user(session, user.id)
        permission_keys = self._list_permission_keys_for_roles(session, role_keys)
        access_token, access_expire_at = self._issue_access_token(user)
        refresh_token = self._issue_refresh_token(session, user_id=user.id, ip_address=ip_address, user_agent=user_agent)

        self._audit(
            session,
            event_type="auth.reset_password",
            event_status="success",
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
            detail={},
        )
        session.commit()
        return access_token, refresh_token, access_expire_at, self._build_authenticated_user(user, role_keys, permission_keys)

    def refresh(
        self,
        session: Session,
        *,
        refresh_token: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[str, str, datetime, AuthenticatedUser]:
        token_hash = hash_raw_token(refresh_token)
        now = self._now()
        token_row = session.scalar(
            select(AuthRefreshToken).where(
                and_(
                    AuthRefreshToken.token_hash == token_hash,
                    AuthRefreshToken.revoked_at.is_(None),
                    AuthRefreshToken.expires_at > now,
                )
            )
        )
        if token_row is None:
            raise WebAppError(status_code=401, code="unauthorized", message="Refresh token is invalid or expired")
        user = self.user_repository.get_by_id(session, token_row.user_id)
        if user is None or not user.is_active:
            raise WebAppError(status_code=401, code="unauthorized", message="User does not exist")

        new_refresh_token = self._issue_refresh_token(session, user_id=user.id, ip_address=ip_address, user_agent=user_agent)
        token_row.revoked_at = now
        token_row.revoked_reason = "rotated"
        token_row.status = "revoked"
        token_row.updated_at = now

        role_keys = self._list_role_keys_for_user(session, user.id)
        permission_keys = self._list_permission_keys_for_roles(session, role_keys)
        access_token, access_expire_at = self._issue_access_token(user)
        self._audit(
            session,
            event_type="auth.refresh",
            event_status="success",
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
            detail={},
        )
        session.commit()
        return access_token, new_refresh_token, access_expire_at, self._build_authenticated_user(user, role_keys, permission_keys)

    def logout(
        self,
        session: Session,
        *,
        user: AuthenticatedUser,
        refresh_token: str | None,
    ) -> None:
        if refresh_token:
            token_hash = hash_raw_token(refresh_token)
            now = self._now()
            token_row = session.scalar(
                select(AuthRefreshToken).where(
                    and_(
                        AuthRefreshToken.user_id == user.id,
                        AuthRefreshToken.token_hash == token_hash,
                        AuthRefreshToken.revoked_at.is_(None),
                    )
                )
            )
            if token_row is not None:
                token_row.revoked_at = now
                token_row.revoked_reason = "logout"
                token_row.status = "revoked"
                token_row.updated_at = now
        self._audit(session, event_type="auth.logout", event_status="success", user=user, detail={})
        session.commit()

    def logout_all(self, session: Session, *, user: AuthenticatedUser) -> int:
        affected = self._revoke_all_refresh_tokens(session, user_id=user.id, reason="logout_all")
        self._audit(session, event_type="auth.logout_all", event_status="success", user=user, detail={"affected": affected})
        session.commit()
        return affected

    def list_sessions(self, session: Session, *, user_id: int, limit: int = 100) -> list[AuthRefreshToken]:
        safe_limit = max(1, min(limit, 500))
        return list(
            session.scalars(
                select(AuthRefreshToken)
                .where(AuthRefreshToken.user_id == user_id)
                .order_by(desc(AuthRefreshToken.issued_at), desc(AuthRefreshToken.id))
                .limit(safe_limit)
            )
        )

    def revoke_session(self, session: Session, *, user_id: int, session_id: int) -> None:
        row = session.scalar(
            select(AuthRefreshToken).where(
                and_(AuthRefreshToken.id == session_id, AuthRefreshToken.user_id == user_id)
            )
        )
        if row is None:
            raise WebAppError(status_code=404, code="not_found", message="Session does not exist")
        if row.revoked_at is None:
            now = self._now()
            row.revoked_at = now
            row.revoked_reason = "session_revoked"
            row.status = "revoked"
            row.updated_at = now
        session.commit()

    def validate_password(self, password: str) -> None:
        self._validate_password(password)

    def ensure_authorization_seed(self, session: Session) -> None:
        self._ensure_authorization_seed(session)

    def revoke_all_refresh_tokens(self, session: Session, *, user_id: int, reason: str) -> int:
        return self._revoke_all_refresh_tokens(session, user_id=user_id, reason=reason)

    def should_expose_action_token_debug(self) -> bool:
        return self._should_expose_action_token_debug()

    def _validate_password(self, password: str) -> None:
        if len(password) < max(1, self.settings.auth_password_min_length):
            raise WebAppError(
                status_code=422,
                code="validation_error",
                message=f"Password must be at least {self.settings.auth_password_min_length} characters",
            )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        normalized = AuthService._coerce_utc(value)
        return normalized.isoformat() if normalized else None

    @staticmethod
    def _coerce_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _default_role(self) -> str:
        default_role = (self.settings.auth_default_role or ROLE_VIEWER).strip().lower()
        return default_role or ROLE_VIEWER

    def _should_expose_action_token_debug(self) -> bool:
        return bool(self.settings.auth_debug_expose_action_token) or self.settings.app_env in {"local", "dev", "test"}

    def _record_failed_login(self, session: Session, *, user: AppUser, now: datetime) -> None:
        user.failed_login_count = int(user.failed_login_count or 0) + 1
        user.last_failed_login_at = now
        max_failures = max(1, self.settings.auth_login_max_failures)
        if user.failed_login_count >= max_failures:
            user.locked_until = now + timedelta(minutes=max(1, self.settings.auth_lock_minutes))
            user.account_state = ACCOUNT_STATE_LOCKED
        session.flush()

    @staticmethod
    def _is_locked(user: AppUser, now: datetime) -> bool:
        locked_until = AuthService._coerce_utc(user.locked_until)
        return bool(locked_until and locked_until > now)

    def _issue_access_token(self, user: AppUser) -> tuple[str, datetime]:
        expire_at = self._now() + timedelta(minutes=self.settings.jwt_expire_minutes)
        return (
            self.jwt_service.encode(user_id=user.id, username=user.username, is_admin=user.is_admin),
            expire_at,
        )

    def _issue_refresh_token(
        self,
        session: Session,
        *,
        user_id: int,
        ip_address: str | None,
        user_agent: str | None,
    ) -> str:
        raw_token = generate_raw_token()
        now = self._now()
        row = AuthRefreshToken(
            user_id=user_id,
            token_hash=hash_raw_token(raw_token),
            status="active",
            issued_at=now,
            expires_at=now + timedelta(days=max(1, self.settings.auth_refresh_token_expire_days)),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        session.add(row)
        session.flush()
        return raw_token

    def _create_action_token(
        self,
        session: Session,
        *,
        user_id: int,
        action_type: str,
        expire_minutes: int,
        payload: dict | None = None,
    ) -> str:
        now = self._now()
        session.execute(
            update(AuthActionToken)
            .where(
                and_(
                    AuthActionToken.user_id == user_id,
                    AuthActionToken.action_type == action_type,
                    AuthActionToken.used_at.is_(None),
                    AuthActionToken.revoked_at.is_(None),
                )
            )
            .values(revoked_at=now, updated_at=now)
        )
        raw_token = generate_raw_token()
        row = AuthActionToken(
            user_id=user_id,
            action_type=action_type,
            token_hash=hash_raw_token(raw_token),
            payload_json=payload or {},
            expires_at=now + timedelta(minutes=max(1, expire_minutes)),
        )
        session.add(row)
        session.flush()
        return raw_token

    def _consume_action_token(
        self,
        session: Session,
        *,
        token: str,
        action_type: str,
    ) -> tuple[AuthActionToken, AppUser]:
        now = self._now()
        row = session.scalar(
            select(AuthActionToken).where(
                and_(
                    AuthActionToken.token_hash == hash_raw_token(token),
                    AuthActionToken.action_type == action_type,
                    AuthActionToken.used_at.is_(None),
                    AuthActionToken.revoked_at.is_(None),
                )
            )
        )
        expires_at = self._coerce_utc(row.expires_at) if row else None
        if row is None or expires_at is None or expires_at <= now:
            raise WebAppError(status_code=400, code="invalid_token", message="Token is invalid or expired")
        user = self.user_repository.get_by_id(session, row.user_id)
        if user is None:
            raise WebAppError(status_code=401, code="unauthorized", message="User does not exist")
        return row, user

    def _find_user_by_identifier(self, session: Session, identifier: str) -> AppUser | None:
        trimmed = identifier.strip()
        if not trimmed:
            return None
        if "@" in trimmed:
            return self.user_repository.get_by_email(session, normalize_email(trimmed) or "")
        return self.user_repository.get_by_username(session, trimmed)

    def _require_valid_invite(self, session: Session, *, invite_code: str, email: str | None) -> AuthInviteCode:
        now = self._now()
        row = session.scalar(
            select(AuthInviteCode).where(
                and_(
                    AuthInviteCode.code_hash == hash_raw_token(invite_code.strip()),
                    AuthInviteCode.disabled_at.is_(None),
                )
            )
        )
        if row is None:
            raise WebAppError(status_code=422, code="invalid_invite", message="Invite code is invalid")
        expires_at = self._coerce_utc(row.expires_at)
        if expires_at and expires_at <= now:
            raise WebAppError(status_code=422, code="invalid_invite", message="Invite code has expired")
        if row.used_count >= row.max_uses:
            raise WebAppError(status_code=422, code="invalid_invite", message="Invite code has been fully used")
        if row.assigned_email:
            if not email or row.assigned_email.lower() != email.lower():
                raise WebAppError(status_code=422, code="invalid_invite", message="Invite code does not match the email")
        return row

    def _list_role_keys_for_user(self, session: Session, user_id: int) -> list[str]:
        return sorted(
            {
                key
                for key in session.scalars(select(AuthUserRole.role_key).where(AuthUserRole.user_id == user_id)).all()
                if key
            }
        )

    def _list_permission_keys_for_roles(self, session: Session, role_keys: list[str]) -> list[str]:
        if not role_keys:
            return []
        return sorted(
            {
                key
                for key in session.scalars(
                    select(AuthRolePermission.permission_key).where(AuthRolePermission.role_key.in_(role_keys))
                ).all()
                if key
            }
        )

    def _assign_roles(
        self,
        session: Session,
        user_id: int,
        role_keys: list[str],
        *,
        assigned_by_user_id: int | None,
    ) -> None:
        if not role_keys:
            role_keys = [ROLE_VIEWER]
        existing = {
            key
            for key in session.scalars(select(AuthUserRole.role_key).where(AuthUserRole.user_id == user_id)).all()
            if key
        }
        for role_key in sorted(set(role_keys)):
            if role_key in existing:
                continue
            session.add(
                AuthUserRole(
                    user_id=user_id,
                    role_key=role_key,
                    assigned_by_user_id=assigned_by_user_id,
                )
            )
        session.flush()

    def replace_roles(
        self,
        session: Session,
        *,
        user_id: int,
        role_keys: list[str],
        assigned_by_user_id: int | None,
    ) -> list[str]:
        self._ensure_authorization_seed(session)
        target = sorted(set(role_keys)) or [ROLE_VIEWER]
        session.execute(delete(AuthUserRole).where(AuthUserRole.user_id == user_id))
        for role_key in target:
            session.add(AuthUserRole(user_id=user_id, role_key=role_key, assigned_by_user_id=assigned_by_user_id))
        session.flush()
        return target

    def _revoke_all_refresh_tokens(self, session: Session, *, user_id: int, reason: str) -> int:
        now = self._now()
        result = session.execute(
            update(AuthRefreshToken)
            .where(and_(AuthRefreshToken.user_id == user_id, AuthRefreshToken.revoked_at.is_(None)))
            .values(revoked_at=now, revoked_reason=reason, status="revoked", updated_at=now)
        )
        return int(result.rowcount or 0)

    def _ensure_authorization_seed(self, session: Session) -> None:
        role_keys = set(session.scalars(select(AuthRole.key)).all())
        now = self._now()
        for key, name, description in DEFAULT_ROLES:
            if key not in role_keys:
                session.add(AuthRole(key=key, name=name, description=description, is_system=True))

        permission_keys = set(session.scalars(select(AuthPermission.key)).all())
        for key, name, description in DEFAULT_PERMISSIONS:
            if key not in permission_keys:
                session.add(AuthPermission(key=key, name=name, description=description))
        session.flush()

        mapping = {
            (role_key, permission_key)
            for role_key, permission_key in session.execute(
                select(AuthRolePermission.role_key, AuthRolePermission.permission_key)
            ).all()
        }
        for role_key, permission_list in DEFAULT_ROLE_PERMISSIONS.items():
            for permission_key in permission_list:
                key = (role_key, permission_key)
                if key in mapping:
                    continue
                session.add(AuthRolePermission(role_key=role_key, permission_key=permission_key))
        session.flush()

    def _build_authenticated_user(
        self,
        user: AppUser,
        role_keys: list[str],
        permission_keys: list[str],
    ) -> AuthenticatedUser:
        return AuthenticatedUser(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            email=user.email,
            account_state=user.account_state,
            is_admin=user.is_admin,
            is_active=user.is_active,
            roles=tuple(role_keys),
            permissions=tuple(permission_keys),
        )

    def _audit(
        self,
        session: Session,
        *,
        event_type: str,
        event_status: str,
        user: AuthenticatedUser | AppUser | None = None,
        username_snapshot: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        detail: dict | None = None,
    ) -> None:
        user_id = None
        username = username_snapshot
        if user is not None:
            user_id = user.id
            username = username or user.username
        session.add(
            AuthAuditLog(
                user_id=user_id,
                username_snapshot=username,
                event_type=event_type,
                event_status=event_status,
                ip_address=ip_address,
                user_agent=user_agent,
                detail_json=detail or {},
                occurred_at=self._now(),
            )
        )
        session.flush()


__all__ = ["AuthService"]
