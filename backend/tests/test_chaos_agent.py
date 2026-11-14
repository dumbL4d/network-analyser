"""The chaos agent (infra/chaos-agent/agent.py) and the backend's client for it.

The agent is the one component that can reach the Docker socket, so its
checks are tested directly: the shared secret, the allow-list, the input
validation, and exactly which ``docker`` commands it runs.

No Docker is needed. ``FakeDocker`` stands in for the docker command line: it
answers the handful of commands the agent uses and records every one of them.
The last section starts the agent's real HTTP server on a loopback port and
talks to it with the backend's ``ChaosClient``.
"""

import importlib.util
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from app.services.chaos_client import ChaosAgentError, ChaosClient, ChaosUnavailable, SimContainer

AGENT_FILE = Path(__file__).resolve().parents[2] / "infra" / "chaos-agent" / "agent.py"
_spec = importlib.util.spec_from_file_location("chaos_agent", AGENT_FILE)
agent_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agent_module)

TOKEN = "a-shared-secret-for-tests"
NO_QDISC = "qdisc noqueue 0: root refcnt 2"


class FakeDocker:
    """The docker CLI, reduced to what the agent calls."""

    def __init__(self) -> None:
        # service name -> container. Only the first three carry the sim label.
        self.containers = {
            "sim-sw-ot": {"id": "aaa111", "running": True, "sim": True, "netem": None},
            "sim-scanner-1": {"id": "bbb222", "running": True, "sim": True, "netem": None},
            "sim-fw-01": {"id": "ccc333", "running": False, "sim": True, "netem": None},
            "backend": {"id": "ddd444", "running": True, "sim": False, "netem": None},
        }
        self.commands: list[list[str]] = []
        self.fail_on: str | None = None  # a docker subcommand that should fail

    def _by_id(self, container_id: str) -> dict:
        return next(c for c in self.containers.values() if c["id"] == container_id)

    def __call__(self, arguments: list[str]) -> tuple[int, str]:
        self.commands.append(arguments)
        if arguments[0] == self.fail_on:
            return 1, "Cannot connect to the Docker daemon"
        if arguments[0] == "ps":
            # Docker applies the label filter; the fake does the same.
            assert arguments[1:4] == ["--all", "--filter", "label=netanalyser.sim=true"]
            return 0, "\n".join(
                f"{c['id']}\t{'running' if c['running'] else 'exited'}\t{name}"
                for name, c in self.containers.items()
                if c["sim"]
            )
        if arguments[0] == "stop":
            self._by_id(arguments[-1])["running"] = False
            return 0, arguments[-1]
        if arguments[0] == "start":
            self._by_id(arguments[-1])["running"] = True
            return 0, arguments[-1]
        if arguments[0] == "exec":
            container, tc = self._by_id(arguments[1]), arguments[2:]
            if tc[:3] == ["tc", "qdisc", "show"]:
                netem = container["netem"]
                return 0, f"qdisc netem 8001: root refcnt 2 limit 1000 {netem}" if netem else NO_QDISC
            if tc[:3] == ["tc", "qdisc", "replace"]:
                container["netem"] = " ".join(tc[tc.index("netem") + 1 :])
                return 0, ""
            if tc[:3] == ["tc", "qdisc", "del"]:
                container["netem"] = None
                return 0, ""
        raise AssertionError(f"the agent ran an unexpected docker command: {arguments}")

    def ran(self, subcommand: str) -> list[list[str]]:
        return [command for command in self.commands if command[0] == subcommand]


@pytest.fixture
def docker() -> FakeDocker:
    return FakeDocker()


@pytest.fixture
def agent(docker):
    return agent_module.Agent(TOKEN, docker)


def call(agent, method: str, path: str, body: dict | None = None, token: str | None = TOKEN):
    return agent.handle(method, path, token, b"" if body is None else json.dumps(body).encode())


# =============================================================================
# The shared secret
# =============================================================================


@pytest.mark.parametrize("token", [None, "", "wrong", TOKEN + "x", TOKEN[:-1]])
def test_a_request_without_the_right_secret_is_refused_before_docker_is_touched(agent, docker, token):
    for method, path in [("GET", "/containers"), ("POST", "/containers/sim-sw-ot/stop")]:
        assert call(agent, method, path, token=token) == (401, {"detail": "missing or wrong X-Chaos-Token"})

    assert docker.commands == []


@pytest.mark.parametrize("token", ["", "short", "fifteen-chars-!"])
def test_the_agent_refuses_to_run_without_a_real_secret(token):
    with pytest.raises(ValueError, match="at least 16 characters"):
        agent_module.Agent(token)


def test_the_agent_process_exits_with_an_explanation_when_no_secret_is_set(monkeypatch):
    monkeypatch.delenv("CHAOS_AGENT_TOKEN", raising=False)

    with pytest.raises(SystemExit) as exit_:
        agent_module.main()

    assert "the shared secret must have at least 16 characters" in str(exit_.value)
    assert "openssl rand -hex 32" in str(exit_.value)


# =============================================================================
# The allow-list: only containers labelled netanalyser.sim=true
# =============================================================================


def test_list_shows_only_labelled_containers(agent, docker):
    status, body = call(agent, "GET", "/containers")

    assert status == 200
    assert body == {
        "containers": [
            {"name": "sim-fw-01", "running": False, "netem": None},
            {"name": "sim-scanner-1", "running": True, "netem": None},
            {"name": "sim-sw-ot", "running": True, "netem": None},
        ]
    }
    # The selection is Docker's own label filter, not a guess from the name.
    (ps,) = docker.ran("ps")
    assert ps[:4] == ["ps", "--all", "--filter", "label=netanalyser.sim=true"]


def test_under_compose_only_the_agents_own_project_is_listed(docker):
    scoped = agent_module.Agent(TOKEN, docker, project="infra")

    assert call(scoped, "GET", "/containers")[0] == 200

    (ps,) = docker.ran("ps")
    assert ps[:6] == [
        "ps", "--all",
        "--filter", "label=netanalyser.sim=true",
        "--filter", "label=com.docker.compose.project=infra",
    ]  # fmt: skip


@pytest.mark.parametrize("project", ["infra; reboot", "--all", "Infra", "a b"])
def test_a_project_name_that_could_alter_the_command_is_refused(project):
    with pytest.raises(ValueError, match="Compose project name"):
        agent_module.Agent(TOKEN, project=project)


@pytest.mark.parametrize(
    ("method", "action", "body"),
    [("POST", "stop", None), ("POST", "start", None), ("PUT", "netem", {"delay_ms": 100}), ("DELETE", "netem", None)],
)
def test_a_container_without_the_label_cannot_be_touched(agent, docker, method, action, body):
    status, answer = call(agent, method, f"/containers/backend/{action}", body)

    assert status == 404
    assert answer == {"detail": "'backend' is not a simulated device (label netanalyser.sim=true)"}
    assert [command[0] for command in docker.commands] == ["ps"]  # it looked, and did nothing


@pytest.mark.parametrize(
    "name",
    ["sim-sw-ot;reboot", "$(reboot)", "-rf", "SIM-SW-OT", "sim sw ot", "..", "sim-sw-ot%20--privileged", "a" * 64],
)
def test_a_name_that_is_not_a_plain_service_name_never_reaches_docker(agent, docker, name):
    for method, action in [("POST", "stop"), ("POST", "start"), ("PUT", "netem"), ("DELETE", "netem")]:
        status, answer = call(agent, method, f"/containers/{name}/{action}", {"delay_ms": 100})

        assert (status, answer) == (400, {"detail": "invalid container name"})
    assert docker.commands == []  # refused before anything was asked of Docker


@pytest.mark.parametrize("name", ["ddd444", "sim-sw-ot-2", "frontend"])
def test_a_well_formed_name_that_is_not_in_the_list_is_refused(agent, docker, name):
    # "ddd444" is the real id of the unlabelled backend container: an id is not accepted either.
    assert call(agent, "POST", f"/containers/{name}/stop")[0] == 404
    assert docker.ran("stop") == []


def test_only_the_container_id_docker_reported_is_passed_on(agent, docker):
    call(agent, "POST", "/containers/sim-sw-ot/stop")
    call(agent, "POST", "/containers/sim-fw-01/start")

    # Never the name from the request: the id from the labelled listing.
    assert docker.ran("stop") == [["stop", "--time", "0", "aaa111"]]
    assert docker.ran("start") == [["start", "ccc333"]]


# =============================================================================
# Stop and start
# =============================================================================


def test_stop_and_start(agent, docker):
    assert call(agent, "POST", "/containers/sim-sw-ot/stop") == (200, {"name": "sim-sw-ot", "running": False})
    assert docker.containers["sim-sw-ot"]["running"] is False

    assert call(agent, "POST", "/containers/sim-sw-ot/start") == (200, {"name": "sim-sw-ot", "running": True})
    assert docker.containers["sim-sw-ot"]["running"] is True


def test_stopping_a_stopped_container_and_starting_a_running_one_is_fine(agent, docker):
    assert call(agent, "POST", "/containers/sim-fw-01/stop")[0] == 200
    assert call(agent, "POST", "/containers/sim-sw-ot/start")[0] == 200


# =============================================================================
# netem: delay, jitter, loss
# =============================================================================


@pytest.mark.parametrize(
    ("body", "settings"),
    [
        ({"delay_ms": 200, "jitter_ms": 40, "loss_pct": 2.5}, ["delay", "200ms", "40ms", "loss", "2.5%"]),
        ({"delay_ms": 150}, ["delay", "150ms"]),
        ({"loss_pct": 10}, ["loss", "10%"]),
        ({"delay_ms": 100, "jitter_ms": 0, "loss_pct": 0}, ["delay", "100ms"]),
    ],
)
def test_netem_runs_tc_inside_the_container(agent, docker, body, settings):
    status, answer = call(agent, "PUT", "/containers/sim-sw-ot/netem", body)

    assert (status, answer) == (200, {"name": "sim-sw-ot", "netem": " ".join(settings)})
    assert docker.ran("exec") == [
        ["exec", "aaa111", "tc", "qdisc", "replace", "dev", "eth0", "root", "netem", *settings]
    ]


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ({}, "give a delay_ms or a loss_pct above 0"),
        ({"delay_ms": 0, "loss_pct": 0}, "give a delay_ms or a loss_pct above 0"),
        ({"delay_ms": 100, "jitter_ms": 101}, "jitter_ms cannot be larger than delay_ms"),
        ({"delay_ms": -1}, "delay_ms must be a whole number from 0 to 10000"),
        ({"delay_ms": 10001}, "delay_ms must be a whole number from 0 to 10000"),
        ({"delay_ms": 1.5}, "delay_ms must be a whole number from 0 to 10000"),
        ({"delay_ms": "100ms; reboot"}, "delay_ms must be a whole number from 0 to 10000"),
        ({"delay_ms": True}, "delay_ms must be a whole number from 0 to 10000"),
        ({"delay_ms": 100, "jitter_ms": "1"}, "jitter_ms must be a whole number from 0 to 10000"),
        ({"loss_pct": 100.5}, "loss_pct must be a number from 0 to 100"),
        ({"loss_pct": [5]}, "loss_pct must be a number from 0 to 100"),
    ],
)
def test_netem_rejects_values_it_would_not_put_on_a_command_line(agent, docker, body, reason):
    assert call(agent, "PUT", "/containers/sim-sw-ot/netem", body) == (400, {"detail": reason})
    assert docker.ran("exec") == []


@pytest.mark.parametrize("raw", [b"not json", b"[1, 2]", b'"delay"'])
def test_netem_needs_a_json_object(agent, docker, raw):
    status, _ = agent.handle("PUT", "/containers/sim-sw-ot/netem", TOKEN, raw)

    assert status == 400
    assert docker.ran("exec") == []


def test_netem_on_a_stopped_container_is_a_conflict(agent, docker):
    assert call(agent, "PUT", "/containers/sim-fw-01/netem", {"delay_ms": 100}) == (
        409,
        {"detail": "'sim-fw-01' is not running"},
    )
    assert docker.ran("exec") == []


def test_list_reports_the_netem_in_force(agent, docker):
    call(agent, "PUT", "/containers/sim-sw-ot/netem", {"delay_ms": 200, "jitter_ms": 40, "loss_pct": 2})

    listed = {c["name"]: c["netem"] for c in call(agent, "GET", "/containers")[1]["containers"]}

    assert listed == {"sim-fw-01": None, "sim-scanner-1": None, "sim-sw-ot": "delay 200ms 40ms loss 2%"}


def test_the_netem_line_of_a_real_tc_is_understood(agent, docker, monkeypatch):
    # Copied from `tc qdisc show dev eth0` in a sim container (iproute2 in Alpine 3.20).
    real = "qdisc netem 8001: root refcnt 11 limit 1000 delay 200ms  40ms loss 2% seed 1185887037437083945"
    run = docker.__call__

    def tc_says(arguments):
        if arguments[2:5] == ["tc", "qdisc", "show"]:
            docker.commands.append(arguments)
            return 0, real
        return run(arguments)

    monkeypatch.setattr(agent, "_run", tc_says)

    listed = {c["name"]: c["netem"] for c in call(agent, "GET", "/containers")[1]["containers"]}

    assert listed["sim-sw-ot"] == "delay 200ms 40ms loss 2%"  # without the seed tc made up


def test_clearing_netem_deletes_the_qdisc_only_where_there_is_one(agent, docker):
    call(agent, "PUT", "/containers/sim-sw-ot/netem", {"delay_ms": 200})
    docker.commands.clear()

    assert call(agent, "DELETE", "/containers/sim-sw-ot/netem") == (200, {"name": "sim-sw-ot", "netem": None})
    assert ["exec", "aaa111", "tc", "qdisc", "del", "dev", "eth0", "root"] in docker.commands

    docker.commands.clear()
    for name in ("sim-sw-ot", "sim-scanner-1", "sim-fw-01"):  # cleared already, never set, stopped
        assert call(agent, "DELETE", f"/containers/{name}/netem")[0] == 200
    assert [c for c in docker.ran("exec") if "del" in c] == []


# =============================================================================
# Everything else
# =============================================================================


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/"),
        ("GET", "/containers/sim-sw-ot"),
        ("GET", "/containers/sim-sw-ot/stop"),  # wrong method
        ("DELETE", "/containers/sim-sw-ot/stop"),
        ("POST", "/containers/sim-sw-ot/remove"),
        ("POST", "/containers/sim-sw-ot/stop/extra"),
        ("POST", "/exec"),
    ],
)
def test_there_are_no_other_endpoints(agent, docker, method, path):
    assert call(agent, method, path) == (404, {"detail": "no such endpoint"})
    assert docker.commands == []


def test_a_docker_failure_is_reported_not_raised(agent, docker):
    docker.fail_on = "stop"

    status, answer = call(agent, "POST", "/containers/sim-sw-ot/stop")

    assert status == 502
    assert answer == {"detail": "docker stop failed: Cannot connect to the Docker daemon"}


def test_the_docker_runner_never_uses_a_shell(monkeypatch):
    seen = {}

    def fake_run(command, **options):
        seen.update(command=command, options=options)
        return type("Done", (), {"returncode": 0, "stdout": "ok\n", "stderr": ""})()

    monkeypatch.setattr(agent_module.subprocess, "run", fake_run)

    assert agent_module.docker_cli(["stop", "--time", "0", "aaa111"]) == (0, "ok")
    assert seen["command"] == ["docker", "stop", "--time", "0", "aaa111"]  # a list: no shell parsing
    assert "shell" not in seen["options"]


# =============================================================================
# The backend's client against the agent's real HTTP server (loopback only)
# =============================================================================


@pytest.fixture
def served(docker):
    """The agent's HTTP server on a free loopback port, with the fake docker."""

    class Handler(agent_module.Handler):
        agent = agent_module.Agent(TOKEN, docker)

        def log_message(self, format, *args):  # noqa: A002
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_the_client_and_the_agent_understand_each_other(served, docker):
    client = ChaosClient(served, TOKEN)

    assert client.containers() == [
        SimContainer("sim-fw-01", False, None),
        SimContainer("sim-scanner-1", True, None),
        SimContainer("sim-sw-ot", True, None),
    ]
    client.stop("sim-sw-ot")
    client.start("sim-fw-01")
    client.set_netem("sim-scanner-1", 200, 40, 2.5)

    assert client.containers() == [
        SimContainer("sim-fw-01", True, None),
        SimContainer("sim-scanner-1", True, "delay 200ms 40ms loss 2.5%"),
        SimContainer("sim-sw-ot", False, None),
    ]
    client.clear_netem("sim-scanner-1")
    assert docker.containers["sim-scanner-1"]["netem"] is None


def test_the_client_reports_what_the_agent_refused(served):
    client = ChaosClient(served, TOKEN)

    with pytest.raises(ChaosAgentError) as refused:
        client.stop("backend")
    assert (refused.value.status, str(refused.value)) == (
        404,
        "'backend' is not a simulated device (label netanalyser.sim=true)",
    )

    with pytest.raises(ChaosAgentError) as conflict:
        client.set_netem("sim-fw-01", 100, 0, 0)  # it is stopped
    assert conflict.value.status == 409


def test_a_wrong_secret_is_explained_to_the_backend(served, docker):
    with pytest.raises(ChaosAgentError) as refused:
        ChaosClient(served, "not-the-shared-secret").containers()

    assert refused.value.status == 401
    assert str(refused.value) == "the backend and the chaos agent do not have the same CHAOS_AGENT_TOKEN"
    assert docker.commands == []


def test_a_name_with_odd_characters_cannot_escape_the_path(served, docker):
    client = ChaosClient(served, TOKEN)

    for name in ("sim-sw-ot/../../exec", "sim-sw-ot?x=1", "sim-sw-ot/stop#"):
        with pytest.raises(ChaosAgentError):
            client.stop(name)

    assert docker.ran("stop") == []


def test_no_agent_at_the_address_is_unavailable_not_a_crash():
    client = ChaosClient("http://127.0.0.1:9", TOKEN, timeout=2)  # nothing listens on the discard port

    with pytest.raises(ChaosUnavailable, match="The chaos agent is not reachable"):
        client.containers()


def test_an_error_that_is_not_from_the_agent_is_still_reported(docker):
    from http.server import BaseHTTPRequestHandler

    class NotAnAgent(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"<html>proxy error</html>")

        def log_message(self, format, *args):  # noqa: A002
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), NotAnAgent)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(ChaosAgentError) as error:
            ChaosClient(f"http://127.0.0.1:{server.server_address[1]}", TOKEN).containers()
    finally:
        server.shutdown()
        server.server_close()

    assert (error.value.status, str(error.value)) == (500, "Internal Server Error")


def test_an_oversized_request_is_refused(served):
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        f"{served}/containers/sim-sw-ot/netem",
        method="PUT",
        data=b"x" * 5000,
        headers={"X-Chaos-Token": TOKEN},
    )
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(request, timeout=5)

    assert refused.value.code == 413
