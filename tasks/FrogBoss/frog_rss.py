"""Follow Mianlingqi Miao's RSS predictions for the current China server round.

Source logic: zzliux/assttyys_autojs, src/common/funcList/401_对弈竞猜.ts
https://github.com/zzliux/assttyys_autojs/tree/57350f30ccf205c62e308a1916772c07919c2743
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from math import isfinite
from numbers import Real
import re
from typing import Optional
from xml.etree import ElementTree

import requests


RSS_URL = 'https://rsshub.zzliux.cn/163/ds/462382f1127b46c5add1185d88f0ea40'
CHINA_TIME = timezone(timedelta(hours=8))
_TIME = re.compile(r'(?<!\d)([01]?\d|2[0-3])[:：]([0-5]\d)(?!\d)')
_HINT = re.compile(r'翻盘|[左右红蓝]')


def _china_now(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now(CHINA_TIME)
    if now.tzinfo is None:
        now = now.replace(tzinfo=CHINA_TIME)
    return now.astimezone(CHINA_TIME)


def round_start(now: Optional[datetime] = None) -> datetime:
    now = _china_now(now)
    return now.replace(hour=now.hour // 2 * 2, minute=0, second=0, microsecond=0)


class _FeedText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in ('br', 'p', 'div'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('p', 'div'):
            self.parts.append('\n')


def _plain_text(text: str) -> str:
    parser = _FeedText()
    parser.feed(unescape(text))
    return ''.join(parser.parts)


@dataclass(frozen=True)
class RssPrediction:
    hint: str
    round_start: datetime
    published_at: datetime
    title: str
    link: str

    def choose_side(self, left, right) -> str:
        if self.hint in ('左', '红'):
            return 'LEFT'
        if self.hint in ('右', '蓝'):
            return 'RIGHT'
        # The reference treats 翻盘 as the minority; equal counts choose right.
        if not all(isinstance(n, Real) and isfinite(n) and n >= 0 for n in (left, right)) or left + right <= 0:
            raise ValueError('翻盘建议需要有效的左右下注人数')
        return 'LEFT' if left < right else 'RIGHT'


def parse_prediction(feed: bytes, now: Optional[datetime] = None) -> Optional[RssPrediction]:
    """Read the latest five non-test-server items, with date and round checks."""
    now = _china_now(now)
    current_round = round_start(now)
    items_seen = 0
    for item in ElementTree.fromstring(feed).findall('./channel/item'):
        title = _plain_text(item.findtext('title', ''))
        description = _plain_text(item.findtext('description', ''))
        if '体验服' in title + description:
            continue
        items_seen += 1
        if items_seen > 5:
            break
        try:
            published = parsedate_to_datetime(item.findtext('pubDate', ''))
            if published.tzinfo is None:
                continue
            published = published.astimezone(CHINA_TIME)
        except (TypeError, ValueError, OverflowError):
            continue
        if published.date() != now.date() or published > now:
            continue

        text = description if '对弈竞猜' in description else title + '\n' + description
        heading = text.find('对弈竞猜')
        if heading < 0:
            continue
        text = text[heading:]
        times = list(_TIME.finditer(text))
        for index, stamp in enumerate(times):
            if int(stamp[1]) != current_round.hour or int(stamp[2]) != 0:
                continue
            end = times[index + 1].start() if index + 1 < len(times) else len(text)
            segment = text[stamp.end():end]
            # Do not borrow a previous result or another round's recommendation.
            segment = re.split(r'上局|上一局|上场|上一场', segment, maxsplit=1)[0]
            hint = _HINT.search(segment)
            if hint:
                return RssPrediction(hint[0], current_round, published, title,
                                     item.findtext('link', ''))
    return None


def fetch_prediction(now: Optional[datetime] = None) -> Optional[RssPrediction]:
    """Fetch once with bounded network waits; caller schedules failed retries."""
    response = requests.get(RSS_URL, timeout=(3, 5))
    response.raise_for_status()
    return parse_prediction(response.content, now)
