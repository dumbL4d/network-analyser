"""Chaos agent: a thin executor for fault injection on the simulated devices.

It can do five things, and only to containers that carry the Docker label
``netanalyser.sim=true``:

    GET    /containers                 list them: run state and active netem
    POST   /containers/{name}/stop     stop one
    POST   /containers/{name}/start    start one
    PUT    /containers/{name}/netem    add delay / jitter / loss (tc netem)
    DELETE /containers/{name}/netem    remove it again

``{name}`` is the container's Compose service name, for example ``sim-sw-ot``.

WHICH devices to break is decided by the backend, which knows the topology.
This service knows nothing about it: it only carries out single steps.

SECURITY. The agent talks to the Docker daemon through the Docker socket, and
whoever controls that socket controls the host. So it is kept small and strict:

* Every request must carry the shared secret in ``X-Chaos-Token``. The agent
  refuses to start without a secret of at least 16 characters.
* A target is looked up, on every request, in the list of containers Docker
  itself reports for the label (and, under Compose, for the agent's own
  project). Only the container id from that list is ever passed to Docker,
  never a value taken from the request. A name that is not in the list is
  rejected, so the label is the allow-list.
* No shell is involved: every command is an argument list, and every number
  is range-checked and formatted here.
* It is not published to the host and sits on an internal network that only
  the backend shares (see infra/docker-compose.yml and docs/chaos.md).

Python standard library only, plus the ``docker`` command-line client.
"""

import hmac
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SIM_LABEL = "netanalyser.sim=true"
SERVICE_LABEL = "com.docker.compose.service"
PROJECT_LABEL = "com.docker.compose.project"
# What a Compose service name can look like. Checked before the allow-list.
NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,62}")
INTERFACE = "eth0"  # a simulated device has one network interface
MIN_TOKEN_LENGTH = 16
MAX_BODY_BYTES = 4096
MAX_DELAY_MS = 10_000
PORT = 8081

# Runs the docker CLI with the given arguments: (exit code, combined output).
Run = Callable[[list[str]], tuple[int, str]]


def docker_cli(arguments: list[str]) -> tuple[int, str]:
    """Run ``docker <arguments>``. Never through a shell."""
    try:
        done = subprocess.run(
            ["docker", *arguments], capture_output=True, text=True, timeout=30, check=False
        )
    except subprocess.TimeoutExpired:
        return 124, "the docker command timed out"
    except OSError as error:  # the docker binary is missing
        return 127, str(error)
    return done.returncode, (done.stdout + done.stderr).strip()


class Refused(Exception):
    """A request the agent will not carry out: HTTP status and reason."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


class Agent:
    """The request logic, separate from the HTTP server so it can be tested
    with a fake ``run`` instead of a Docker daemon."""

    def __init__(self, token: str, run: Run = docker_cli, project: str = "") -> None:
        if len(token) < MIN_TOKEN_LENGTH:
            raise ValueError(f"the shared secret must have at least {MIN_TOKEN_LENGTH} characters")
        if project and not NAME.fullmatch(project):
            raise ValueError("the Compose project name has characters that are not allowed")
        self._token = token
        self._run = run
        # When set, only this Compose project's containers count: the same
        # stack started under another project name is left alone.
        self._project = project

    # --- the one entry point ---------------------------------------------------

    def handle(self, method: str, path: str, token: str | None, body: bytes) -> tuple[int, dict]:
        """Carry out one request. Returns (HTTP status, JSON body)."""
        try:
            if token is None or not hmac.compare_digest(token.encode(), self._token.encode()):
                raise Refused(401, "missing or wrong X-Chaos-Token")
            return 200, self._route(method, path.split("?")[0], body)
        except Refused as refused:
            return refused.status, {"detail": refused.reason}

    def _route(self, method: str, path: str, body: bytes) -> dict:
        parts = path.strip("/").split("/")
        if parts == ["containers"] and method == "GET":
            return {"containers": self._list()}
        if len(parts) == 3 and parts[0] == "containers":
            name, action = parts[1], parts[2]
            if (method, action) == ("POST", "stop"):
                return self._stop(name)
            if (method, action) == ("POST", "start"):
                return self._start(name)
            if (method, action) == ("PUT", "netem"):
                return self._set_netem(name, body)
            if (method, action) == ("DELETE", "netem"):
                return self._clear_netem(name)
        raise Refused(404, "no such endpoint")

    # --- the allow-list --------------------------------------------------------

    def _docker(self, arguments: list[str]) -> str:
        """Run a docker command that is expected to succeed."""
        code, output = self._run(arguments)
        if code != 0:
            raise Refused(502, f"docker {arguments[0]} failed: {output[:300]}")
        return output

    def _sims(self) -> dict[str, tuple[str, bool]]:
        """The simulated devices: service name -> (container id, is it running).

        Asked from Docker on every request, so the answer is never stale.
        """
        project = ["--filter", f"label={PROJECT_LABEL}={self._project}"] if self._project else []
        output = self._docker(
            [
                "ps",
                "--all",
                "--filter",
                f"label={SIM_LABEL}",
                *project,
                "--format",
                '{{.ID}}\t{{.State}}\t{{.Label "' + SERVICE_LABEL + '"}}',
            ]
        )
        sims: dict[str, tuple[str, bool]] = {}
        for line in output.splitlines():
            fields = line.split("\t")
            if len(fields) == 3 and NAME.fullmatch(fields[2]):
                sims[fields[2]] = (fields[0], fields[1] == "running")
        return sims

    def _target(self, name: str) -> tuple[str, bool]:
        """(container id, running) of an allowed target, or refuse."""
        if not NAME.fullmatch(name):
            raise Refused(400, "invalid container name")
        sims = self._sims()
        if name not in sims:
            raise Refused(404, f"'{name}' is not a simulated device (label {SIM_LABEL})")
        return sims[name]

    # --- the five actions ------------------------------------------------------

    def _netem_of(self, container_id: str) -> str | None:
        """The netem settings on a running container, or None."""
        code, output = self._run(["exec", container_id, "tc", "qdisc", "show", "dev", INTERFACE])
        if code != 0:
            return None  # tc is missing or the container just stopped: nothing to report
        match = re.search(r"qdisc netem \S+ root(?: refcnt \d+)?(?: limit \d+)?(.*)", output)
        if match is None:
            return None
        # Newer tc versions append the random seed they picked: not a setting.
        settings = re.sub(r"\bseed \d+", "", match.group(1))
        return " ".join(settings.split()) or "active"

    def _list(self) -> list[dict]:
        return [
            {"name": name, "running": running, "netem": self._netem_of(container_id) if running else None}
            for name, (container_id, running) in sorted(self._sims().items())
        ]

    def _stop(self, name: str) -> dict:
        container_id, _ = self._target(name)
        # -t 0: the stub has nothing to shut down. "docker stop" (not "kill")
        # also tells the restart policy that this stop is intended.
        self._docker(["stop", "--time", "0", container_id])
        return {"name": name, "running": False}

    def _start(self, name: str) -> dict:
        container_id, _ = self._target(name)
        self._docker(["start", container_id])
        return {"name": name, "running": True}

    def _set_netem(self, name: str, body: bytes) -> dict:
        try:
            wanted = json.loads(body or b"{}")
        except ValueError:
            raise Refused(400, "the body must be JSON") from None
        if not isinstance(wanted, dict):
            raise Refused(400, "the body must be a JSON object")
        delay = self._number(wanted, "delay_ms", MAX_DELAY_MS, whole=True)
        jitter = self._number(wanted, "jitter_ms", MAX_DELAY_MS, whole=True)
        loss = self._number(wanted, "loss_pct", 100, whole=False)
        if jitter > delay:
            raise Refused(400, "jitter_ms cannot be larger than delay_ms")
        if delay == 0 and loss == 0:
            raise Refused(400, "give a delay_ms or a loss_pct above 0")

        container_id, running = self._target(name)
        if not running:
            raise Refused(409, f"'{name}' is not running")
        settings: list[str] = []
        if delay:
            settings += ["delay", f"{delay}ms"] + ([f"{jitter}ms"] if jitter else [])
        if loss:
            settings += ["loss", f"{loss:g}%"]
        self._docker(
            ["exec", container_id, "tc", "qdisc", "replace", "dev", INTERFACE, "root", "netem", *settings]
        )
        return {"name": name, "netem": " ".join(settings)}

    @staticmethod
    def _number(wanted: dict, key: str, maximum: float, whole: bool) -> float:
        value = wanted.get(key, 0)
        allowed = (int,) if whole else (int, float)
        # bool is an int in Python; it is not a number here.
        if isinstance(value, bool) or not isinstance(value, allowed) or not 0 <= value <= maximum:
            kind = "a whole number" if whole else "a number"
            raise Refused(400, f"{key} must be {kind} from 0 to {maximum:g}")
        return value

    def _clear_netem(self, name: str) -> dict:
        container_id, running = self._target(name)
        # A stopped container has no netem (it gets a new network namespace
        # when it starts), and there is nothing to delete where none is set.
        if running and self._netem_of(container_id) is not None:
            self._docker(["exec", container_id, "tc", "qdisc", "del", "dev", INTERFACE, "root"])
        return {"name": name, "netem": None}


class Handler(BaseHTTPRequestHandler):
    """Turns HTTP into ``Agent.handle`` calls. Nothing else."""

    agent: Agent
    timeout = 15  # seconds a client may take to send its request

    def _respond(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY_BYTES:
            status, payload = 413, {"detail": "request body missing a valid length, or too large"}
        else:
            status, payload = self.agent.handle(
                self.command, self.path, self.headers.get("X-Chaos-Token"), self.rfile.read(length)
            )
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_DELETE = _respond

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 (the base class's name)
        # One line per request on stderr: an audit trail. The secret is in a
        # header, which is never logged.
        sys.stderr.write(f"chaos-agent {self.address_string()} {format % args}\n")


def main() -> None:
    token = os.environ.get("CHAOS_AGENT_TOKEN", "")
    try:
        Handler.agent = Agent(token, project=os.environ.get("CHAOS_AGENT_PROJECT", ""))
    except ValueError as error:
        sys.exit(f"chaos-agent: cannot start: {error}. Generate a secret with: openssl rand -hex 32")
    print(f"chaos-agent: listening on port {PORT}", file=sys.stderr, flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
