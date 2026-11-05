"""Authentication and role-based authorization dependencies."""

import uuid
from typing import Annotated

import jwt
import sqlalchemy as sa
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_app_session, get_read_connection
from app.models.entities import ROLES, User
from app.services import audit

bearer = HTTPBearer(auto_error=False)
ROLE_RANK = {role: i for i, role in enumerate(ROLES)}  # viewer < analyst < admin

AppSession = Annotated[Session, Depends(get_app_session)]
ReadConn = Annotated[sa.Connection, Depends(get_read_connection)]


def get_current_user(
    request: Request,
    session: AppSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"}
    )
    if credentials is None:
        raise unauthorized
    try:
        payload = decode_access_token(credentials.credentials)
        user = session.get(User, uuid.UUID(payload["sub"]))
    except (jwt.InvalidTokenError, ValueError):
        raise unauthorized from None
    if user is None or not user.is_active:
        raise unauthorized
    request.state.user_id = str(user.id)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(minimum: str):
    """Dependency factory: the user's role must be at least `minimum`."""

    def check(request: Request, user: CurrentUser, session: AppSession) -> User:
        if ROLE_RANK[user.role] < ROLE_RANK[minimum]:
            audit.record(
                session,
                request,
                "authorization",
                "denied",
                user.id,
                path=request.url.path,
                required=minimum,
                role=user.role,
            )
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role '{minimum}' or higher")
        return user

    return check


Viewer = Annotated[User, Depends(require_role("viewer"))]
Analyst = Annotated[User, Depends(require_role("analyst"))]
Admin = Annotated[User, Depends(require_role("admin"))]
