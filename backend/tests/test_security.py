"""Security hardening: the forced password change, how the default accounts
are seeded, tokens of accounts that are gone, login throttling over HTTP,
CORS, and the signing secret. The limiter itself is in test_rate_limit.py,
stream tickets in test_stream_tickets.py and the audit log in test_audit.py."""

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlmodel import Session, select

from app.core.config import Settings, settings
from app.core.security import (
    MIN_JWT_SECRET_LENGTH,
    PLACEHOLDER_JWT_SECRETS,
    hash_password,
    jwt_secret_problem,
    verify_password,
)
from app.db.seed_users import seed_default_users
from app.db.session import engine
from app.main import app
from app.models.user import User
from app.routers import auth
from app.services.rate_limit import login_throttle
from app.services.stream_tickets import stream_tickets
from tests.helpers import wipe_database
from tests.test_auth import _bearer, _token
from tests.test_rate_limit import FakeClock

PASSWORD_CHANGE_REQUIRED = {
    "detail": {
        "code": "password_change_required",
        "message": "Change your password before using the API",
    }
}


@pytest.fixture
def secure(db, monkeypatch) -> None:
    """DEMO_MODE off, as shipped (the suite pins it on).

    Name it BEFORE ``client`` in a test's arguments, so the app starts without
    DEMO_MODE. That startup finds the two default accounts still on their demo
    passwords and makes them change it.
    """
    monkeypatch.setattr(settings, "DEMO_MODE", False)


def _login(client, username: str, password: str):
    return client.post("/api/auth/login", data={"username": username, "password": password})


def _headers(client, username: str, password: str) -> dict[str, str]:
    response = _login(client, username, password)
    assert response.status_code == 200, response.text
    return _bearer(response.json()["access_token"])


def _change_password(client, headers, current: str, new: str):
    return client.patch(
        "/api/auth/change-password",
        headers=headers,
        json={"current_password": current, "new_password": new},
    )


def _user(username: str) -> User:
    with Session(engine) as session:
        return session.exec(select(User).where(User.username == username)).one()


def _update_user(username: str, **values) -> None:
    with Session(engine) as session:
        user = session.exec(select(User).where(User.username == username)).one()
        for field, value in values.items():
            setattr(user, field, value)
        session.add(user)
        session.commit()


# =============================================================================
# The forced password change
# =============================================================================

# What an account that still has to change its password may call ...
OPEN_ROUTES = {
    ("GET", "/api/health"),
    ("POST", "/api/auth/login"),
    ("GET", "/api/auth/me"),
    ("PATCH", "/api/auth/change-password"),
}
# ... and the one route that takes a ticket instead of the token (see below).
STREAM = ("GET", "/api/stream/status")


def _locked_routes() -> list:
    """Every other (method, path) the app serves. Built from ``app.routes``,
    so a route added later is covered automatically."""
    return [
        pytest.param(method, route.path, id=f"{method} {route.path}")
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in sorted(route.methods)
        if (method, route.path) not in OPEN_ROUTES | {STREAM}
    ]


def test_a_default_account_is_told_at_login_that_it_must_change_its_password(secure, client):
    response = _login(client, "admin", "admin123")

    assert response.status_code == 200
    assert response.json()["must_change_password"] is True
    assert client.get("/api/auth/me", headers=_bearer(response.json()["access_token"])).json() == {
        "username": "admin",
        "role": "admin",
        "must_change_password": True,
    }


@pytest.mark.parametrize(("method", "path"), _locked_routes())
def test_every_other_endpoint_is_403_until_the_password_is_changed(secure, client, method, path):
    headers = _headers(client, "admin", "admin123")
    url = re.sub(r"\{[^}]+\}", "1", path)  # fill path parameters with a dummy value

    response = client.request(method, url, headers=headers)

    assert (response.status_code, response.json()) == (403, PASSWORD_CHANGE_REQUIRED)


def test_the_stream_stays_closed_until_the_password_is_changed(secure, client):
    # No ticket can be had (POST /api/stream/ticket is 403, above), and one
    # from before would not help either.
    ticket = stream_tickets.issue("admin")

    response = client.get("/api/stream/status", params={"ticket": ticket})

    assert (response.status_code, response.json()) == (403, PASSWORD_CHANGE_REQUIRED)


def test_changing_the_password_opens_the_api_for_the_same_token(secure, client):
    headers = _headers(client, "admin", "admin123")
    assert client.get("/api/devices", headers=headers).status_code == 403

    response = _change_password(client, headers, "admin123", "a-new-password")

    assert (response.status_code, response.json()) == (200, {"detail": "Password updated successfully"})
    assert client.get("/api/devices", headers=headers).status_code == 200
    assert client.get("/api/auth/me", headers=headers).json()["must_change_password"] is False
    assert _login(client, "admin", "a-new-password").json()["must_change_password"] is False
    assert _user("admin").must_change_password is False


@pytest.mark.parametrize(
    ("current", "new", "status", "detail"),
    [
        ("admin123", "admin123", 422, "The new password must be different from the current one"),
        ("admin123", "short", 422, "Password must be at least 8 characters"),
        ("not-my-password", "a-new-password", 401, "Current password is incorrect"),
    ],
    ids=["same-password", "too-short", "wrong-current-password"],
)
def test_a_rejected_change_leaves_the_account_locked(secure, client, current, new, status, detail):
    headers = _headers(client, "admin", "admin123")

    response = _change_password(client, headers, current, new)

    assert (response.status_code, response.json()) == (status, {"detail": detail})
    assert client.get("/api/devices", headers=headers).status_code == 403
    assert _user("admin").must_change_password is True
    assert _login(client, "admin", "admin123").status_code == 200  # the password is unchanged


def test_each_default_account_changes_its_own_password(secure, client):
    admin = _headers(client, "admin", "admin123")
    viewer = _headers(client, "viewer", "viewer123")
    assert _change_password(client, admin, "admin123", "a-new-password").status_code == 200

    # The viewer is still locked, and unlocks itself the same way.
    assert client.get("/api/devices", headers=viewer).json() == PASSWORD_CHANGE_REQUIRED
    assert _change_password(client, viewer, "viewer123", "another-password").status_code == 200
    assert client.get("/api/devices", headers=viewer).status_code == 200


def test_an_account_created_by_an_admin_is_not_made_to_change_its_password(secure, client):
    admin = _headers(client, "admin", "admin123")
    _change_password(client, admin, "admin123", "a-new-password")
    new_user = {"username": "operator", "password": "operator-pass", "role": "viewer"}
    assert client.post("/api/users", headers=admin, json=new_user).status_code == 201

    response = _login(client, "operator", "operator-pass")

    assert response.json()["must_change_password"] is False
    assert client.get("/api/devices", headers=_bearer(response.json()["access_token"])).status_code == 200


def test_demo_mode_switches_the_forced_change_off(client, admin_headers):
    # Even for an account that is flagged, as in a database that was first
    # started without DEMO_MODE.
    _update_user("admin", must_change_password=True)

    assert client.get("/api/devices", headers=admin_headers).status_code == 200
    assert client.get("/api/auth/me", headers=admin_headers).json()["must_change_password"] is False
    assert _login(client, "admin", "admin123").json()["must_change_password"] is False


# =============================================================================
# Seeding the default accounts
# =============================================================================


def _reseed_users() -> None:
    """What the first start of a new installation does to the user table."""
    with engine.begin() as connection:
        connection.execute(User.__table__.delete())
    seed_default_users()


def _generated_passwords(caplog) -> dict[str, str]:
    """username -> password, for every password the seed generated and logged."""
    return {
        record.args[0]: record.args[1]
        for record in caplog.records
        if record.name == "app.db.seed_users" and "Generated the initial password" in record.msg
    }


def test_the_insecure_switches_are_off_by_default():
    defaults = {name: field.default for name, field in Settings.model_fields.items()}

    assert defaults["DEMO_MODE"] is False
    assert defaults["ADMIN_INITIAL_PASSWORD"] is None and defaults["VIEWER_INITIAL_PASSWORD"] is None
    assert defaults["JWT_EXPIRE_MINUTES"] == 60


def test_a_new_database_gets_the_configured_initial_passwords(db, monkeypatch, caplog):
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    monkeypatch.setattr(settings, "ADMIN_INITIAL_PASSWORD", "from-env-admin")
    monkeypatch.setattr(settings, "VIEWER_INITIAL_PASSWORD", "from-env-viewer")
    before = datetime.now(timezone.utc)

    with caplog.at_level(logging.INFO, logger="app.db.seed_users"):
        _reseed_users()

    for username, password, role in (("admin", "from-env-admin", "admin"), ("viewer", "from-env-viewer", "viewer")):
        user = _user(username)
        assert verify_password(password, user.password_hash)
        assert (user.role, user.must_change_password) == (role, True)
        assert before <= user.created_at <= datetime.now(timezone.utc)
    # Nothing was generated, and a configured password is never written to the log.
    assert _generated_passwords(caplog) == {}
    assert "from-env" not in caplog.text


@pytest.mark.parametrize("unset", [None, ""], ids=["not-set", "set-to-nothing"])
def test_a_missing_initial_password_is_generated_and_logged_once(db, monkeypatch, caplog, unset):
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    monkeypatch.setattr(settings, "ADMIN_INITIAL_PASSWORD", unset)
    monkeypatch.setattr(settings, "VIEWER_INITIAL_PASSWORD", unset)

    with caplog.at_level(logging.INFO, logger="app.db.seed_users"):
        _reseed_users()

    generated = _generated_passwords(caplog)
    assert set(generated) == {"admin", "viewer"}
    assert generated["admin"] != generated["viewer"]
    assert all(len(password) >= 16 for password in generated.values())
    assert not verify_password("admin123", _user("admin").password_hash)

    # The generated password works, once, to get in and change it.
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="app.db.seed_users"), TestClient(app) as client:
        response = _login(client, "admin", generated["admin"])
        assert response.status_code == 200
        assert response.json()["must_change_password"] is True
    # That second start generated nothing and logged no password.
    assert _generated_passwords(caplog) == {}
    assert generated["admin"] not in caplog.text and generated["viewer"] not in caplog.text


def test_only_the_missing_password_is_generated(db, monkeypatch, caplog):
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    monkeypatch.setattr(settings, "ADMIN_INITIAL_PASSWORD", "from-env-admin")

    with caplog.at_level(logging.INFO, logger="app.db.seed_users"):
        _reseed_users()

    generated = _generated_passwords(caplog)
    assert set(generated) == {"viewer"}
    assert verify_password(generated["viewer"], _user("viewer").password_hash)
    assert verify_password("from-env-admin", _user("admin").password_hash)


def test_demo_mode_seeds_the_documented_credentials_and_says_so_loudly(db, monkeypatch, caplog):
    monkeypatch.setattr(settings, "ADMIN_INITIAL_PASSWORD", "ignored-in-demo-mode")

    with caplog.at_level(logging.INFO, logger="app.db.seed_users"):
        _reseed_users()
        seed_default_users()  # the next start, still in DEMO_MODE

    for username, password in (("admin", "admin123"), ("viewer", "viewer123")):
        user = _user(username)
        assert verify_password(password, user.password_hash)
        assert user.must_change_password is False
    assert _generated_passwords(caplog) == {}
    # Each start says that DEMO_MODE is on, and nothing else is worth a warning.
    warnings = [record.message for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 2 and all(warning.startswith("DEMO_MODE is on") for warning in warnings)


@pytest.mark.parametrize("demo_mode", [True, False])
def test_seeding_never_overwrites_an_existing_password(client, admin_headers, monkeypatch, demo_mode):
    assert _change_password(client, admin_headers, "admin123", "a-new-password").status_code == 200
    monkeypatch.setattr(settings, "DEMO_MODE", demo_mode)
    monkeypatch.setattr(settings, "ADMIN_INITIAL_PASSWORD", "from-env-admin")

    seed_default_users()  # the next start

    admin = _user("admin")
    assert verify_password("a-new-password", admin.password_hash)
    assert admin.must_change_password is False


def test_without_demo_mode_an_account_still_on_its_demo_password_must_change_it(db, monkeypatch, caplog):
    # A database from before the forced change (or first started in DEMO_MODE):
    # the admin never changed the documented password, the viewer did.
    _update_user("viewer", password_hash=hash_password("changed-long-ago"))
    monkeypatch.setattr(settings, "DEMO_MODE", False)

    with caplog.at_level(logging.WARNING, logger="app.db.seed_users"):
        for _ in range(2):  # two starts: the second has nothing left to flag
            with TestClient(app):
                pass

    assert _user("admin").must_change_password is True
    assert _user("viewer").must_change_password is False
    assert [record.getMessage() for record in caplog.records] == [
        "'admin' still has the documented demo password: it has to be changed at the next login"
    ]


def test_only_the_default_accounts_are_checked_for_demo_passwords(client, admin_headers, monkeypatch):
    new_user = {"username": "operator", "password": "admin123", "role": "viewer"}
    assert client.post("/api/users", headers=admin_headers, json=new_user).status_code == 201
    monkeypatch.setattr(settings, "DEMO_MODE", False)

    seed_default_users()

    assert _user("operator").must_change_password is False


# =============================================================================
# Tokens: the account must still exist, and be the same account
# =============================================================================

OPERATOR = {"username": "operator", "password": "operator-pass", "role": "viewer"}


def test_a_new_account_can_use_its_token_at_once(client, admin_headers):
    # ``iat`` is in whole seconds: a token issued in the very second its
    # account was created must not look older than the account.
    assert client.post("/api/users", headers=admin_headers, json=OPERATOR).status_code == 201
    assert _user("operator").created_at is not None

    headers = _headers(client, "operator", "operator-pass")

    assert client.get("/api/auth/me", headers=headers).status_code == 200


def test_a_token_of_a_deleted_account_does_not_work_for_a_new_one_of_the_same_name(client, admin_headers):
    # "operator" existed, got this token a minute ago, and was deleted. Now an
    # admin creates a new "operator".
    issued_a_minute_ago = datetime.now(timezone.utc) - timedelta(minutes=1)
    old_token = _token(sub="operator", iat=issued_a_minute_ago)
    assert client.post("/api/users", headers=admin_headers, json=OPERATOR).status_code == 201

    response = client.get("/api/auth/me", headers=_bearer(old_token))

    assert (response.status_code, response.json()) == (401, {"detail": "Could not validate credentials"})


def test_an_account_from_before_the_upgrade_has_no_creation_time_and_keeps_working(client):
    # Migration 0006 leaves created_at empty for the accounts that existed.
    _update_user("viewer", created_at=None)
    issued_yesterday = _token(sub="viewer", iat=datetime.now(timezone.utc) - timedelta(days=1))

    assert client.get("/api/auth/me", headers=_bearer(issued_yesterday)).status_code == 200


# =============================================================================
# Login throttling
# =============================================================================


@pytest.fixture
def clock() -> FakeClock:
    """Puts the app's login throttle on a clock the test moves."""
    fake = FakeClock()
    login_throttle.__init__(clock=fake)
    return fake


TOO_MANY = {"detail": "Too many failed attempts. Try again in 300 seconds."}


def test_five_wrong_passwords_and_the_sixth_attempt_is_429(client, clock):
    for _ in range(5):
        response = _login(client, "admin", "wrong-password")
        assert (response.status_code, response.json()) == (401, {"detail": "Incorrect username or password"})

    response = _login(client, "admin", "admin123")  # even with the right password

    assert (response.status_code, response.json()) == (429, TOO_MANY)
    assert response.headers["retry-after"] == "300"


def test_the_block_ends_when_the_failures_are_five_minutes_old(client, clock):
    for _ in range(5):
        _login(client, "admin", "wrong-password")

    clock.advance(299.5)
    response = _login(client, "admin", "admin123")
    assert response.status_code == 429
    assert response.headers["retry-after"] == "1"  # rounded up to whole seconds
    assert response.json() == {"detail": "Too many failed attempts. Try again in 1 seconds."}

    clock.advance(0.5)
    assert _login(client, "admin", "admin123").status_code == 200


def test_attempts_made_while_blocked_do_not_prolong_the_block(client, clock):
    for _ in range(5):
        _login(client, "admin", "wrong-password")

    clock.advance(200)
    for _ in range(3):
        assert _login(client, "admin", "wrong-password").status_code == 429

    clock.advance(100)
    assert _login(client, "admin", "admin123").status_code == 200


def test_an_attempt_is_counted_before_its_password_is_checked(client, monkeypatch):
    # Checking a password takes a while. A guess that arrives meanwhile must
    # already find this one counted, or parallel guesses would all get through.
    blocked_during_the_check = []
    real_verify = auth.verify_password

    def verify(plain: str, hashed: str) -> bool:
        blocked_during_the_check.append(login_throttle.retry_after("testclient", "admin") > 0)
        return real_verify(plain, hashed)

    monkeypatch.setattr(auth, "verify_password", verify)

    for _ in range(5):
        _login(client, "admin", "wrong-password")

    assert blocked_during_the_check == [False, False, False, False, True]


def test_a_right_password_is_not_held_against_the_address(client):
    for _ in range(30):  # more than the 20 an address may get wrong
        assert _login(client, "admin", "admin123").status_code == 200

    assert _login(client, "viewer", "viewer123").status_code == 200


def test_a_right_current_password_is_not_counted_even_if_the_change_is_rejected(client, admin_headers):
    for _ in range(8):  # the current password is right; the new one is too short
        assert _change_password(client, admin_headers, "admin123", "short").status_code == 422

    assert _change_password(client, admin_headers, "admin123", "a-new-password").status_code == 200


def test_other_usernames_and_other_addresses_are_not_blocked(client):
    for _ in range(5):
        _login(client, "admin", "wrong-password")
    assert _login(client, "admin", "admin123").status_code == 429

    assert _login(client, "viewer", "viewer123").status_code == 200
    elsewhere = TestClient(app, client=("10.0.0.7", 50000))
    assert _login(elsewhere, "admin", "admin123").status_code == 200


def test_a_successful_login_resets_the_count(client):
    for _ in range(4):
        assert _login(client, "admin", "wrong-password").status_code == 401
    assert _login(client, "admin", "admin123").status_code == 200

    for _ in range(4):
        assert _login(client, "admin", "wrong-password").status_code == 401
    assert _login(client, "admin", "admin123").status_code == 200


def test_a_username_that_does_not_exist_is_throttled_like_one_that_does(client):
    # Otherwise the 429 would tell which usernames exist.
    for _ in range(5):
        assert _login(client, "no-such-user", "whatever").status_code == 401

    assert _login(client, "no-such-user", "whatever").status_code == 429


def test_a_username_that_does_not_exist_costs_a_password_check_as_well(client, monkeypatch):
    # So that the response time does not tell which usernames exist either.
    checked = []
    real_verify = auth.verify_password

    def verify(plain: str, hashed: str) -> bool:
        checked.append(hashed)
        return real_verify(plain, hashed)

    monkeypatch.setattr(auth, "verify_password", verify)

    assert _login(client, "no-such-user", "whatever").status_code == 401
    assert checked == [auth._NO_SUCH_USER_HASH]
    assert auth._NO_SUCH_USER_HASH.startswith("$2b$")  # a real bcrypt hash, of a random password


@pytest.mark.parametrize("password", ["with-a-\x00-byte", "x" * 5000], ids=["nul-byte", "5000-characters"])
@pytest.mark.parametrize("username", ["admin", "no-such-user"])
def test_a_password_that_cannot_be_hashed_is_a_wrong_password_not_a_crash(client, username, password):
    for _ in range(5):
        response = _login(client, username, password)
        assert (response.status_code, response.json()) == (401, {"detail": "Incorrect username or password"})

    assert _login(client, username, password).status_code == 429  # and it is counted like any other


def test_twenty_wrong_passwords_block_the_address_whatever_the_usernames(client):
    for attempt in range(20):
        assert _login(client, f"user-{attempt}", "whatever").status_code == 401

    assert _login(client, "admin", "admin123").status_code == 429
    elsewhere = TestClient(app, client=("10.0.0.7", 50000))
    assert _login(elsewhere, "admin", "admin123").status_code == 200


def test_only_the_start_of_an_overlong_username_is_counted(client):
    # The form does not limit the username; the throttle must not be made to
    # remember megabytes of them.
    start = "x" * auth.MAX_LOGGED_USERNAME_CHARS
    for attempt in range(5):
        assert _login(client, f"{start}{attempt}", "whatever").status_code == 401

    assert _login(client, f"{start}-and-more", "whatever").status_code == 429


def test_wrong_current_passwords_are_throttled_like_wrong_login_passwords(client, admin_headers):
    for _ in range(5):
        assert _change_password(client, admin_headers, "not-my-password", "a-new-password").status_code == 401

    response = _change_password(client, admin_headers, "admin123", "a-new-password")

    assert (response.status_code, response.json()) == (429, TOO_MANY)
    assert response.headers["retry-after"] == "300"
    # They are guesses at the same password, so the login is blocked as well.
    assert _login(client, "admin", "admin123").status_code == 429
    assert _login(client, "admin", "a-new-password").status_code == 429


@pytest.mark.parametrize("password", ["new-with-\x00-byte", "x" * 1025], ids=["nul-byte", "1025-characters"])
def test_a_new_password_that_cannot_be_hashed_is_422(client, admin_headers, password):
    changed = _change_password(client, admin_headers, "admin123", password)
    new_user = {"username": "operator", "password": password, "role": "viewer"}
    created = client.post("/api/users", headers=admin_headers, json=new_user)

    assert (changed.status_code, created.status_code) == (422, 422)
    assert _login(client, "admin", "admin123").status_code == 200  # unchanged
    assert _change_password(client, admin_headers, password, "a-new-password").status_code == 401


def test_the_longest_password_allowed_can_be_set_and_used(client, admin_headers):
    longest = "p" * 1024

    assert _change_password(client, admin_headers, "admin123", longest).status_code == 200
    assert _login(client, "admin", longest).status_code == 200


# =============================================================================
# CORS
# =============================================================================

ORIGIN = "http://localhost:5173"  # CORS_ORIGINS in conftest.py


def _preflight(client, origin: str = ORIGIN, method: str = "PATCH", headers: str = "authorization,content-type"):
    """What a browser sends before a cross-origin request that is not "simple"."""
    return client.options(
        "/api/settings",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": headers,
        },
    )


def test_a_listed_origin_may_call_the_api(client):
    response = _preflight(client)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["access-control-allow-methods"] == "GET, POST, PATCH, DELETE"
    # No cookies: the API only looks at the Authorization header.
    assert "access-control-allow-credentials" not in response.headers
    # The response to the request itself names the origin too.
    answered = client.get("/api/health", headers={"Origin": ORIGIN})
    assert answered.headers["access-control-allow-origin"] == ORIGIN


@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "DELETE"])
def test_the_methods_the_frontend_uses_are_allowed(client, method):
    assert _preflight(client, method=method).status_code == 200


@pytest.mark.parametrize(
    ("origin", "method", "headers", "refused"),
    [
        ("http://evil.example", "PATCH", "authorization", "origin"),
        ("http://localhost:5174", "PATCH", "authorization", "origin"),  # another port is another origin
        (ORIGIN, "PUT", "authorization", "method"),
        (ORIGIN, "PATCH", "x-something-else", "headers"),
    ],
    ids=["unknown-origin", "other-port", "unused-method", "unused-header"],
)
def test_a_preflight_for_anything_else_is_refused(client, origin, method, headers, refused):
    response = _preflight(client, origin, method, headers)

    assert (response.status_code, response.text) == (400, f"Disallowed CORS {refused}")


def test_a_response_to_an_unlisted_origin_names_no_origin(client):
    response = client.get("/api/health", headers={"Origin": "http://evil.example"})

    # Served, but without this header the browser keeps it from that page.
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize(
    "origins",
    [
        ["*"],
        ["http://*.example.com"],
        ["localhost:8080"],
        ["ftp://localhost:8080"],
        ["http://"],
        ["http://localhost:8080/"],
        ["http://localhost:8080/app"],
        ["http://a.example http://b.example"],
        ["http://localhost:8080", "*"],
    ],
)
def test_cors_origins_must_be_exact_origins(origins):
    with pytest.raises(ValidationError, match="is not an exact origin"):
        Settings(CORS_ORIGINS=origins)


def test_exact_origins_are_accepted():
    origins = ["https://monitor.example.com", "http://10.0.0.5:8080"]

    assert Settings(CORS_ORIGINS=origins).CORS_ORIGINS == origins
    assert Settings(CORS_ORIGINS=[]).CORS_ORIGINS == []  # no cross-origin access at all


# --- the signing secret ---------------------------------------------------------
# Whoever knows JWT_SECRET_KEY can sign a token for any account without a
# password. The repository ships two example values, and the backend used to
# start on them without a word.

REPO = Path(__file__).resolve().parents[2]
SHIPPED_SECRET = "CHANGE_ME_DEV_ONLY_INSECURE_DEFAULT"


@pytest.mark.parametrize("secret", [*sorted(PLACEHOLDER_JWT_SECRETS), "", "short", "x" * (MIN_JWT_SECRET_LENGTH - 1)])
def test_a_placeholder_or_a_short_secret_is_a_problem(secret):
    assert jwt_secret_problem(secret) is not None


@pytest.mark.parametrize("secret", ["x" * MIN_JWT_SECRET_LENGTH, "0f" * 32])
def test_a_long_secret_of_ones_own_is_not(secret):
    assert jwt_secret_problem(secret) is None


def test_every_secret_the_repository_ships_is_on_the_placeholder_list():
    shipped = {Settings.model_fields["JWT_SECRET_KEY"].default}
    for example in (REPO / "backend" / ".env.example", REPO / "infra" / ".env.example"):
        values = re.findall(r"^JWT_SECRET_KEY=(.*)$", example.read_text(), flags=re.MULTILINE)
        assert len(values) == 1, f"{example} should set JWT_SECRET_KEY exactly once"
        shipped.update(values)

    # Change an example file and this fails until the list follows.
    assert shipped == PLACEHOLDER_JWT_SECRETS


@pytest.fixture
def shipped_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", SHIPPED_SECRET)


def test_the_backend_refuses_to_start_on_a_shipped_secret(secure, shipped_secret):
    wipe_database()

    with pytest.raises(RuntimeError, match="Refusing to start: JWT_SECRET_KEY is still a placeholder"):
        with TestClient(app):
            pass

    # It stopped before the first migration: nothing was created or seeded.
    assert inspect(engine).get_table_names() == []


def test_the_backend_refuses_to_start_on_a_short_secret(secure, monkeypatch):
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "x" * 31)

    with pytest.raises(RuntimeError, match="is 31 characters long, and it has to be at least 32"):
        with TestClient(app):
            pass


def test_demo_mode_starts_on_a_shipped_secret_and_says_so(db, shipped_secret, caplog):
    assert settings.DEMO_MODE is True  # pinned in conftest.py

    with caplog.at_level(logging.WARNING, logger="app.core.security"), TestClient(app) as started:
        assert started.get("/api/health").status_code == 200

    warnings = [record.message for record in caplog.records if record.name == "app.core.security"]
    assert len(warnings) == 1
    assert "placeholder" in warnings[0] and "Starting anyway because DEMO_MODE is on" in warnings[0]


def test_a_secret_of_ones_own_starts_without_that_warning(secure, caplog):
    with caplog.at_level(logging.WARNING, logger="app.core.security"), TestClient(app) as started:
        assert started.get("/api/health").status_code == 200

    assert [record for record in caplog.records if record.name == "app.core.security"] == []
