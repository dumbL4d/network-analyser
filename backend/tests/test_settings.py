"""Monitoring settings API. The "applies on the next poll cycle" behaviour is
covered in test_poll_loop.py."""

import pytest

from app.core.config import settings

DEFAULTS = {
    "id": 1,
    "site_name": "Warehouse Network Monitor",
    "poll_interval_seconds": 10.0,
    "latency_warn_ms": 100.0,
    "latency_crit_ms": 500.0,
    "flap_threshold": 3,
    "failure_threshold": 3,
    "recovery_threshold": 2,
    "pings_per_cycle": 4,
    "ping_gap_ms": 200,
    "loss_warn_pct": 20.0,
    "jitter_warn_ms": 30.0,
    "anomaly_enabled": True,
    "anomaly_detector": "ewma",
    "anomaly_k": 3.0,
    "anomaly_m": 3,
    "anomaly_alpha": 0.1,
    "anomaly_window": 60,
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
        "pings_per_cycle": 6,
        "ping_gap_ms": 250,
        "loss_warn_pct": 10.0,
        "jitter_warn_ms": 15.0,
        "anomaly_enabled": False,
        "anomaly_detector": "rolling",
        "anomaly_k": 4.0,
        "anomaly_m": 5,
        "anomaly_alpha": 0.2,
        "anomaly_window": 120,
    }

    response = _patch(client, admin_headers, **form)

    assert response.status_code == 200
    assert response.json() == {"id": 1, **form}


# --- probing: pings per cycle, the gap, and the loss and jitter thresholds -------


@pytest.mark.parametrize(
    "fields",
    [
        {"pings_per_cycle": 1},
        {"pings_per_cycle": 10},  # 10 x 0.2 s + 2 s = 4 s of the 8 s a 10 s interval allows
        {"ping_gap_ms": 10},
        {"ping_gap_ms": 5000, "pings_per_cycle": 1, "poll_interval_seconds": 60},
        {"loss_warn_pct": 0.5},
        {"loss_warn_pct": 100},
        {"jitter_warn_ms": 0.1},
        {"jitter_warn_ms": 2500},
    ],
)
def test_probe_settings_accept_the_ends_of_their_ranges(client, admin_headers, fields):
    response = _patch(client, admin_headers, **fields)

    assert response.status_code == 200
    assert response.json() == {**DEFAULTS, **fields}
    assert _settings(client, admin_headers) == response.json()  # persisted


@pytest.mark.parametrize(
    ("fields", "detail"),
    [
        ({"pings_per_cycle": 0}, "pings_per_cycle must be between 1 and 10"),
        ({"pings_per_cycle": 11}, "pings_per_cycle must be between 1 and 10"),
        ({"pings_per_cycle": -1}, "pings_per_cycle must be between 1 and 10"),
        ({"ping_gap_ms": 9}, "ping_gap_ms must be between 10 and 5000"),
        ({"ping_gap_ms": 5001}, "ping_gap_ms must be between 10 and 5000"),
        ({"ping_gap_ms": 0}, "ping_gap_ms must be between 10 and 5000"),
        ({"loss_warn_pct": 0}, "loss_warn_pct must be above 0 and at most 100"),
        ({"loss_warn_pct": -5}, "loss_warn_pct must be above 0 and at most 100"),
        ({"loss_warn_pct": 100.1}, "loss_warn_pct must be above 0 and at most 100"),
        ({"jitter_warn_ms": 0}, "jitter_warn_ms must be above 0"),
        ({"jitter_warn_ms": -1}, "jitter_warn_ms must be above 0"),
    ],
)
def test_probe_settings_out_of_range_are_rejected(client, admin_headers, fields, detail):
    response = _patch(client, admin_headers, **fields)

    assert response.status_code == 422
    assert response.json() == {"detail": detail}
    assert _settings(client, admin_headers) == DEFAULTS  # nothing was saved


@pytest.mark.parametrize("field", ["pings_per_cycle", "ping_gap_ms"])
def test_pings_and_gap_must_be_whole_numbers(client, admin_headers, field):
    assert _patch(client, admin_headers, **{field: 2.5}).status_code == 422
    assert _patch(client, admin_headers, **{field: "four"}).status_code == 422


def test_probes_that_do_not_fit_in_the_poll_interval_are_rejected_with_the_reason(client, admin_headers):
    response = _patch(client, admin_headers, pings_per_cycle=10, ping_gap_ms=700)

    assert response.status_code == 422
    assert response.json() == {
        "detail": (
            "pings_per_cycle x ping_gap_ms + the ping timeout is 9 s (10 x 700 ms + 2 s), which does not "
            "fit comfortably inside the poll interval of 10 s: at most 8 s (80% of it). Lower "
            "pings_per_cycle or ping_gap_ms, or raise poll_interval_seconds."
        )
    }
    assert _settings(client, admin_headers) == DEFAULTS  # nothing was saved


def test_the_same_probes_are_accepted_with_a_longer_poll_interval(client, admin_headers):
    response = _patch(client, admin_headers, pings_per_cycle=10, ping_gap_ms=700, poll_interval_seconds=15)

    assert response.status_code == 200  # 9 s of the 12 s allowed


def test_the_fit_is_checked_against_the_stored_values_of_the_fields_not_sent(client, admin_headers):
    assert _patch(client, admin_headers, poll_interval_seconds=5).status_code == 200
    # Stored now: 4 pings, 200 ms apart, every 5 s. Allowed: 4 s.
    assert _patch(client, admin_headers, pings_per_cycle=10).status_code == 200  # exactly 4 s
    assert _patch(client, admin_headers, ping_gap_ms=201).status_code == 422  # 4.01 s
    assert _patch(client, admin_headers, pings_per_cycle=9, ping_gap_ms=201).status_code == 200

    assert _settings(client, admin_headers)["ping_gap_ms"] == 201


def test_shortening_the_poll_interval_is_rejected_when_the_probes_no_longer_fit(client, admin_headers):
    assert _patch(client, admin_headers, pings_per_cycle=10, ping_gap_ms=700, poll_interval_seconds=15).status_code == 200

    response = _patch(client, admin_headers, poll_interval_seconds=10)

    assert response.status_code == 422
    assert response.json()["detail"].startswith("pings_per_cycle x ping_gap_ms + the ping timeout is 9 s")
    assert _settings(client, admin_headers)["poll_interval_seconds"] == 15.0


def test_the_ping_timeout_counts_towards_the_fit(client, admin_headers, monkeypatch):
    monkeypatch.setattr(settings, "PING_TIMEOUT_SECONDS", 8.0)  # 4 x 0.2 s + 8 s = 8.8 s of 8 s

    response = _patch(client, admin_headers, pings_per_cycle=4)

    assert response.status_code == 422
    assert "(4 x 200 ms + 8 s)" in response.json()["detail"]
    # A change that has nothing to do with probing is not held up by it.
    assert _patch(client, admin_headers, site_name="Plant 2", loss_warn_pct=10).status_code == 200


def test_an_out_of_range_value_is_reported_before_the_fit(client, admin_headers):
    response = _patch(client, admin_headers, pings_per_cycle=50, ping_gap_ms=5000)

    assert response.json() == {"detail": "pings_per_cycle must be between 1 and 10"}


# --- anomaly detection -----------------------------------------------------------


@pytest.mark.parametrize(
    "fields",
    [
        {"anomaly_enabled": False},
        {"anomaly_detector": "rolling"},
        {"anomaly_k": 1},
        {"anomaly_k": 10},
        {"anomaly_m": 1},
        {"anomaly_m": 20},
        {"anomaly_alpha": 0.01},
        {"anomaly_alpha": 0.5},
        {"anomaly_window": 30},  # the warm-up
        {"anomaly_window": 1000},
    ],
)
def test_anomaly_settings_accept_the_ends_of_their_ranges(client, admin_headers, fields):
    response = _patch(client, admin_headers, **fields)

    assert response.status_code == 200
    assert response.json() == {**DEFAULTS, **fields}
    assert _settings(client, admin_headers) == response.json()  # persisted


@pytest.mark.parametrize(
    ("fields", "detail"),
    [
        ({"anomaly_k": 0.9}, "anomaly_k must be between 1 and 10"),
        ({"anomaly_k": 10.1}, "anomaly_k must be between 1 and 10"),
        ({"anomaly_m": 0}, "anomaly_m must be between 1 and 20"),
        ({"anomaly_m": 21}, "anomaly_m must be between 1 and 20"),
        ({"anomaly_alpha": 0.009}, "anomaly_alpha must be between 0.01 and 0.5"),
        ({"anomaly_alpha": 0.51}, "anomaly_alpha must be between 0.01 and 0.5"),
        ({"anomaly_window": 29}, "anomaly_window must be between 30 and 1000"),
        ({"anomaly_window": 1001}, "anomaly_window must be between 30 and 1000"),
    ],
)
def test_anomaly_settings_out_of_range_are_rejected(client, admin_headers, fields, detail):
    response = _patch(client, admin_headers, **fields)

    assert response.status_code == 422
    assert response.json() == {"detail": detail}
    assert _settings(client, admin_headers) == DEFAULTS  # nothing was saved


@pytest.mark.parametrize(
    "fields",
    [
        {"anomaly_detector": "median"},  # not one of the two detectors
        {"anomaly_detector": ""},
        {"anomaly_enabled": "sometimes"},
        {"anomaly_m": 2.5},
        {"anomaly_window": 60.5},
        {"anomaly_k": "three"},
    ],
)
def test_anomaly_settings_of_the_wrong_kind_are_rejected(client, admin_headers, fields):
    assert _patch(client, admin_headers, **fields).status_code == 422
    assert _settings(client, admin_headers) == DEFAULTS
