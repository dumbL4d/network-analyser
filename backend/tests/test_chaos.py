"""Fault injection: planning, the controller and the admin endpoints.

No Docker anywhere: ``FakeChaosClient`` stands in for the chaos agent. It
remembers every call and behaves like a set of containers, so the tests can
check both WHAT the backend decided to stop and what state that leaves.

Most tests run on the shipped topology, where both tier switches are
dual-homed:

    fw-01 ─┬─ sw-edge ───┬─ sw-server ── srv-prod-1, srv-prod-2
           │             └─ sw-ot ────── plc, hmi, 2 access points, scanner
           └─ sw-edge-2 ··· sw-server and sw-ot   (extra links)
"""

import json
import logging
import random
import threading
import time

import pytest

from app.core.config import settings
from app.db.seed import seed_devices_from_json
from app.models import AuditEvent, Device, DeviceLink
from app.services.chaos import (
    SCENARIOS,
    _in_a_thread,
    chaos_controller,
    plan_failure,
    report_leftover_faults,
)
from app.services.chaos_client import ChaosAgentError, ChaosUnavailable, SimContainer
from app.services.device_links import canonical_pair
from app.services.topology_analysis import what_if
from tests.conftest import REAL_SEED_FILE
from tests.helpers import seed_devices, stored

OT_CHILDREN = ["ap-aisle-1", "ap-aisle-2", "hmi-panel-1", "plc-conveyor-1", "scanner-1"]
SERVERS = ["srv-prod-1", "srv-prod-2"]
BEHIND_THE_EDGE = sorted([*OT_CHILDREN, *SERVERS, "sw-ot", "sw-server"])


class FakeChaosClient:
    """The chaos agent, without Docker: every simulated device is a flag."""

    def __init__(self, device_ids: list[str]) -> None:
        self.running = {f"sim-{device_id}": True for device_id in device_ids}
        self.netem: dict[str, str] = {}
        self.calls: list[tuple] = []
        self.cannot_start: set[str] = set()

    def containers(self) -> list[SimContainer]:
        return [
            SimContainer(name, running, self.netem.get(name) if running else None)
            for name, running in sorted(self.running.items())
        ]

    def _allowed(self, name: str) -> None:
        if name not in self.running:  # what the real agent answers for anything unlabelled
            raise ChaosAgentError(404, f"'{name}' is not a simulated device")

    def stop(self, name: str) -> None:
        self._allowed(name)
        self.calls.append(("stop", name))
        self.running[name] = False
        self.netem.pop(name, None)  # a stopped container loses its netem

    def start(self, name: str) -> None:
        self._allowed(name)
        if name in self.cannot_start:
            raise ChaosAgentError(502, "docker start failed")
        self.calls.append(("start", name))
        self.running[name] = True

    def set_netem(self, name: str, delay_ms: int, jitter_ms: int, loss_pct: float) -> None:
        self._allowed(name)
        self.calls.append(("netem", name, delay_ms, jitter_ms, loss_pct))
        self.netem[name] = f"delay {delay_ms}ms {jitter_ms}ms loss {loss_pct:g}%"

    def clear_netem(self, name: str) -> None:
        self._allowed(name)
        self.calls.append(("clear", name))
        self.netem.pop(name, None)

    def stopped(self) -> list[str]:
        return sorted(name.removeprefix("sim-") for name, running in self.running.items() if not running)


class FakeEvent:
    """A ``threading.Event`` for a flap that is run inline: ``wait`` returns
    at once and records how long the flap wanted to sleep."""

    def __init__(self) -> None:
        self.waits: list[float] = []
        self._set = False

    def set(self) -> None:
        self._set = True

    def is_set(self) -> bool:
        return self._set

    def wait(self, timeout: float) -> bool:
        self.waits.append(timeout)
        return self._set


def shipped_topology() -> tuple[list[Device], list[DeviceLink]]:
    items = json.loads(REAL_SEED_FILE.read_text())
    devices = [
        Device(id=i["id"], name=i["name"], type=i["type"], ip=i["ip"], zone=i["zone"], parent_id=i["parentId"])
        for i in items
    ]
    links = [
        DeviceLink(device_a_id=a, device_b_id=b)
        for item in items
        for a, b in [canonical_pair(item["id"], other) for other in item.get("links", [])]
    ]
    return devices, links


@pytest.fixture
def shipped(db: None) -> None:
    """The shipped topology in the database: twelve devices, two extra links."""
    seed_devices_from_json(str(REAL_SEED_FILE))


@pytest.fixture
def agent(monkeypatch) -> FakeChaosClient:
    """A fake chaos agent with a container for every shipped device. Flaps do
    not start a thread: they are collected in ``agent.flaps`` to be run inline."""
    fake = FakeChaosClient([device.id for device in shipped_topology()[0]])
    fake.flaps = []
    fake.events = []  # one FakeEvent per flap, in the order the flaps were started

    def new_event() -> FakeEvent:
        fake.events.append(FakeEvent())
        return fake.events[-1]

    monkeypatch.setattr(chaos_controller, "client_factory", lambda: fake)
    monkeypatch.setattr(chaos_controller, "spawn", lambda run, name: fake.flaps.append(run))
    monkeypatch.setattr(chaos_controller, "new_event", new_event)
    return fake


def post(client, headers, path: str, body: dict | None = None):
    return client.post(f"/api/chaos/{path}", headers=headers, json=body)


def faults(response) -> list[tuple[str, str]]:
    assert response.status_code == 200, response.text
    return [(fault["device_id"], fault["kind"]) for fault in response.json()["faults"]]


# =============================================================================
# Planning: which devices have to become unreachable (pure)
# =============================================================================


def test_one_edge_switch_takes_nothing_else_with_it():
    devices, links = shipped_topology()

    assert plan_failure(devices, links, ["sw-edge"]) == {"sw-edge"}
    assert plan_failure(devices, links, ["sw-edge-2"]) == {"sw-edge-2"}


def test_both_edge_switches_take_everything_behind_them():
    devices, links = shipped_topology()

    assert plan_failure(devices, links, ["sw-edge", "sw-edge-2"]) == {"sw-edge", "sw-edge-2", *BEHIND_THE_EDGE}


def test_a_tier_switch_takes_its_single_homed_devices():
    devices, links = shipped_topology()

    assert plan_failure(devices, links, ["sw-ot"]) == {"sw-ot", *OT_CHILDREN}
    assert plan_failure(devices, links, ["scanner-1"]) == {"scanner-1"}  # a leaf takes nothing


def test_without_redundancy_the_edge_switch_takes_everything_behind_it():
    devices = seed_devices()  # the classic tree: one edge switch, no links

    assert plan_failure(devices, [], ["sw-edge"]) == {"sw-edge", *BEHIND_THE_EDGE}
    assert plan_failure(devices, [], []) == set()


def test_the_plan_is_what_the_what_if_simulator_predicts():
    devices, links = shipped_topology()
    ids = [device.id for device in devices]
    for seed in range(300):
        rng = random.Random(seed)
        failed = rng.sample(ids, rng.randint(0, len(ids)))

        predicted = what_if(devices, links, failed)

        assert plan_failure(devices, links, failed) == set(failed) | set(predicted.unreachable_device_ids), (
            f"seed {seed}: {failed}"
        )


# =============================================================================
# POST /api/chaos/fail
# =============================================================================


def test_failing_one_edge_switch_stops_only_that_container(shipped, agent, client, admin_headers):
    response = post(client, admin_headers, "fail", {"device_ids": ["sw-edge"]})

    assert faults(response) == [("sw-edge", "failed")]
    assert agent.calls == [("stop", "sim-sw-edge")]  # the redundancy absorbs it


def test_failing_the_second_edge_switch_cuts_off_everything_behind_both(shipped, agent, client, admin_headers):
    post(client, admin_headers, "fail", {"device_ids": ["sw-edge"]})
    agent.calls.clear()

    response = post(client, admin_headers, "fail", {"device_ids": ["sw-edge-2"]})

    # The cut-off set is computed for BOTH failures together.
    assert sorted(agent.calls) == sorted([("stop", f"sim-{d}") for d in ["sw-edge-2", *BEHIND_THE_EDGE]])
    assert faults(response) == sorted(
        [("sw-edge", "failed"), ("sw-edge-2", "failed"), *[(d, "cut_off") for d in BEHIND_THE_EDGE]]
    )


def test_failing_a_tier_switch_stops_its_children_too(shipped, agent, client, admin_headers):
    response = post(client, admin_headers, "fail", {"device_ids": ["sw-ot"]})

    assert agent.stopped() == sorted(["sw-ot", *OT_CHILDREN])
    assert faults(response) == sorted([("sw-ot", "failed"), *[(d, "cut_off") for d in OT_CHILDREN]])
    details = {f["device_id"]: f["detail"] for f in response.json()["faults"]}
    assert details["sw-ot"] == "stopped on request"
    assert details["scanner-1"] == "stopped because nothing leads to it any more"


def test_on_the_tree_without_links_the_edge_switch_takes_everything(agent, client, admin_headers):
    # The classic 11-device tree is in the database here: no sw-edge-2, no links.
    post(client, admin_headers, "fail", {"device_ids": ["sw-edge"]})

    assert agent.stopped() == sorted(["sw-edge", *BEHIND_THE_EDGE])


def test_failing_the_same_device_again_does_nothing_more(shipped, agent, client, admin_headers):
    post(client, admin_headers, "fail", {"device_ids": ["sw-ot"]})
    agent.calls.clear()

    response = post(client, admin_headers, "fail", {"device_ids": ["sw-ot", "scanner-1"]})

    assert agent.calls == []  # all of them are down already
    assert ("scanner-1", "failed") in faults(response)  # but the scanner now counts as failed itself


@pytest.mark.parametrize("body", [{}, {"device_ids": []}, {"device_ids": "sw-ot"}, {"device_ids": [1]}])
def test_fail_needs_at_least_one_device_id(shipped, agent, client, admin_headers, body):
    assert post(client, admin_headers, "fail", body).status_code == 422
    assert agent.calls == []


# =============================================================================
# Allow-list: only known devices that have a simulated container
# =============================================================================


def test_an_unknown_device_is_rejected_before_anything_is_stopped(shipped, agent, client, admin_headers):
    response = post(client, admin_headers, "fail", {"device_ids": ["sw-ot", "ghost"]})

    assert (response.status_code, response.json()) == (422, {"detail": "Unknown device(s): ghost"})
    assert agent.calls == []


def test_a_device_without_a_simulated_container_is_rejected(shipped, agent, client, admin_headers):
    del agent.running["sim-sw-ot"]  # e.g. real hardware: in the database, but not a container

    for path, body in [
        ("fail", {"device_ids": ["sw-ot"]}),
        ("degrade", {"device_id": "sw-ot", "delay_ms": 100}),
        ("flap", {"device_id": "sw-ot", "period_s": 10, "duration_s": 20}),
    ]:
        response = post(client, admin_headers, path, body)

        assert response.status_code == 422, path
        assert response.json()["detail"].startswith("No simulated container for: sw-ot"), path
    assert agent.calls == []


def test_only_simulated_containers_are_ever_touched(shipped, agent, client, admin_headers):
    agent.running["backend"] = True  # something else the agent might know about
    del agent.running["sim-scanner-1"]  # a device that is cut off but has no container

    post(client, admin_headers, "fail", {"device_ids": ["sw-ot"]})
    state = client.get("/api/chaos/state", headers=admin_headers).json()

    assert "backend" not in state["controllable_device_ids"]
    assert {name for _, name in agent.calls} == {f"sim-{d}" for d in ["sw-ot", *OT_CHILDREN] if d != "scanner-1"}


# =============================================================================
# POST /api/chaos/degrade
# =============================================================================


def test_degrade_applies_netem_and_shows_up_as_a_fault(shipped, agent, client, admin_headers):
    response = post(
        client, admin_headers, "degrade", {"device_id": "sw-edge", "delay_ms": 200, "jitter_ms": 40, "loss_pct": 2.5}
    )

    assert agent.calls == [("netem", "sim-sw-edge", 200, 40, 2.5)]
    assert response.json()["faults"] == [
        {"device_id": "sw-edge", "kind": "degraded", "detail": "200 ms delay, 40 ms jitter, 2.5% loss"}
    ]


@pytest.mark.parametrize(
    "body",
    [
        {"device_id": "sw-edge"},  # nothing to do
        {"device_id": "sw-edge", "delay_ms": 0, "loss_pct": 0},
        {"device_id": "sw-edge", "delay_ms": 100, "jitter_ms": 200},  # more jitter than delay
        {"device_id": "sw-edge", "delay_ms": -1},
        {"device_id": "sw-edge", "delay_ms": 5001},
        {"device_id": "sw-edge", "loss_pct": 101},
        {"device_id": "sw-edge", "delay_ms": "fast"},
        {"delay_ms": 100},  # no device
    ],
)
def test_degrade_rejects_values_that_make_no_sense(shipped, agent, client, admin_headers, body):
    assert post(client, admin_headers, "degrade", body).status_code == 422
    assert agent.calls == []


def test_a_device_that_is_down_cannot_be_degraded(shipped, agent, client, admin_headers):
    post(client, admin_headers, "fail", {"device_ids": ["sw-ot"]})

    response = post(client, admin_headers, "degrade", {"device_id": "scanner-1", "delay_ms": 100})

    assert (response.status_code, response.json()) == (
        409,
        {"detail": "'scanner-1' is down, so it cannot be degraded"},
    )


def test_stopping_a_degraded_device_ends_its_degradation(shipped, agent, client, admin_headers):
    post(client, admin_headers, "degrade", {"device_id": "scanner-1", "delay_ms": 100})

    response = post(client, admin_headers, "fail", {"device_ids": ["sw-ot"]})

    assert ("scanner-1", "cut_off") in faults(response)
    assert ("scanner-1", "degraded") not in faults(response)
    # And after a restore it is not degraded any more either.
    assert faults(post(client, admin_headers, "restore-all")) == []


# =============================================================================
# POST /api/chaos/flap
# =============================================================================


def test_flap_switches_the_device_off_and_on_and_leaves_it_on(shipped, agent, client, admin_headers):
    response = post(client, admin_headers, "flap", {"device_id": "plc-conveyor-1", "period_s": 80, "duration_s": 160})

    assert response.json()["faults"] == [
        {"device_id": "plc-conveyor-1", "kind": "flapping", "detail": "on right now; switches every 40 s"}
    ]
    assert agent.calls == []  # the work happens in the background task
    (run,) = agent.flaps

    run()  # the whole flap, inline: 160 s / 80 s = 2 cycles

    assert agent.calls == [("stop", "sim-plc-conveyor-1"), ("start", "sim-plc-conveyor-1")] * 2
    assert agent.events[0].waits == [40, 40, 40, 40]  # half a period off, half a period on, twice
    assert agent.stopped() == []
    assert faults(client.get("/api/chaos/state", headers=admin_headers)) == []  # it ended by itself


def test_a_flapping_switch_takes_what_is_behind_it_down_and_up_with_it(shipped, agent, client, admin_headers):
    post(client, admin_headers, "flap", {"device_id": "sw-ot", "period_s": 60, "duration_s": 60})

    agent.flaps[0]()

    everything = ["sw-ot", *OT_CHILDREN]
    assert sorted(agent.calls[: len(everything)]) == sorted(("stop", f"sim-{d}") for d in everything)
    assert sorted(agent.calls[len(everything) :]) == sorted(("start", f"sim-{d}") for d in everything)


def test_a_flap_shows_as_off_while_its_device_is_down(shipped, agent, client, admin_headers, monkeypatch):
    post(client, admin_headers, "flap", {"device_id": "scanner-1", "period_s": 20, "duration_s": 20})
    seen = []

    def look(self, timeout):  # called while the flap "sleeps"
        seen.append(client.get("/api/chaos/state", headers=admin_headers).json()["faults"])
        return False

    monkeypatch.setattr(FakeEvent, "wait", look)
    agent.flaps[0]()

    assert seen == [
        [{"device_id": "scanner-1", "kind": "flapping", "detail": "off right now; switches every 10 s"}],
        [{"device_id": "scanner-1", "kind": "flapping", "detail": "on right now; switches every 10 s"}],
    ]


def test_restore_all_ends_a_flap(shipped, agent, client, admin_headers):
    post(client, admin_headers, "flap", {"device_id": "scanner-1", "period_s": 20, "duration_s": 200})

    assert faults(post(client, admin_headers, "restore-all")) == []
    agent.flaps[0]()  # the background task wakes up afterwards ...

    assert agent.calls == []  # ... and finds it has nothing left to do


def test_a_new_flap_replaces_a_running_one(shipped, agent, client, admin_headers):
    post(client, admin_headers, "flap", {"device_id": "scanner-1", "period_s": 20, "duration_s": 200})
    post(client, admin_headers, "flap", {"device_id": "scanner-1", "period_s": 10, "duration_s": 10})
    old, new = agent.flaps

    assert agent.events[0].is_set() and not agent.events[1].is_set()  # the old one was told to stop
    old()
    assert agent.calls == []  # replaced: it does nothing
    new()
    assert agent.calls == [("stop", "sim-scanner-1"), ("start", "sim-scanner-1")]


def test_failing_a_flapping_device_ends_the_flap_and_keeps_it_down(shipped, agent, client, admin_headers):
    post(client, admin_headers, "flap", {"device_id": "scanner-1", "period_s": 20, "duration_s": 200})

    response = post(client, admin_headers, "fail", {"device_ids": ["scanner-1"]})

    assert chaos_controller._flaps == {}  # the flap is over, not merely overruled
    agent.flaps[0]()
    assert faults(response) == [("scanner-1", "failed")]
    assert agent.stopped() == ["scanner-1"]


def test_a_failed_device_cannot_be_flapped(shipped, agent, client, admin_headers):
    post(client, admin_headers, "fail", {"device_ids": ["scanner-1"]})

    response = post(client, admin_headers, "flap", {"device_id": "scanner-1", "period_s": 20, "duration_s": 20})

    assert response.status_code == 409
    assert agent.flaps == []


def test_a_flap_that_loses_the_agent_ends_without_crashing(shipped, agent, client, admin_headers, monkeypatch, caplog):
    post(client, admin_headers, "flap", {"device_id": "scanner-1", "period_s": 20, "duration_s": 20})

    def gone():
        raise ChaosUnavailable("The chaos agent is not reachable")

    monkeypatch.setattr(chaos_controller, "client_factory", gone)
    agent.flaps[0]()  # must not raise

    assert "flapping scanner-1 ended early" in caplog.text


def test_a_flap_that_could_not_switch_its_device_back_on_tries_once_more_at_the_end(
    shipped, agent, client, admin_headers, monkeypatch, caplog
):
    post(client, admin_headers, "flap", {"device_id": "scanner-1", "period_s": 20, "duration_s": 20})
    start, attempts = agent.start, []

    def start_fails_the_first_time(name):
        attempts.append(name)
        if len(attempts) == 1:
            raise ChaosAgentError(502, "docker start failed")
        start(name)

    monkeypatch.setattr(agent, "start", start_fails_the_first_time)
    agent.flaps[0]()

    assert "flapping scanner-1 ended early: docker start failed" in caplog.text
    assert agent.stopped() == []  # the retry at the end brought it back
    assert faults(client.get("/api/chaos/state", headers=admin_headers)) == []


@pytest.fixture
def real_threads(agent, monkeypatch) -> None:
    """Flaps run the way they do in production: a real thread, a real Event."""
    monkeypatch.setattr(chaos_controller, "spawn", _in_a_thread)
    monkeypatch.setattr(chaos_controller, "new_event", threading.Event)


def wait_for(condition, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def flap_thread(device_id: str) -> threading.Thread | None:
    return next((t for t in threading.enumerate() if t.name == f"chaos-flap-{device_id}"), None)


def test_a_flap_really_runs_in_a_background_thread(shipped, agent, real_threads):
    state = chaos_controller.flap("scanner-1", period_s=0.04, duration_s=0.08, actor="tester")

    assert [fault.kind for fault in state.faults] == ["flapping"]  # returned at once
    assert wait_for(lambda: flap_thread("scanner-1") is None)  # two cycles, then the thread ends
    assert agent.calls == [("stop", "sim-scanner-1"), ("start", "sim-scanner-1")] * 2
    assert chaos_controller.state().faults == []


def test_restore_all_wakes_a_sleeping_flap_thread_and_ends_it(shipped, agent, real_threads):
    chaos_controller.flap("scanner-1", period_s=120, duration_s=600, actor="tester")
    assert wait_for(lambda: agent.stopped() == ["scanner-1"])  # it is in its first "off" half
    thread = flap_thread("scanner-1")

    chaos_controller.restore_all("tester")
    thread.join(timeout=5)  # not after a minute: at once

    assert not thread.is_alive()
    assert agent.stopped() == []
    assert agent.calls == [("stop", "sim-scanner-1"), ("start", "sim-scanner-1")]


@pytest.mark.parametrize(
    "body",
    [
        {"device_id": "scanner-1", "period_s": 1, "duration_s": 20},  # too fast
        {"device_id": "scanner-1", "period_s": 20, "duration_s": 4000},  # too long
        {"device_id": "scanner-1", "period_s": 20},
        {"period_s": 20, "duration_s": 20},
    ],
)
def test_flap_rejects_values_out_of_range(shipped, agent, client, admin_headers, body):
    assert post(client, admin_headers, "flap", body).status_code == 422
    assert agent.flaps == []


# =============================================================================
# POST /api/chaos/scenario/{name}
# =============================================================================


def test_scenario_ot_switch_failure(shipped, agent, client, admin_headers):
    response = post(client, admin_headers, "scenario/ot-switch-failure")

    assert faults(response) == sorted([("sw-ot", "failed"), *[(d, "cut_off") for d in OT_CHILDREN]])


def test_scenario_edge_switch_failure_is_absorbed_by_the_redundancy(shipped, agent, client, admin_headers):
    response = post(client, admin_headers, "scenario/edge-switch-failure")

    assert faults(response) == [("sw-edge", "failed")]
    assert agent.stopped() == ["sw-edge"]


def test_scenario_double_edge_failure(shipped, agent, client, admin_headers):
    response = post(client, admin_headers, "scenario/double-edge-failure")

    assert len(agent.stopped()) == 11  # everything but the firewall
    assert [d for d, kind in faults(response) if kind == "failed"] == ["sw-edge", "sw-edge-2"]


def test_scenario_flapping_plc(shipped, agent, client, admin_headers):
    response = post(client, admin_headers, "scenario/flapping-plc")

    assert faults(response) == [("plc-conveyor-1", "flapping")]
    agent.flaps[0]()
    assert agent.calls == [("stop", "sim-plc-conveyor-1"), ("start", "sim-plc-conveyor-1")] * 5  # 400 s / 80 s


def test_scenario_degraded_uplink(shipped, agent, client, admin_headers):
    response = post(client, admin_headers, "scenario/degraded-uplink")

    assert agent.calls == [("netem", "sim-sw-edge", 200, 40, 2)]
    assert faults(response) == [("sw-edge", "degraded")]


def test_unknown_scenario_is_404(shipped, agent, client, admin_headers):
    response = post(client, admin_headers, "scenario/meteor-strike")

    assert (response.status_code, response.json()) == (404, {"detail": "Unknown scenario 'meteor-strike'"})


def test_every_scenario_is_listed_and_names_devices_that_are_shipped(shipped, agent, client, admin_headers):
    state = client.get("/api/chaos/state", headers=admin_headers).json()

    assert [scenario["name"] for scenario in state["scenarios"]] == [
        "ot-switch-failure",
        "edge-switch-failure",
        "double-edge-failure",
        "flapping-plc",
        "degraded-uplink",
    ]
    assert all(set(scenario) == {"name", "title", "description"} for scenario in state["scenarios"])
    shipped_ids = {device.id for device in shipped_topology()[0]}
    for preset in SCENARIOS.values():
        used = [*preset.fail, *(preset.degrade or ())[:1], *(preset.flap or ())[:1]]
        assert used and set(used) <= shipped_ids, preset.name


# =============================================================================
# POST /api/chaos/restore-all and GET /api/chaos/state
# =============================================================================


def test_state_when_nothing_is_broken(shipped, agent, client, admin_headers):
    state = client.get("/api/chaos/state", headers=admin_headers).json()

    assert set(state) == {"faults", "scenarios", "controllable_device_ids"}
    assert state["faults"] == []
    assert state["controllable_device_ids"] == sorted(device.id for device in shipped_topology()[0])


def test_restore_all_starts_everything_and_removes_every_slowdown(shipped, agent, client, admin_headers):
    post(client, admin_headers, "scenario/double-edge-failure")
    post(client, admin_headers, "degrade", {"device_id": "fw-01", "loss_pct": 10})
    agent.calls.clear()

    response = post(client, admin_headers, "restore-all")

    assert faults(response) == []
    assert agent.stopped() == [] and agent.netem == {}
    assert len(agent.calls) == 12  # eleven starts and one netem removed


def test_restore_all_is_idempotent(shipped, agent, client, admin_headers):
    post(client, admin_headers, "scenario/ot-switch-failure")
    post(client, admin_headers, "restore-all")
    agent.calls.clear()

    for _ in range(2):
        assert faults(post(client, admin_headers, "restore-all")) == []

    assert agent.calls == []  # nothing was broken, so nothing was done


def test_faults_from_before_a_restart_are_reported_as_leftover_and_restored(shipped, agent, client, admin_headers):
    post(client, admin_headers, "scenario/ot-switch-failure")
    post(client, admin_headers, "degrade", {"device_id": "fw-01", "delay_ms": 300})
    chaos_controller.reset()  # the backend restarts: its memory is gone, the faults are not

    state = client.get("/api/chaos/state", headers=admin_headers)

    assert faults(state) == sorted([("fw-01", "leftover"), ("sw-ot", "leftover"), *[(d, "leftover") for d in OT_CHILDREN]])
    details = {f["device_id"]: f["detail"] for f in state.json()["faults"]}
    assert details["sw-ot"] == "stopped, but not by this backend: left over from an earlier run"
    assert details["fw-01"].startswith("slowed down (delay 300ms")
    assert faults(post(client, admin_headers, "restore-all")) == []
    assert agent.stopped() == [] and agent.netem == {}


def test_a_new_failure_does_not_start_devices_left_over_from_before(shipped, agent, client, admin_headers):
    agent.running["sim-srv-prod-1"] = False  # stopped by something else

    post(client, admin_headers, "fail", {"device_ids": ["scanner-1"]})

    assert agent.calls == [("stop", "sim-scanner-1")]
    assert agent.stopped() == ["scanner-1", "srv-prod-1"]


def test_restore_all_carries_on_past_a_device_that_will_not_start(shipped, agent, client, admin_headers):
    post(client, admin_headers, "scenario/ot-switch-failure")
    agent.cannot_start = {"sim-hmi-panel-1"}

    response = post(client, admin_headers, "restore-all")

    assert response.status_code == 502
    assert "sim-hmi-panel-1: docker start failed" in response.json()["detail"]
    assert agent.stopped() == ["hmi-panel-1"]  # everything else is back


def test_startup_reports_faults_that_are_still_in_place(shipped, agent, caplog):
    agent.running["sim-sw-ot"] = False
    agent.netem["sim-fw-01"] = "delay 300ms"

    with caplog.at_level(logging.INFO, logger="app.services.chaos"):
        report_leftover_faults()

    (record,) = caplog.records
    assert record.levelname == "WARNING"
    assert "2 fault(s) are still in place from an earlier run" in record.message
    assert "sw-ot (stopped" in record.message and "fw-01 (slowed down (delay 300ms)" in record.message
    assert "restore-all" in record.message


def test_startup_says_so_when_nothing_is_left_over(shipped, agent, caplog):
    with caplog.at_level(logging.INFO, logger="app.services.chaos"):
        report_leftover_faults()

    assert [(r.levelname, r.message) for r in caplog.records] == [
        ("INFO", "Chaos: the agent is reachable and no faults are in place")
    ]


# =============================================================================
# The agent is not there
# =============================================================================

ENDPOINTS = [
    ("GET", "state", None),
    ("POST", "fail", {"device_ids": ["sw-ot"]}),
    ("POST", "degrade", {"device_id": "sw-ot", "delay_ms": 100}),
    ("POST", "flap", {"device_id": "sw-ot", "period_s": 10, "duration_s": 20}),
    ("POST", "scenario/ot-switch-failure", None),
    ("POST", "restore-all", None),
]
IDS = [f"{method} {path}" for method, path, _ in ENDPOINTS]


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS, ids=IDS)
def test_chaos_is_503_when_it_is_not_configured(shipped, client, admin_headers, method, path, body):
    assert settings.CHAOS_AGENT_URL is None and settings.CHAOS_AGENT_TOKEN is None  # the default

    response = client.request(method, f"/api/chaos/{path}", headers=admin_headers, json=body)

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail.startswith("Fault injection is not enabled on this backend.")
    assert "--profile chaos" in detail and "docs/chaos.md" in detail  # says what to do


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS, ids=IDS)
def test_chaos_is_503_when_the_agent_does_not_answer(shipped, client, admin_headers, monkeypatch, method, path, body):
    monkeypatch.setattr(settings, "CHAOS_AGENT_URL", "http://127.0.0.1:9")  # nothing listens there
    monkeypatch.setattr(settings, "CHAOS_AGENT_TOKEN", "a-shared-secret-for-tests")

    response = client.request(method, f"/api/chaos/{path}", headers=admin_headers, json=body)

    assert response.status_code == 503
    assert response.json()["detail"].startswith("The chaos agent is not reachable")


@pytest.mark.parametrize(
    ("url", "token"),
    [("http://chaos-agent:8081", None), ("http://chaos-agent:8081", ""), (None, "a-shared-secret-for-tests")],
)
def test_chaos_needs_both_the_address_and_the_secret(shipped, client, admin_headers, monkeypatch, url, token):
    monkeypatch.setattr(settings, "CHAOS_AGENT_URL", url)
    monkeypatch.setattr(settings, "CHAOS_AGENT_TOKEN", token)

    response = client.get("/api/chaos/state", headers=admin_headers)

    assert response.status_code == 503
    assert response.json()["detail"].startswith("Fault injection is not enabled on this backend.")


def test_a_request_does_not_queue_forever_behind_a_hanging_one(shipped, agent, client, admin_headers, monkeypatch):
    monkeypatch.setattr("app.services.chaos.BUSY_AFTER_SECONDS", 0.05)
    holding, release = threading.Event(), threading.Event()

    def hang() -> None:  # an earlier request that is stuck talking to the agent
        with chaos_controller._lock:
            holding.set()
            release.wait(5)

    stuck = threading.Thread(target=hang)
    stuck.start()
    try:
        assert holding.wait(5)
        response = client.get("/api/chaos/state", headers=admin_headers)
    finally:
        release.set()
        stuck.join()

    assert response.status_code == 503
    assert response.json()["detail"].startswith("Fault injection is still busy with an earlier request")
    assert client.get("/api/chaos/state", headers=admin_headers).status_code == 200  # and works again afterwards


def test_a_wrong_agent_address_is_reported_not_followed(shipped, client, admin_headers, monkeypatch):
    monkeypatch.setattr(settings, "CHAOS_AGENT_URL", "file:///etc/passwd")
    monkeypatch.setattr(settings, "CHAOS_AGENT_TOKEN", "a-shared-secret-for-tests")

    response = client.get("/api/chaos/state", headers=admin_headers)

    assert (response.status_code, response.json()) == (
        503,
        {"detail": "CHAOS_AGENT_URL must start with http:// or https://"},
    )


def test_startup_does_not_fail_when_the_agent_is_missing(shipped, caplog):
    with caplog.at_level(logging.INFO, logger="app.services.chaos"):
        report_leftover_faults()  # not configured: must not raise

    assert [r.message for r in caplog.records] == [
        "Chaos: the agent is not configured or not running; fault injection is off"
    ]


def test_startup_reports_an_agent_that_answers_with_an_error(shipped, agent, monkeypatch, caplog):
    def refuse():
        raise ChaosAgentError(401, "the backend and the chaos agent do not have the same CHAOS_AGENT_TOKEN")

    monkeypatch.setattr(agent, "containers", refuse)

    report_leftover_faults()  # must not raise

    assert "Chaos: the agent answered with an error: the backend and the chaos agent do not have" in caplog.text


def test_an_error_from_the_agent_is_a_502_with_its_message(shipped, agent, client, admin_headers, monkeypatch):
    def refuse(name):
        raise ChaosAgentError(502, "docker stop failed: permission denied")

    monkeypatch.setattr(agent, "stop", refuse)

    response = post(client, admin_headers, "fail", {"device_ids": ["scanner-1"]})

    assert (response.status_code, response.json()) == (
        502,
        {"detail": "The chaos agent could not do that: docker stop failed: permission denied"},
    )


# =============================================================================
# Admin only, and logged
# =============================================================================


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS, ids=IDS)
def test_chaos_is_admin_only(shipped, agent, client, viewer_headers, method, path, body):
    response = client.request(method, f"/api/chaos/{path}", headers=viewer_headers, json=body)

    assert (response.status_code, response.json()) == (403, {"detail": "Insufficient permissions"})
    assert agent.calls == [] and agent.flaps == []


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS, ids=IDS)
def test_chaos_needs_a_token(client, method, path, body):
    assert client.request(method, f"/api/chaos/{path}", json=body).status_code == 401


def audited() -> list[tuple]:
    """(actor, action, target, details) of the chaos events in the audit log."""
    events = stored(AuditEvent.__table__, "actor", "action", "target", "details")
    return [event for event in events if event[1].startswith("chaos.")]


def test_every_action_is_written_to_the_audit_log(shipped, agent, client, admin_headers):
    post(client, admin_headers, "fail", {"device_ids": ["sw-ot", "srv-prod-2"]})
    post(client, admin_headers, "degrade", {"device_id": "fw-01", "delay_ms": 100, "jitter_ms": 10, "loss_pct": 1})
    post(client, admin_headers, "flap", {"device_id": "srv-prod-1", "period_s": 20, "duration_s": 40})
    post(client, admin_headers, "scenario/edge-switch-failure")
    post(client, admin_headers, "restore-all")

    assert audited() == [
        ("admin", "chaos.fail", "sw-ot, srv-prod-2", {}),
        ("admin", "chaos.degrade", "fw-01", {"delay_ms": 100, "jitter_ms": 10, "loss_pct": 1.0}),
        ("admin", "chaos.flap", "srv-prod-1", {"period_s": 20.0, "duration_s": 40.0}),
        ("admin", "chaos.scenario", "edge-switch-failure", {}),
        ("admin", "chaos.restore_all", None, {}),
    ]


def test_looking_at_the_state_is_not_audited(shipped, agent, client, admin_headers):
    assert client.get("/api/chaos/state", headers=admin_headers).status_code == 200

    assert audited() == []


def test_an_action_that_did_not_go_through_is_not_audited(shipped, agent, client, admin_headers, viewer_headers, monkeypatch):
    assert post(client, viewer_headers, "fail", {"device_ids": ["sw-ot"]}).status_code == 403
    assert post(client, admin_headers, "fail", {"device_ids": ["no-such-device"]}).status_code == 422
    assert post(client, admin_headers, "scenario/no-such-scenario").status_code == 404
    post(client, admin_headers, "fail", {"device_ids": ["scanner-1"]})
    assert post(client, admin_headers, "flap", {"device_id": "scanner-1", "period_s": 10, "duration_s": 20}).status_code == 409

    def refuse(name):
        raise ChaosAgentError(502, "docker stop failed: permission denied")

    monkeypatch.setattr(agent, "stop", refuse)
    assert post(client, admin_headers, "fail", {"device_ids": ["sw-ot"]}).status_code == 502

    assert audited() == [("admin", "chaos.fail", "scanner-1", {})]


def test_an_action_is_not_audited_when_fault_injection_is_off(shipped, client, admin_headers):
    assert post(client, admin_headers, "restore-all").status_code == 503

    assert audited() == []


def test_every_action_is_logged_with_who_did_it(shipped, agent, client, admin_headers, caplog):
    with caplog.at_level(logging.INFO, logger="app.services.chaos"):
        post(client, admin_headers, "fail", {"device_ids": ["sw-ot"]})
        post(client, admin_headers, "degrade", {"device_id": "fw-01", "delay_ms": 100, "jitter_ms": 10, "loss_pct": 1})
        post(client, admin_headers, "flap", {"device_id": "srv-prod-1", "period_s": 20, "duration_s": 20})
        post(client, admin_headers, "scenario/edge-switch-failure")
        post(client, admin_headers, "restore-all")

    log = "\n".join(record.message for record in caplog.records)
    assert "Chaos: admin failed ['sw-ot']; containers stopped: ['ap-aisle-1'" in log
    assert "Chaos: admin degraded fw-01: 100 ms delay, 10 ms jitter, 1% loss" in log
    assert "Chaos: admin started flapping srv-prod-1: 1 cycles of 20 s" in log
    assert "Chaos: admin started scenario edge-switch-failure" in log
    assert "Chaos: admin restored all; started [" in log
