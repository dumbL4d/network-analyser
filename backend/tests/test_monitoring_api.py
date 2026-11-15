"""Read-only monitoring endpoints: health, status, history, flaps, incidents,
playbooks and the SSE status stream."""

import json
from typing import get_args

import pytest

from app.core.config import settings
from app.data.playbooks import PLAYBOOKS
from app.main import stream_status
from app.models.user import User
from app.schemas.device import DeviceType
from app.services.flap_store import flap_store
from app.services.history_store import history_store
from app.services.status_store import status_store
from tests.helpers import make_status, seed_devices

# What a status carries about its probes when nothing was measured.
NO_PROBE_DETAILS = {"latency_min_ms": None, "latency_max_ms": None, "loss_pct": None, "jitter_ms": None}

# --- health / status -----------------------------------------------------------


def test_health_is_public(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "app": settings.APP_NAME, "env": settings.APP_ENV}


def test_status_is_empty_until_the_first_poll(client, admin_headers):
    assert client.get("/api/status", headers=admin_headers).json() == {}


def test_status_returns_the_latest_reading_per_device(client, admin_headers):
    healthy = make_status("fw-01", "healthy", 1.5)
    # What the debouncer publishes while one lost ping is still unconfirmed.
    pending = make_status("sw-ot", "healthy").model_copy(
        update={"raw_status": "down", "consecutive_failures": 1}
    )
    status_store.update([healthy, pending])

    assert client.get("/api/status", headers=admin_headers).json() == {
        "fw-01": {
            # The three original keys...
            "status": "healthy",
            "latency_ms": 1.5,
            "timestamp": healthy.timestamp.isoformat(),
            # ...and the ones added with debouncing. A reading that never went
            # through the debouncer reports its status as the raw status.
            "raw_status": "healthy",
            "consecutive_failures": 0,
            "consecutive_successes": 0,
            # ...and the ones added with multi-ping probing (none measured here).
            **NO_PROBE_DETAILS,
        },
        "sw-ot": {
            "status": "healthy",
            "latency_ms": None,
            "timestamp": pending.timestamp.isoformat(),
            "raw_status": "down",
            "consecutive_failures": 1,
            "consecutive_successes": 0,
            **NO_PROBE_DETAILS,
        },
    }
    assert healthy.timestamp.isoformat().endswith("+00:00")  # the format clients receive


# --- history -------------------------------------------------------------------


def test_history_of_an_unknown_device_is_404(client, admin_headers):
    response = client.get("/api/history/nope", headers=admin_headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "Device not found"}


def test_history_of_a_device_that_was_never_polled_is_an_empty_list(client, admin_headers):
    response = client.get("/api/history/fw-01", headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == []


def test_history_returns_the_samples_oldest_first(client, admin_headers):
    first = make_status("fw-01", "healthy", 1.5)
    second = make_status("fw-01", "down")
    history_store.record([first])
    history_store.record([second])

    assert client.get("/api/history/fw-01", headers=admin_headers).json() == [
        # Unlike /api/status, this endpoint writes UTC as "Z".
        # Packet loss and jitter were added later; these readings measured none.
        {
            "latency_ms": 1.5,
            "timestamp": first.timestamp.isoformat().replace("+00:00", "Z"),
            "loss_pct": None,
            "jitter_ms": None,
        },
        {
            "latency_ms": None,
            "timestamp": second.timestamp.isoformat().replace("+00:00", "Z"),
            "loss_pct": None,
            "jitter_ms": None,
        },
    ]


# --- flaps ---------------------------------------------------------------------


def test_flaps_lists_every_device_with_the_most_unstable_first(client, admin_headers):
    for status in ("healthy", "down", "healthy"):  # two changes
        flap_store.record([make_status("sw-ot", status)])
    for device_id in ("ap-aisle-2", "ap-aisle-1"):  # one change each
        flap_store.record([make_status(device_id, "healthy")])
        flap_store.record([make_status(device_id, "down")])

    rows = client.get("/api/flaps", headers=admin_headers).json()

    assert rows[:3] == [
        {"device_id": "sw-ot", "flap_count": 2},
        {"device_id": "ap-aisle-1", "flap_count": 1},  # ties are broken by device id
        {"device_id": "ap-aisle-2", "flap_count": 1},
    ]
    stable = rows[3:]
    assert all(row["flap_count"] == 0 for row in stable)
    assert [row["device_id"] for row in stable] == sorted(
        device.id for device in seed_devices() if device.id not in {"sw-ot", "ap-aisle-1", "ap-aisle-2"}
    )


# --- incidents -----------------------------------------------------------------


def _incident_summary(client, admin_headers) -> list[tuple[str, str]]:
    response = client.get("/api/incidents", headers=admin_headers)
    assert response.status_code == 200
    return [(incident["device"]["id"], incident["category"]) for incident in response.json()]


def test_incidents_are_computed_from_the_live_statuses_on_every_request(client, admin_headers):
    assert _incident_summary(client, admin_headers) == []  # nothing polled yet

    status_store.update([make_status("sw-ot", "down"), make_status("scanner-1", "down")])
    assert _incident_summary(client, admin_headers) == [
        ("sw-ot", "root_cause"),
        ("scanner-1", "collateral"),
    ]

    # The switch recovers: the scanner is reclassified on the very next request.
    status_store.update([make_status("sw-ot", "healthy", 1.0)])
    assert _incident_summary(client, admin_headers) == [("scanner-1", "root_cause")]

    status_store.update([make_status("scanner-1", "healthy", 1.0)])
    assert _incident_summary(client, admin_headers) == []


def test_incident_response_shape(client, admin_headers):
    status_store.update([make_status("sw-ot", "degraded", 150.0), make_status("scanner-1", "down")])

    root_cause, collateral = client.get("/api/incidents", headers=admin_headers).json()

    assert root_cause == {
        "device": {
            "id": "sw-ot",
            "name": "OT Tier Switch",
            "type": "switch",
            "ip": "10.99.0.4",
            "zone": "ot-tier",
            "parent_id": "sw-edge",
            "ping_port": 80,
            "notes": "",
        },
        "status": "degraded",
        "latency_ms": 150.0,
        "category": "root_cause",
        "downstream_affected": [collateral["device"]],
    }
    assert (collateral["device"]["id"], collateral["category"]) == ("scanner-1", "collateral")
    assert collateral["downstream_affected"] == []


# --- playbooks -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("device_type", "state"),
    [(device_type, state) for device_type in PLAYBOOKS for state in ("down", "degraded")],
)
def test_every_device_type_has_a_playbook_for_both_states(client, admin_headers, device_type, state):
    response = client.get(f"/api/playbooks/{device_type}/{state}", headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == {
        "device_type": device_type,
        "state": state,
        "steps": PLAYBOOKS[device_type][state],
    }
    assert len(response.json()["steps"]) >= 1


def test_playbooks_cover_exactly_the_allowed_device_types():
    assert set(PLAYBOOKS) == set(get_args(DeviceType))


@pytest.mark.parametrize("path", ["/api/playbooks/router/down", "/api/playbooks/switch/healthy"])
def test_playbook_rejects_an_unknown_type_or_state(client, admin_headers, path):
    assert client.get(path, headers=admin_headers).status_code == 422


# --- SSE status stream ---------------------------------------------------------


async def test_status_stream_sends_the_snapshot_then_each_update_then_unsubscribes():
    # Driven through the endpoint function: TestClient cannot read a response
    # that never ends. Token handling for this route is covered in test_auth.py.
    status_store.update([make_status("fw-01", "healthy", 1.0)])
    caller = User(id=1, username="admin", password_hash="x", role="admin")

    response = await stream_status(current_user=caller)
    events = response.body_iterator

    first = await anext(events)  # sent immediately on connect
    assert first["event"] == "status"
    assert json.loads(first["data"])["fw-01"]["status"] == "healthy"

    went_down = make_status("fw-01", "down")
    status_store.update([went_down])  # what the poll loop does every cycle
    second = await anext(events)
    assert second["event"] == "status"
    assert json.loads(second["data"]) == {
        "fw-01": {
            "status": "down",
            "latency_ms": None,
            "timestamp": went_down.timestamp.isoformat(),
            "raw_status": "down",
            "consecutive_failures": 0,
            "consecutive_successes": 0,
            **NO_PROBE_DETAILS,
        }
    }

    await events.aclose()  # the browser disconnects
    assert status_store._subscribers == []
