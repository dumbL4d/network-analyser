# Anomaly detection: measured results

How well do the anomaly detectors find anomalies, and how often do they cry
wolf? This page answers with numbers, from traces in which the right answer is
known. Everything here is printed by one script and can be reproduced:

```sh
cd backend
python scripts/eval_anomaly.py        # the two tables below, in about a second
```

No database, no network and no Docker are involved. The detectors measured are
the classes the backend runs (`app/services/anomaly/detectors.py`), not copies.

## What was measured

**Traces.** A trace is three days of readings, one every 10 seconds (25,920
readings). A latency trace is a base of 20 ms plus Gaussian noise with a
standard deviation of 2 ms. Four situations:

| Scenario | What the baseline does |
| --- | --- |
| latency, flat baseline | nothing: 20 ms, day and night |
| latency, daily rhythm | rises and falls by 8 ms over a day (a sine wave) |
| latency, daily rhythm, 1% glitches | the same, and 1 reading in 100 is far off for that one reading |
| packet loss, 4 probes | loss in steps of 25%, with each probe lost 1 time in 100 |

A glitch is noise, not an anomaly: a detector that reports one has raised a
false alarm.

**Anomalies.** Into every latency trace go about 40 anomalies at random
places, and where each begins and ends is recorded:

| Kind | What it is | Length | Height |
| --- | --- | --- | --- |
| spike | a few readings far above normal | 3 to 8 readings | 16 to 40 ms |
| step | the level jumps, stays, and comes back | 60 to 240 readings | 10 to 24 ms |
| drift | the level creeps up in a straight line, then comes back | 240 to 480 readings | 12 to 24 ms at the end |

Into a packet-loss trace go periods of 20 to 120 polls in which each probe is
lost 25% to 60% of the time. They are counted as steps.

**Detectors.** All three use the same rule (a reading is "above" when it is
more than k = 3 standard deviations over the baseline, and an anomaly is
m = 3 readings in a row above) and differ only in what the baseline is:

| Detector | Its baseline |
| --- | --- |
| static threshold | the mean and spread of its first 30 readings, never updated: a threshold someone set once |
| EWMA (alpha 0.1) | an exponentially weighted mean and variance; frozen while readings are above the threshold |
| rolling z-score (W 60) | the mean and spread of the last 60 readings, whatever they were |

**Metrics**, counted per anomaly and per alarm (an alarm is a run of flagged
readings), over five traces per scenario (seeds 42 to 46):

- **Recall**: the share of the anomalies that were flagged at all.
- **Precision**: the share of the alarms that overlapped a real anomaly.
- **Mean delay**: for the anomalies that were caught, how many readings after
  the anomaly began the first flag came. With m = 3 the best possible is 2.
- **False alarms / 1000**: alarms that overlapped no anomaly, per 1000
  readings outside the anomalies. 1000 readings are about 2.8 hours.
- **Step readings flagged**: the share of the readings inside steps that were
  flagged. It separates a detector that says "still wrong" for as long as a
  step lasts from one that only marks where it began.

## Results

<!-- results:begin -->
| Scenario | Detector | Precision | Recall | Mean delay (readings) | False alarms / 1000 |
| --- | --- | --- | --- | --- | --- |
| latency, flat baseline | static threshold | 1.00 | 1.00 | 14.1 | 0.00 |
| latency, flat baseline | EWMA (alpha 0.1) | 0.99 | 0.88 | 2.0 | 0.01 |
| latency, flat baseline | rolling z-score (W 60) | 1.00 | 0.84 | 2.0 | 0.00 |
| latency, daily rhythm | static threshold | 0.12 | 0.99 | 18.1 | 24.41 |
| latency, daily rhythm | EWMA (alpha 0.1) | 0.99 | 0.88 | 2.0 | 0.01 |
| latency, daily rhythm | rolling z-score (W 60) | 1.00 | 0.84 | 2.0 | 0.00 |
| latency, daily rhythm, 1% glitches | static threshold | 0.21 | 0.82 | 19.7 | 10.67 |
| latency, daily rhythm, 1% glitches | EWMA (alpha 0.1) | 0.99 | 0.88 | 2.0 | 0.01 |
| latency, daily rhythm, 1% glitches | rolling z-score (W 60) | 1.00 | 0.72 | 2.0 | 0.00 |
| packet loss, 4 probes | static threshold | 1.00 | 0.99 | 5.1 | 0.05 |
| packet loss, 4 probes | EWMA (alpha 0.1) | 0.99 | 1.00 | 3.2 | 0.08 |
| packet loss, 4 probes | rolling z-score (W 60) | 0.97 | 0.58 | 3.2 | 0.03 |

| Scenario | Detector | Spikes caught | Steps caught | Drifts caught | Step readings flagged |
| --- | --- | --- | --- | --- | --- |
| latency, flat baseline | static threshold | 136 of 136 (100%) | 41 of 41 (100%) | 22 of 22 (100%) | 99% |
| latency, flat baseline | EWMA (alpha 0.1) | 135 of 136 (99%) | 41 of 41 (100%) | 0 of 22 (0%) | 95% |
| latency, flat baseline | rolling z-score (W 60) | 131 of 136 (96%) | 37 of 41 (90%) | 0 of 22 (0%) | 2% |
| latency, daily rhythm | static threshold | 136 of 136 (100%) | 41 of 41 (100%) | 21 of 22 (95%) | 89% |
| latency, daily rhythm | EWMA (alpha 0.1) | 135 of 136 (99%) | 41 of 41 (100%) | 0 of 22 (0%) | 95% |
| latency, daily rhythm | rolling z-score (W 60) | 131 of 136 (96%) | 37 of 41 (90%) | 0 of 22 (0%) | 2% |
| latency, daily rhythm, 1% glitches | static threshold | 122 of 136 (90%) | 27 of 41 (66%) | 15 of 22 (68%) | 52% |
| latency, daily rhythm, 1% glitches | EWMA (alpha 0.1) | 135 of 136 (99%) | 41 of 41 (100%) | 0 of 22 (0%) | 97% |
| latency, daily rhythm, 1% glitches | rolling z-score (W 60) | 119 of 136 (88%) | 24 of 41 (59%) | 0 of 22 (0%) | 1% |
| packet loss, 4 probes | static threshold | none injected | 178 of 179 (99%) | none injected | 54% |
| packet loss, 4 probes | EWMA (alpha 0.1) | none injected | 179 of 179 (100%) | none injected | 62% |
| packet loss, 4 probes | rolling z-score (W 60) | none injected | 103 of 179 (58%) | none injected | 2% |
<!-- results:end -->

The same seed always gives exactly these figures. Other seeds give the same
picture: with seeds 1, 7, 100 and 2024 the EWMA detector's recall on latency
was between 0.81 and 0.92 and its precision between 0.98 and 1.00.

## What the numbers say

**The static threshold is the best detector when nothing ever changes, and
useless when the baseline moves.** On the flat baseline it caught everything
with no false alarm. It is also the only one that caught the slow drifts,
because it never forgets where "normal" was. Give the baseline a daily rhythm
and its precision falls to 0.12, with 24 false alarms per 1000 readings: on
average one every seven minutes, bunched around the daily high, when normal
readings sit above a line that was drawn in the morning. With glitches it
fails in one of two ways, depending on luck. In three of the five traces a
glitch fell among its first 30 readings and widened the spread it measured
for good: no false alarms, and most steps and drifts missed. In the other two
it caught everything and raised 600 false alarms per trace.

**The EWMA detector is the most dependable of the three, and blind to slow
drift.** It caught 99% of the spikes and every step in all three latency
scenarios, two readings after they began, with one false alarm in 114,000
normal readings. The daily rhythm and the glitches made no difference: it
follows the first, and the frozen baseline never learns the second. It kept
flagging a step for as long as the step lasted (95% of the readings). But it
caught **none** of the 22 drifts. A level that creeps up by less than a tenth
of a millisecond per reading is, to a baseline that adapts, simply the new
normal.
That is not a tuning problem: no alpha fixes it without breaking something
else.

**The rolling z-score is the weakest.** It learns from every reading, so an
anomaly spoils its own window. On clean traces it missed 5 of 136 spikes and
4 of 41 steps. Eight of those nine began within 60 readings of an earlier
anomaly, whose readings were still in the window. The ninth was a step whose
third reading happened to dip: by the time three readings in a row could
have been above the threshold, the step's own readings had raised it. With
glitches it missed 17 spikes and 17 steps. It marks where a step begins and
then goes quiet (2% of the readings), because the window fills with the new
level. On packet loss it
caught only 58% of the lossy periods: the first lossy polls raise the window's
spread faster than three polls in a row can clear it. Its one advantage is
the other side of the same coin: a change that is there to stay becomes
normal after W readings (60 here), where the EWMA detector takes 360.

**Packet loss, measured with 4 probes, is a coarse signal.** Loss moves in
steps of 25%, so the detectors have little to work with, and the static
threshold does about as well as the EWMA detector (recall 0.99 against 1.00).
The EWMA detector had more false alarms here than on latency (0.08 per 1000
readings, about one every 35 hours): three polls in a row that each lose one
probe by chance.

**Which one the backend uses.** The EWMA detector is the default because of
these figures. The fixed latency and loss thresholds of the status
classification stay in force next to it, which is what catches the slow
drifts the detector cannot see: a drift is "degraded" once it crosses them.
Anomalies are advisory for the same reason. A detector that is right 99% of
the time still raises a false alarm now and then, and that should cost a
badge, not an incident.

## Changing the parameters

The script takes `--k`, `--m`, `--alpha` and `--window` (and `--seed`,
`--traces`, `--samples`). Two things it shows:

- `--alpha 0.3` makes the EWMA baseline jumpy: precision on latency falls to
  about 0.85, with 0.3 false alarms per 1000 readings. Small values (0.02 to
  0.1) all behave like the default.
- `--window 30` makes the rolling detector worse (recall on packet loss about
  0.34), `--window 240` better (about 0.73). A larger window is contaminated
  more slowly, and forgets more slowly.

## What this does not show

- The traces are synthetic. Real latency is not Gaussian and real anomalies do
  not come in three tidy shapes. The figures compare the detectors with each
  other under the same conditions; they do not promise the same precision on a
  real network.
- Every anomaly here is at least 5 noise widths high. Smaller ones are caught
  less often, by any detector.
- A baseline is given credit for a spread of at least 1 ms of latency and 5
  points of loss (the values the backend uses). On a device steadier than
  that, a change has to exceed 3 ms or 15 points to count.
- An anomaly that never ends is not in the traces: the longest step lasts
  240 readings. The EWMA detector reports a level that stays for 360 readings
  in a row and then accepts it as the new normal (it forgets its baseline and
  warms up again); the rolling detector stops after W readings. Neither rule
  is exercised by these figures.
