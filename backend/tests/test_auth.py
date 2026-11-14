"""Authentication, tokens and role checks."""

import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.routing import APIRoute
from jose import jwt

from app.core.config import settings
from app.main import app

# The only API routes that are meant to work without a token.
PUBLIC_ROUTES = {("GET", "/api/health"), ("POST", "/api/auth/login")}
SSE_ROUTE = ("GET", "/api/stream/status")


def _protected_routes() -> list:
    """Every (method, path) the app serves, minus the public ones.

    Built from ``app.routes`` so a route added later is covered automatically.
    The interactive docs (/docs, /openapi.json, /redoc) are not ``APIRoute``
    objects and are left out.
    """
    params = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in sorted(route.methods):
            key = (method, route.path)
            if key in PUBLIC_ROUTES:
                continue
            marks = []
            if key == SSE_ROUTE:
                marks.append(
                    pytest.mark.xfail(
                        strict=True,
                        reason=(
                            "BUG: the SSE stream answers 422 (missing 'token' query "
                            "parameter) instead of 401 when no token is supplied"
                        ),
                    )
                )
            params.append(pytest.param(method, route.path, id=f"{method} {route.path}", marks=marks))
    return params


def _token(sub: str | None = "admin", minutes: int = 5, secret: str | None = None, **claims) -> str:
    payload = {"exp": datetime.now(timezone.utc) + timedelta(minutes=minutes), **claims}
    if sub is not None:
        payload["sub"] = sub
    return jwt.encode(payload, secret or settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- 401: no token / bad token -------------------------------------------------


@pytest.mark.parametrize(("method", "path"), _protected_routes())
def test_protected_route_returns_401_without_a_token(client, method, path):
    url = re.sub(r"\{[^}]+\}", "1", path)  # fill path parameters with a dummy value

    response = client.request(method, url)

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_public_routes_work_without_a_token(client):
    assert client.get("/api/health").status_code == 200
    # Reached without a token: it complains about the missing form fields.
    assert client.post("/api/auth/login").status_code == 422


@pytest.mark.parametrize(
    "make_token",
    [
        lambda: "not-a-jwt",
        lambda: _token(secret="some-other-secret"),
        lambda: _token(minutes=-1),
        lambda: _token(sub="no-such-user"),
        lambda: _token(sub=None),
    ],
    ids=["garbage", "wrong-signature", "expired", "unknown-user", "no-subject"],
)
def test_invalid_token_returns_401(client, make_token):
    response = client.get("/api/devices", headers=_bearer(make_token()))

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_stream_rejects_an_invalid_query_token(client):
    response = client.get("/api/stream/status", params={"token": "not-a-jwt"})

    assert response.status_code == 401


def test_any_correctly_signed_token_is_accepted_without_a_login(client):
    # Tokens are stateless: the server keeps no session, it only checks the
    # signature, the expiry and that the user still exists.
    response = client.get("/api/auth/me", headers=_bearer(_token(sub="viewer")))

    assert response.status_code == 200
    assert response.json() == {"username": "viewer", "role": "viewer"}


# --- login ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("username", "password", "role"),
    [("admin", "admin123", "admin"), ("viewer", "viewer123", "viewer")],
)
def test_login_with_the_seeded_accounts(client, username, password, role):
    response = client.post("/api/auth/login", data={"username": username, "password": password})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "token_type", "role", "username"}
    assert (body["token_type"], body["role"], body["username"]) == ("bearer", role, username)

    claims = jwt.decode(
        body["access_token"], settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )
    assert (claims["sub"], claims["role"]) == (username, role)
    lifetime = datetime.fromtimestamp(claims["exp"], timezone.utc) - datetime.now(timezone.utc)
    assert timedelta(minutes=479) < lifetime <= timedelta(minutes=480)  # 8 hours


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("admin", "wrong-password"),
        ("no-such-user", "admin123"),
        ("Admin", "admin123"),  # usernames are case-sensitive
        ("admin", ""),
    ],
)
def test_login_failure_is_a_generic_401(client, username, password):
    response = client.post("/api/auth/login", data={"username": username, "password": password})

    assert response.status_code == 401
    # Same message whether the username or the password was wrong.
    assert response.json() == {"detail": "Incorrect username or password"}


def test_login_requires_a_username_and_password_form(client):
    assert client.post("/api/auth/login", data={"username": "admin"}).status_code == 422
    assert client.post("/api/auth/login", json={"username": "admin", "password": "admin123"}).status_code == 422


def test_me_returns_the_callers_identity(client, admin_headers, viewer_headers):
    assert client.get("/api/auth/me", headers=admin_headers).json() == {"username": "admin", "role": "admin"}
    assert client.get("/api/auth/me", headers=viewer_headers).json() == {"username": "viewer", "role": "viewer"}


# --- roles ---------------------------------------------------------------------

NEW_DEVICE = {"id": "plc-new", "name": "New PLC", "type": "plc", "ip": "10.99.0.50", "zone": "ot-tier"}
NEW_USER = {"username": "operator", "password": "operator-pass", "role": "viewer"}

ADMIN_ONLY = [
    ("POST", "/api/devices", NEW_DEVICE),
    ("PATCH", "/api/devices/fw-01", {"name": "Renamed"}),
    ("DELETE", "/api/devices/scanner-1", None),
    ("PATCH", "/api/settings", {"site_name": "Renamed"}),
    ("GET", "/api/users", None),
    ("POST", "/api/users", NEW_USER),
    ("DELETE", "/api/users/1", None),
    ("POST", "/api/incidents/1/acknowledge", None),
    ("POST", "/api/incidents/1/notes", {"text": "checked the cabling"}),
]


@pytest.mark.parametrize(
    ("method", "path", "body"), ADMIN_ONLY, ids=[f"{method} {path}" for method, path, _ in ADMIN_ONLY]
)
def test_admin_only_route_returns_403_for_a_viewer(client, viewer_headers, method, path, body):
    response = client.request(method, path, headers=viewer_headers, json=body)

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient permissions"}


def test_a_rejected_viewer_request_changes_nothing(client, viewer_headers, admin_headers):
    client.delete("/api/devices/scanner-1", headers=viewer_headers)
    client.delete("/api/users/1", headers=viewer_headers)
    client.patch("/api/settings", headers=viewer_headers, json={"site_name": "Renamed"})

    assert client.get("/api/devices/scanner-1", headers=admin_headers).status_code == 200
    assert len(client.get("/api/users", headers=admin_headers).json()) == 2
    assert client.get("/api/settings", headers=admin_headers).json()["site_name"] == "Warehouse Network Monitor"


@pytest.mark.parametrize(
    "path",
    [
        "/api/auth/me",
        "/api/status",
        "/api/devices",
        "/api/devices/fw-01",
        "/api/history/fw-01",
        "/api/flaps",
        "/api/incidents",
        "/api/incidents/history",
        "/api/stats/incidents",
        "/api/stats/availability",
        "/api/playbooks/switch/down",
        "/api/settings",
    ],
)
def test_a_viewer_can_read_everything_except_users(client, viewer_headers, path):
    assert client.get(path, headers=viewer_headers).status_code == 200


def test_the_role_comes_from_the_database_not_from_the_token(client):
    # A viewer's token that claims to be an admin still gets a viewer's rights.
    forged_claim = _bearer(_token(sub="viewer", role="admin"))

    assert client.get("/api/users", headers=forged_claim).status_code == 403


# --- change password -----------------------------------------------------------


def _change_password(client, headers, current: str, new: str):
    return client.patch(
        "/api/auth/change-password",
        headers=headers,
        json={"current_password": current, "new_password": new},
    )


def _can_log_in(client, username: str, password: str) -> bool:
    response = client.post("/api/auth/login", data={"username": username, "password": password})
    return response.status_code == 200


def test_change_password(client, admin_headers):
    response = _change_password(client, admin_headers, "admin123", "a-new-password")

    assert response.status_code == 200
    assert response.json() == {"detail": "Password updated successfully"}
    assert not _can_log_in(client, "admin", "admin123")
    assert _can_log_in(client, "admin", "a-new-password")


def test_a_viewer_can_change_their_own_password(client, viewer_headers):
    assert _change_password(client, viewer_headers, "viewer123", "a-new-password").status_code == 200
    assert _can_log_in(client, "viewer", "a-new-password")


def test_change_password_rejects_a_wrong_current_password(client, admin_headers):
    response = _change_password(client, admin_headers, "not-my-password", "a-new-password")

    assert response.status_code == 401
    assert response.json() == {"detail": "Current password is incorrect"}
    assert _can_log_in(client, "admin", "admin123")  # unchanged


def test_change_password_enforces_the_8_character_minimum(client, admin_headers):
    too_short = _change_password(client, admin_headers, "admin123", "1234567")

    assert too_short.status_code == 422
    assert too_short.json() == {"detail": "Password must be at least 8 characters"}
    assert _change_password(client, admin_headers, "admin123", "12345678").status_code == 200


def test_change_password_requires_both_fields(client, admin_headers):
    response = client.patch(
        "/api/auth/change-password", headers=admin_headers, json={"new_password": "a-new-password"}
    )

    assert response.status_code == 422


def test_a_token_issued_before_a_password_change_stays_valid(client, admin_headers):
    # Documented MVP behaviour: there is no token blocklist, so the old session
    # keeps working until the token expires.
    _change_password(client, admin_headers, "admin123", "a-new-password")

    assert client.get("/api/auth/me", headers=admin_headers).status_code == 200
