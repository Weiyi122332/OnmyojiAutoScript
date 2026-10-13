"""Timing for the two wheel movements in a dojo candidate list."""

import time
from random import randint, uniform


WHEEL_COUNT_RANGES = ((9, 9), (5, 6))
WHEEL_POINT = (1165, 400)  # Inside the right candidate list, above the refresh button.
WHEEL_INTERVAL_RANGE = (0.05, 0.15)
WHEEL_DURATION_RANGE = (0.75, 1.0)
WHEEL_SETTLE_DELAY = 1.5


def choose_wheel_count(screen_index: int) -> int:
    if screen_index not in (1, 2):
        raise ValueError('Only the second and third list screens need wheel movements')
    minimum, maximum = WHEEL_COUNT_RANGES[screen_index - 1]
    return minimum if minimum == maximum else randint(minimum, maximum)


def wheel_intervals(count: int) -> list[float]:
    """Randomize gaps while fitting the whole first-to-last notch duration."""
    gaps = count - 1
    minimum, maximum = WHEEL_INTERVAL_RANGE
    if gaps < 1:
        raise ValueError('A wheel batch needs at least two events')
    # Five or six notches cannot provide a random 0.75–1s span with these gaps.
    # Preserve the requested counts and random gap bounds for the shorter batch.
    if gaps * maximum <= WHEEL_DURATION_RANGE[0]:
        return [uniform(minimum, maximum) for _ in range(gaps)]
    lower = max(WHEEL_DURATION_RANGE[0], gaps * minimum)
    upper = min(WHEEL_DURATION_RANGE[1], gaps * maximum)
    if lower > upper:
        raise ValueError(f'Cannot fit {count} wheel events into the configured timing ranges')
    remaining_time = uniform(lower, upper)
    intervals = []
    for remaining_gaps in range(gaps, 0, -1):
        if remaining_gaps == 1:
            interval = remaining_time
        else:
            interval = uniform(max(minimum, remaining_time - (remaining_gaps - 1) * maximum),
                               min(maximum, remaining_time - (remaining_gaps - 1) * minimum))
        intervals.append(interval)
        remaining_time -= interval
    return intervals


def scroll_dokan_list(client, count: int) -> float:
    """Connect and position the mouse before timing; settle after the last notch."""
    intervals = wheel_intervals(count)
    client.connect()
    client.prepare_scroll(*WHEEL_POINT)
    started = time.monotonic()
    client.scroll(*WHEEL_POINT)
    next_event = started
    last_event_started = started
    for interval in intervals:
        # Include ADB delivery in the inter-event gaps instead of adding its
        # latency to every randomized sleep.
        next_event += interval
        delay = max(next_event, last_event_started + WHEEL_INTERVAL_RANGE[0]) - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        last_event_started = time.monotonic()
        client.scroll(*WHEEL_POINT)
    elapsed = time.monotonic() - started
    time.sleep(WHEEL_SETTLE_DELAY)
    return elapsed
