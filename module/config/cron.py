# This Python file uses the following encoding: utf-8
"""crontab 表达式解析：给任务调度器用的「定时规则」。

支持的标准 5 字段写法（分 时 日 月 周）：

    *        任意取值
    5        具体取值
    1,3,5    列表
    1-5      区间
    */15     步长
    1-30/5   区间步长

月份可以写 jan..dec，星期可以写 sun..sat，星期日既可以写 0 也可以写 7。
另外支持 @hourly / @daily / @midnight / @weekly / @monthly / @yearly 简写。

「日」和「周」同时被限定时，按 crontab 的规则取「或」（满足任意一个就匹配）；
只限定其中一个时取「与」。时间都按本机时间（和调度器的其它时间设置一致）。
"""

from datetime import datetime, timedelta, time
from typing import Optional

MONTH_NAMES = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}
WEEKDAY_NAMES = {
    'sun': 0, 'mon': 1, 'tue': 2, 'wed': 3, 'thu': 4, 'fri': 5, 'sat': 6,
}
MACROS = {
    '@hourly': '0 * * * *',
    '@daily': '0 0 * * *',
    '@midnight': '0 0 * * *',
    '@weekly': '0 0 * * 0',
    '@monthly': '0 0 1 * *',
    '@yearly': '0 0 1 1 *',
    '@annually': '0 0 1 1 *',
}
# 向后搜索的上限（天）。写错规则时不会死循环，例如「2 月 30 号」。
MAX_SEARCH_DAYS = 366 * 8


class CronError(ValueError):
    """cron 表达式写错时抛出。"""


def _parse_value(text: str, minimum: int, maximum: int, names: dict = None) -> int:
    """解析单个取值，支持英文缩写。"""
    text = text.strip().lower()
    if names and text in names:
        return names[text]
    try:
        value = int(text)
    except ValueError:
        raise CronError(f'无法识别的取值 `{text}`')
    if value < minimum or value > maximum:
        raise CronError(f'取值 `{text}` 超出范围 {minimum}-{maximum}')
    return value


def _parse_field(text: str, minimum: int, maximum: int, names: dict = None) -> set:
    """把一个字段展开成取值集合。"""
    text = text.strip().lower()
    if not text:
        raise CronError('字段不能为空')

    result = set()
    for item in text.split(','):
        item = item.strip()
        if not item:
            raise CronError('列表里有空项')

        step = 1
        if '/' in item:
            item, _, step_text = item.partition('/')
            try:
                step = int(step_text.strip())
            except ValueError:
                raise CronError(f'步长 `{step_text}` 不是数字')
            if step <= 0:
                raise CronError(f'步长 `{step_text}` 必须大于 0')
            item = item.strip()

        if item in ('*', '?'):
            start, end = minimum, maximum
        elif '-' in item:
            left, _, right = item.partition('-')
            start = _parse_value(left, minimum, maximum, names)
            end = _parse_value(right, minimum, maximum, names)
            if start > end:
                raise CronError(f'区间 `{item}` 的起点大于终点')
        else:
            start = end = _parse_value(item, minimum, maximum, names)

        for value in range(start, end + 1, step):
            if minimum <= value <= maximum:
                result.add(value)

    if not result:
        raise CronError(f'字段 `{text}` 没有有效取值')
    return result


class CronExpression:
    """一条解析好的 cron 规则。"""

    def __init__(self, expression: str):
        self.expression = str(expression).strip()
        text = MACROS.get(self.expression.lower(), self.expression)
        fields = text.split()
        if len(fields) != 5:
            raise CronError('需要 5 个字段：分 时 日 月 周')

        self.minutes = _parse_field(fields[0], 0, 59)
        self.hours = _parse_field(fields[1], 0, 23)
        self.days = _parse_field(fields[2], 1, 31)
        self.months = _parse_field(fields[3], 1, 12, MONTH_NAMES)
        # 星期日既可以写 0 也可以写 7，统一成 0
        self.weekdays = {0 if value == 7 else value
                         for value in _parse_field(fields[4], 0, 7, WEEKDAY_NAMES)}
        self.day_restricted = fields[2].strip() not in ('*', '?')
        self.weekday_restricted = fields[4].strip() not in ('*', '?')
        self._minutes = sorted(self.minutes)
        self._hours = sorted(self.hours)

    def __str__(self) -> str:
        return self.expression

    __repr__ = __str__

    def _match_day(self, date_time) -> bool:
        """日 / 周 两个字段的组合判断。"""
        day_ok = date_time.day in self.days
        weekday_ok = ((date_time.weekday() + 1) % 7) in self.weekdays
        if self.day_restricted and self.weekday_restricted:
            return day_ok or weekday_ok
        return day_ok and weekday_ok

    def _match_date(self, date_time) -> bool:
        if date_time.month not in self.months:
            return False
        return self._match_day(date_time)

    def matches(self, date_time: datetime) -> bool:
        """判断某个时刻是否命中规则（秒忽略，只看分）。"""
        if date_time.month not in self.months:
            return False
        if date_time.hour not in self.hours or date_time.minute not in self.minutes:
            return False
        return self._match_day(date_time)

    def next_after(self, date_time: datetime, inclusive: bool = False) -> datetime:
        """
        取 date_time 之后的第一个命中时刻。

        :param date_time: 基准时间
        :param inclusive: True 时，如果 date_time 本身就是命中时刻就返回它自己
        :return: 命中时刻（秒为 0）
        """
        base = date_time.replace(second=0, microsecond=0)
        if base < date_time or (base == date_time and not inclusive):
            base += timedelta(minutes=1)
        return self._search(base)

    def _search(self, base: datetime) -> datetime:
        """从 base（整分钟）开始向后找第一个命中时刻。"""
        start_day = base.date()
        day = start_day
        for _ in range(MAX_SEARCH_DAYS):
            if self._match_date(day):
                start_hour = base.hour if day == start_day else 0
                start_minute = base.minute if day == start_day else 0
                for hour in self._hours:
                    if hour < start_hour:
                        continue
                    for minute in self._minutes:
                        if hour == start_hour and minute < start_minute:
                            continue
                        return datetime.combine(day, time(hour=hour, minute=minute))
            day += timedelta(days=1)
        raise CronError(f'cron `{self.expression}` 在 {MAX_SEARCH_DAYS} 天内没有匹配的时刻')


def parse_cron(expression: str) -> CronExpression:
    """
    解析 cron 表达式，写错时抛 CronError。

    :param expression: 例如 `0 5 * * *`
    :return: CronExpression
    """
    return CronExpression(expression)


def try_parse_cron(expression: str) -> Optional[CronExpression]:
    """
    解析 cron 表达式，空白或写错时返回 None（由调用方决定怎么提示）。

    :param expression: 例如 `0 5 * * *`
    :return: CronExpression 或 None
    """
    text = str(expression or '').strip()
    if not text:
        return None
    try:
        return CronExpression(text)
    except CronError:
        return None


def cron_error(expression: str) -> Optional[str]:
    """
    返回表达式的问题描述，正常时返回 None。用于给用户提示。

    :param expression: cron 表达式
    :return: 错误说明或 None
    """
    text = str(expression or '').strip()
    if not text:
        return None
    try:
        CronExpression(text)
    except CronError as error:
        return str(error)
    return None


if __name__ == '__main__':
    now = datetime(2026, 9, 24, 20, 0, 0)
    for rule in ('0 5 * * *', '30 20 * * 1', '*/30 9-23 * * *', '@daily'):
        print(rule, '->', CronExpression(rule).next_after(now))
    for rule in ('', '* * *', '0 25 * * *', '0 5 32 * *', 'bogus'):
        print(repr(rule), 'error:', cron_error(rule))
