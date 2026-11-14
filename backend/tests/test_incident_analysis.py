"""Root cause vs collateral classification on the seeded warehouse tree.

    fw-01
    └── sw-edge
        ├── sw-server ── srv-prod-1, srv-prod-2
        └── sw-ot ────── plc-conveyor-1, hmi-panel-1, ap-aisle-1, ap-aisle-2, scanner-1

``analyze_incidents`` is a pure function, so these tests need no database.
"""

import random
from collections.abc import Iterable

from app.schemas.incident import IncidentOut
from app.services.incident_analysis import analyze_incidents
from app.services.ping_engine import DeviceStatus
from tests.helpers import make_status, seed_devices

OT_CHILDREN = ["ap-aisle-1", "ap-aisle-2", "hmi-panel-1", "plc-conveyor-1", "scanner-1"]
OT_SUBTREE = ["sw-ot", *OT_CHILDREN]


def snapshot(
    down: Iterable[str] = (),
    degraded: Iterable[str] = (),
    unknown: Iterable[str] = (),
    missing: Iterable[str] = (),
) -> dict[str, DeviceStatus]:
    """A status for every seeded device: healthy unless listed otherwise.

    Devices in ``missing`` get no entry at all (never polled yet).
    """
    statuses: dict[str, DeviceStatus] = {}
    for device in seed_devices():
        if device.id in missing:
            continue
        if device.id in down:
            statuses[device.id] = make_status(device.id, "down")
        elif device.id in degraded:
            statuses[device.id] = make_status(device.id, "degraded", 150.0)
        elif device.id in unknown:
            statuses[device.id] = make_status(device.id, "unknown")
        else:
            statuses[device.id] = make_status(device.id, "healthy", 1.0)
    return statuses


def analyze(**kwargs: Iterable[str]) -> list[IncidentOut]:
    return analyze_incidents(seed_devices(), snapshot(**kwargs))


def summary(incidents: list[IncidentOut]) -> list[tuple[str, str]]:
    return [(incident.device.id, incident.category) for incident in incidents]


def downstream(incident: IncidentOut) -> list[str]:
    # Sorted on purpose: the order inside downstream_affected follows the
    # traversal and is not part of the documented contract.
    return sorted(device.id for device in incident.downstream_affected)


def test_the_seed_file_still_describes_the_tree_these_tests_assume():
    parents = {device.id: device.parent_id for device in seed_devices()}

    assert parents == {
        "fw-01": None,
        "sw-edge": "fw-01",
        "sw-server": "sw-edge",
        "sw-ot": "sw-edge",
        "srv-prod-1": "sw-server",
        "srv-prod-2": "sw-server",
        **{child: "sw-ot" for child in OT_CHILDREN},
    }


def test_all_healthy_means_no_incidents():
    assert analyze() == []


def test_single_leaf_down_is_one_root_cause_with_nothing_downstream():
    incidents = analyze(down=["scanner-1"])

    assert summary(incidents) == [("scanner-1", "root_cause")]
    assert incidents[0].status == "down"
    assert incidents[0].latency_ms is None
    assert incidents[0].downstream_affected == []


def test_switch_down_with_its_five_children_is_one_root_cause_and_five_collateral():
    incidents = analyze(down=OT_SUBTREE)

    assert summary(incidents) == [
        ("sw-ot", "root_cause"),
        ("ap-aisle-1", "collateral"),
        ("ap-aisle-2", "collateral"),
        ("hmi-panel-1", "collateral"),
        ("plc-conveyor-1", "collateral"),
        ("scanner-1", "collateral"),
    ]
    assert downstream(incidents[0]) == OT_CHILDREN
    # Collateral entries never carry a downstream list of their own.
    assert all(incident.downstream_affected == [] for incident in incidents[1:])


def test_firewall_down_on_its_own_is_a_single_root_cause():
    incidents = analyze(down=["fw-01"])

    assert summary(incidents) == [("fw-01", "root_cause")]
    assert incidents[0].downstream_affected == []


def test_firewall_down_with_everything_behind_it_unreachable():
    everything = [device.id for device in seed_devices()]
    behind_firewall = sorted(set(everything) - {"fw-01"})

    incidents = analyze(down=everything)

    assert summary(incidents) == [
        ("fw-01", "root_cause"),
        *[(device_id, "collateral") for device_id in behind_firewall],
    ]
    assert downstream(incidents[0]) == behind_firewall


def test_degraded_parent_with_healthy_children_is_a_root_cause_alone():
    incidents = analyze(degraded=["sw-ot"])

    assert summary(incidents) == [("sw-ot", "root_cause")]
    assert incidents[0].status == "degraded"
    assert incidents[0].latency_ms == 150.0
    assert incidents[0].downstream_affected == []


def test_recovery_reclassifies_from_scratch():
    # 1. Switch and one PLC both down: the PLC is a consequence.
    assert summary(analyze(down=["sw-ot", "plc-conveyor-1"])) == [
        ("sw-ot", "root_cause"),
        ("plc-conveyor-1", "collateral"),
    ]
    # 2. The switch recovers but the PLC stays down: it is now its own cause.
    assert summary(analyze(down=["plc-conveyor-1"])) == [("plc-conveyor-1", "root_cause")]
    # 3. Everything recovers.
    assert analyze() == []


def test_two_independent_root_causes():
    incidents = analyze(down=["srv-prod-1", *OT_SUBTREE])

    assert summary(incidents) == [
        ("srv-prod-1", "root_cause"),
        ("sw-ot", "root_cause"),
        *[(child, "collateral") for child in OT_CHILDREN],
    ]
    assert downstream(incidents[0]) == []
    assert downstream(incidents[1]) == OT_CHILDREN


def test_ordering_is_root_causes_then_collateral_each_sorted_by_id():
    statuses = snapshot(down=["srv-prod-2", "srv-prod-1", *OT_SUBTREE])
    expected = [
        ("srv-prod-1", "root_cause"),
        ("srv-prod-2", "root_cause"),
        ("sw-ot", "root_cause"),
        ("ap-aisle-1", "collateral"),
        ("ap-aisle-2", "collateral"),
        ("hmi-panel-1", "collateral"),
        ("plc-conveyor-1", "collateral"),
        ("scanner-1", "collateral"),
    ]

    # The result must not depend on the order the devices are supplied in.
    for seed in range(5):
        devices = seed_devices()
        random.Random(seed).shuffle(devices)
        assert summary(analyze_incidents(devices, statuses)) == expected


def test_incident_carries_the_device_metadata_and_live_reading():
    incident = analyze(degraded=["fw-01"])[0]

    assert incident.model_dump() == {
        "device": {
            "id": "fw-01",
            "name": "Edge Firewall",
            "type": "firewall",
            "ip": "10.99.0.1",
            "zone": "edge",
            "parent_id": None,
            "ping_port": 80,
            "notes": "",
        },
        "status": "degraded",
        "latency_ms": 150.0,
        "category": "root_cause",
        "downstream_affected": [],
    }


# --- Current behaviour worth knowing (flagged in the Prompt 0 audit) ----------


def test_unknown_or_never_polled_devices_are_not_incidents():
    everything = [device.id for device in seed_devices()]

    assert analyze(unknown=everything) == []
    assert analyze(missing=everything) == []


def test_down_device_under_an_unknown_parent_is_a_root_cause():
    assert summary(analyze(unknown=["sw-ot"], down=["scanner-1"])) == [
        ("scanner-1", "root_cause")
    ]


def test_down_device_under_a_merely_degraded_parent_is_collateral():
    incidents = analyze(degraded=["sw-ot"], down=["plc-conveyor-1"])

    assert summary(incidents) == [("sw-ot", "root_cause"), ("plc-conveyor-1", "collateral")]
    assert downstream(incidents[0]) == ["plc-conveyor-1"]
