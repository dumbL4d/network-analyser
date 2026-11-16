"""Topology analysis endpoints: single points of failure and the what-if simulator.

Most tests run on the SHIPPED topology (twelve devices, two extra links):

    fw-01 ─┬─ sw-edge ───┬─ sw-server ── srv-prod-1, srv-prod-2
           │             └─ sw-ot ────── plc, hmi, 2 access points, scanner
           └─ sw-edge-2 ··· sw-server and sw-ot   (extra links)

Both tier switches are dual-homed: each reaches the firewall through either
edge switch.
"""

import pytest
from sqlalchemy import func, select
from sqlmodel import SQLModel

from app.db.seed import seed_devices_from_json
from app.db.session import engine
from app.models import Device
from app.services.status_store import status_store
from app.services.topology_analysis import spof_report
from tests.conftest import REAL_SEED_FILE
from tests.helpers import make_status, seed_devices

OT_CHILDREN = ["ap-aisle-1", "ap-aisle-2", "hmi-panel-1", "plc-conveyor-1", "scanner-1"]
SERVERS = ["srv-prod-1", "srv-prod-2"]
BEHIND_THE_EDGE = sorted([*OT_CHILDREN, *SERVERS, "sw-ot", "sw-server"])
EVERYTHING_BUT_THE_FIREWALL = sorted([*BEHIND_THE_EDGE, "sw-edge", "sw-edge-2"])


@pytest.fixture
def shipped(db: None) -> None:
    """The shipped topology: the classic tree plus sw-edge-2 and its two links."""
    seed_devices_from_json(str(REAL_SEED_FILE))


def spof(client, headers) -> list[tuple[str, int, list[str]]]:
    response = client.get("/api/analysis/spof", headers=headers)
    assert response.status_code == 200
    return [(item["device_id"], item["blast_radius"], item["cut_off_device_ids"]) for item in response.json()]


def what_if(client, headers, failed: list[str]) -> dict:
    response = client.post("/api/analysis/what-if", headers=headers, json={"failed_device_ids": failed})
    assert response.status_code == 200, response.text
    return response.json()


def incidents(body: dict) -> list[tuple[str, str, list[str]]]:
    """Each predicted incident as (device, category, devices listed as affected)."""
    return [
        (item["device"]["id"], item["category"], sorted(d["id"] for d in item["downstream_affected"]))
        for item in body["incidents"]
    ]


# =============================================================================
# GET /api/analysis/spof
# =============================================================================


def test_spof_on_the_shipped_topology(shipped, client, admin_headers):
    # Neither edge switch is a single point of failure: the other one takes over.
    assert spof(client, admin_headers) == [
        ("fw-01", 11, EVERYTHING_BUT_THE_FIREWALL),
        ("sw-ot", 5, OT_CHILDREN),
        ("sw-server", 2, SERVERS),
    ]


def test_spof_response_shape(shipped, client, admin_headers):
    first = client.get("/api/analysis/spof", headers=admin_headers).json()[0]

    assert set(first) == {"device_id", "blast_radius", "cut_off_device_ids"}
    assert first["blast_radius"] == len(first["cut_off_device_ids"])


def test_spof_on_the_tree_without_links(client, admin_headers):
    # The classic 11-device tree: everything on the way to the firewall is one.
    assert spof(client, admin_headers) == [
        ("fw-01", 10, sorted([*BEHIND_THE_EDGE, "sw-edge"])),
        ("sw-edge", 9, BEHIND_THE_EDGE),
        ("sw-ot", 5, OT_CHILDREN),
        ("sw-server", 2, SERVERS),
    ]


def test_removing_a_link_makes_the_edge_switch_a_spof_again(shipped, client, admin_headers):
    links = client.get("/api/links", headers=admin_headers).json()
    ot_uplink = next(link for link in links if (link["device_a_id"], link["device_b_id"]) == ("sw-edge-2", "sw-ot"))

    assert client.delete(f"/api/links/{ot_uplink['id']}", headers=admin_headers).status_code == 204

    # sw-ot has one way up again; sw-server still has two.
    assert spof(client, admin_headers) == [
        ("fw-01", 11, EVERYTHING_BUT_THE_FIREWALL),
        ("sw-edge", 6, sorted([*OT_CHILDREN, "sw-ot"])),
        ("sw-ot", 5, OT_CHILDREN),
        ("sw-server", 2, SERVERS),
    ]


def test_spofs_with_the_same_blast_radius_are_ordered_by_id():
    def device(device_id: str, parent_id: str | None = None) -> Device:
        return Device(id=device_id, name=device_id, type="switch", ip="10.0.0.1", zone="lab", parent_id=parent_id)

    # core ── s2 ── x   and   core ── s1 ── y: both switches cut off one device.
    devices = [device("core"), device("s2", "core"), device("s1", "core"), device("x", "s2"), device("y", "s1")]

    assert [(spof.device_id, spof.blast_radius) for spof in spof_report(devices, [])] == [
        ("core", 4),
        ("s1", 1),  # before s2, although s2 comes first in the input
        ("s2", 1),
    ]


def test_no_devices_means_no_spofs(client, admin_headers):
    with engine.begin() as connection:
        connection.execute(SQLModel.metadata.tables["device"].delete())

    assert spof(client, admin_headers) == []


# =============================================================================
# POST /api/analysis/what-if
# =============================================================================


def test_losing_one_edge_switch_cuts_nothing_off(shipped, client, admin_headers):
    for edge_switch in ("sw-edge", "sw-edge-2"):
        body = what_if(client, admin_headers, [edge_switch])

        assert incidents(body) == [(edge_switch, "root_cause", [])]
        assert (body["unreachable_device_ids"], body["total_blast_radius"]) == ([], 0)


def test_losing_both_edge_switches_cuts_off_everything_behind_them(shipped, client, admin_headers):
    body = what_if(client, admin_headers, ["sw-edge", "sw-edge-2"])

    assert (body["unreachable_device_ids"], body["total_blast_radius"]) == (BEHIND_THE_EDGE, 9)
    # Both failures are root causes and share the collateral devices.
    assert incidents(body) == [
        ("sw-edge", "root_cause", BEHIND_THE_EDGE),
        ("sw-edge-2", "root_cause", BEHIND_THE_EDGE),
        *[(device_id, "collateral", []) for device_id in BEHIND_THE_EDGE],
    ]


def test_losing_a_tier_switch_cuts_off_its_single_homed_children(shipped, client, admin_headers):
    body = what_if(client, admin_headers, ["sw-ot"])

    assert (body["unreachable_device_ids"], body["total_blast_radius"]) == (OT_CHILDREN, 5)
    assert incidents(body) == [
        ("sw-ot", "root_cause", OT_CHILDREN),
        *[(device_id, "collateral", []) for device_id in OT_CHILDREN],
    ]


def test_losing_a_leaf_affects_nothing_else(shipped, client, admin_headers):
    body = what_if(client, admin_headers, ["scanner-1"])

    assert incidents(body) == [("scanner-1", "root_cause", [])]
    assert body["total_blast_radius"] == 0


def test_a_failed_device_behind_another_failure_is_collateral_but_not_counted_as_cut_off(
    shipped, client, admin_headers
):
    body = what_if(client, admin_headers, ["sw-ot", "scanner-1"])

    # The scanner was said to fail, so it is not "cut off"; the other four are.
    assert body["unreachable_device_ids"] == [d for d in OT_CHILDREN if d != "scanner-1"]
    assert body["total_blast_radius"] == 4
    assert incidents(body)[0] == ("sw-ot", "root_cause", OT_CHILDREN)
    assert ("scanner-1", "collateral", []) in incidents(body)


def test_independent_failures_are_separate_root_causes(shipped, client, admin_headers):
    body = what_if(client, admin_headers, ["sw-edge", "sw-server", "scanner-1"])

    assert incidents(body) == [
        ("scanner-1", "root_cause", []),
        ("sw-edge", "root_cause", SERVERS),  # joined to sw-server, so they share its collateral
        ("sw-server", "root_cause", SERVERS),
        ("srv-prod-1", "collateral", []),
        ("srv-prod-2", "collateral", []),
    ]
    assert body["unreachable_device_ids"] == SERVERS


def test_losing_the_firewall_cuts_off_everything(shipped, client, admin_headers):
    body = what_if(client, admin_headers, ["fw-01"])

    assert (body["unreachable_device_ids"], body["total_blast_radius"]) == (EVERYTHING_BUT_THE_FIREWALL, 11)
    assert incidents(body)[0] == ("fw-01", "root_cause", EVERYTHING_BUT_THE_FIREWALL)


def test_no_failures_means_no_incidents(shipped, client, admin_headers):
    assert what_if(client, admin_headers, []) == {
        "incidents": [],
        "unreachable_device_ids": [],
        "total_blast_radius": 0,
    }


def test_a_device_named_twice_counts_once(shipped, client, admin_headers):
    assert what_if(client, admin_headers, ["sw-ot", "sw-ot"]) == what_if(client, admin_headers, ["sw-ot"])


def test_what_if_on_the_tree_without_links(client, admin_headers):
    # No second edge switch here: sw-edge takes everything behind it with it.
    body = what_if(client, admin_headers, ["sw-edge"])

    assert (body["unreachable_device_ids"], body["total_blast_radius"]) == (BEHIND_THE_EDGE, 9)
    assert incidents(body)[0] == ("sw-edge", "root_cause", BEHIND_THE_EDGE)


def test_what_if_incidents_have_the_shape_of_the_live_incident_list(shipped, client, admin_headers):
    status_store.update([make_status("scanner-1", "down")])
    (live,) = client.get("/api/incidents", headers=admin_headers).json()

    (predicted,) = what_if(client, admin_headers, ["scanner-1"])["incidents"]

    assert set(predicted) == set(live) == {"device", "status", "latency_ms", "category", "downstream_affected"}
    assert predicted["device"] == live["device"]
    assert (predicted["status"], predicted["latency_ms"], predicted["category"]) == ("down", None, "root_cause")


@pytest.mark.parametrize(
    ("failed", "detail"),
    [
        (["ghost"], "Unknown device(s): ghost"),
        (["sw-ot", "zzz", "aaa"], "Unknown device(s): aaa, zzz"),
    ],
)
def test_what_if_rejects_unknown_devices(shipped, client, admin_headers, failed, detail):
    response = client.post("/api/analysis/what-if", headers=admin_headers, json={"failed_device_ids": failed})

    assert (response.status_code, response.json()) == (422, {"detail": detail})


@pytest.mark.parametrize("body", [{}, {"failed_device_ids": "sw-ot"}, {"failed_device_ids": [1, 2]}, None])
def test_what_if_requires_a_list_of_device_ids(shipped, client, admin_headers, body):
    assert client.post("/api/analysis/what-if", headers=admin_headers, json=body).status_code == 422


def row_counts() -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table.name: connection.execute(select(func.count()).select_from(table)).scalar()
            for table in SQLModel.metadata.sorted_tables
        }


def test_what_if_touches_neither_the_live_status_nor_anything_stored(shipped, client, admin_headers):
    # Live: only the scanner is down.
    status_store.update(
        [make_status(device.id, "down" if device.id == "scanner-1" else "healthy") for device in seed_devices()]
    )
    live_statuses = dict(status_store.get_all())
    live_incidents = client.get("/api/incidents", headers=admin_headers).json()
    rows = row_counts()

    body = what_if(client, admin_headers, ["fw-01"])  # imagine the worst

    assert body["total_blast_radius"] == 11
    assert status_store.get_all() == live_statuses
    assert client.get("/api/incidents", headers=admin_headers).json() == live_incidents
    assert row_counts() == rows  # no incident, event, sample or transition was written


def test_what_if_starts_from_a_healthy_network_whatever_the_live_status_is(shipped, client, admin_headers):
    status_store.update([make_status("scanner-1", "down"), make_status("sw-ot", "down")])

    assert what_if(client, admin_headers, [])["incidents"] == []
    assert incidents(what_if(client, admin_headers, ["srv-prod-1"])) == [("srv-prod-1", "root_cause", [])]


# =============================================================================
# Roles
# =============================================================================


def test_a_viewer_can_read_the_analysis_and_run_a_what_if(shipped, client, viewer_headers):
    assert [device_id for device_id, _, _ in spof(client, viewer_headers)] == ["fw-01", "sw-ot", "sw-server"]
    assert what_if(client, viewer_headers, ["sw-ot"])["total_blast_radius"] == 5


@pytest.mark.parametrize(("method", "path"), [("GET", "/api/analysis/spof"), ("POST", "/api/analysis/what-if")])
def test_the_analysis_needs_a_token(client, method, path):
    assert client.request(method, path, json={"failed_device_ids": []}).status_code == 401
