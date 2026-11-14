"""Incident analysis when the topology has redundant links.

The small topology most of these tests use:

    core ── s1 ── plc       plc has two uplinks: s1 (its parent) and s2 (a link)
      │      └─── hmi       hmi has only s1
      └──── s2 ···plc

Without links ``analyze_incidents`` must behave exactly as before; the Prompt 1
characterization tests (test_incident_analysis.py) pin that and are untouched.
"""

import random
from collections.abc import Iterable

import pytest
from sqlmodel import Session, select

from app.db.session import engine
from app.models.device import Device
from app.models.device_link import DeviceLink
from app.models.incident import Incident
from app.schemas.incident import IncidentOut
from app.services.device_links import add_link, canonical_pair
from app.services.incident_analysis import _analyze_with_links, analyze_incidents
from app.services.ping_engine import DeviceStatus
from app.services.status_store import status_store
from tests.helpers import FakePing, ip_of, make_status, run_cycles, seed_devices


def device(device_id: str, parent_id: str | None = None) -> Device:
    return Device(id=device_id, name=device_id.upper(), type="switch", ip="10.0.0.1", zone="lab", parent_id=parent_id)


def link(a: str, b: str) -> DeviceLink:
    device_a_id, device_b_id = canonical_pair(a, b)
    return DeviceLink(device_a_id=device_a_id, device_b_id=device_b_id)


def snapshot(
    devices: list[Device],
    down: Iterable[str] = (),
    degraded: Iterable[str] = (),
    unknown: Iterable[str] = (),
    missing: Iterable[str] = (),
) -> dict[str, DeviceStatus]:
    """A status for every device: healthy unless listed. ``missing`` devices
    get no entry at all (never polled yet)."""
    statuses = {}
    for item in devices:
        if item.id in missing:
            continue
        status = (
            "down" if item.id in down
            else "degraded" if item.id in degraded
            else "unknown" if item.id in unknown
            else "healthy"
        )  # fmt: skip
        statuses[item.id] = make_status(item.id, status, 1.0 if status == "healthy" else None)
    return statuses


def result(incidents: list[IncidentOut]) -> list[tuple[str, str, list[str]]]:
    """Each incident as (device, category, devices listed as affected)."""
    return [
        (incident.device.id, incident.category, [affected.id for affected in incident.downstream_affected])
        for incident in incidents
    ]


DEVICES = [device("core"), device("s1", "core"), device("s2", "core"), device("plc", "s1"), device("hmi", "s1")]
LINKS = [link("plc", "s2")]


def analyze(links: list[DeviceLink] | None = LINKS, **statuses: Iterable[str]) -> list[tuple[str, str, list[str]]]:
    return result(analyze_incidents(DEVICES, snapshot(DEVICES, **statuses), links))


# =============================================================================
# Redundancy
# =============================================================================


def test_losing_one_of_two_uplinks_causes_no_collateral():
    # s1 is down and so is plc. plc is still reachable through s2, so its
    # failure is its own: two root causes, nothing collateral.
    assert analyze(down=["s1", "plc"]) == [("plc", "root_cause", []), ("s1", "root_cause", [])]

    # The same snapshot on the tree alone blames plc on s1.
    assert analyze(links=None, down=["s1", "plc"]) == [("s1", "root_cause", ["plc"]), ("plc", "collateral", [])]


def test_losing_both_uplinks_causes_collateral():
    # Nothing leads to plc any more. It is collateral, and both failed
    # uplinks are to blame.
    assert analyze(down=["s1", "s2", "plc"]) == [
        ("s1", "root_cause", ["plc"]),
        ("s2", "root_cause", ["plc"]),
        ("plc", "collateral", []),
    ]


def test_a_healthy_device_behind_one_failed_uplink_is_no_incident():
    assert analyze(down=["s1"]) == [("s1", "root_cause", [])]


def test_a_device_with_one_uplink_is_still_collateral_when_it_fails():
    # hmi hangs under s1 only: the link elsewhere does not help it.
    assert analyze(down=["s1", "hmi"]) == [("s1", "root_cause", ["hmi"]), ("hmi", "collateral", [])]


def test_root_causes_in_one_failure_region_share_its_collateral():
    # s1, plc and hmi are joined to each other and all unhealthy: one region.
    # s1 and plc are both reachable (plc through s2), so both are root causes,
    # and hmi is listed under both. A root cause is never listed as affected.
    assert analyze(down=["s1", "plc", "hmi"]) == [
        ("plc", "root_cause", ["hmi"]),
        ("s1", "root_cause", ["hmi"]),
        ("hmi", "collateral", []),
    ]


def test_separate_failure_regions_keep_their_own_collateral():
    devices = [*DEVICES, device("scanner", "s2"), device("panel", "s2")]

    incidents = analyze_incidents(devices, snapshot(devices, down=["s1", "hmi", "s2", "scanner", "panel"]), LINKS)

    # plc is healthy, so the two failed switches are not joined to each other.
    assert result(incidents) == [
        ("s1", "root_cause", ["hmi"]),
        ("s2", "root_cause", ["panel", "scanner"]),  # sorted by device id
        ("hmi", "collateral", []),
        ("panel", "collateral", []),
        ("scanner", "collateral", []),
    ]


def test_a_failed_root_takes_everything_behind_it():
    assert analyze(down=["core", "s1", "s2", "plc", "hmi"]) == [
        ("core", "root_cause", ["hmi", "plc", "s1", "s2"]),
        ("hmi", "collateral", []),
        ("plc", "collateral", []),
        ("s1", "collateral", []),
        ("s2", "collateral", []),
    ]


def test_a_second_root_keeps_a_device_reachable():
    #   c1 ── s ── d      and s is also linked to the second root c2
    devices = [device("c1"), device("c2"), device("s", "c1"), device("d", "s")]
    links = [link("s", "c2")]

    with_links = analyze_incidents(devices, snapshot(devices, down=["c1", "s", "d"]), links)
    tree_only = analyze_incidents(devices, snapshot(devices, down=["c1", "s", "d"]))

    # s is reached from c2, so it failed by itself; d is behind it.
    assert result(with_links) == [("c1", "root_cause", ["d"]), ("s", "root_cause", ["d"]), ("d", "collateral", [])]
    assert sorted_result(tree_only) == [
        ("c1", "root_cause", ["d", "s"]),
        ("d", "collateral", []),
        ("s", "collateral", []),
    ]


def test_incident_carries_the_device_metadata_and_live_reading():
    statuses = snapshot(DEVICES, down=["s1"], degraded=["plc"])
    statuses["plc"] = make_status("plc", "degraded", 150.0)

    plc, s1 = analyze_incidents(DEVICES, statuses, LINKS)

    assert (plc.device.id, plc.device.name, plc.device.parent_id) == ("plc", "PLC", "s1")
    assert (plc.status, plc.latency_ms, plc.category) == ("degraded", 150.0, "root_cause")
    assert (s1.status, s1.latency_ms, s1.category) == ("down", None, "root_cause")


# =============================================================================
# What counts as healthy
# =============================================================================


def test_an_unknown_or_never_polled_device_does_not_block_the_way():
    # "unknown" means the probe itself failed. It is not a failure of the device.
    assert analyze(down=["plc"], unknown=["s1", "s2"]) == [("plc", "root_cause", [])]
    assert analyze(down=["plc"], missing=["s1", "s2"]) == [("plc", "root_cause", [])]
    assert analyze(unknown=["core"], missing=["hmi"]) == []  # and is no incident itself


def test_a_degraded_device_blocks_the_way_like_a_down_one():
    assert analyze(degraded=["s1"], down=["hmi"]) == [("s1", "root_cause", ["hmi"]), ("hmi", "collateral", [])]


def test_a_failure_behind_a_healthy_device_behind_a_failure_is_collateral_in_nobodys_region():
    #   core ── a ── mid ── far       a and far are down, mid still answers
    #     └──── side ···a
    devices = [device("core"), device("a", "core"), device("mid", "a"), device("far", "mid"), device("side", "core")]

    incidents = analyze_incidents(devices, snapshot(devices, down=["a", "far"]), [link("side", "a")])

    # Reachability is decided from the roots: the only way to far leads
    # through a. But far is not joined to a through unhealthy devices, so it
    # is listed under no root cause.
    assert result(incidents) == [("a", "root_cause", []), ("far", "collateral", [])]


# =============================================================================
# No links: exactly the old behaviour
# =============================================================================


def tree_rule(devices: list[Device], statuses: dict[str, DeviceStatus]) -> list[tuple[str, str, list[str]]]:
    """The original rule, written out independently of the application code:
    a root cause has a parent that is not unhealthy, and is given every
    unhealthy device below it; anything else unhealthy is collateral."""
    parent = {item.id: item.parent_id for item in devices}

    def unhealthy(device_id: str) -> bool:
        return device_id in statuses and statuses[device_id].status in ("down", "degraded")

    def below(device_id: str) -> list[str]:
        found = []
        for item in devices:
            ancestor = parent[item.id]
            while ancestor is not None and ancestor != device_id:
                ancestor = parent.get(ancestor)
            if ancestor == device_id and unhealthy(item.id):
                found.append(item.id)
        return sorted(found)

    roots = [d.id for d in devices if unhealthy(d.id) and not (parent[d.id] in parent and unhealthy(parent[d.id]))]
    collateral = [d.id for d in devices if unhealthy(d.id) and d.id not in roots]
    return [(i, "root_cause", below(i)) for i in sorted(roots)] + [(i, "collateral", []) for i in sorted(collateral)]


def random_tree(rng: random.Random) -> list[Device]:
    devices = [device("d00")]
    for index in range(1, rng.randint(1, 12)):
        devices.append(device(f"d{index:02d}", f"d{rng.randrange(index):02d}"))
    return devices


def sorted_result(incidents: list[IncidentOut]) -> list[tuple[str, str, list[str]]]:
    # Without links the order inside downstream_affected follows the traversal
    # and is not part of the contract, so compare it sorted.
    return [(device_id, category, sorted(affected)) for device_id, category, affected in result(incidents)]


def test_without_links_the_result_is_exactly_the_old_one():
    for seed in range(600):
        rng = random.Random(seed)
        devices = seed_devices() if seed % 2 else random_tree(rng)
        statuses = {
            item.id: make_status(item.id, rng.choice(["healthy", "healthy", "down", "degraded", "unknown"]))
            for item in devices
            if rng.random() < 0.9  # some devices have never been polled
        }

        before = analyze_incidents(devices, statuses)  # how every caller used to call it

        assert analyze_incidents(devices, statuses, None) == before, f"seed {seed}"
        assert analyze_incidents(devices, statuses, []) == before, f"seed {seed}"
        assert sorted_result(before) == tree_rule(devices, statuses), f"seed {seed}"


def test_on_a_snapshot_a_tree_can_really_produce_both_rules_agree():
    """In a real tree a device behind a failed one cannot answer. On every
    such snapshot the reachability rule says exactly what the tree rule says,
    so switching rules when the first link is added changes nothing there."""
    for seed in range(600):
        rng = random.Random(seed)
        devices = random_tree(rng)
        parent = {item.id: item.parent_id for item in devices}
        failed = {item.id for item in devices if rng.random() < 0.25}
        down = set()
        for item in devices:  # a parent is always listed before its children
            if item.id in failed or parent[item.id] in down:
                down.add(item.id)
        statuses = snapshot(devices, down=down)

        by_tree = analyze_incidents(devices, statuses)
        by_reachability = _analyze_with_links(devices, statuses, [])

        assert sorted_result(by_reachability) == sorted_result(by_tree), f"seed {seed}"


# =============================================================================
# The application uses the stored links
# =============================================================================

pytest_db = pytest.mark.usefixtures("db")


def store_link(a: str, b: str) -> None:
    with Session(engine) as session:
        add_link(session, a, b)


def publish(down: Iterable[str]) -> None:
    status_store.update(
        [make_status(item.id, "down" if item.id in down else "healthy") for item in seed_devices()]
    )


@pytest_db
def test_the_live_incidents_endpoint_uses_the_stored_links(client, admin_headers):
    publish(down=["sw-ot", "plc-conveyor-1", "scanner-1"])

    def live() -> list[tuple[str, str, list[str]]]:
        body = client.get("/api/incidents", headers=admin_headers).json()
        return [
            (item["device"]["id"], item["category"], sorted(d["id"] for d in item["downstream_affected"]))
            for item in body
        ]

    assert live() == [
        ("sw-ot", "root_cause", ["plc-conveyor-1", "scanner-1"]),
        ("plc-conveyor-1", "collateral", []),
        ("scanner-1", "collateral", []),
    ]

    store_link("plc-conveyor-1", "sw-server")  # a second uplink for the PLC

    assert live() == [
        ("plc-conveyor-1", "root_cause", ["scanner-1"]),  # reachable through sw-server: its own failure
        ("sw-ot", "root_cause", ["scanner-1"]),
        ("scanner-1", "collateral", []),
    ]


@pytest_db
async def test_the_incident_tracker_uses_the_stored_links():
    def root_devices() -> list[tuple[str, list[str]]]:
        with Session(engine) as session:
            rows = session.exec(select(Incident).order_by(Incident.root_device_id)).all()
            return [(row.root_device_id, row.affected_device_ids) for row in rows]

    store_link("plc-conveyor-1", "sw-server")
    ping = FakePing()
    for device_id in ("sw-ot", "plc-conveyor-1"):
        ping.outcomes[ip_of(device_id)] = (False, 0.0)

    await run_cycles(1, ping)  # a device's first result is accepted at once

    # With its second uplink the PLC is a root cause, so it gets an incident
    # of its own. On the tree alone it would be collateral of sw-ot.
    assert root_devices() == [("plc-conveyor-1", []), ("sw-ot", [])]
