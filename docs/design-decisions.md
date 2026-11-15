# Design decisions

The main choices in this project, each with the reason, what was considered
instead, and what it costs. How the system works is in
[architecture.md](architecture.md); the algorithms are in
[algorithms.md](algorithms.md).

## 1. Server-Sent Events for the live status

**Decision.** The backend pushes a full status snapshot to every open browser
after each poll cycle, over Server-Sent Events (SSE). Everything else
(history, incidents, statistics) is fetched with ordinary REST requests, on a
timer where it has to stay fresh.

**Why.** The live data flows one way, from the server to the browser, which
is exactly what SSE is for. It is plain HTTP, so it needs no extra protocol
and passes through nginx or a proxy unchanged, and the browser has the client
built in (`EventSource`). A snapshot of a dozen devices is small, so sending
the whole picture every cycle is simpler than sending changes and can never
leave a browser with a half-updated view.

**Instead of.**

- *WebSocket.* Two-way, with its own protocol and handshake. Nothing here
  needs the browser to talk back on the same channel.
- *Polling the status.* The view would lag by up to one interval, and every
  browser would ask even when nothing changed.

**The price.**

- `EventSource` cannot send an `Authorization` header. The stream is
  therefore opened with a single-use ticket (see
  [Stream tickets](algorithms.md#stream-tickets)), which is extra machinery.
- Every open tab holds one connection.
- A full snapshot per cycle would be wasteful with thousands of devices.

## 2. SQLite

**Decision.** One SQLite file holds everything that is stored.

**Why.** There is one backend process at one site, and it writes little: one
transaction per poll cycle. SQLite needs no server and no administration, the
whole database is one file in a Docker volume, and the tests run against a
real database file in milliseconds.

**Instead of.** PostgreSQL would add a service to run, secure and back up,
for a workload with a single writer. A time-series database would be more
still.

**The price.**

- One writer at a time. The hourly retention job takes the write lock up
  front and works in small batches, so it cannot hold up the poll loop.
- Foreign keys are not enforced in this setup, so the API has to keep the
  references true.
- Several backends, or several sites sharing one store, would need a server
  database.

## 3. Debouncing

**Decision.** A device's status changes only when several polls in a row
agree: 3 to get worse, 2 to recover, both configurable.

**Why.** ICMP packets get lost on healthy networks. Without debouncing, one
bad poll changes a device's status, opens an incident and counts two flaps. A
monitor that does this is quickly ignored, which defeats its purpose. The
thresholds are uneven on purpose: a false alarm costs an operator's
attention, while a recovery is good news that is cheap to check.

**Instead of.**

- *No debouncing:* what the system did originally.
- *A vote over a window* ("3 of the last 5"). It reacts to intermittent loss,
  but the rule is harder to explain and to predict.

**The price.**

- A real outage is confirmed on the third failing poll. With the defaults that
  is about 50 seconds, because every ping to a device that does not answer
  waits for its timeout. A lower `PING_TIMEOUT_SECONDS` shortens it.
- Loss that comes and goes without three bad polls in a row never becomes a
  status. That is what the packet-loss figure, the raw history and the
  anomaly detector are for.

## 4. Anomalies are advisory

**Decision.** The anomaly detectors add a badge and chart markers. They never
change a status and never open an incident.

**Why.** A status has to be explainable: "three polls in a row got no reply" is
a fact. An anomaly is a statistical judgement, and it is sometimes wrong. The
evaluation ([anomaly-evaluation.md](anomaly-evaluation.md)) shows where:
neither detector catches a slow drift, and the rolling detector caught only
58% of the packet-loss anomalies. If such a signal opened incidents, the
system would create the alert noise it exists to remove.

**Instead of.**

- *Letting anomalies raise incidents:* more alerts, some of them false.
- *Fixed thresholds only:* they do not know what is normal for a device. 40
  ms is fine for one link and ten times too slow for another.

**The price.** Nobody is paged by an anomaly, so it can go unseen.

**Related choices.** The default detector is EWMA: constant memory and time,
it follows a daily rhythm, and it freezes its baseline during an anomaly so
that a spike cannot hide itself. After an hour above the threshold it accepts
the new level, so a permanent change is not flagged for ever.

## 5. Pure functions for the analysis

**Decision.** Classification, debouncing, root-cause analysis, the graph
engine, the incident difference, rollups and the detectors are pure
functions: plain data in, plain data out, no database and no clock.

**Why.** They can be tested on thousands of generated cases, and compared
with slow but obvious versions of themselves. The what-if simulator and the
fault planner reuse the live analysis instead of copying it, so a prediction
and the live view cannot disagree.

**The price.** The analysis is recomputed from scratch every cycle. That is
linear in the size of the network in practice (the worst cases are in
[algorithms.md](algorithms.md)), which costs nothing with tens of devices.

## 6. The incident tracker keeps no incidents in memory

**Decision.** After every cycle the tracker compares the analysis with the
unresolved incidents in the database and stores the difference. It keeps no
incident in memory.

**Why.** A restart then needs no recovery step: the next cycle continues the
incidents that are still valid, resolves the ones that ended while the
backend was down, and opens new ones. A partial unique index backs it up:
one unresolved incident per root device.

**The price.** A few extra queries per cycle.

## 7. A parent tree plus extra links

**Decision.** Every device has one parent. Redundancy is added on top, as
extra undirected links between devices.

**Why.** The project started with a tree, and the stored data and the user
interface are built on it. Adding links keeps all of that valid: with no
links stored, the original tree rule is used unchanged, and existing tests
pass untouched.

**Instead of.** Replacing `parent_id` with a general list of edges. It would
have needed a data migration and a new layout, for the same analysis.

**The price.** There are two rules to explain, and with links a device cut
off by two failures is listed under both.

## 8. Graph algorithms written by hand

**Decision.** Tarjan's low-link search, the blast radius and union-find are
implemented in `topology_graph.py`, without a graph library.

**Why.** It is a requirement of the project, and the algorithms are short.
They are written without recursion, so a deep network cannot hit Python's
recursion limit.

**The price.** More code to get right. It is checked against a brute force
on seeded random graphs.

## 9. Fault injection in its own small service

**Decision.** The backend decides what to break; a separate agent with five
operations carries it out. The agent only starts with the Compose profile
`chaos`.

**Why.** Stopping containers needs the Docker socket, and whoever holds that
controls the host. Keeping it out of the backend means a bug in the API
cannot reach it. The agent is tiny, has no published port, and only touches
containers labelled as simulated devices.

**The price.** One more container and a shared secret. It works on the
simulated network only. See [chaos.md](chaos.md).

## 10. Tokens in a header, tickets for the stream

**Decision.** The login token is sent in the `Authorization` header and kept
in the browser's `localStorage`.

**Why.** A browser never adds that header on its own, so another website
cannot ride a logged-in session (no CSRF). The frontend and the API are two
origins, which makes cookies awkward.

**The price.** Script running in the page could read the token. The
Content-Security-Policy and the 60-minute lifetime limit that. A token cannot
be revoked before it expires. See [security.md](security.md).

## 11. One process, hot state in memory

**Decision.** The backend is a single process. The latest snapshot, recent
history, debounce state, detectors, login throttle and stream tickets are in
its memory.

**Why.** One asyncio task polls, and the pages read from memory, which keeps
both simple and fast. What must survive a restart is in SQLite, and the
caches are refilled from it at startup.

**The price.** It does not scale out: a second process would poll twice and
hold different state. The throttle and the tickets are empty after a restart.

## 12. Migrations run at startup

**Decision.** The backend runs the Alembic migrations before it seeds. Every
migration only adds.

**Why.** An existing installation upgrades by starting the new version. No
manual step, and no data is lost.

**The price.** A migration that fails stops the start. Alembic does not run
SQLite migrations inside a transaction, so a half-applied one is not rolled
back.

## 13. Ping as the only probe

**Decision.** Devices are monitored with ICMP echo, several per cycle.

**Why.** Almost every network device answers ping, including PLCs and
switches that accept nothing else from a monitor. It needs no agent and no
credentials on the device. Several pings per cycle give packet loss and
jitter as well as latency.

**The price.** It measures reachability, not whether the service on a device
works.

## What would change at a larger scale

| Today | With hundreds of devices or several sites |
| --- | --- |
| SQLite, one writer | A server database |
| One process, state in memory | Shared state, so that more than one backend can run |
| Full snapshot per cycle over SSE | Changes only, or paged snapshots |
| One history request per device | A bulk history endpoint |
| Ping | Ping plus protocol checks (SNMP, Modbus, HTTP) |
