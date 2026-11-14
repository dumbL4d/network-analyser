"""The stored-incident endpoints: history, detail, acknowledge and notes."""

from datetime import datetime, timedelta, timezone

import pytest

from tests.helpers import store_incident

# Well in the past, so that events added "now" by the API come after it.
T0 = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


@pytest.fixture
def three_incidents(client) -> dict[str, int]:
    """A resolved, an acknowledged and an open incident, oldest first."""
    return {
        "resolved": store_incident(
            "sw-ot", at(0), first_failure_at=at(-1), resolved_at=at(30), peak_affected_count=5,
            affected_device_ids=("ap-aisle-1", "scanner-1"),
        ),
        "acknowledged": store_incident("scanner-1", at(60), acknowledged_by="admin"),
        "open": store_incident("srv-prod-1", at(120)),
    }


def history(client, headers, **params) -> dict:
    response = client.get("/api/incidents/history", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def ids(page: dict) -> list[int]:
    return [item["id"] for item in page["items"]]


# --- history -------------------------------------------------------------------


def test_history_is_empty_before_any_incident(client, viewer_headers):
    assert history(client, viewer_headers) == {"total": 0, "limit": 50, "offset": 0, "items": []}


def test_history_lists_incidents_most_recent_first(client, viewer_headers, three_incidents):
    page = history(client, viewer_headers)

    assert page["total"] == 3
    assert ids(page) == [three_incidents["open"], three_incidents["acknowledged"], three_incidents["resolved"]]
    assert page["items"][-1] == {
        "id": three_incidents["resolved"],
        "root_device_id": "sw-ot",
        "state": "resolved",
        "opened_at": "2026-01-15T10:00:00Z",
        "first_failure_at": "2026-01-15T09:59:00Z",
        "acknowledged_at": None,
        "acknowledged_by": None,
        "resolved_at": "2026-01-15T10:30:00Z",
        "peak_affected_count": 5,
        "affected_device_ids": ["ap-aisle-1", "scanner-1"],
    }


def test_history_is_paginated_with_limit_and_offset(client, viewer_headers, three_incidents):
    first = history(client, viewer_headers, limit=2)
    second = history(client, viewer_headers, limit=2, offset=2)

    assert (first["total"], first["limit"], first["offset"]) == (3, 2, 0)
    assert ids(first) == [three_incidents["open"], three_incidents["acknowledged"]]
    assert (second["total"], second["offset"]) == (3, 2)
    assert ids(second) == [three_incidents["resolved"]]


def test_history_filters_by_state(client, viewer_headers, three_incidents):
    resolved = history(client, viewer_headers, state="resolved")
    unresolved = history(client, viewer_headers, state=["open", "acknowledged"])  # the filter may be repeated

    assert (resolved["total"], ids(resolved)) == (1, [three_incidents["resolved"]])
    assert (unresolved["total"], ids(unresolved)) == (2, [three_incidents["open"], three_incidents["acknowledged"]])


def test_history_filters_by_root_device(client, viewer_headers, three_incidents):
    assert ids(history(client, viewer_headers, device_id="scanner-1")) == [three_incidents["acknowledged"]]
    assert history(client, viewer_headers, device_id="fw-01")["total"] == 0
    assert history(client, viewer_headers, device_id="sw-ot", state="open")["total"] == 0  # filters combine


@pytest.mark.parametrize(
    "params",
    [{"state": "closed"}, {"limit": 0}, {"limit": 201}, {"offset": -1}],
)
def test_history_rejects_invalid_parameters(client, viewer_headers, params):
    assert client.get("/api/incidents/history", headers=viewer_headers, params=params).status_code == 422


# --- detail --------------------------------------------------------------------


def test_incident_detail_includes_the_timeline(client, admin_headers, viewer_headers, three_incidents):
    incident_id = three_incidents["open"]
    client.post(f"/api/incidents/{incident_id}/acknowledge", headers=admin_headers)

    response = client.get(f"/api/incidents/{incident_id}", headers=viewer_headers)

    assert response.status_code == 200
    body = response.json()
    assert (body["id"], body["root_device_id"], body["state"]) == (incident_id, "srv-prod-1", "acknowledged")
    assert [event["type"] for event in body["events"]] == ["opened", "acknowledged"]  # oldest first
    assert set(body["events"][0]) == {"id", "ts", "type", "details"}
    assert body["events"][1]["details"] == {"by": "admin"}


def test_unknown_incident_is_404(client, admin_headers):
    assert client.get("/api/incidents/999", headers=admin_headers).status_code == 404
    assert client.post("/api/incidents/999/acknowledge", headers=admin_headers).status_code == 404
    assert client.post("/api/incidents/999/notes", headers=admin_headers, json={"text": "x"}).status_code == 404
    assert client.get("/api/incidents/999", headers=admin_headers).json() == {"detail": "Incident not found"}


# --- acknowledge ---------------------------------------------------------------


def test_admin_acknowledges_an_open_incident(client, admin_headers, three_incidents):
    response = client.post(f"/api/incidents/{three_incidents['open']}/acknowledge", headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert (body["state"], body["acknowledged_by"]) == ("acknowledged", "admin")
    assert body["acknowledged_at"] is not None
    assert body["events"][-1]["type"] == "acknowledged"


def test_viewer_cannot_acknowledge(client, viewer_headers, admin_headers, three_incidents):
    incident_id = three_incidents["open"]

    response = client.post(f"/api/incidents/{incident_id}/acknowledge", headers=viewer_headers)

    assert response.status_code == 403
    assert client.get(f"/api/incidents/{incident_id}", headers=admin_headers).json()["state"] == "open"


@pytest.mark.parametrize("state", ["acknowledged", "resolved"])
def test_only_an_open_incident_can_be_acknowledged(client, admin_headers, three_incidents, state):
    incident_id = three_incidents[state]

    response = client.post(f"/api/incidents/{incident_id}/acknowledge", headers=admin_headers)

    assert response.status_code == 409
    assert response.json() == {"detail": f"Incident is already {state}"}
    after = client.get(f"/api/incidents/{incident_id}", headers=admin_headers).json()
    assert after["state"] == state
    assert [event["type"] for event in after["events"]] == ["opened"]  # no event was added


# --- notes ---------------------------------------------------------------------


def test_admin_adds_a_note_to_the_timeline(client, admin_headers, three_incidents):
    incident_id = three_incidents["open"]

    response = client.post(
        f"/api/incidents/{incident_id}/notes", headers=admin_headers, json={"text": "  Replaced the SFP.  "}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "open"  # a note does not change the state
    note = body["events"][-1]
    assert note["type"] == "note"
    assert note["details"] == {"by": "admin", "text": "Replaced the SFP."}  # surrounding spaces are trimmed


def test_a_note_can_be_added_after_the_incident_is_resolved(client, admin_headers, three_incidents):
    response = client.post(
        f"/api/incidents/{three_incidents['resolved']}/notes", headers=admin_headers, json={"text": "Root cause: PoE budget."}
    )

    assert response.status_code == 201
    assert response.json()["state"] == "resolved"


def test_viewer_cannot_add_a_note(client, viewer_headers, admin_headers, three_incidents):
    incident_id = three_incidents["open"]

    response = client.post(f"/api/incidents/{incident_id}/notes", headers=viewer_headers, json={"text": "hello"})

    assert response.status_code == 403
    assert len(client.get(f"/api/incidents/{incident_id}", headers=admin_headers).json()["events"]) == 1


@pytest.mark.parametrize("body", [{}, {"text": ""}, {"text": "   "}, {"text": "x" * 2001}])
def test_a_note_needs_some_text_of_at_most_2000_characters(client, admin_headers, three_incidents, body):
    response = client.post(f"/api/incidents/{three_incidents['open']}/notes", headers=admin_headers, json=body)

    assert response.status_code == 422
