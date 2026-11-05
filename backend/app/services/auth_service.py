"""Registration, login, refresh-token rotation with reuse detection, logout."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.models.entities import RefreshToken, User
from app.services import audit

# Verified when the email is unknown so response time does not reveal which emails exist.
_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")


def _issue_tokens(session: Session, user: User, family_id: uuid.UUID | None = None) -> dict:
    access, expires_in = create_access_token(user.id, user.role)
    refresh, refresh_hash = new_refresh_token()
    days = get_settings().jwt_refresh_token_expire_days
    token = RefreshToken(
        user_id=user.id,
        token_hash=refresh_hash,
        family_id=family_id or uuid.uuid4(),
        expires_at=datetime.now(UTC) + timedelta(days=days),
    )
    session.add(token)
    session.flush()
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": expires_in,
        "_refresh_row": token,
    }


def register(session: Session, request: Request, email: str, password: str, full_name: str) -> User:
    email = email.lower()
    if session.scalar(select(User).where(User.email == email)):
        audit.record(session, request, "register", "failure", reason="email_taken")
        raise ApiError(409, "email_taken", "An account with this email already exists")
    user = User(
        email=email, full_name=full_name, password_hash=hash_password(password), role="viewer"
    )
    session.add(user)
    session.flush()
    audit.record(session, request, "register", "success", user.id)
    return user


def login(session: Session, request: Request, email: str, password: str) -> dict:
    user = session.scalar(select(User).where(User.email == email.lower()))
    valid = verify_password(password, user.password_hash if user else _DUMMY_HASH)
    if not user or not valid or not user.is_active:
        audit.record(
            session,
            request,
            "login",
            "failure",
            user.id if user else None,
            reason="inactive" if user and valid else "bad_credentials",
        )
        session.commit()  # keep the failure record even though we raise
        raise ApiError(401, "invalid_credentials", "Invalid email or password")
    user.last_login_at = datetime.now(UTC)
    tokens = _issue_tokens(session, user)
    audit.record(session, request, "login", "success", user.id)
    tokens.pop("_refresh_row")
    return tokens


def refresh(session: Session, request: Request, refresh_token: str) -> dict:
    token = session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(refresh_token))
    )
    now = datetime.now(UTC)
    if token is None:
        raise ApiError(401, "invalid_refresh_token", "Invalid refresh token")
    if token.revoked_at is not None:
        # A rotated token was presented again: assume theft, revoke the whole family.
        session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        audit.record(session, request, "refresh", "denied", token.user_id, reason="token_reuse")
        session.commit()
        raise ApiError(401, "refresh_token_reused", "Refresh token already used; session revoked")
    if token.expires_at <= now:
        raise ApiError(401, "refresh_token_expired", "Refresh token expired")
    user = session.get(User, token.user_id)
    if user is None or not user.is_active:
        raise ApiError(401, "invalid_refresh_token", "Invalid refresh token")
    tokens = _issue_tokens(session, user, token.family_id)
    token.revoked_at = now
    token.replaced_by_id = tokens.pop("_refresh_row").id
    audit.record(session, request, "refresh", "success", user.id)
    return tokens


def logout(session: Session, request: Request, refresh_token: str, user: User) -> None:
    token = session.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_refresh_token(refresh_token),
            RefreshToken.user_id == user.id,
        )
    )
    if token is not None:
        session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
    audit.record(session, request, "logout", "success", user.id)
