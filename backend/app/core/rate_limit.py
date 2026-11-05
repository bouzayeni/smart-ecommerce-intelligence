"""Per-client rate limiting (slowapi). The in-memory store suits a single API process; with
several workers or hosts, point `storage_uri` at Redis."""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[get_settings().rate_limit_default],
    headers_enabled=True,
)
