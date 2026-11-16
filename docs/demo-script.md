# Demo script: five minutes

A timed walk through the system for an evaluation. It shows the problem (one
failure, six devices down), the solution (one incident, five alerts
suppressed), what redundancy changes, an advisory anomaly, and the audit
trail.

Every label below is what the screen shows. The header links are
**Topology**, **Metrics**, **Stability**, **Incidents** and **Admin**; the
Admin tabs are **Devices**, **Links**, **Settings**, **Users**, **Chaos** and
**Audit**.

The timings were measured on the simulated network on Docker Desktop, with
the default monitoring settings and the one demo setting below (a 1-second
ping timeout):

| What | How long |
| --- | --- |
| Fault table fills after **Run** | 1 to 2 s |
| Incident appears after **Run** | about 15 s, at most 25 |
| "All monitored devices healthy" after **Restore all** | about 15 s, at most 27 |
| `ANOMALY` badge after **Degrade** | about 20 s, at most 25 |

The backend confirms the outage after 7 to 15 seconds; the Incidents page
asks it every 10 seconds, which is the rest. With the default 2-second ping
timeout allow three seconds more.

## Before the audience arrives

Allow ten minutes.

1. In `infra/.env` set four values:

   ```sh
   JWT_SECRET_KEY=<output of: openssl rand -hex 32>
   CHAOS_AGENT_TOKEN=<output of: openssl rand -hex 32>
   DEMO_MODE=true
   PING_TIMEOUT_SECONDS=1
   ```

2. Start from a clean database. This deletes the stack's stored data:

   ```sh
   make seed-reset CHAOS=1
   ```

3. Open <http://localhost:8411> and sign in as `admin` / `admin123`.
4. Rehearse once. **Admin**, **Chaos**, "OT switch failure", **Run**. Open
   **Incidents** and wait for the incident. Back in **Chaos**, press
   **Restore all**, and check that **Incidents** says "All monitored devices
   healthy". This proves the chaos agent works and leaves one resolved
   incident in the history.
5. Wait until the stack has been up for five minutes. The anomaly detectors
   need 30 readings of every device (four minutes) before they judge
   anything.
6. Finish on **Topology**, with all twelve device cards in view.

## The five minutes

### 0:00 The network

- **Click:** nothing. You are on **Topology**.
- **Expect:** twelve cards, all `HEALTHY`. Badges `SPOF 11` on Edge Firewall,
  `SPOF 5` on OT Tier Switch and `SPOF 2` on Server Tier Switch. Two blue
  dashed lines from Edge Switch 2. At the top right of the graph: "12 devices
  · status updated" with a time that moves every few seconds.
- **Say:** this is a small plant network, monitored live over a
  Server-Sent Events stream. A `SPOF` badge says how many devices lose their
  connection if that one fails. The dashed lines are redundant links.

### 0:35 Predict a failure

- **Click:** in the **What-if** panel tick **Edge Switch**, then
  **Simulate**.
- **Expect:** "TOTAL BLAST RADIUS 0".
- **Click:** also tick **Edge Switch 2**, then **Simulate**.
- **Expect:** "TOTAL BLAST RADIUS 9". On the graph two cards read `FAILED`
  and nine `CUT OFF`, under the banner "What-if: predicted statuses, not
  live".
- **Click:** **Reset**. All twelve are `HEALTHY` again.
- **Say:** one edge switch can fail without cutting anything off, because the
  other one still leads to both tier switches. Both together cut off nine
  devices. This is calculated with union-find, and nothing on the network
  was touched.

### 1:15 Break something

- **Click:** **Admin**, **Chaos**, the card "OT switch failure", **Run**.
- **Expect:** within two seconds the fault table lists six devices: OT Tier
  Switch as `Failed` ("stopped on request") and five as `Cut off` ("stopped
  because nothing leads to it any more").
- **Say:** the simulated devices are separate containers, so stopping a
  switch would not take anything else down. The backend works out what the
  failure cuts off and stops those too, as real hardware would behave.

### 1:30 One incident, not six alerts

- **Click:** **Incidents**. Keep talking: this takes about 15 seconds.
- **Say, while waiting:** a status only changes after three results in a row
  agree, so that one bad poll never raises an alarm. A device that misses a
  poll is asked again a second later, and once more, so the three results
  take about seven seconds. That is the delay you are watching.
- **Expect:** a red `6` next to **Incidents** in the header. On the
  **Active** tab one card "OT Tier Switch", `ROOT CAUSE`, `OPEN`, "Affects 5
  other devices", and five `COLLATERAL` cards. The cards at the top read
  "INCIDENTS 2" and "ALERTS SUPPRESSED 10": five from the rehearsal and five
  now.
- **Say:** six devices are down. A monitor that only pings would raise six
  alerts. This one raises a single incident for the switch that failed and
  files the other five under it.
- **Click:** **Guided fix** on the root-cause card.
- **Expect:** a four-step playbook for a switch that is down, starting with
  "Check power LED", with **Back** and **Next**.

### 2:30 Work the incident

- **Click:** **Timeline** on the root-cause card.
- **Expect:** the page "Incident #2: OT Tier Switch", `OPEN`, with the first
  failing probe, the time it was opened and the detection delay.
- **Click:** **Acknowledge**.
- **Expect:** `ACKNOWLEDGED`, with the time and "by admin".
- **Click:** type a note under "Add a note to the timeline", then
  **Add note**.
- **Expect:** the note at the end of the timeline, after "Incident opened"
  and "Acknowledged".
- **Say:** the incident is stored in the database, so it survives a restart.
  Acknowledging and adding notes are admin actions and are audit-logged.

### 3:05 Recover

- **Click:** **Admin**, **Chaos**, **Restore all**.
- **Expect:** "No faults in place: every simulated device is running
  normally."
- **Click:** **Incidents**, and after about 15 seconds the **History** tab.
- **Expect:** **Active** says "All monitored devices healthy". **History**
  lists incident 2 as `RESOLVED`, with its duration and "5" peak affected.
- **Say:** nobody closed it. It resolved when the switch answered two polls
  in a row, and the time to recovery is recorded.

### 3:40 An advisory anomaly

- **Click:** **Admin**, **Chaos**. Under "Degrade a device" choose
  **Production Server 1**, set "Delay (ms)" to `40`, "Jitter (ms)" to `0` and
  "Loss (%)" to `0`, then **Degrade**.
- **Expect:** the fault table shows "Production Server 1", `Degraded`, "40 ms
  delay, 0 ms jitter, 0% loss".
- **Click:** **Topology**.
- **Expect:** after about 20 seconds the card of Production Server 1 gets an
  `ANOMALY` badge. It stays green and `HEALTHY`. Hovering over the badge
  shows, with the figures measured at that moment, "Unusual latency: 47.1 ms,
  usually about 3.2 ms (advisory: the status is unchanged)".
- **Click:** the card.
- **Expect:** the device page, with "Anomaly (advisory)" and the same
  sentence, and the unusual period shaded on the latency chart.
- **Say:** 40 milliseconds is far below the 100-millisecond threshold, so the
  status is right to stay healthy. For this device it is fifteen times its
  normal. The detector learns each device's own baseline. It only advises:
  no status changed and no incident was opened.

### 4:30 Who did what

- **Click:** **Admin**, **Audit**.
- **Expect:** newest first: `chaos.degrade`, `chaos.restore_all`,
  `incident.note_added`, `incident.acknowledged` and `chaos.scenario` from
  this demo. Below them are the rehearsal's two chaos entries and
  `auth.login`. Each has the user and the address.
- **Say:** every login and every admin action is recorded.

### 4:50 Close

- **Click:** **Chaos**, **Restore all**.
- **Say:** the backend behind all of this is covered by an automated test
  suite that runs on every push, and the graph algorithms are checked against
  brute-force versions on random networks.

## If something goes wrong

| What you see | What to do |
| --- | --- |
| The Chaos tab says "Fault injection is not available." | The agent is not running. `make up CHAOS=1` starts it in about 30 seconds (it needs `CHAOS_AGENT_TOKEN` in `infra/.env`). Or carry on without it: see below. |
| No incident 30 seconds after **Run** | Open **Topology**. If "status updated" has stopped moving, reload the page. If the devices are `DOWN` there, wait one more poll. Otherwise look at `docker compose -f infra/docker-compose.yml logs backend --tail 20`. |
| The topology page is empty | Reload the page. |
| An amber line under the header: "Monitoring has fallen behind…", "Monitoring has not completed a poll yet…" or "The backend is not answering…" | The statuses on screen are old, and the line says so. `docker compose -f infra/docker-compose.yml logs backend --tail 20` usually says why: a cycle that fails is logged with its error. `docker compose -f infra/docker-compose.yml restart backend` starts the poll loop again; the line goes away by itself within about 20 seconds. |
| No `ANOMALY` badge after 45 seconds | The detectors were still warming up: the backend was restarted less than five minutes ago, or the slowdown began during the warm-up. Do not wait. Say so, show the results table in [anomaly-evaluation.md](anomaly-evaluation.md), and press **Restore all**. |
| "Too many failed attempts. Try again in N seconds." at the login | Wait, or run `docker compose -f infra/docker-compose.yml restart backend`: the throttle is in memory. |
| "Incorrect username or password" for `admin` / `admin123` | The database was created without `DEMO_MODE`. Run `make seed-reset CHAOS=1` with `DEMO_MODE=true` in `infra/.env`. |
| The frontend loads but nothing else does | The backend did not start. `docker compose -f infra/docker-compose.yml logs backend --tail 5` says why; "Refusing to start" means `JWT_SECRET_KEY` is still a placeholder. |

**Without the chaos agent.** Do the first two steps as written. Then stop the
OT switch and the five devices behind it by hand:

```sh
docker compose -f infra/docker-compose.yml stop sim-sw-ot sim-plc-conveyor-1 \
  sim-hmi-panel-1 sim-ap-aisle-1 sim-ap-aisle-2 sim-scanner-1
```

The incident steps work as written. To recover, run the same command with
`start` in place of `stop`. Leave the anomaly step out.

**Without Docker.** Show the system from the tests instead, which need
neither Docker nor a network:

```sh
make test                                             # the whole backend suite, about 30 s
cd backend && .venv/bin/python scripts/eval_anomaly.py   # the anomaly evaluation, about 1 s
```

Then walk through the architecture diagram in the [README](../README.md) and
[algorithms.md](algorithms.md).

## Afterwards

```sh
make down
```
