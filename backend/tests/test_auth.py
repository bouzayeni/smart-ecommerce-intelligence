"""Authentication, token rotation, RBAC administration, rate limiting, audit trail."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.db
PW = "Str0ng-enough-password"


def _register(client, email=None):
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    return email, client.post(
        "/api/auth/register", json={"email": email, "password": PW, "full_name": "Test"}
    )


def _login(client, email, password=PW):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_register_login_me(client):
    email, r = _register(client)
    assert r.status_code == 201 and r.json()["role"] == "viewer"
    assert "password_hash" not in r.json()
    tokens = _login(client, email).json()
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == email


@pytest.mark.parametrize(
    "password", ["short", "alllowercase123", "ALLUPPERCASE123", "NoDigitsHere!!"]
)
def test_weak_passwords_are_rejected(client, password):
    r = client.post(
        "/api/auth/register",
        json={"email": "weak@example.com", "password": password, "full_name": "W"},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_duplicate_email_is_rejected_case_insensitively(client):
    email, _ = _register(client)
    _, r = _register(client, email.upper())
    assert r.status_code == 409


def test_failed_login_is_audited(client, warehouse, app_schema):
    email, _ = _register(client)
    r = _login(client, email, "Wrong-password-1")
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"
    from app.db.session import app_engine

    with app_engine().connect() as conn:
        rows = conn.execute(
            sa.text(
                "select status, details from audit_log where action = 'login' "
                "and user_id = (select id from users where email = :e)"
            ),
            {"e": email},
        ).all()
    assert ("failure", {"reason": "bad_credentials"}) in [tuple(r) for r in rows]


def test_unknown_email_and_wrong_password_look_identical(client):
    email, _ = _register(client)
    a = _login(client, email, "Wrong-password-1").json()["error"]
    b = _login(client, "nobody@example.com", "Wrong-password-1").json()["error"]
    assert (a["code"], a["message"]) == (b["code"], b["message"])


def test_refresh_rotates_and_reuse_revokes_the_family(client):
    email, _ = _register(client)
    first = _login(client, email).json()
    second = client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert second.status_code == 200
    assert second.json()["refresh_token"] != first["refresh_token"]
    reuse = client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert reuse.status_code == 401 and reuse.json()["error"]["code"] == "refresh_token_reused"
    # The legitimately rotated token is now revoked too (whole family).
    after = client.post("/api/auth/refresh", json={"refresh_token": second.json()["refresh_token"]})
    assert after.status_code == 401


def test_logout_revokes_refresh_token(client):
    email, _ = _register(client)
    tokens = _login(client, email).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    r = client.post(
        "/api/auth/logout", json={"refresh_token": tokens["refresh_token"]}, headers=headers
    )
    assert r.status_code == 204
    assert (
        client.post(
            "/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        ).status_code
        == 401
    )


def test_tampered_and_expired_tokens_are_rejected(client, make_user):
    from app.core.config import get_settings

    user = make_user("viewer")
    good = user["headers"]["Authorization"].split()[1]
    tampered = good[:-2] + ("aa" if good[-2:] != "aa" else "bb")
    s = get_settings()
    expired = jwt.encode(
        {
            "sub": str(user["id"]),
            "role": "viewer",
            "type": "access",
            "exp": datetime.now(UTC) - timedelta(minutes=1),
        },
        s.jwt_secret_key.get_secret_value(),
        algorithm="HS256",
    )
    wrong_type = jwt.encode(
        {
            "sub": str(user["id"]),
            "type": "refresh",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        s.jwt_secret_key.get_secret_value(),
        algorithm="HS256",
    )
    none_alg = jwt.encode(
        {"sub": str(user["id"]), "type": "access", "exp": datetime.now(UTC) + timedelta(minutes=5)},
        key=None,
        algorithm="none",
    )
    for token in (tampered, expired, wrong_type, none_alg):
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401, token


def test_only_admins_change_roles(client, make_user):
    admin, analyst, target = make_user("admin"), make_user("analyst"), make_user("viewer")
    url = f"/api/auth/users/{target['id']}/role"
    assert client.patch(url, json={"role": "admin"}, headers=analyst["headers"]).status_code == 403
    r = client.patch(url, json={"role": "analyst"}, headers=admin["headers"])
    assert r.status_code == 200 and r.json()["role"] == "analyst"
    assert (
        client.patch(url, json={"role": "superuser"}, headers=admin["headers"]).status_code == 422
    )


def test_login_is_rate_limited(client):
    from app.core.config import get_settings

    limit = int(get_settings().rate_limit_auth.split("/")[0])
    codes = [
        _login(client, "nobody@example.com", "Wrong-password-1").status_code
        for _ in range(limit + 1)
    ]
    assert codes[:limit] == [401] * limit
    assert codes[-1] == 429
