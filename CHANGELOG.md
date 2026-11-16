# Changelog

What each commit since `4df7c97` added, newest first. They were made on the
branch `feat/tech-update`, which has since been merged into `main`. The
number of backend tests is the size of the suite after that commit.

## chore: merge upstream main (ports 8410/8411, both loopback origins)

- Takes in upstream's `b54dd7e`. The backend now listens on port 8410 and
  the frontend on 8411 (they were 8000 and 8080), and the API allows the
  frontend under `localhost` and under `127.0.0.1`, which a browser treats as
  two different origins.
- Carried into what this branch had rewritten: the README and the docs, the
  compose file, both `.env.example` files, and the address that the frontend
  image's Content-Security-Policy is built with. `infra/README.md` stays
  folded into the README.
- `test_docs.py` now fails if one file names another port than the rest, or
  if a CORS list the repository ships is not made of exact origins.
- 1446 tests.

## 12afb1e feat: stagger pings, poll at a fixed rate and retry suspect devices

- **Staggered pings.** A device's pings are sent `ping_gap_ms` apart without
  waiting for each other's replies, so a device that does not answer costs
  one timeout per cycle (2.6 s in all) instead of one per ping (8.6 s).
- **Fixed-rate loop.** A cycle starts one poll interval after the cycle
  before it started, not after it ended.
- **Retry on suspect.** A device whose result is worse than its confirmed
  status is probed again a second later, between two cycles. The retry
  counts for the debouncer, the status, the transitions and the incidents.
  No sample is stored for it, and the history and the anomaly detectors do
  not see it. A status that a retry confirmed survives a restart: the
  warm-up goes by a stored change that is newer than the last sample.
- A new database polls every 8 s (was 10). An existing database keeps the
  interval it has stored. The ping gap stays 200 ms.
- Measured on the simulated network: an outage is confirmed after 10 to 17 s
  (was 46 to 56 s). The stale-data limit follows the new ping timing: 26.6 s
  with the defaults.
- No migration, no new setting, no new dependency.
- 1444 tests.

## 538af4f feat: warn when the monitoring data is stale

- The poll loop notes when each cycle completes. `GET /api/health` keeps
  `status`, `app` and `env`, and adds `last_poll_at`, `last_poll_age_seconds`
  and `poll_stale`. The last is true when no cycle has completed for three
  poll intervals plus the longest the pings of one cycle can take (38.6 s
  with the default settings).
- Every page behind the login shows an amber warning while that is the
  case, or while the backend does not answer. It goes away by itself with
  the next completed cycle. Before, the pages went on showing the last
  statuses.
- The Topology page fills what the header and the warning leave of the
  window; it used to assume that only the header was above it.
- No migration, no new setting, no new dependency.
- 1396 tests.

## f392eef docs: finalize README, docs and demo script

- The README is now the entry page: the problem and the solution, what is
  implemented, the architecture, an ER diagram of the database, the API
  table, setup, configuration, testing and the known limitations.
- New documents: [architecture](docs/architecture.md),
  [algorithms](docs/algorithms.md) (each with its cost and a correctness
  argument), [design decisions](docs/design-decisions.md) and a timed
  [demo script](docs/demo-script.md). `infra/README.md` was folded into the
  README.
- A `Makefile` with `up`, `down`, `seed-reset`, `test`, `lint` and `build`.
  Both `.env.example` files list every setting.
- `test_docs.py` fails if the API table or the ER diagram no longer matches
  the code, if a setting is missing from the configuration tables or from an
  `.env.example` file, or if a link between the documents is broken.
- Fixed: on about 1 page load in 20 the topology graph stayed invisible until
  a reload. Added a "Topology" link to the header.
- Removed: a manual ping script, the Vite template README, an unused icon
  file, a dead constant, and comments that referred to an old ticket
  numbering.
- 1372 tests.

## a38ef90 fix: refuse placeholder secrets and invalid settings, ids and loops

- The backend refuses to start on a placeholder `JWT_SECRET_KEY` or one
  shorter than 32 characters. `DEMO_MODE` is the only exception.
- Settings reject NaN, Infinity and out-of-range values; the poll interval is
  at most an hour.
- Device ids are limited to what is safe in a URL, and text fields have a
  length.
- A loop of parents can no longer hang the incident analysis, and the seed
  loader skips a device that would close one.
- A rejected request body that cannot be echoed gets a 422 instead of a 500.
- 1368 tests.

## 3e52091 feat: re-learn the EWMA baseline after an hour-long anomaly

- After 360 readings in a row above the threshold (an hour at the default
  poll interval) the EWMA detector accepts the new level and re-learns, so a
  change that is there to stay is not flagged for ever.
- 1237 tests.

## 127c17a fix: do not count a device with its own incident as collateral

- A device that has its own incident is no longer counted among the affected
  devices of the incident above it, so "alerts suppressed" does not count it
  twice.
- 1233 tests.

## ac7eb3d feat: add EWMA and rolling z-score anomaly detection with evaluation

- One detector per device and metric (latency, packet loss), EWMA or rolling
  z-score, chosen in the settings. Advisory: a badge and chart markers, never
  a status change or an incident.
- `scripts/eval_anomaly.py` measures both detectors and a fixed threshold on
  synthetic traces; the results are in
  [docs/anomaly-evaluation.md](docs/anomaly-evaluation.md), and a test ties
  the document to the script.
- Migration `0008`. 1229 tests.

## 9d34f16 feat: add multi-ping probing with packet loss and jitter metrics

- Several pings per device per cycle (4 by default) give packet loss and
  jitter besides latency; too much of either counts as degraded.
- Both are stored, rolled up, served by the API and charted.
- Migration `0007`. 1089 tests.

## 691a5ab feat: harden auth, add SSE tickets, login throttling and audit log

- No built-in passwords; a seeded account must change its password at the
  first login. `DEMO_MODE` restores the demo logins.
- Sliding-window login throttle, 60-minute tokens, a token of a deleted
  account is rejected.
- The status stream is opened with a single-use ticket instead of the token
  in the URL.
- Strict CORS, a Content-Security-Policy and other headers from nginx, and an
  audit log with an Audit tab.
- Migration `0006`. 955 tests.

## 718c626 feat: add topology-aware fault injection with isolated chaos agent

- An admin-only Chaos tab fails, slows down or flaps simulated devices, with
  five presets and Restore all. A failure also stops every device it cuts
  off.
- A separate chaos agent holds the Docker socket. It only starts with the
  Compose profile `chaos`.
- 766 tests.

## c51181d feat: add redundant links, SPOF analysis and what-if simulation

- API and Admin tab for extra links; the seeded topology gains a second edge
  switch linked to both tier switches.
- `GET /api/analysis/spof` and `POST /api/analysis/what-if`; SPOF badges and
  a What-if panel on the topology page.
- 598 tests.

## ec209ad feat: add redundancy-aware graph engine with Tarjan, DSU, blast radius

- Extra, undirected links between devices in a new `device_link` table.
- A hand-written graph engine: reachability, articulation points, bridges,
  blast radius and single points of failure, without recursion.
- With links stored, incident analysis follows reachability; with none it is
  unchanged.
- Migration `0005`. 535 tests.

## 3340001 feat: add persisted incident lifecycle, MTTR and availability stats

- Every root cause is a stored incident (open, acknowledged, resolved) with a
  timeline, opened and resolved by a tracker after each poll cycle.
- Detection delay, MTTR, alerts suppressed and per-device availability.
- Incident summary cards, Active and History tabs, a detail page with
  acknowledge and notes; an availability table on the Stability page.
- Migration `0004`. 466 tests.

## 46d6922 feat: persist latency history and transitions with retention and rollups

- Every poll and every confirmed status change is written to SQLite.
- An hourly job turns raw samples older than a day into 1-minute rollups and
  deletes rollups and transitions older than 30 days.
- History, flap counts and debounce state are reloaded at startup; charts get
  a time-range selector.
- Migration `0003`. 383 tests.

## 98c15b1 feat: add Alembic migrations and debounced status confirmation

- The schema is managed by Alembic and upgraded at startup; an existing
  database is adopted as it is.
- A status changes only after several polls in a row agree: 3 to get worse,
  2 to recover, both configurable.
- Migrations `0001` and `0002`. 308 tests.

## ad8dded test: add backend test harness, characterization tests and CI

- A pytest suite that pins what the backend did at the time, on a temporary
  database and with a fake ping.
- GitHub Actions: backend tests with a coverage gate, frontend typecheck,
  lint and build.
- 198 tests.
