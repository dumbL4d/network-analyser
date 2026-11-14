"""Monitoring settings API. The "applies on the next poll cycle" behaviour is
covered in test_poll_loop.py."""

import pytest

DEFAULTS = {
    "id": 1,
    "site_name": "Warehouse Network Monitor",
    "poll_interval_seconds": 10.0,
    "latency_warn_ms": 100.0,
    "latency_crit_ms": 500.0,
    "flap_threshold": 3,
    "failure_threshold": 3,
    "recovery_threshold": 2,
}


def _settings(client, headers) -> dict:
    response = client.get("/api/settings", headers=headers)
    assert response.status_code == 200
    return response.json()


def _patch(client, admin_headers, **fields):
    return client.patch("/api/settings", headers=admin_headers, json=fields)


def test_settings_start_at_the_seeded_defaults(client, viewer_headers):
    assert _settings(client, viewer_headers) == DEFAULTS


def test_patch_updates_only_the_fields_that_were_sent(client, admin_headers):
    response = _patch(client, admin_headers, site_name="Plant 2", flap_threshold=5)

    assert response.status_code == 200
    assert response.json() == {**DEFAULTS, "site_name": "Plant 2", "flap_threshold": 5}
    assert _settings(client, admin_headers) == response.json()  # persisted


def test_null_fields_are_treated_as_not_sent(client, admin_headers):
    response = _patch(client, admin_headers, site_name=None, flap_threshold=5)

    assert response.status_code == 200
    assert response.json() == {**DEFAULTS, "flap_threshold": 5}


def test_poll_interval_has_a_5_second_minimum(client, admin_headers):
    too_fast = _patch(client, admin_headers, poll_interval_seconds=4.9)

    assert too_fast.status_code == 422
    assert too_fast.json() == {"detail": "poll_interval_seconds must be at least 5.0 seconds"}
    assert _patch(client, admin_headers, poll_interval_seconds=5.0).status_code == 200


@pytest.mark.parametrize(
    "fields",
    [
        {"latency_warn_ms": 600.0, "latency_crit_ms": 500.0},  # warn above crit
        {"latency_warn_ms": 500.0, "latency_crit_ms": 500.0},  # equal is rejected too
        {"latency_warn_ms": 500.0},  # checked against the stored crit (500)
        {"latency_crit_ms": 100.0},  # checked against the stored warn (100)
    ],
)
def test_warn_threshold_must_stay_below_crit(client, admin_headers, fields):
    response = _patch(client, admin_headers, **fields)

    assert response.status_code == 422
    assert response.json() == {"detail": "latency_warn_ms must be less than latency_crit_ms"}
    assert _settings(client, admin_headers) == DEFAULTS  # nothing was saved


def test_thresholds_can_be_moved_together(client, admin_headers):
    response = _patch(client, admin_headers, latency_warn_ms=600.0, latency_crit_ms=900.0)

    assert response.status_code == 200
    assert (response.json()["latency_warn_ms"], response.json()["latency_crit_ms"]) == (600.0, 900.0)


# --- debounce thresholds (failure_threshold / recovery_threshold) --------------

DEBOUNCE_FIELDS = ["failure_threshold", "recovery_threshold"]


@pytest.mark.parametrize("field", DEBOUNCE_FIELDS)
@pytest.mark.parametrize("value", [1, 10])
def test_debounce_threshold_accepts_the_ends_of_its_range(client, admin_headers, field, value):
    response = _patch(client, admin_headers, **{field: value})

    assert response.status_code == 200
    assert response.json() == {**DEFAULTS, field: value}
    assert _settings(client, admin_headers) == response.json()  # persisted


@pytest.mark.parametrize("field", DEBOUNCE_FIELDS)
@pytest.mark.parametrize("value", [0, 11, -1])
def test_debounce_threshold_outside_1_to_10_is_rejected(client, admin_headers, field, value):
    response = _patch(client, admin_headers, **{field: value})

    assert response.status_code == 422
    assert response.json() == {"detail": f"{field} must be between 1 and 10"}
    assert _settings(client, admin_headers) == DEFAULTS  # nothing was saved


@pytest.mark.parametrize("field", DEBOUNCE_FIELDS)
def test_debounce_threshold_must_be_a_whole_number(client, admin_headers, field):
    assert _patch(client, admin_headers, **{field: 2.5}).status_code == 422
    assert _patch(client, admin_headers, **{field: "three"}).status_code == 422


def test_the_admin_settings_form_payload_is_accepted(client, admin_headers):
    # The Admin > Settings tab sends every field on Save, changed or not.
    form = {
        "site_name": "Plant 2",
        "poll_interval_seconds": 20.0,
        "latency_warn_ms": 150.0,
        "latency_crit_ms": 600.0,
        "flap_threshold": 4,
        "failure_threshold": 5,
        "recovery_threshold": 1,
    }

    response = _patch(client, admin_headers, **form)

    assert response.status_code == 200
    assert response.json() == {"id": 1, **form}
