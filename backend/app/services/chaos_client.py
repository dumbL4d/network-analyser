"""HTTP client for the chaos agent (infra/chaos-agent/agent.py).

The agent is the only thing that can touch the simulated devices' containers.
This client is the backend's side of that conversation: five calls, one per
primitive the agent offers. What to break and when is decided in
app/services/chaos.py; nothing here knows the topology.

Standard library only (urllib), so the backend gains no dependency.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import quote

from app.core.config import settings

HOW_TO_ENABLE = (
    "Set CHAOS_AGENT_TOKEN in infra/.env and start the stack with "
    "'docker compose -f infra/docker-compose.yml --profile chaos up -d' "
    "(see docs/chaos.md)."
)


class ChaosUnavailable(Exception):
    """Fault injection cannot be used right now: it is not configured, or the
    agent does not answer. The message says what to do."""


class ChaosAgentError(Exception):
    """The agent answered, but refused or failed the request."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class SimContainer:
    """One simulated device as the agent sees it."""

    name: str  # the Compose service name, e.g. "sim-sw-ot"
    running: bool
    netem: str | None  # the delay/loss settings in force, if any


class ChaosClient:
    def __init__(self, base_url: str, token: str, timeout: float = 15.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        # No proxy, whatever the environment says: this is a call to a
        # neighbouring container and must not be sent anywhere else.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def containers(self) -> list[SimContainer]:
        """Every simulated device, with its run state and netem settings."""
        return [
            SimContainer(item["name"], item["running"], item["netem"])
            for item in self._call("GET", "/containers")["containers"]
        ]

    def stop(self, name: str) -> None:
        self._call("POST", f"/containers/{quote(name, safe='')}/stop")

    def start(self, name: str) -> None:
        self._call("POST", f"/containers/{quote(name, safe='')}/start")

    def set_netem(self, name: str, delay_ms: int, jitter_ms: int, loss_pct: float) -> None:
        self._call(
            "PUT",
            f"/containers/{quote(name, safe='')}/netem",
            {"delay_ms": delay_ms, "jitter_ms": jitter_ms, "loss_pct": loss_pct},
        )

    def clear_netem(self, name: str) -> None:
        self._call("DELETE", f"/containers/{quote(name, safe='')}/netem")

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        request = urllib.request.Request(
            self._base_url + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"X-Chaos-Token": self._token, "Content-Type": "application/json"},
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read())["detail"]
            except (ValueError, KeyError, TypeError):
                detail = error.reason
            if error.code == 401:
                detail = "the backend and the chaos agent do not have the same CHAOS_AGENT_TOKEN"
            raise ChaosAgentError(error.code, str(detail)) from None
        except (urllib.error.URLError, OSError, ValueError) as error:
            # Refused, unknown host, timed out, or not an agent at all.
            raise ChaosUnavailable(
                f"The chaos agent is not reachable ({getattr(error, 'reason', error)}). {HOW_TO_ENABLE}"
            ) from None


def configured_client() -> ChaosClient:
    """The client for the agent named in the settings, or ``ChaosUnavailable``."""
    url, token = settings.CHAOS_AGENT_URL, settings.CHAOS_AGENT_TOKEN
    if not url or not token:
        raise ChaosUnavailable(f"Fault injection is not enabled on this backend. {HOW_TO_ENABLE}")
    if not url.startswith(("http://", "https://")):
        raise ChaosUnavailable("CHAOS_AGENT_URL must start with http:// or https://")
    return ChaosClient(url, token)
