"""The links API: list, add and delete the extra links between devices.

The rules themselves are tested in test_device_links.py; here it is about the
HTTP contract: shapes, status codes, messages and roles. The database is the
classic 11-device tree with no links.
"""

import pytest
from sqlmodel import Session

from app.db.session import engine
from app.services import device_links
from app.services.device_links import LinkConflict, add_link


def create(client, headers, a: str, b: str):
    return client.post("/api/links", headers=headers, json={"device_a_id": a, "device_b_id": b})


def listed(client, headers) -> list[tuple[str, str]]:
    response = client.get("/api/links", headers=headers)
    assert response.status_code == 200
    return [(link["device_a_id"], link["device_b_id"]) for link in response.json()]


# --- list and create -----------------------------------------------------------


def test_there_are_no_links_to_begin_with(client, admin_headers):
    assert client.get("/api/links", headers=admin_headers).json() == []


def test_create_returns_the_link_with_the_smaller_id_first(client, admin_headers):
    response = create(client, admin_headers, "sw-server", "plc-conveyor-1")

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "device_a_id", "device_b_id"}
    assert (body["device_a_id"], body["device_b_id"]) == ("plc-conveyor-1", "sw-server")
    assert isinstance(body["id"], int)


def test_list_is_ordered_by_the_two_device_ids(client, admin_headers):
    create(client, admin_headers, "sw-server", "scanner-1")
    create(client, admin_headers, "hmi-panel-1", "srv-prod-1")
    create(client, admin_headers, "hmi-panel-1", "plc-conveyor-1")

    assert listed(client, admin_headers) == [
        ("hmi-panel-1", "plc-conveyor-1"),
        ("hmi-panel-1", "srv-prod-1"),
        ("scanner-1", "sw-server"),
    ]


# --- validation ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "status", "detail"),
    [
        ("scanner-1", "scanner-1", 422, "A device cannot be linked to itself"),
        ("scanner-1", "ghost", 422, "Device 'ghost' does not exist"),
        ("ghost", "scanner-1", 422, "Device 'ghost' does not exist"),
        ("scanner-1", "sw-ot", 409, "'scanner-1' and 'sw-ot' are already connected as parent and child"),
        ("sw-edge", "sw-server", 409, "'sw-edge' and 'sw-server' are already connected as parent and child"),
        ("plc-conveyor-1", "sw-server", 409, "'plc-conveyor-1' and 'sw-server' are already linked"),
        ("sw-server", "plc-conveyor-1", 409, "'sw-server' and 'plc-conveyor-1' are already linked"),
    ],
)
def test_create_rejects_a_link_that_breaks_a_rule(client, admin_headers, a, b, status, detail):
    create(client, admin_headers, "plc-conveyor-1", "sw-server")

    response = create(client, admin_headers, a, b)

    assert (response.status_code, response.json()) == (status, {"detail": detail})
    assert listed(client, admin_headers) == [("plc-conveyor-1", "sw-server")]  # nothing was added


@pytest.mark.parametrize("body", [{}, {"device_a_id": "scanner-1"}, {"device_a_id": "scanner-1", "device_b_id": None}])
def test_create_requires_both_device_ids(client, admin_headers, body):
    assert client.post("/api/links", headers=admin_headers, json=body).status_code == 422


@pytest.mark.usefixtures("db")
def test_a_pair_stored_by_someone_else_in_the_meantime_is_a_conflict_not_a_crash(monkeypatch):
    with Session(engine) as session:
        add_link(session, "plc-conveyor-1", "sw-server")
    # The check passes (as if it ran just before the other request committed).
    monkeypatch.setattr(device_links, "check_link", lambda parents, existing, a, b: ("plc-conveyor-1", "sw-server"))

    with Session(engine) as session, pytest.raises(LinkConflict, match="already linked"):
        add_link(session, "plc-conveyor-1", "sw-server")


# --- delete --------------------------------------------------------------------


def test_delete_removes_the_link(client, admin_headers):
    link_id = create(client, admin_headers, "plc-conveyor-1", "sw-server").json()["id"]
    create(client, admin_headers, "hmi-panel-1", "sw-server")

    response = client.delete(f"/api/links/{link_id}", headers=admin_headers)

    assert (response.status_code, response.content) == (204, b"")
    assert listed(client, admin_headers) == [("hmi-panel-1", "sw-server")]
    # And the pair can be linked again afterwards.
    assert create(client, admin_headers, "plc-conveyor-1", "sw-server").status_code == 201


def test_delete_unknown_link_is_404(client, admin_headers):
    response = client.delete("/api/links/999", headers=admin_headers)

    assert (response.status_code, response.json()) == (404, {"detail": "Link not found"})


def test_deleting_a_device_removes_its_links_from_the_list(client, admin_headers):
    create(client, admin_headers, "scanner-1", "sw-server")
    create(client, admin_headers, "hmi-panel-1", "scanner-1")
    create(client, admin_headers, "hmi-panel-1", "sw-server")

    assert client.delete("/api/devices/scanner-1", headers=admin_headers).status_code == 204

    assert listed(client, admin_headers) == [("hmi-panel-1", "sw-server")]


# --- roles -----------------------------------------------------------------------


def test_a_viewer_can_list_links_but_not_change_them(client, admin_headers, viewer_headers):
    link_id = create(client, admin_headers, "plc-conveyor-1", "sw-server").json()["id"]

    assert listed(client, viewer_headers) == [("plc-conveyor-1", "sw-server")]
    assert create(client, viewer_headers, "hmi-panel-1", "sw-server").status_code == 403
    assert client.delete(f"/api/links/{link_id}", headers=viewer_headers).status_code == 403
    assert listed(client, admin_headers) == [("plc-conveyor-1", "sw-server")]  # nothing changed
