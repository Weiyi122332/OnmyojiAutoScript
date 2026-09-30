"""China server betting windows: seven two-hour rounds from 10:00 to 24:00."""
from datetime import datetime, time, timedelta, timezone


CHINA_TIME = timezone(timedelta(hours=8))
ROUND_HOURS = range(10, 24, 2)


def beijing_now() -> datetime:
    # The scheduler stores naive local timestamps; game times are Beijing times.
    return datetime.now(CHINA_TIME).replace(tzinfo=None)


def advance_delta(before_end: time) -> timedelta:
    advance = timedelta(hours=before_end.hour, minutes=before_end.minute,
                        seconds=before_end.second)
    if not timedelta(0) < advance <= timedelta(hours=2):
        raise ValueError('结束前下注时间必须大于 0 秒且不超过 2 小时')
    return advance


def next_bet_time(now: datetime, before_end: time, skip_current: bool = False) -> datetime:
    """Allow late starts within a round's betting window; skip completed rounds."""
    if now.tzinfo is not None:
        now = now.astimezone(CHINA_TIME)
    advance = advance_delta(before_end)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for offset in (0, 1):
        for hour in ROUND_HOURS:
            start = (day + timedelta(days=offset)).replace(hour=hour)
            end = start + timedelta(hours=2)
            if end <= now or (skip_current and start <= now < end):
                continue
            return max(now, end - advance)
    raise ValueError('无法计算对弈竞猜下次下注时间')
