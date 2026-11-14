"""The shipped topology and how it is seeded.

``infra/devices.seed.json`` describes twelve devices and two extra links that
make the warehouse network redundant:

    fw-01 ─┬─ sw-edge ───┬─ sw-server ── srv-prod-1, srv-prod-2
           │             └─ sw-ot ────── plc, hmi, 2 access points, scanner
           └─ sw-edge-2 ··· sw-server and sw-ot   (extra links)

The rest of the suite runs on a frozen copy of the older 11-device tree
(tests/data/classic_tree.seed.json), so this file is where the real seed, the
compose file that simulates it, and link seeding are checked.
"""

import json
import re

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import main
from app.core.config import settings
from app.db.seed import seed_devices_from_json
from app.db.session import engine, init_db
from app.models import Device, DeviceLink
from app.services.device_links import delete_link, device_graph
from app.services.topology_graph import reachable_from_roots
from tests.conftest import REAL_SEED_FILE, SEED_FILE
from tests.helpers import wipe_database

COMPOSE_FILE = REAL_SEED_FILE.parent / "docker-compose.yml"
SHIPPED_LINKS = [("sw-edge-2", "sw-ot"), ("sw-edge-2", "sw-server")]


def stored() -> tuple[list[str], list[tuple[str, str]]]:
    """(device ids, links) in the database, both sorted."""
    with Session(engine) as session:
        return (
            sorted(session.exec(select(Device.id)).all()),
            sorted((link.device_a_id, link.device_b_id) for link in session.exec(select(DeviceLink)).all()),
        )


def seed_file(tmp_path, devices: list[dict]) -> str:
    path = tmp_path / "devices.seed.json"
    path.write_text(json.dumps(devices))
    return str(path)


def entry(device_id: str, parent_id: str | None = None, **extra) -> dict:
    return {"id": device_id, "name": device_id, "type": "switch", "ip": "10.0.0.1", "zone": "lab",
            "parentId": parent_id, **extra}  # fmt: skip


# --- the shipped files -----------------------------------------------------------


def test_the_shipped_seed_has_a_second_edge_switch_with_two_extra_links():
    devices = {item["id"]: item for item in json.loads(REAL_SEED_FILE.read_text())}

    assert len(devices) == 12
    assert devices["sw-edge-2"] == {
        "id": "sw-edge-2",
        "name": "Edge Switch 2",
        "type": "switch",
        "ip": "10.99.0.5",
        "zone": "edge",
        "parentId": "fw-01",
        "links": ["sw-server", "sw-ot"],
    }
    # No other device carries links, and every address is used once.
    assert [device_id for device_id, item in devices.items() if "links" in item] == ["sw-edge-2"]
    assert len({item["ip"] for item in devices.values()}) == 12


def test_the_compose_file_simulates_every_seeded_device_at_its_address():
    seeded = {item["id"]: item["ip"] for item in json.loads(REAL_SEED_FILE.read_text())}
    simulated = dict(
        re.findall(
            r"^  sim-([a-z0-9-]+):\n(?:    .*\n)*?        ipv4_address: ([0-9.]+)$",
            COMPOSE_FILE.read_text(),
            flags=re.MULTILINE,
        )
    )

    assert simulated == seeded
    assert simulated["sw-edge-2"] == "10.99.0.5"


# --- seeding ---------------------------------------------------------------------


@pytest.fixture
def shipped_seed(monkeypatch) -> None:
    """Start the app with the shipped seed file instead of the classic tree."""
    monkeypatch.setattr(settings, "SEED_PATH", str(REAL_SEED_FILE))


def test_a_new_installation_gets_the_redundant_topology(shipped_seed):
    wipe_database()

    with TestClient(main.app):  # startup migrates, then seeds
        devices, links = stored()

    assert len(devices) == 12 and "sw-edge-2" in devices
    assert links == SHIPPED_LINKS


def test_restarting_does_not_duplicate_devices_or_links(shipped_seed):
    wipe_database()

    for _ in range(3):
        with TestClient(main.app):
            pass

    devices, links = stored()
    assert (len(devices), links) == (12, SHIPPED_LINKS)


def test_an_existing_installation_gains_the_new_switch_and_its_links(db, shipped_seed):
    """The upgrade path: a database seeded with the 11-device tree, restarted
    with the new seed file."""
    before, _ = stored()
    assert len(before) == 11

    with TestClient(main.app):
        devices, links = stored()

    assert sorted(set(devices) - set(before)) == ["sw-edge-2"]
    assert links == SHIPPED_LINKS
    # Both tier switches now have a way to the firewall that avoids sw-edge.
    with Session(engine) as session:
        graph = device_graph(session.exec(select(Device)).all(), session.exec(select(DeviceLink)).all())
    assert reachable_from_roots(graph, {"sw-edge"}) == set(devices)


def test_a_seeded_link_that_was_deleted_comes_back_on_restart_like_a_seeded_device(shipped_seed):
    wipe_database()
    with TestClient(main.app):
        pass
    with Session(engine) as session:
        delete_link(session, session.exec(select(DeviceLink.id)).first())
    assert len(stored()[1]) == 1

    with TestClient(main.app):
        pass

    assert stored()[1] == SHIPPED_LINKS


@pytest.mark.usefixtures("db")
def test_a_seed_file_without_links_seeds_no_links():
    seed_devices_from_json(str(SEED_FILE))  # the classic tree: a plain list of devices

    assert stored()[1] == []


def test_seed_links_that_break_a_rule_are_skipped_and_the_rest_is_seeded(tmp_path, caplog):
    wipe_database()
    init_db()
    path = seed_file(
        tmp_path,
        [
            entry("core"),
            entry("s1", "core", links=["s2", "s2", "s1", "ghost", "core"]),  # ok, repeated, self, unknown, its parent
            entry("s2", "core", links=["s1"]),  # the same link from the other side
        ],
    )

    seed_devices_from_json(path)
    seed_devices_from_json(path)  # and again: nothing more

    assert stored() == (["core", "s1", "s2"], [("s1", "s2")])
    assert "Seed link s1 -- ghost skipped: Device 'ghost' does not exist" in caplog.text
    assert "Seed link s1 -- s1 skipped: A device cannot be linked to itself" in caplog.text
