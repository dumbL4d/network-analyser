"""Device CRUD: parent validation, cycle prevention, delete rules."""

import pytest

NEW_DEVICE = {
    "id": "plc-new",
    "name": "New PLC",
    "type": "plc",
    "ip": "10.99.0.50",
    "zone": "ot-tier",
    "parent_id": "sw-ot",
}


def _get(client, admin_headers, device_id: str) -> dict:
    response = client.get(f"/api/devices/{device_id}", headers=admin_headers)
    assert response.status_code == 200
    return response.json()


def _create(client, admin_headers, **overrides):
    return client.post("/api/devices", headers=admin_headers, json={**NEW_DEVICE, **overrides})


def _patch(client, admin_headers, device_id: str, **fields):
    return client.patch(f"/api/devices/{device_id}", headers=admin_headers, json=fields)


# --- read ----------------------------------------------------------------------


def test_list_returns_the_eleven_seeded_devices(client, admin_headers):
    devices = client.get("/api/devices", headers=admin_headers).json()

    assert len(devices) == 11
    assert {device["type"] for device in devices} == {
        "firewall", "switch", "server", "plc", "hmi", "ap", "scanner",
    }


def test_get_device(client, admin_headers):
    assert _get(client, admin_headers, "sw-ot") == {
        "id": "sw-ot",
        "name": "OT Tier Switch",
        "type": "switch",
        "ip": "10.99.0.4",
        "zone": "ot-tier",
        "parent_id": "sw-edge",
        "ping_port": 80,
        "notes": "",
    }


def test_get_unknown_device_is_404(client, admin_headers):
    response = client.get("/api/devices/nope", headers=admin_headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "Device not found"}


# --- create --------------------------------------------------------------------


def test_create_device_fills_in_the_defaults(client, admin_headers):
    response = _create(client, admin_headers)

    assert response.status_code == 201
    assert response.json() == {**NEW_DEVICE, "ping_port": 80, "notes": ""}
    assert _get(client, admin_headers, "plc-new") == response.json()
    assert len(client.get("/api/devices", headers=admin_headers).json()) == 12


def test_create_top_level_device_without_a_parent(client, admin_headers):
    response = _create(client, admin_headers, id="fw-02", type="firewall", parent_id=None)

    assert response.status_code == 201
    assert response.json()["parent_id"] is None


def test_create_rejects_a_duplicate_id(client, admin_headers):
    # Reported as 409 even when the parent is also wrong: the duplicate check runs first.
    response = _create(client, admin_headers, id="fw-01", parent_id="ghost")

    assert response.status_code == 409
    assert response.json() == {"detail": "Device 'fw-01' already exists"}


def test_create_rejects_an_unknown_device_type(client, admin_headers):
    assert _create(client, admin_headers, type="router").status_code == 422


def test_create_rejects_a_parent_that_does_not_exist(client, admin_headers):
    response = _create(client, admin_headers, parent_id="ghost")

    assert response.status_code == 422
    assert response.json() == {"detail": "parent_id 'ghost' does not reference an existing device"}
    assert client.get("/api/devices/plc-new", headers=admin_headers).status_code == 404


def test_create_rejects_a_device_that_is_its_own_parent(client, admin_headers):
    response = _create(client, admin_headers, parent_id="plc-new")

    assert response.status_code == 422
    assert response.json() == {"detail": "A device cannot be its own parent"}


# --- update --------------------------------------------------------------------


def test_update_changes_only_the_fields_that_were_sent(client, admin_headers):
    before = _get(client, admin_headers, "scanner-1")

    response = _patch(client, admin_headers, "scanner-1", name="Dock Scanner", notes="moved to dock 4")

    assert response.status_code == 200
    assert response.json() == {**before, "name": "Dock Scanner", "notes": "moved to dock 4"}
    assert _get(client, admin_headers, "scanner-1") == response.json()


def test_update_unknown_device_is_404(client, admin_headers):
    assert _patch(client, admin_headers, "nope", name="x").status_code == 404


def test_update_rejects_an_unknown_device_type(client, admin_headers):
    assert _patch(client, admin_headers, "scanner-1", type="router").status_code == 422


def test_the_device_id_cannot_be_changed(client, admin_headers):
    response = _patch(client, admin_headers, "scanner-1", id="scanner-9")

    assert response.status_code == 200  # the unknown field is ignored
    assert response.json()["id"] == "scanner-1"


def test_reparent_to_another_existing_device(client, admin_headers):
    response = _patch(client, admin_headers, "scanner-1", parent_id="sw-server")

    assert response.status_code == 200
    assert _get(client, admin_headers, "scanner-1")["parent_id"] == "sw-server"


def test_reparent_rejects_a_parent_that_does_not_exist(client, admin_headers):
    response = _patch(client, admin_headers, "scanner-1", parent_id="ghost")

    assert response.status_code == 422
    assert response.json() == {"detail": "parent_id 'ghost' does not reference an existing device"}
    assert _get(client, admin_headers, "scanner-1")["parent_id"] == "sw-ot"


def test_reparent_rejects_a_device_as_its_own_parent(client, admin_headers):
    response = _patch(client, admin_headers, "scanner-1", parent_id="scanner-1")

    assert response.status_code == 422
    assert response.json() == {"detail": "A device cannot be its own parent"}


@pytest.mark.parametrize(
    ("device_id", "new_parent"),
    [
        ("fw-01", "sw-edge"),  # its direct child
        ("fw-01", "scanner-1"),  # a leaf three levels below it
        ("sw-edge", "plc-conveyor-1"),  # a grandchild
        ("sw-ot", "ap-aisle-2"),  # its direct child
    ],
)
def test_reparent_under_a_descendant_is_rejected_as_a_cycle(client, admin_headers, device_id, new_parent):
    before = _get(client, admin_headers, device_id)

    response = _patch(client, admin_headers, device_id, parent_id=new_parent)

    assert response.status_code == 422
    assert response.json() == {"detail": "This would create a circular parent reference"}
    assert _get(client, admin_headers, device_id) == before


def test_a_null_parent_in_a_patch_is_ignored(client, admin_headers):
    # Current behaviour: PATCH treats null as "not provided", so a device
    # cannot be detached from its parent this way. The admin UI says so too.
    response = _patch(client, admin_headers, "scanner-1", parent_id=None)

    assert response.status_code == 200
    assert response.json()["parent_id"] == "sw-ot"


# --- delete --------------------------------------------------------------------


def test_delete_a_leaf_device(client, admin_headers):
    response = client.delete("/api/devices/scanner-1", headers=admin_headers)

    assert response.status_code == 204
    assert client.get("/api/devices/scanner-1", headers=admin_headers).status_code == 404
    assert len(client.get("/api/devices", headers=admin_headers).json()) == 10


def test_delete_is_blocked_while_the_device_has_children(client, admin_headers):
    response = client.delete("/api/devices/sw-ot", headers=admin_headers)

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Cannot delete 'sw-ot': it has 5 downstream device(s). Reassign or delete them first."
    }
    assert client.get("/api/devices/sw-ot", headers=admin_headers).status_code == 200


def test_a_parent_can_be_deleted_once_its_children_are_gone(client, admin_headers):
    for child in ("srv-prod-1", "srv-prod-2"):
        assert client.delete(f"/api/devices/{child}", headers=admin_headers).status_code == 204

    assert client.delete("/api/devices/sw-server", headers=admin_headers).status_code == 204


def test_delete_unknown_device_is_404(client, admin_headers):
    assert client.delete("/api/devices/nope", headers=admin_headers).status_code == 404


# --- what a device may contain --------------------------------------------------

ID_RULE = "id must be 1 to 64 characters: letters, digits, '.', '_' or '-', starting with a letter or digit"


@pytest.mark.parametrize(
    "device_id",
    ["", " ", "a/b", "a b", "a?b", "a#b", "a%2Fb", ".", "..", ".hidden", "-x", "_x", "x" * 65, "plc-né", "plc-1\n"],
)
def test_create_rejects_an_id_that_is_not_safe_in_a_url(client, admin_headers, device_id):
    # "" and "a/b" used to be stored, and could then never be opened or deleted.
    response = _create(client, admin_headers, id=device_id)

    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == f"Value error, {ID_RULE}"
    assert len(client.get("/api/devices", headers=admin_headers).json()) == 11  # nothing was stored


@pytest.mark.parametrize("device_id", ["a", "7", "PLC-1", "plc_1.b", "10.99.0.50", "x" * 64])
def test_an_accepted_id_can_be_opened_and_deleted_again(client, admin_headers, device_id):
    assert _create(client, admin_headers, id=device_id).status_code == 201

    assert _get(client, admin_headers, device_id)["id"] == device_id
    assert client.delete(f"/api/devices/{device_id}", headers=admin_headers).status_code == 204


@pytest.mark.parametrize(
    "fields",
    [
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 101},
        {"zone": ""},
        {"zone": "x" * 101},
        {"ip": ""},
        {"ip": "x" * 256},
        {"notes": "x" * 2001},
        {"ping_port": 0},
        {"ping_port": -5},
        {"ping_port": 65536},
        {"ping_port": 10**30},
    ],
)
def test_empty_oversized_and_out_of_range_fields_are_rejected(client, admin_headers, fields):
    assert _create(client, admin_headers, **fields).status_code == 422
    assert client.get("/api/devices/plc-new", headers=admin_headers).status_code == 404

    before = _get(client, admin_headers, "scanner-1")
    assert _patch(client, admin_headers, "scanner-1", **fields).status_code == 422
    assert _get(client, admin_headers, "scanner-1") == before


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        ('{"ping_port": Infinity}', "application/json"),
        ('{"ping_port": NaN}', "application/json"),
        ("NaN", "application/json"),
        ('{"name": "\\ud800"}', "application/json"),  # half a surrogate pair
        (b"\xff\xfe", "text/plain"),  # bytes that are not text
    ],
)
def test_a_rejected_body_that_cannot_be_echoed_is_a_422_not_a_500(client, admin_headers, body, content_type):
    headers = {**admin_headers, "Content-Type": content_type}
    before = _get(client, admin_headers, "scanner-1")

    assert client.patch("/api/devices/scanner-1", headers=headers, content=body).status_code == 422
    assert _get(client, admin_headers, "scanner-1") == before


def test_fields_at_their_limits_are_accepted_and_text_is_trimmed(client, admin_headers):
    response = _create(
        client,
        admin_headers,
        name="  " + "n" * 100 + "  ",
        zone="z" * 100,
        ip="h" * 255,
        notes="x" * 2000,
        ping_port=65535,
    )

    assert response.status_code == 201
    created = response.json()
    assert (created["name"], created["zone"], created["ip"]) == ("n" * 100, "z" * 100, "h" * 255)
    assert (len(created["notes"]), created["ping_port"]) == (2000, 65535)

    renamed = _patch(client, admin_headers, "plc-new", name=" Renamed ", ping_port=1)
    assert (renamed.json()["name"], renamed.json()["ping_port"]) == ("Renamed", 1)
