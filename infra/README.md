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

   `infra/.env` is git-ignored; never commit it.

## Start

```sh
docker compose -f infra/docker-compose.yml up -d --build
```

This brings up **13 containers**: 11 `sim-*` Alpine stubs standing in for
warehouse hardware, the backend (FastAPI + SQLite on port 8000), and the
frontend (nginx static SPA on port 8080).

## Access

- Frontend UI: <http://localhost:8080> (or the deployment's actual address)
- Backend API: <http://localhost:8000>/api/... (`/api/health` for a smoke check)

Default seeded logins:

| User   | Password   | Role  |
| ------ | ---------- | ----- |
| `admin` | `admin123` | admin |
| `viewer` | `viewer123` | viewer |

> **Change the passwords immediately after first login.** The admin can change
> their own password on the Account page and manage every user's account via
> Admin → Users — this is exactly what the password-change and user-management
> features are for. Do not leave `admin123` in front of real network devices.

## Stop

```sh
docker compose -f infra/docker-compose.yml down
```

Container recreation (`down`/`up`, rebuilds, `restart`) keeps persisted data —
settings, users, devices, latency history and status transitions — in the
`backend-data` named volume. How long the history is kept is set by the
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

The 11 `sim-*` containers are ICMP-pingable Alpine stubs arranged in the
topology described in `infra/devices.seed.json` (firewall at `10.99.0.1`,
switches, PLCs, HMIs, access points, scanners on `10.99.0.0/24`). The backend
pings them over ICMP (`CAP_NET_RAW`) on the shared `warehouse-net`.

When real hardware is ready, replace the device definitions in
`infra/devices.seed.json` (and, if needed, the sim services here) with the real
device IPs — the backend and frontend work against whatever the seeded devices
are, with no code changes.

## Deeper reads

- `docker-compose.yml` — full service wiring (networks, volumes, env pass-through).
- `../backend/Dockerfile` and `../frontend/Dockerfile` — the production images.
- `../README.md` — overall project overview and development setup.