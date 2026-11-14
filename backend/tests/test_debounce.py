"""The debounce state machine (pure: no database, no clock).

Rules under test, from app/services/debounce.py:

    ranking  healthy < degraded < down < unknown
    first    a device's first result is accepted as it is
    worse    the last F raw results are all worse than the confirmed status
             -> confirmed becomes the mildest of them   (F = failure_threshold)
    better   the last R raw results are all better than the confirmed status
             -> confirmed becomes the worst of them     (R = recovery_threshold)
"""

import itertools
import random

import pytest

from app.models.settings import AppSettings
from app.services.debounce import (
    DEFAULT_FAILURE_THRESHOLD,
    DEFAULT_RECOVERY_THRESHOLD,
    MAX_THRESHOLD,
    MIN_THRESHOLD,
    SEVERITY,
    Debouncer,
    DebounceState,
    state_from_history,
    step,
)
from tests.helpers import make_status

STATUSES = ("healthy", "degraded", "down", "unknown")


def feed(
    state: DebounceState | None,
    raws: list[str],
    failure_threshold: int = 3,
    recovery_threshold: int = 2,
) -> tuple[DebounceState | None, list[str]]:
    """Feed raw results one at a time. Returns the final state and the
    confirmed status after each result."""
    confirmed = []
    for raw in raws:
        state = step(state, raw, failure_threshold, recovery_threshold)
        confirmed.append(state.confirmed)
    return state, confirmed


def run(raws: list[str], failure_threshold: int = 3, recovery_threshold: int = 2) -> list[str]:
    return feed(None, raws, failure_threshold, recovery_threshold)[1]


# --- defaults and the first result ---------------------------------------------


def test_defaults_and_allowed_range():
    assert (DEFAULT_FAILURE_THRESHOLD, DEFAULT_RECOVERY_THRESHOLD) == (3, 2)
    assert (MIN_THRESHOLD, MAX_THRESHOLD) == (1, 10)
    # A newly seeded settings row starts from the same defaults.
    row = AppSettings()
    assert (row.failure_threshold, row.recovery_threshold) == (3, 2)


@pytest.mark.parametrize("raw", STATUSES)
def test_first_ever_result_is_accepted_immediately(raw):
    state = step(None, raw, failure_threshold=10, recovery_threshold=10)

    assert state.confirmed == raw
    assert state.recent == (raw,)


# --- getting worse: threshold boundaries ---------------------------------------


@pytest.mark.parametrize("threshold", range(1, 11))
def test_down_is_confirmed_on_exactly_the_nth_down_in_a_row(threshold):
    confirmed = run(["healthy", *["down"] * threshold], failure_threshold=threshold)

    # Still healthy for the first threshold-1 lost pings, down on the last one.
    assert confirmed == ["healthy"] * threshold + ["down"]


def test_a_single_lost_ping_changes_nothing():
    assert run(["healthy", "down", "healthy", "healthy"]) == ["healthy"] * 4


def test_a_good_result_in_between_restarts_the_count():
    raws = ["healthy", "down", "down", "healthy", "down", "down", "down"]

    assert run(raws) == ["healthy"] * 6 + ["down"]


def test_healthy_to_degraded_uses_the_failure_threshold():
    assert run(["healthy", "degraded", "degraded", "degraded"]) == [
        "healthy", "healthy", "healthy", "degraded",
    ]


def test_degraded_to_down_needs_the_full_run_of_down_results():
    assert run(["degraded", "down", "down", "down"]) == [
        "degraded", "degraded", "degraded", "down",
    ]


def test_mixed_bad_results_confirm_the_mildest_of_them():
    # Never healthy, but never three "down" in a row either: the device is
    # reported as degraded, and only a full run of "down" takes it to down.
    raws = ["healthy", "down", "degraded", "down", "down", "down"]

    assert run(raws) == ["healthy", "healthy", "healthy", "degraded", "degraded", "down"]


# --- getting better: threshold boundaries --------------------------------------


@pytest.mark.parametrize("start", ["degraded", "down", "unknown"])
@pytest.mark.parametrize("threshold", range(1, 11))
def test_healthy_is_confirmed_on_exactly_the_nth_healthy_in_a_row(start, threshold):
    confirmed = run([start, *["healthy"] * threshold], recovery_threshold=threshold)

    assert confirmed == [start] * threshold + ["healthy"]


def test_a_bad_result_in_between_restarts_the_recovery_count():
    assert run(["down", "healthy", "down", "healthy", "healthy"]) == [
        "down", "down", "down", "down", "healthy",
    ]


def test_down_to_degraded_then_healthy():
    # Replies again, but slowly: two results better than "down" make it
    # degraded (the worse of the two), and two healthy ones make it healthy.
    assert run(["down", "healthy", "degraded", "healthy", "healthy"]) == [
        "down", "down", "degraded", "degraded", "healthy",
    ]


def test_full_outage_and_recovery_with_the_defaults():
    raws = ["healthy", "down", "down", "down", "down", "healthy", "healthy", "healthy"]

    assert run(raws) == [
        "healthy", "healthy", "healthy", "down", "down", "down", "healthy", "healthy",
    ]


# --- flapping input ------------------------------------------------------------


@pytest.mark.parametrize(
    "pattern",
    [
        ("down", "healthy"),
        ("down", "down", "healthy"),
        ("degraded", "healthy"),
        ("unknown", "healthy"),
        ("down", "degraded", "healthy"),
    ],
)
def test_flapping_results_never_change_a_healthy_device(pattern):
    raws = ["healthy", *itertools.islice(itertools.cycle(pattern), 60)]

    assert set(run(raws)) == {"healthy"}


def test_flapping_results_never_bring_a_down_device_back():
    raws = ["down", *itertools.islice(itertools.cycle(("healthy", "down")), 60)]

    assert set(run(raws)) == {"down"}


# --- "unknown" (the probe itself failed) ---------------------------------------


def test_a_single_probe_error_is_ignored():
    assert run(["healthy", "unknown", "healthy"]) == ["healthy"] * 3


def test_repeated_probe_errors_confirm_unknown():
    assert run(["healthy", "unknown", "unknown", "unknown"]) == [
        "healthy", "healthy", "healthy", "unknown",
    ]


def test_a_probe_error_counts_as_at_least_as_bad_as_down():
    # "unknown" ranks worst, so it does not break a run of "down" results.
    assert run(["healthy", "down", "unknown", "down"]) == [
        "healthy", "healthy", "healthy", "down",
    ]


def test_leaving_unknown_takes_the_recovery_threshold():
    assert run(["unknown", "healthy", "healthy"]) == ["unknown", "unknown", "healthy"]
    assert run(["unknown", "down", "down"]) == ["unknown", "unknown", "down"]


# --- threshold values ----------------------------------------------------------


def test_thresholds_of_one_switch_debouncing_off():
    rng = random.Random(7)
    raws = [rng.choice(STATUSES) for _ in range(300)]

    assert run(raws, failure_threshold=1, recovery_threshold=1) == raws


def test_the_two_thresholds_are_independent():
    # Fail fast, recover slowly.
    assert run(["healthy", "down", "healthy", "healthy", "healthy"], 1, 3) == [
        "healthy", "down", "down", "down", "healthy",
    ]


def test_out_of_range_thresholds_are_clamped_to_1_and_10():
    assert run(["healthy", "down"], failure_threshold=0) == ["healthy", "down"]
    assert run(["healthy", *["down"] * 9], failure_threshold=99)[-1] == "healthy"
    assert run(["healthy", *["down"] * 10], failure_threshold=99)[-1] == "down"


# --- thresholds changed live ---------------------------------------------------


def test_lowering_the_failure_threshold_counts_results_already_seen():
    state, confirmed = feed(None, ["healthy", "down", "down", "down"], failure_threshold=5)
    assert confirmed[-1] == "healthy"  # three of the five needed

    state = step(state, "down", failure_threshold=2)  # the admin lowers it to 2

    assert state.confirmed == "down"


def test_raising_the_failure_threshold_delays_a_pending_change():
    state, _ = feed(None, ["healthy", "down", "down"], failure_threshold=3)

    state = step(state, "down", failure_threshold=5)  # would have been confirmed at 3
    assert state.confirmed == "healthy"

    state, confirmed = feed(state, ["down", "down"], failure_threshold=5)
    assert confirmed == ["healthy", "down"]  # confirmed on the fifth


def test_lowering_the_recovery_threshold_counts_results_already_seen():
    state, confirmed = feed(None, ["down", "healthy", "healthy"], recovery_threshold=5)
    assert confirmed[-1] == "down"

    state = step(state, "healthy", recovery_threshold=3)

    assert state.confirmed == "healthy"


def test_changing_a_threshold_never_undoes_a_confirmed_status():
    state, confirmed = feed(None, ["healthy", "down", "down", "down"], failure_threshold=3)
    assert confirmed[-1] == "down"

    state = step(state, "down", failure_threshold=10)

    assert state.confirmed == "down"


# --- streak info ---------------------------------------------------------------


def test_streak_counters_follow_the_raw_results():
    state = None
    seen = []
    for raw in ["healthy", "healthy", "down", "degraded", "unknown", "healthy"]:
        state = step(state, raw)
        seen.append((state.consecutive_failures, state.consecutive_successes))

    # Anything that is not healthy counts as a failure.
    assert seen == [(0, 1), (0, 2), (1, 0), (2, 0), (3, 0), (0, 1)]


def test_streak_counters_keep_counting_past_the_remembered_window():
    state, _ = feed(None, ["healthy", *["down"] * 25])

    assert (state.consecutive_failures, state.consecutive_successes) == (25, 0)
    assert len(state.recent) == MAX_THRESHOLD  # only the last 10 raw results are kept


# --- every short sequence, checked against the rules ---------------------------


def _check_every_transition(raws: tuple[str, ...], failure_threshold: int, recovery_threshold: int) -> None:
    """Replay ``raws`` and check each step against the rules, using the full
    list of raw results rather than the state machine's own short memory."""
    state = None
    for index, raw in enumerate(raws):
        new = step(state, raw, failure_threshold, recovery_threshold)
        if state is None:
            assert new.confirmed == raw
        else:
            before = SEVERITY[state.confirmed]
            seen = raws[: index + 1]
            last_f = seen[-failure_threshold:]
            last_r = seen[-recovery_threshold:]
            all_worse = len(last_f) == failure_threshold and all(SEVERITY[s] > before for s in last_f)
            all_better = len(last_r) == recovery_threshold and all(SEVERITY[s] < before for s in last_r)
            if all_worse:
                expected = min(last_f, key=SEVERITY.get)
            elif all_better:
                expected = max(last_r, key=SEVERITY.get)
            else:
                expected = state.confirmed
            assert new.confirmed == expected, (raws[: index + 1], failure_threshold, recovery_threshold)

        # Invariants that tie the streak counters to the confirmed status.
        if new.consecutive_failures >= failure_threshold:
            assert new.confirmed != "healthy"
        if new.consecutive_successes >= recovery_threshold:
            assert new.confirmed == "healthy"
        state = new


@pytest.mark.parametrize("failure_threshold", [1, 2, 3])
@pytest.mark.parametrize("recovery_threshold", [1, 2, 3])
def test_every_sequence_of_up_to_five_results_follows_the_rules(failure_threshold, recovery_threshold):
    for length in range(1, 6):
        for raws in itertools.product(STATUSES, repeat=length):
            _check_every_transition(raws, failure_threshold, recovery_threshold)


def test_every_sequence_of_six_results_follows_the_rules_with_the_defaults():
    for raws in itertools.product(STATUSES, repeat=6):
        _check_every_transition(raws, DEFAULT_FAILURE_THRESHOLD, DEFAULT_RECOVERY_THRESHOLD)


def test_long_random_sequences_follow_the_rules_for_every_threshold_up_to_ten():
    # Longer than the 10 results the state machine remembers.
    rng = random.Random(2026)
    for _ in range(200):
        raws = tuple(rng.choices(STATUSES, weights=(5, 2, 4, 1), k=60))
        _check_every_transition(raws, rng.randint(1, 10), rng.randint(1, 10))


# --- Debouncer: the per-device holder used by the poll loop --------------------


def test_apply_returns_confirmed_readings_with_raw_status_and_streaks():
    debouncer = Debouncer()
    debouncer.apply([make_status("a", "healthy", 1.0), make_status("b", "healthy", 2.0)])
    second_cycle = [make_status("a", "down"), make_status("b", "healthy", 2.5)]

    confirmed = debouncer.apply(second_cycle)

    assert [
        (r.device_id, r.status, r.raw_status, r.consecutive_failures, r.consecutive_successes)
        for r in confirmed
    ] == [
        ("a", "healthy", "down", 1, 0),  # one lost ping: not confirmed yet
        ("b", "healthy", "healthy", 0, 2),
    ]
    # Latency and timestamp are those of this cycle's raw reading.
    assert confirmed[0].latency_ms is None
    assert confirmed[0].timestamp == second_cycle[0].timestamp
    assert confirmed[1].latency_ms == 2.5
    # The raw readings themselves are left untouched (history still needs them).
    assert (second_cycle[0].status, second_cycle[0].raw_status) == ("down", None)


def test_apply_uses_the_thresholds_it_is_given():
    debouncer = Debouncer()
    debouncer.apply([make_status("a", "healthy", 1.0)])

    (confirmed,) = debouncer.apply([make_status("a", "down")], failure_threshold=1, recovery_threshold=1)

    assert confirmed.status == "down"


def test_devices_are_debounced_independently():
    debouncer = Debouncer()
    debouncer.apply([make_status("a", "healthy", 1.0), make_status("b", "healthy", 1.0)])
    for _ in range(3):
        confirmed = debouncer.apply([make_status("a", "down"), make_status("b", "healthy", 1.0)])

    assert [r.status for r in confirmed] == ["down", "healthy"]


def test_state_of_a_device_that_is_no_longer_polled_is_dropped():
    debouncer = Debouncer()
    debouncer.apply([make_status("a", "healthy", 1.0), make_status("b", "healthy", 1.0)])
    assert set(debouncer.get_states()) == {"a", "b"}

    debouncer.apply([make_status("a", "down")])  # "b" was deleted
    assert set(debouncer.get_states()) == {"a"}

    # A device created later with the same id starts afresh: its first result
    # is accepted at once, while "a" is still one lost ping short of down.
    confirmed = debouncer.apply([make_status("a", "down"), make_status("b", "down")])
    assert [r.status for r in confirmed] == ["healthy", "down"]


# --- rebuilding state after a restart ------------------------------------------


def test_state_from_history_equals_the_state_the_machine_had():
    raws = ["healthy", "healthy", "down", "healthy", "down", "down"]
    state, _ = feed(None, raws)

    rebuilt = state_from_history(state.confirmed, raws)

    assert rebuilt == state
    # ...so the next result is judged exactly as it would have been.
    assert step(rebuilt, "down") == step(state, "down")
    assert step(rebuilt, "down").confirmed == "down"


def test_state_from_history_keeps_only_the_results_the_machine_remembers():
    raws = ["down"] * 36  # as many samples as the history cache reloads

    state = state_from_history("down", raws)

    assert state.recent == ("down",) * MAX_THRESHOLD
    # The streak can only be counted as far back as the stored results go.
    assert (state.consecutive_failures, state.consecutive_successes) == (36, 0)


def test_a_restored_device_is_not_treated_as_never_seen():
    debouncer = Debouncer()
    debouncer.restore({"a": state_from_history("healthy", ["healthy", "healthy"])})

    (confirmed,) = debouncer.apply([make_status("a", "down")])

    # One lost ping after the restart: still healthy, not "first result, so down".
    assert (confirmed.status, confirmed.raw_status, confirmed.consecutive_failures) == ("healthy", "down", 1)
