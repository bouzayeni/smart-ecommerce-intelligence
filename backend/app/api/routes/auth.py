import uuid

from fastapi import APIRouter, Request, Response, status

from app.api.deps import Admin, AppSession, CurrentUser
from app.core.config import get_settings
from app.core.errors import not_found
from app.core.rate_limit import limiter
from app.models.entities import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    RoleUpdate,
    TokenResponse,
    UserOut,
)
from app.services import audit, auth_service

router = APIRouter(prefix="/auth", tags=["auth"])
AUTH_LIMIT = get_settings().rate_limit_auth


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(AUTH_LIMIT)
def register(request: Request, response: Response, body: RegisterRequest, session: AppSession):
    """Self-service sign-up. New accounts are viewers; an admin grants higher roles."""
    return auth_service.register(session, request, body.email, body.password, body.full_name)


@router.post("/login", response_model=TokenResponse)
@limiter.limit(AUTH_LIMIT)
def login(request: Request, response: Response, body: LoginRequest, session: AppSession):
    return auth_service.login(session, request, body.email, body.password)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit(AUTH_LIMIT)
def refresh(request: Request, response: Response, body: RefreshRequest, session: AppSession):
    """Rotate the refresh token. Presenting an already-rotated token revokes the session."""
    return auth_service.refresh(session, request, body.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, body: RefreshRequest, user: CurrentUser, session: AppSession):
    auth_service.logout(session, request, body.refresh_token, user)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return user


@router.patch("/users/{user_id}/role", response_model=UserOut, tags=["admin"])
def set_role(
    request: Request, user_id: uuid.UUID, body: RoleUpdate, admin: Admin, session: AppSession
):
    target = session.get(User, user_id)
    if target is None:
        raise not_found("User")
    previous, target.role = target.role, body.role
    audit.record(
        session,
        request,
        "role_change",
        "success",
        admin.id,
        target=str(user_id),
        previous=previous,
        new=body.role,
    )
    return target
