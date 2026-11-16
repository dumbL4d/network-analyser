"""Admin user management, including the self-delete and last-admin guards."""

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.db.session import engine
from app.models.user import User
from app.routers.users import delete_user


def _create(client, admin_headers, username="operator", password="operator-pass", role="viewer"):
    return client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": username, "password": password, "role": role},
    )


def _usernames(client, admin_headers) -> list[str]:
    return [user["username"] for user in client.get("/api/users", headers=admin_headers).json()]


def test_list_users_is_sorted_by_username_and_never_exposes_hashes(client, admin_headers):
    response = client.get("/api/users", headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == [
        {"id": 1, "username": "admin", "role": "admin"},
        {"id": 2, "username": "viewer", "role": "viewer"},
    ]


def test_create_user(client, admin_headers):
    response = _create(client, admin_headers)

    assert response.status_code == 201
    assert response.json() == {"id": 3, "username": "operator", "role": "viewer"}
    assert _usernames(client, admin_headers) == ["admin", "operator", "viewer"]
    # The new account can log in with the password it was given.
    login = client.post("/api/auth/login", data={"username": "operator", "password": "operator-pass"})
    assert login.status_code == 200
    assert login.json()["role"] == "viewer"


def test_passwords_are_stored_as_bcrypt_hashes(client, admin_headers):
    _create(client, admin_headers)

    with Session(engine) as session:
        user = session.exec(select(User).where(User.username == "operator")).one()
    assert user.password_hash.startswith("$2b$")
    assert "operator-pass" not in user.password_hash


def test_create_user_rejects_a_duplicate_username(client, admin_headers):
    response = _create(client, admin_headers, username="viewer")

    assert response.status_code == 409
    assert response.json() == {"detail": "Username 'viewer' already exists"}


def test_create_user_enforces_the_8_character_minimum(client, admin_headers):
    too_short = _create(client, admin_headers, password="1234567")

    assert too_short.status_code == 422
    assert too_short.json() == {"detail": "Password must be at least 8 characters"}
    assert _create(client, admin_headers, password="12345678").status_code == 201


def test_create_user_rejects_an_unknown_role(client, admin_headers):
    assert _create(client, admin_headers, role="superuser").status_code == 422


def test_delete_user(client, admin_headers, viewer_headers):
    response = client.delete("/api/users/2", headers=admin_headers)

    assert response.status_code == 204
    assert _usernames(client, admin_headers) == ["admin"]
    # The account is gone: it can neither log in nor keep using its old token.
    assert client.post("/api/auth/login", data={"username": "viewer", "password": "viewer123"}).status_code == 401
    assert client.get("/api/auth/me", headers=viewer_headers).status_code == 401


def test_delete_unknown_user_is_404(client, admin_headers):
    response = client.delete("/api/users/999", headers=admin_headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_an_admin_cannot_delete_their_own_account(client, admin_headers):
    response = client.delete("/api/users/1", headers=admin_headers)

    assert response.status_code == 400
    assert response.json() == {"detail": "Cannot delete your own account while logged in"}
    assert _usernames(client, admin_headers) == ["admin", "viewer"]


def test_an_admin_can_delete_another_admin(client, admin_headers):
    created = _create(client, admin_headers, username="second-admin", role="admin").json()

    assert client.delete(f"/api/users/{created['id']}", headers=admin_headers).status_code == 204
    assert _usernames(client, admin_headers) == ["admin", "viewer"]


def test_the_last_admin_cannot_be_deleted(db):
    # Over HTTP this guard is shadowed by the self-delete guard: when only one
    # admin exists, the only caller allowed to delete it is that same admin.
    # It matters when the caller's own account has just disappeared (two admins
    # deleting each other), which is reproduced here by calling the handler
    # with an admin that is no longer in the database.
    departed_admin = User(id=999, username="departed", password_hash="x", role="admin")

    with Session(engine) as session:
        with pytest.raises(HTTPException) as raised:
            delete_user(user_id=1, session=session, current_user=departed_admin)

        assert raised.value.status_code == 400
        assert raised.value.detail == "Cannot delete the last remaining admin account"
        assert session.get(User, 1) is not None
