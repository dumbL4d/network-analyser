"""The audit log: an entry for every audited action, none for a request that
was rejected, and GET /api/audit. (The chaos actions are in test_chaos.py.)"""

import json
import logging
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.db.session import engine
from app.main import app
from app.models.audit import AuditEvent
from app.services import audit
from tests.helpers import store_incident, stored


def trail(*, logins: bool = False) -> list[tuple]:
    """(actor, action, target, details) of every event, oldest first.

    The ``admin_headers`` and ``viewer_headers`` fixtures log in, so
    successful logins are left out unless a test is about them.
    """
    events = stored(AuditEvent.__table__, "actor", "action", "target", "details")
    return [event for event in events if logins or event[1] != "auth.login"]


def _login(client, username: str, password: str):
    return client.post("/api/auth/login", data={"username": username, "password": password})


def _change_password(client, headers, current: str, new: str):
    return client.patch(
        "/api/auth/change-password",
        headers=headers,
        json={"current_password": current, "new_password": new},
    )


# =============================================================================
# One entry per audited action
# =============================================================================


def test_logins_are_recorded_whether_they_succeed_or_fail(client):
    assert _login(client, "admin", "admin123").status_code == 200
    assert _login(client, "admin", "wrong-password").status_code == 401
    assert _login(client, "no-such-user", "whatever").status_code == 401

    assert trail(logins=True) == [
        ("admin", "auth.login", None, {}),
        ("admin", "auth.login_failed", None, {}),
        ("no-such-user", "auth.login_failed", None, {}),  # the name that was tried
    ]


def test_an_entry_has_the_time_and_the_address_of_the_caller(client):
    before = datetime.now(timezone.utc)
    _login(client, "admin", "admin123")
    _login(TestClient(app, client=("10.0.0.7", 50000)), "viewer", "viewer123")

    (first_ts, first_ip), (_, second_ip) = stored(AuditEvent.__table__, "ts", "ip")

    assert (first_ip, second_ip) == ("testclient", "10.0.0.7")
    assert before <= first_ts.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc)


def test_the_throttle_blocking_a_caller_is_recorded_once(client):
    for _ in range(5):
        _login(client, "admin", "wrong-password")
    for _ in range(3):  # refused: neither counted nor logged
        assert _login(client, "admin", "admin123").status_code == 429

    assert trail() == [("admin", "auth.login_failed", None, {})] * 5 + [
        ("admin", "auth.login_blocked", None, {})
    ]


def test_a_block_caused_by_wrong_current_passwords_is_recorded_too(client, admin_headers):
    for _ in range(5):
        _change_password(client, admin_headers, "not-my-password", "a-new-password")

    assert trail() == [("admin", "auth.login_blocked", None, {})]


def test_only_the_start_of_an_overlong_username_is_recorded(client):
    _login(client, "x" * 5000, "whatever")

    assert trail() == [("x" * 128, "auth.login_failed", None, {})]


def test_a_password_change_is_recorded(client, viewer_headers):
    assert _change_password(client, viewer_headers, "viewer123", "a-new-password").status_code == 200

    assert trail() == [("viewer", "auth.password_changed", None, {"forced": False})]


def test_a_forced_password_change_is_recorded_as_such(db, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    with TestClient(app) as client:  # this start makes the default accounts change theirs
        token = _login(client, "admin", "admin123").json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert _change_password(client, headers, "admin123", "a-new-password").status_code == 200

    assert trail() == [("admin", "auth.password_changed", None, {"forced": True})]


def test_a_wrong_current_password_changes_nothing_and_records_no_change(client, admin_headers):
    assert _change_password(client, admin_headers, "not-my-password", "a-new-password").status_code == 401

    assert trail() == []


def test_creating_and_deleting_a_user_is_recorded(client, admin_headers):
    new_user = {"username": "operator", "password": "operator-pass", "role": "viewer"}
    created = client.post("/api/users", headers=admin_headers, json=new_user)
    assert created.status_code == 201
    assert client.delete(f"/api/users/{created.json()['id']}", headers=admin_headers).status_code == 204

    assert trail() == [
        ("admin", "user.created", "operator", {"role": "viewer"}),
        ("admin", "user.deleted", "operator", {"role": "viewer"}),
    ]


NEW_DEVICE = {"id": "plc-new", "name": "New PLC", "type": "plc", "ip": "10.99.0.50", "zone": "ot-tier"}


def test_creating_updating_and_deleting_a_device_is_recorded(client, admin_headers):
    assert client.post("/api/devices", headers=admin_headers, json=NEW_DEVICE).status_code == 201
    changes = {"name": "Line 3 PLC", "ip": "10.99.0.50", "parent_id": "sw-ot"}  # the ip is not a change
    assert client.patch("/api/devices/plc-new", headers=admin_headers, json=changes).status_code == 200
    assert client.delete("/api/devices/plc-new", headers=admin_headers).status_code == 204

    assert trail() == [
        (
            "admin",
            "device.created",
            "plc-new",
            {
                "name": "New PLC",
                "type": "plc",
                "ip": "10.99.0.50",
                "zone": "ot-tier",
                "parent_id": None,
                "ping_port": 80,
                "notes": "",
            },
        ),
        (
            "admin",
            "device.updated",
            "plc-new",
            {
                "changes": {
                    "name": {"from": "New PLC", "to": "Line 3 PLC"},
                    "parent_id": {"from": None, "to": "sw-ot"},
                }
            },
        ),
        ("admin", "device.deleted", "plc-new", {"name": "Line 3 PLC", "ip": "10.99.0.50"}),
    ]


def test_creating_and_deleting_a_link_is_recorded(client, admin_headers):
    link = {"device_a_id": "sw-server", "device_b_id": "scanner-1"}
    created = client.post("/api/links", headers=admin_headers, json=link)
    assert created.status_code == 201
    link_id = created.json()["id"]
    assert client.delete(f"/api/links/{link_id}", headers=admin_headers).status_code == 204

    assert trail() == [
        ("admin", "link.created", "scanner-1 <-> sw-server", {"link_id": link_id}),
        ("admin", "link.deleted", "scanner-1 <-> sw-server", {"link_id": link_id}),
    ]


def test_a_settings_change_is_recorded_with_the_old_and_the_new_values(client, admin_headers):
    update = {"site_name": "Plant 2", "poll_interval_seconds": 30, "flap_threshold": 3}  # 3 is what it was
    assert client.patch("/api/settings", headers=admin_headers, json=update).status_code == 200

    assert trail() == [
        (
            "admin",
            "settings.updated",
            None,
            {
                "changes": {
                    "site_name": {"from": "Warehouse Network Monitor", "to": "Plant 2"},
                    "poll_interval_seconds": {"from": 10.0, "to": 30.0},
                }
            },
        )
    ]


def test_acknowledging_an_incident_and_adding_a_note_is_recorded(client, admin_headers):
    incident_id = store_incident("sw-ot", datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc))
    url = f"/api/incidents/{incident_id}"
    assert client.post(f"{url}/acknowledge", headers=admin_headers).status_code == 200
    note = {"text": "replaced the uplink cable"}
    assert client.post(f"{url}/notes", headers=admin_headers, json=note).status_code == 201

    # Who and which incident. The text of the note is in the incident's timeline.
    assert trail() == [
        ("admin", "incident.acknowledged", str(incident_id), {"root_device_id": "sw-ot"}),
        ("admin", "incident.note_added", str(incident_id), {"root_device_id": "sw-ot"}),
    ]


# =============================================================================
# What is not recorded
# =============================================================================

REJECTED = [
    ("viewer", "POST", "/api/devices", NEW_DEVICE, 403),
    ("viewer", "PATCH", "/api/settings", {"site_name": "Plant 2"}, 403),
    ("admin", "POST", "/api/devices", {**NEW_DEVICE, "id": "fw-01"}, 409),
    ("admin", "POST", "/api/devices", {**NEW_DEVICE, "parent_id": "no-such-device"}, 422),
    ("admin", "PATCH", "/api/devices/no-such-device", {"name": "Renamed"}, 404),
    ("admin", "DELETE", "/api/devices/sw-ot", None, 409),
    ("admin", "POST", "/api/users", {"username": "viewer", "password": "long-enough", "role": "viewer"}, 409),
    ("admin", "POST", "/api/users", {"username": "operator", "password": "short", "role": "viewer"}, 422),
    ("admin", "DELETE", "/api/users/1", None, 400),
    ("admin", "DELETE", "/api/users/999", None, 404),
    ("admin", "PATCH", "/api/settings", {"poll_interval_seconds": 1}, 422),
    ("admin", "POST", "/api/links", {"device_a_id": "fw-01", "device_b_id": "fw-01"}, 422),
    ("admin", "DELETE", "/api/links/999", None, 404),
    ("admin", "POST", "/api/incidents/999/acknowledge", None, 404),
    ("admin", "POST", "/api/incidents/999/notes", {"text": "hello"}, 404),
]


@pytest.mark.parametrize(
    ("role", "method", "path", "body", "status"),
    REJECTED,
    ids=[f"{role} {method} {path} -> {status}" for role, method, path, _, status in REJECTED],
)
def test_a_rejected_request_leaves_no_entry(client, admin_headers, viewer_headers, role, method, path, body, status):
    headers = admin_headers if role == "admin" else viewer_headers

    assert client.request(method, path, headers=headers, json=body).status_code == status

    assert trail() == []


def test_reading_is_not_recorded(client, admin_headers, viewer_headers):
    for path in ("/api/devices", "/api/settings", "/api/incidents", "/api/auth/me"):
        assert client.get(path, headers=viewer_headers).status_code == 200
    assert client.get("/api/audit", headers=admin_headers).status_code == 200
    assert client.post("/api/stream/ticket", headers=admin_headers).status_code == 200

    assert trail() == []


def test_no_password_and_no_token_ever_reaches_the_log(client, admin_headers):
    token = admin_headers["Authorization"].removeprefix("Bearer ")
    _login(client, "admin", "a-wrong-guess-1")
    new_user = {"username": "operator", "password": "operator-pass", "role": "viewer"}
    client.post("/api/users", headers=admin_headers, json=new_user)
    _change_password(client, admin_headers, "admin123", "a-new-password")

    written = json.dumps(stored(AuditEvent.__table__, "actor", "action", "target", "ip", "details"))

    assert len(trail()) == 3  # the failed login, the new user, the password change
    for secret in ("admin123", "a-wrong-guess-1", "operator-pass", "a-new-password", token, "$2b$"):
        assert secret not in written


# =============================================================================
# A log that cannot be written
# =============================================================================


def test_an_action_still_succeeds_when_its_audit_entry_cannot_be_written(client, admin_headers, monkeypatch, caplog):
    def disk_full(**_):
        raise OSError("disk full")

    monkeypatch.setattr(audit, "AuditEvent", disk_full)

    with caplog.at_level(logging.ERROR, logger="app.services.audit"):
        changed = client.patch("/api/settings", headers=admin_headers, json={"site_name": "Plant 2"})
        logged_in = _login(client, "viewer", "viewer123")

    assert (changed.status_code, changed.json()["site_name"]) == (200, "Plant 2")
    assert logged_in.status_code == 200  # nobody is locked out by a full disk
    assert [record.getMessage() for record in caplog.records] == [
        "Audit: could not record 'settings.updated' by 'admin'",
        "Audit: could not record 'auth.login' by 'viewer'",
    ]


def test_a_failed_write_is_rolled_back_and_cannot_forge_log_lines(db, monkeypatch, caplog):
    def fail() -> None:
        raise OSError("disk full")

    with Session(engine) as session:
        monkeypatch.setattr(session, "commit", fail)
        with caplog.at_level(logging.ERROR, logger="app.services.audit"):
            # Does not raise. The username is whatever somebody typed at the login.
            audit.record_event(session, "eve\nINFO:forged: all is well", "auth.login_failed")
        monkeypatch.undo()
        session.commit()  # nothing of the failed event is left to be written

    assert trail(logins=True) == []
    (message,) = [record.getMessage() for record in caplog.records]
    assert message == "Audit: could not record 'auth.login_failed' by 'eve\\nINFO:forged: all is well'"
    assert "\n" not in message


# =============================================================================
# GET /api/audit
# =============================================================================


def _page(client, headers, **params) -> dict:
    response = client.get("/api/audit", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _record(n: int, start: datetime = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)) -> None:
    """``n`` events, a minute apart: admin edits a device, then viewer fails
    to log in, and so on."""
    with Session(engine) as session:
        for i in range(n):
            actor, action = (("admin", "device.updated"), ("viewer", "auth.login_failed"))[i % 2]
            audit.record_event(
                session, actor, action, f"target-{i}", "10.0.0.1", {"i": i}, now=start + timedelta(minutes=i)
            )


def test_the_log_is_returned_newest_first_with_every_field(client, admin_headers):
    _record(2)
    before = datetime.now(timezone.utc)
    client.patch("/api/settings", headers=admin_headers, json={"site_name": "Plant 2"})

    page = _page(client, admin_headers)

    assert (page["total"], page["limit"], page["offset"]) == (4, 50, 0)  # 2 + the login + the change
    newest = page["items"][0]
    assert set(newest) == {"id", "ts", "actor", "action", "target", "ip", "details"}
    assert (newest["actor"], newest["action"], newest["target"], newest["ip"]) == (
        "admin",
        "settings.updated",
        None,
        "testclient",
    )
    assert newest["details"] == {"changes": {"site_name": {"from": "Warehouse Network Monitor", "to": "Plant 2"}}}
    assert before <= datetime.fromisoformat(newest["ts"]) <= datetime.now(timezone.utc)  # UTC, with its offset
    assert [item["action"] for item in page["items"]] == [
        "settings.updated",
        "auth.login",
        "auth.login_failed",
        "device.updated",
    ]


def test_events_of_the_same_moment_are_returned_newest_id_first(client, admin_headers):
    moment = datetime(2030, 1, 1, tzinfo=timezone.utc)
    with Session(engine) as session:
        for i in range(3):
            audit.record_event(session, "admin", "device.updated", f"target-{i}", now=moment)

    targets = [item["target"] for item in _page(client, admin_headers)["items"][:3]]

    assert targets == ["target-2", "target-1", "target-0"]


def test_the_log_is_paginated(client, admin_headers):
    _record(5)  # with the admin's login: six events

    first = _page(client, admin_headers, limit=4)
    rest = _page(client, admin_headers, limit=4, offset=4)

    assert (first["total"], first["limit"], first["offset"]) == (6, 4, 0)
    assert (rest["total"], rest["limit"], rest["offset"]) == (6, 4, 4)
    assert [item["target"] for item in first["items"]] == [None, "target-4", "target-3", "target-2"]
    assert [item["target"] for item in rest["items"]] == ["target-1", "target-0"]
    assert _page(client, admin_headers, offset=6)["items"] == []


def test_the_log_can_be_filtered_by_actor_and_by_action(client, admin_headers):
    _record(5)

    by_actor = _page(client, admin_headers, actor="viewer")
    by_action = _page(client, admin_headers, action="device.updated")
    by_both = _page(client, admin_headers, actor="admin", action="auth.login")
    one_of_three = _page(client, admin_headers, action="device.updated", limit=1, offset=1)

    assert by_actor["total"] == 2
    assert {(item["actor"], item["action"]) for item in by_actor["items"]} == {("viewer", "auth.login_failed")}
    assert [item["target"] for item in by_action["items"]] == ["target-4", "target-2", "target-0"]
    assert (by_both["total"], len(by_both["items"])) == (1, 1)
    # The total is that of the filter, whatever the page.
    assert (one_of_three["total"], [item["target"] for item in one_of_three["items"]]) == (3, ["target-2"])


def test_a_filter_matches_exactly_and_an_empty_one_matches_everything(client, admin_headers):
    _record(2)

    assert _page(client, admin_headers, actor="adm")["total"] == 0
    assert _page(client, admin_headers, action="device")["total"] == 0
    assert _page(client, admin_headers, actor="nobody")["items"] == []
    assert _page(client, admin_headers, actor="", action="")["total"] == 3


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"limit": "many"}])
def test_page_parameters_out_of_range_are_422(client, admin_headers, params):
    assert client.get("/api/audit", headers=admin_headers, params=params).status_code == 422


def test_the_largest_page_is_200(client, admin_headers):
    assert _page(client, admin_headers, limit=200)["limit"] == 200


def test_a_viewer_cannot_read_the_log(client, viewer_headers):
    response = client.get("/api/audit", headers=viewer_headers)

    assert (response.status_code, response.json()) == (403, {"detail": "Insufficient permissions"})


def test_the_log_cannot_be_changed_through_the_api(client, admin_headers):
    _record(1)

    for method in ("POST", "PATCH", "PUT", "DELETE"):
        assert client.request(method, "/api/audit", headers=admin_headers).status_code == 405
        assert client.request(method, "/api/audit/1", headers=admin_headers).status_code in (404, 405)
