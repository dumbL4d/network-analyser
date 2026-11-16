"""Topology-aware fault injection for the simulated network.

All simulated devices sit on one Docker bridge, so stopping the container of a
switch does NOT make the devices behind it unreachable: each container still
answers ping by itself. To make a failure look real, this module works out
what the failure would cut off, with the graph engine, and makes those devices
unreachable as well.

    desired = failed devices + cut_off(topology, failed devices)

``plan_failure`` computes that set and is pure. ``ChaosController`` keeps the
containers in line with it: it stops what should be down and starts again what
it had stopped and should be up. The actual stopping, starting and slowing
down is done by the chaos agent (app/services/chaos_client.py). The controller
only decides.

The controller's memory (which devices were failed, which are flapping) lives
in this process. What is REALLY broken is always read back from the agent, so
after a backend restart the faults still in place are found and reported as
"leftover", and ``restore_all`` removes them whoever caused them.
"""

import logging
import threading
from collections.abc import Callable, Collection, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlmodel import Session, select

from app.db.session import engine
from app.models.device import Device
from app.models.device_link import DeviceLink
from app.schemas.chaos import ChaosFaultOut, ChaosScenarioOut, ChaosStateOut
from app.services.chaos_client import (
    ChaosAgentError,
    ChaosClient,
    ChaosUnavailable,
    SimContainer,
    configured_client,
)
from app.services.device_links import device_graph
from app.services.topology_graph import cut_off

logger = logging.getLogger(__name__)

# The container of device "sw-ot" is the Compose service "sim-sw-ot".
SIM_PREFIX = "sim-"
# How long a request waits for an earlier chaos request to finish. If the
# agent hangs, requests then fail fast instead of queueing up behind it.
BUSY_AFTER_SECONDS = 20.0


class ChaosError(ValueError):
    """A request that cannot be carried out; the message says why."""


class ChaosConflict(ChaosError):
    """A request that clashes with a fault already in place."""


# --- planning (pure) -------------------------------------------------------------


def plan_failure(
    devices: Collection[Device], links: Collection[DeviceLink], failed: Collection[str]
) -> set[str]:
    """Every device that must become unreachable when ``failed`` fail.

    That is the failed devices themselves plus everything they cut off: the
    devices that would lose every path to a root. Pure.

    Time O((V + E) * alpha(V)), space O(V + E) (see topology_graph.cut_off).
    """
    return set(failed) | cut_off(device_graph(devices, links), failed)


# --- presets -----------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    name: str
    title: str
    description: str
    fail: tuple[str, ...] = ()
    degrade: tuple[str, int, int, float] | None = None  # device, delay ms, jitter ms, loss %
    flap: tuple[str, float, float] | None = None  # device, period s, duration s


SCENARIOS: dict[str, Scenario] = {
    scenario.name: scenario
    for scenario in (
        Scenario(
            "ot-switch-failure",
            "OT switch failure",
            "sw-ot fails. Its five devices have no other way up, so they are cut off too: "
            "one root cause and five collateral devices.",
            fail=("sw-ot",),
        ),
        Scenario(
            "edge-switch-failure",
            "Edge switch failure",
            "sw-edge fails. Both tier switches still reach the firewall through sw-edge-2, "
            "so nothing else goes down: the redundancy absorbs it.",
            fail=("sw-edge",),
        ),
        Scenario(
            "double-edge-failure",
            "Both edge switches fail",
            "sw-edge and sw-edge-2 fail together. Nothing leads to the tier switches any "
            "more: nine devices are cut off.",
            fail=("sw-edge", "sw-edge-2"),
        ),
        Scenario(
            "flapping-plc",
            "Flapping PLC",
            "plc-conveyor-1 goes down and comes back every 80 seconds, for about 7 minutes. "
            "It climbs the flap ranking on the Stability page.",
            flap=("plc-conveyor-1", 80, 400),
        ),
        Scenario(
            "degraded-uplink",
            "Degraded uplink",
            "sw-edge answers slowly: 200 ms delay, 40 ms jitter and 2% packet loss. "
            "It turns degraded without going down.",
            degrade=("sw-edge", 200, 40, 2),
        ),
    )
}


# --- the controller ------------------------------------------------------------------


@dataclass
class _Flap:
    period_s: float
    cycles: int
    cancelled: threading.Event  # set to end the flap early; its wait() is the flap's sleep


def _stored_topology() -> tuple[list[Device], list[DeviceLink]]:
    with Session(engine) as session:
        return list(session.exec(select(Device)).all()), list(session.exec(select(DeviceLink)).all())


def _in_a_thread(run: Callable[[], None], name: str) -> None:
    threading.Thread(target=run, daemon=True, name=name).start()


class ChaosController:
    """Decides which simulated devices are down, and tells the agent.

    Every public method takes the lock, so requests and flap threads never
    change the state at the same time. A request waits a limited time for it
    (``_exclusive``) and then gives up with ``ChaosUnavailable``.
    """

    def __init__(
        self,
        client_factory: Callable[[], ChaosClient] = configured_client,
        load_topology: Callable[[], tuple[list[Device], list[DeviceLink]]] = _stored_topology,
        spawn: Callable[[Callable[[], None], str], None] = _in_a_thread,
    ) -> None:
        self.client_factory = client_factory
        self.load_topology = load_topology
        self.spawn = spawn
        self.new_event: Callable[[], threading.Event] = threading.Event
        self._lock = threading.RLock()
        self._flaps: dict[str, _Flap] = {}
        self.reset()

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        """Hold the lock for one request, or give up if it stays taken."""
        if not self._lock.acquire(timeout=BUSY_AFTER_SECONDS):
            raise ChaosUnavailable(
                "Fault injection is still busy with an earlier request (is the chaos agent hanging?). "
                "Try again in a moment."
            )
        try:
            yield
        finally:
            self._lock.release()

    def reset(self) -> None:
        """Forget everything and end the flap threads. Does not talk to the
        agent: use ``restore_all`` to put the devices back."""
        with self._lock:
            for flap in self._flaps.values():
                flap.cancelled.set()
            self._failed: set[str] = set()  # devices an admin failed
            self._flap_down: set[str] = set()  # flapping devices that are "down" right now
            self._down: set[str] = set()  # devices whose container THIS controller stopped
            self._degraded: dict[str, tuple[int, int, float]] = {}
            self._flaps = {}

    # --- actions -------------------------------------------------------------------

    def fail(self, device_ids: Collection[str], actor: str) -> ChaosStateOut:
        """Fail these devices, and make everything they cut off unreachable."""
        with self._exclusive():
            client = self.client_factory()
            wanted = set(device_ids)
            sims = self._check(client, wanted)
            for device_id in wanted:
                self._cancel_flap(device_id)
            self._failed |= wanted
            stopped, _ = self._reconcile(client, sims)
            logger.info("Chaos: %s failed %s; containers stopped: %s", actor, sorted(wanted), stopped)
            return self._state(client)

    def degrade(
        self, device_id: str, delay_ms: int, jitter_ms: int, loss_pct: float, actor: str
    ) -> ChaosStateOut:
        """Slow a device down: delay, jitter and packet loss on its replies."""
        with self._exclusive():
            client = self.client_factory()
            sims = self._check(client, {device_id})
            if not sims[device_id].running:
                raise ChaosConflict(f"'{device_id}' is down, so it cannot be degraded")
            client.set_netem(SIM_PREFIX + device_id, delay_ms, jitter_ms, loss_pct)
            self._degraded[device_id] = (delay_ms, jitter_ms, loss_pct)
            logger.info(
                "Chaos: %s degraded %s: %d ms delay, %d ms jitter, %g%% loss",
                actor, device_id, delay_ms, jitter_ms, loss_pct,
            )  # fmt: skip
            return self._state(client)

    def flap(self, device_id: str, period_s: float, duration_s: float, actor: str) -> ChaosStateOut:
        """Switch a device off and on again, ``period_s`` per full cycle, for
        about ``duration_s``. Runs in a background thread; a newer flap of the
        same device replaces a running one."""
        with self._exclusive():
            client = self.client_factory()
            self._check(client, {device_id})
            if device_id in self._failed:
                raise ChaosConflict(f"'{device_id}' has been failed; restore it before flapping it")
            self._cancel_flap(device_id)
            flap = _Flap(period_s, max(1, round(duration_s / period_s)), self.new_event())
            self._flaps[device_id] = flap
            logger.info(
                "Chaos: %s started flapping %s: %d cycles of %g s", actor, device_id, flap.cycles, period_s
            )
            state = self._state(client)
        self.spawn(lambda: self._run_flap(device_id, flap), f"chaos-flap-{device_id}")
        return state

    def scenario(self, name: str, actor: str) -> ChaosStateOut:
        """Run a preset (see SCENARIOS). Raises KeyError for an unknown name."""
        preset = SCENARIOS[name]
        logger.info("Chaos: %s started scenario %s", actor, name)
        with self._exclusive():
            if preset.fail:
                state = self.fail(preset.fail, actor)
            if preset.degrade is not None:
                state = self.degrade(*preset.degrade, actor)
            if preset.flap is not None:
                state = self.flap(*preset.flap, actor)
            return state

    def restore_all(self, actor: str) -> ChaosStateOut:
        """Put every simulated device back: started, and not slowed down.

        Works from what the agent reports, not from this controller's memory,
        so it also removes faults left over from an earlier run. Safe to call
        again: when nothing is broken it does nothing.
        """
        with self._exclusive():
            client = self.client_factory()
            self.reset()
            started, cleared, problems = [], [], []
            for container in client.containers():
                try:
                    if container.netem is not None:
                        client.clear_netem(container.name)
                        cleared.append(container.name)
                    if not container.running:
                        client.start(container.name)
                        started.append(container.name)
                except ChaosAgentError as error:
                    problems.append(f"{container.name}: {error}")
            logger.info("Chaos: %s restored all; started %s, netem cleared on %s", actor, started, cleared)
            if problems:
                raise ChaosAgentError(502, "not everything could be restored: " + "; ".join(problems))
            return self._state(client)

    def state(self) -> ChaosStateOut:
        """The faults in place right now, as the agent reports them."""
        with self._exclusive():
            return self._state(self.client_factory())

    # --- internals -----------------------------------------------------------------

    @staticmethod
    def _sims(client: ChaosClient) -> dict[str, SimContainer]:
        """The simulated devices by device id."""
        return {
            container.name.removeprefix(SIM_PREFIX): container
            for container in client.containers()
            if container.name.startswith(SIM_PREFIX)
        }

    def _check(self, client: ChaosClient, device_ids: set[str]) -> dict[str, SimContainer]:
        """Every id must be a device AND have a simulated container. Returns
        the simulated devices."""
        devices, _ = self.load_topology()
        unknown = sorted(device_ids - {device.id for device in devices})
        if unknown:
            raise ChaosError("Unknown device(s): " + ", ".join(unknown))
        sims = self._sims(client)
        missing = sorted(device_ids - sims.keys())
        if missing:
            raise ChaosError(
                "No simulated container for: " + ", ".join(missing)
                + ". Faults can only be injected into the simulated devices."
            )  # fmt: skip
        return sims

    def _reconcile(
        self, client: ChaosClient, sims: dict[str, SimContainer] | None = None
    ) -> tuple[list[str], list[str]]:
        """Bring the containers in line with the plan. Returns the devices
        that were stopped and the ones that were started.

        Only devices this controller stopped are ever started here, so a
        device stopped by something else is left alone. ``sims`` saves asking
        the agent again when the caller has just done so.
        """
        devices, links = self.load_topology()
        if sims is None:
            sims = self._sims(client)
        desired = plan_failure(devices, links, self._failed | self._flap_down) & sims.keys()
        stopped = sorted(desired - self._down)
        for device_id in stopped:
            client.stop(SIM_PREFIX + device_id)
            self._down.add(device_id)
        started = sorted(self._down - desired)
        for device_id in started:
            client.start(SIM_PREFIX + device_id)
            self._down.discard(device_id)
        return stopped, started

    def _cancel_flap(self, device_id: str) -> None:
        flap = self._flaps.pop(device_id, None)
        if flap is not None:
            flap.cancelled.set()
        self._flap_down.discard(device_id)

    def _run_flap(self, device_id: str, flap: _Flap) -> None:
        """The body of a flap thread: down for half a period, up for the
        other half, ``flap.cycles`` times, unless cancelled first."""
        try:
            for _ in range(flap.cycles):
                for down in (True, False):
                    if not self._flap_phase(device_id, flap, down):
                        return
                    if flap.cancelled.wait(flap.period_s / 2):
                        return
        except (ChaosUnavailable, ChaosAgentError) as error:
            logger.warning("Chaos: flapping %s ended early: %s", device_id, error)
        finally:
            self._end_flap(device_id, flap)

    def _flap_phase(self, device_id: str, flap: _Flap, down: bool) -> bool:
        """Switch a flapping device down or up. False if this flap is over."""
        with self._lock:
            if self._flaps.get(device_id) is not flap:
                return False
            if down:
                self._flap_down.add(device_id)
            else:
                self._flap_down.discard(device_id)
            self._reconcile(self.client_factory())
            logger.info("Chaos: flap switched %s %s", device_id, "off" if down else "on")
            return True

    def _end_flap(self, device_id: str, flap: _Flap) -> None:
        """A flap that ran to its end leaves its device up."""
        with self._lock:
            if self._flaps.get(device_id) is not flap:
                return  # cancelled or replaced: whoever did that took care of it
            del self._flaps[device_id]
            self._flap_down.discard(device_id)
            try:
                self._reconcile(self.client_factory())
            except (ChaosUnavailable, ChaosAgentError) as error:
                logger.warning("Chaos: could not bring %s back after flapping: %s", device_id, error)

    def _state(self, client: ChaosClient) -> ChaosStateOut:
        faults: list[ChaosFaultOut] = []

        def fault(device_id: str, kind: str, detail: str) -> None:
            faults.append(ChaosFaultOut(device_id=device_id, kind=kind, detail=detail))

        sims = self._sims(client)
        for device_id, container in sorted(sims.items()):
            flap = self._flaps.get(device_id)
            if not container.running:
                if device_id in self._failed:
                    fault(device_id, "failed", "stopped on request")
                elif device_id in self._flap_down:
                    fault(device_id, "flapping", f"off right now; switches every {flap.period_s / 2:g} s")
                elif device_id in self._down:
                    fault(device_id, "cut_off", "stopped because nothing leads to it any more")
                else:
                    fault(device_id, "leftover", "stopped, but not by this backend: left over from an earlier run")
                continue
            if flap is not None:
                fault(device_id, "flapping", f"on right now; switches every {flap.period_s / 2:g} s")
            if container.netem is not None:
                if device_id in self._degraded:
                    delay_ms, jitter_ms, loss_pct = self._degraded[device_id]
                    fault(device_id, "degraded", f"{delay_ms} ms delay, {jitter_ms} ms jitter, {loss_pct:g}% loss")
                else:
                    fault(
                        device_id,
                        "leftover",
                        f"slowed down ({container.netem}), but not by this backend: left over from an earlier run",
                    )
        return ChaosStateOut(
            faults=faults,
            scenarios=[
                ChaosScenarioOut(name=preset.name, title=preset.title, description=preset.description)
                for preset in SCENARIOS.values()
            ],
            controllable_device_ids=sorted(sims),
        )


chaos_controller = ChaosController()


def report_leftover_faults() -> None:
    """Run once at startup: say in the log whether faults are still in place
    from before the backend (re)started. Never raises."""
    try:
        faults = chaos_controller.state().faults
    except ChaosUnavailable:
        logger.info("Chaos: the agent is not configured or not running; fault injection is off")
    except ChaosAgentError as error:
        logger.warning("Chaos: the agent answered with an error: %s", error)
    else:
        if faults:
            logger.warning(
                "Chaos: %d fault(s) are still in place from an earlier run: %s. "
                "POST /api/chaos/restore-all removes them.",
                len(faults),
                ", ".join(f"{fault.device_id} ({fault.detail})" for fault in faults),
            )
        else:
            logger.info("Chaos: the agent is reachable and no faults are in place")
