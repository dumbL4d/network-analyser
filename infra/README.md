# Network Analyser — Docker Compose Deployment

This directory defines the complete, runnable deployment: the simulated
warehouse network, the FastAPI backend, and the React/nginx frontend, all wired
together on one bridge network (`warehouse-net`).

## Prerequisites

- Docker with Docker Compose (v2) — `docker compose version` should work.
- Nothing else: the stack builds the backend and frontend images itself.

## Setup (one-time)

1. Copy the environment template and open it:

   ```sh
   cp infra/.env.example infra/.env
   ```

2. Generate a **real** JWT signing secret and put it in `infra/.env`:

   ```sh
   openssl rand -hex 32
   ```

   Set the output as `JWT_SECRET_KEY=...`. The backend refuses to start if
   this is unset — it never runs with the insecure developer default from
   `backend/app/core/config.py`.

3. Set `FRONTEND_API_BASE_URL` in `infra/.env` to where the backend is
   reachable **from the end user's browser**:
   - local testing: leave the default `http://localhost:8000`;
   - real deployment: the server's LAN-reachable host/port
     (e.g. `http://10.0.0.50:8000`). This is baked into the frontend at image
     build time, so changing it afterwards requires `up -d --build`.

4. Optional: choose the first passwords of the two default accounts by
   setting `ADMIN_INITIAL_PASSWORD` and `VIEWER_INITIAL_PASSWORD` in
   `infra/.env`. If you leave them empty, the backend generates them (see
   "First login" below).

   `infra/.env` is git-ignored; never commit it.

## Start

```sh
docker compose -f infra/docker-compose.yml up -d --build
```

This brings up **14 containers**: 12 `sim-*` Alpine stubs standing in for
warehouse hardware, the backend (FastAPI + SQLite on port 8000), and the
frontend (nginx static SPA on port 8080).

## Access

- Frontend UI: <http://localhost:8080> (or the deployment's actual address)
- Backend API: <http://localhost:8000>/api/... (`/api/health` for a smoke check)

### First login

The first start creates two accounts, `admin` (role admin) and `viewer` (role
viewer). Their first passwords are the ones you set in `infra/.env`. If you
set none, the backend generated them and wrote them to its log, once:

```sh
docker compose -f infra/docker-compose.yml logs backend | grep "initial password"
```

Sign in with that password and the app takes you to the account page: each of
the two accounts must choose a new password before it can do anything else.
After that the log line is of no use to anyone. Further accounts are created
in Admin → Users.

A login lasts 60 minutes (`JWT_EXPIRE_MINUTES`). After 5 wrong passwords in 5
minutes the login is refused for a while. Everything an admin changes, and
every login, is in Admin → Audit. See `../docs/security.md`.

### Demo mode (insecure)

> **Only for demos. Never on a network that matters.**

`DEMO_MODE=true` in `infra/.env` creates the two accounts with fixed, publicly
known passwords and without the forced change:

| User     | Password    | Role   |
| -------- | ----------- | ------ |
| `admin`  | `admin123`  | admin  |
| `viewer` | `viewer123` | viewer |

It is off by default. It only chooses the passwords when the database is
created and never overwrites existing ones. To switch an existing
installation to the demo credentials, recreate its database:

```sh
docker compose -f infra/docker-compose.yml down -v   # deletes ALL stored data
DEMO_MODE=true docker compose -f infra/docker-compose.yml up -d
```

A database from an older version of this project still has those passwords.
Started without `DEMO_MODE`, the backend makes such an account change its
password at the next login.

## Stop

```sh
docker compose -f infra/docker-compose.yml down
```

Container recreation (`down`/`up`, rebuilds, `restart`) keeps persisted data —
settings, users, devices and their extra links, latency history, status
transitions and incidents — in the `backend-data` named volume. How long the history is kept is set by the
optional retention variables in `infra/.env` (see `.env.example`). When a newer
backend image starts on an existing volume, it upgrades the database schema in
place and keeps the data (see "Database migrations" in `../README.md`).

Add `-v` to also delete that volume **permanently**:

```sh
docker compose -f infra/docker-compose.yml down -v
```

`-v` destroys all persisted device/settings/user data (the DB is re-seeded to
defaults on next start). Never use it casually.

## The simulated network

The 12 `sim-*` containers are ICMP-pingable Alpine stubs arranged in the
topology described in `infra/devices.seed.json` (firewall at `10.99.0.1`, two
edge switches, tier switches, PLCs, HMIs, access points, scanners on
`10.99.0.0/24`). The backend pings them over ICMP (`CAP_NET_RAW`) on the
shared `warehouse-net`.

The topology is redundant: `sw-edge-2` (`10.99.0.5`) hangs under the firewall
next to `sw-edge` and is linked to both tier switches, so either edge switch
can fail without cutting anything off.

The stubs do not really depend on each other: each container answers pings by
itself, so stopping a switch does not take the devices behind it down. To see
what a failure WOULD cut off, use the What-if panel on the Topology page. What
the stubs can show is how the redundancy changes the incident analysis. Wait
about 30 s after each step (three polls confirm a failure):

```sh
# sw-ot is still reachable through sw-edge-2, so its failure is its own:
docker compose -f infra/docker-compose.yml stop sim-sw-edge sim-sw-ot   # two root causes
# with both edge switches gone, nothing leads to sw-ot any more:
docker compose -f infra/docker-compose.yml stop sim-sw-edge-2           # sw-ot becomes collateral
docker compose -f infra/docker-compose.yml start sim-sw-edge sim-sw-edge-2 sim-sw-ot
```

In the seed file a device may carry `"links"`: the ids of devices it is
connected to in addition to its parent. Seeding runs at every start and only
adds what is missing, so an existing installation gains `sw-edge-2` and its
two links on its next restart.

When real hardware is ready, replace the device definitions in
`infra/devices.seed.json` (and, if needed, the sim services here) with the real
device IPs — the backend and frontend work against whatever the seeded devices
are, with no code changes.

## Fault injection (optional)

The stack can break its own simulated devices on purpose, to demonstrate the
monitoring: fail a switch and everything it cuts off, slow a device down,
make a PLC flap. It is off by default, because the service that does it (the
`chaos-agent`) mounts the Docker socket.

```sh
echo "CHAOS_AGENT_TOKEN=$(openssl rand -hex 32)" >> infra/.env
docker compose -f infra/docker-compose.yml --profile chaos up -d --build
```

Then log in as an admin and open Admin, Chaos. Read `../docs/chaos.md` first:
it explains the risk of the Docker socket and what limits it.

For this, every `sim-*` container carries the label `netanalyser.sim=true`,
runs the image built from `sim/Dockerfile` (Alpine plus `iproute2`) and has
the `NET_ADMIN` capability. None of that is used unless the profile is running.

## Deeper reads

- `docker-compose.yml` — full service wiring (networks, volumes, env pass-through).
- `../docs/chaos.md` — fault injection: architecture, risks, scenarios.
- `../docs/security.md` — threat model, what is mitigated, known limitations.
- `../backend/Dockerfile` and `../frontend/Dockerfile` — the production images.
- `../README.md` — overall project overview and development setup.