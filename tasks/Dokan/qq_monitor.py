"""Read a specified person's group messages through NapCat; the scheduler operates the game."""

import hashlib
import html
import json
import math
import re
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from module.logger import logger
from tasks.Dokan.config import QQMessageConfig

CHINA_TZ = timezone(timedelta(hours=8))
STATE_PATH = Path('config/dokan_qq_messages.db')


def local_now():
    return datetime.now(CHINA_TZ)


def keywords(value):
    return [word.strip() for word in re.split(r'[\r\n|]+', value) if word.strip()]


def is_query_time(settings, now):
    current = now.astimezone(CHINA_TZ).time()
    start = settings.qq_query_start_time.replace(tzinfo=None)
    end = settings.qq_query_end_time.replace(tzinfo=None)
    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end


def message_text(message):
    content = message.get('message')
    if isinstance(content, list):
        return ''.join(segment['data'].get('text', '') for segment in content
                       if isinstance(segment, dict) and segment.get('type') == 'text'
                       and isinstance(segment.get('data'), dict)
                       and isinstance(segment['data'].get('text', ''), str))
    raw = content if isinstance(content, str) else message.get('raw_message', '')
    if isinstance(raw, str):
        return html.unescape(re.sub(r'\[CQ:[^\]]*\]', '', raw))
    return ''


def fingerprint(settings):
    values = [settings.napcat_api_url.strip().rstrip('/'), settings.qq_group_id.strip(),
              settings.qq_member_id.strip(), keywords(settings.qq_keywords),
              keywords(settings.qq_excluded_keywords)]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def latest_trigger_message(messages, settings, now):
    """Return the latest opening/cancellation, ignoring other senders and stale messages."""
    matched = []
    for message in messages:
        if not isinstance(message, dict) or message.get('anonymous'):
            continue
        if message.get('post_type', 'message') != 'message':
            continue
        if message.get('message_type', 'group') != 'group':
            continue
        sender = message.get('sender') or {}
        member = message.get('user_id', sender.get('user_id') if isinstance(sender, dict) else None)
        if str(message.get('group_id', settings.qq_group_id.strip())) != settings.qq_group_id.strip() \
                or str(member) != settings.qq_member_id.strip():
            continue
        try:
            timestamp = float(message['time'])
            if not math.isfinite(timestamp):
                continue
            sent_at = datetime.fromtimestamp(timestamp, CHINA_TZ)
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
        if sent_at.date() != now.date() or sent_at > now:
            continue
        text = message_text(message)
        excluded = any(word in text for word in keywords(settings.qq_excluded_keywords))
        opening = any(word in text for word in keywords(settings.qq_keywords))
        if excluded or opening:
            identity = [message.get('message_id'), timestamp, text]
            key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
            matched.append((timestamp, key, opening and not excluded))
    return max(matched, key=lambda item: (item[0], not item[2])) if matched else None


def fetch_group_messages(session, settings, now):
    started = time.monotonic()
    if not is_query_time(settings, now):
        return None
    base = settings.napcat_api_url.strip().rstrip('/')
    parsed = urlparse(base)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username \
            or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Invalid NapCat HTTP endpoint')
    if not settings.qq_group_id.strip().isdigit() or int(settings.qq_group_id.strip()) <= 0 \
            or not settings.qq_member_id.strip().isdigit() or int(settings.qq_member_id.strip()) <= 0 \
            or not keywords(settings.qq_keywords):
        raise ValueError('Missing group, member or opening keywords')
    url = base if base.endswith('/get_group_msg_history') else base + '/get_group_msg_history'
    headers = {'Authorization': 'Bearer ' + settings.napcat_access_token} if settings.napcat_access_token else {}
    messages, cursors, cursor = [], set(), None
    for _ in range(settings.qq_history_max_pages):
        query_now = now + timedelta(seconds=time.monotonic() - started)
        if not is_query_time(settings, query_now):
            break
        payload = {'group_id': settings.qq_group_id.strip(), 'count': settings.qq_history_page_size,
                   'reverse_order': False, 'disable_get_url': True, 'parse_mult_msg': False}
        if cursor is not None:
            payload['message_seq'] = cursor
        response = session.post(url, json=payload, headers=headers, timeout=(3, 8), allow_redirects=False)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get('status') != 'ok' or body.get('retcode') != 0:
            raise ValueError('NapCat history request failed')
        data = body.get('data')
        page = data.get('messages') if isinstance(data, dict) else None
        if not isinstance(page, list):
            raise ValueError('NapCat returned no message list')
        messages.extend(page)
        # Each page is read before deciding, so a newer cancellation wins over an old opening.
        query_now = now + timedelta(seconds=time.monotonic() - started)
        message_match = latest_trigger_message(messages, settings, query_now)
        dated = []
        for message in page:
            try:
                stamp = float(message['time'])
                if math.isfinite(stamp):
                    dated.append((stamp, str(message.get('message_id', ''))))
            except (KeyError, TypeError, ValueError):
                continue
        if message_match is not None or not dated:
            return message_match
        oldest, next_cursor = min(dated)
        if oldest < datetime.combine(query_now.date(), datetime.min.time(), CHINA_TZ).timestamp() \
                or not next_cursor or next_cursor in cursors:
            break
        cursors.add(next_cursor)
        cursor = next_cursor
    return latest_trigger_message(messages, settings, now + timedelta(seconds=time.monotonic() - started))


class QQDokanState:
    """Persist only a message hash and permission; no QQ message text or credentials."""

    def __init__(self, profile, path=STATE_PATH):
        self.profile = profile
        self.path = Path(path)

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=3)
        connection.execute('''CREATE TABLE IF NOT EXISTS dokan_qq_permit (
            profile TEXT PRIMARY KEY, day TEXT, fingerprint TEXT, message_key TEXT,
            allowed INTEGER, started INTEGER)''')
        return connection

    def flags(self, settings, now=None):
        if not settings.qq_message_enable or not self.path.exists():
            return False, False
        now = now or local_now()
        with closing(self._connect()) as connection, connection:
            row = connection.execute('SELECT allowed, started FROM dokan_qq_permit '
                                     'WHERE profile=? AND day=? AND fingerprint=?',
                                     (self.profile, now.date().isoformat(), fingerprint(settings))).fetchone()
        return (bool(row[0]), bool(row[0]) and not row[1]) if row else (False, False)

    def record(self, settings, message_match, now):
        if message_match is None:
            return
        _, key, allowed = message_match
        context = (self.profile, now.date().isoformat(), fingerprint(settings))
        with closing(self._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT message_key, allowed, started FROM dokan_qq_permit '
                                     'WHERE profile=? AND day=? AND fingerprint=?', context).fetchone()
            if row and row[:2] == (key, int(allowed)):
                return
            started = row[2] if row else 0
            connection.execute('INSERT OR REPLACE INTO dokan_qq_permit VALUES (?, ?, ?, ?, ?, ?)',
                               (*context, key, int(allowed), started))

    def consume(self, settings, now=None):
        now = now or local_now()
        if not self.path.exists():
            return
        with closing(self._connect()) as connection, connection:
            connection.execute('UPDATE dokan_qq_permit SET started=1 '
                               'WHERE profile=? AND day=? AND fingerprint=? AND allowed=1',
                               (self.profile, now.date().isoformat(), fingerprint(settings)))


class DokanQQMonitor:
    def __init__(self, profile, state_path=STATE_PATH):
        self.profile = profile
        self.state = QQDokanState(profile, state_path)
        self.ready = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._last_error = None
        self._last_error_at = 0.0
        self._settings_stamp = None
        self._settings_cache = None

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name='DokanQQMonitor', daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()

    def _load_settings(self):
        # Do not access the running task's mutable Config from the worker thread.
        path = Path('config') / f'{self.profile}.json'
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
        if stamp == self._settings_stamp:
            return self._settings_cache
        data = json.loads(path.read_text('utf-8'))
        dokan = data.get('dokan', {})
        result = (QQMessageConfig.model_validate(dokan.get('qq_message_config', {})),
                  bool(dokan.get('scheduler', {}).get('enable', False)))
        self._settings_stamp, self._settings_cache = stamp, result
        return result

    def poll_once(self, session, settings, task_enabled=True, now=None):
        if not settings.qq_message_enable or not task_enabled:
            self.ready.clear()
            return
        now = now or local_now()
        allowed, before = self.state.flags(settings, now)
        if allowed or not is_query_time(settings, now):
            # A matched day stays quiet even after restart or before its task can start.
            if before:
                self.ready.set()
            else:
                self.ready.clear()
            return
        started = time.monotonic()
        match = fetch_group_messages(session, settings, now)
        now += timedelta(seconds=time.monotonic() - started)
        self.state.record(settings, match, now)
        pending = self.state.flags(settings, now)[1]
        if pending:
            self.ready.set()
            if not before:
                logger.info('QQ福利寮开启消息已匹配，等待当前任务结束后优先运行道馆')
        else:
            self.ready.clear()

    def _run(self):
        with requests.Session() as session:
            session.trust_env = False
            next_poll, previous = 0.0, None
            while not self._stop.is_set():
                interval = 60
                try:
                    settings, task_enabled = self._load_settings()
                    interval = settings.qq_poll_interval
                    now = local_now()
                    current = (settings.model_dump_json(), task_enabled, now.date(), is_query_time(settings, now))
                    if current != previous:
                        next_poll, previous = 0.0, current
                    if time.monotonic() < next_poll:
                        self._stop.wait(min(1, next_poll - time.monotonic()))
                        continue
                    self.poll_once(session, settings, task_enabled, now)
                    self._last_error = None
                except Exception as exc:
                    error = type(exc).__name__
                    if error != self._last_error or time.monotonic() - self._last_error_at >= 60:
                        logger.warning(f'NapCat道馆消息检查失败（{error}），按检测间隔重试')
                        self._last_error, self._last_error_at = error, time.monotonic()
                    # A failed request cannot open the gate or consume the pending trigger.
                next_poll = time.monotonic() + interval
                self._stop.wait(min(1, interval))
