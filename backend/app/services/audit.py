"""Audit trail of security-relevant actions (app.audit_log)."""

import uuid

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.entities import AuditLog


def record(
    session: Session,
    request: Request | None,
    action: str,
    status: str,
    user_id: uuid.UUID | None = None,
    **details,
) -> None:
    session.add(
        AuditLog(
            user_id=user_id,
            action=action,
            status=status,
            request_id=getattr(request.state, "request_id", None) if request else None,
            ip_address=request.client.host if request and request.client else None,
            details=details or None,
        )
    )
