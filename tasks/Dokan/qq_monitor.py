"""Read today's welfare status from the TRSS-Yunzai plugin; the scheduler operates the game."""

import hashlib
import json
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


def is_query_time(settings, now):
    current = now.astimezone(CHINA_TZ).time()
    start = settings.qq_query_start_time.replace(tzinfo=None)
    end = settings.qq_query_end_time.replace(tzinfo=None)
    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end


def fingerprint(settings):
    values = ['welfare-plugin-v1', settings.welfare_plugin_url.strip().rstrip('/'),
              hashlib.sha256(settings.welfare_plugin_token.encode()).hexdigest()]
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def fetch_welfare_status(session, settings, now):
    if not is_query_time(settings, now):
        return None
    url = settings.welfare_plugin_url.strip().rstrip('/')
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username \
            or parsed.password or parsed.query or parsed.fragment or not parsed.path.strip('/'):
        raise ValueError('Invalid welfare plugin status URL')
    if not settings.welfare_plugin_token.strip():
        raise ValueError('Missing welfare plugin token')
    response = session.get(url, headers={'Authorization': 'Bearer ' + settings.welfare_plugin_token},
                           timeout=(3, 8), allow_redirects=False)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or type(body.get('opened')) is not bool \
            or not isinstance(body.get('date'), str):
        raise ValueError('Invalid welfare plugin status')
    if body['date'] != now.astimezone(CHINA_TZ).date().isoformat():
        return None
    return body


class QQDokanState:
    """Persist the daily permission and consumption state; no messages or credentials."""

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
                                     (self.profile, now.astimezone(CHINA_TZ).date().isoformat(), fingerprint(settings))).fetchone()
        return (bool(row[0]), bool(row[0]) and not row[1]) if row else (False, False)

    def record(self, settings, status, now):
        if not isinstance(status, dict) or status.get('opened') is not True \
                or status.get('date') != now.astimezone(CHINA_TZ).date().isoformat():
            return
        key, allowed = status['date'], True
        context = (self.profile, now.astimezone(CHINA_TZ).date().isoformat(), fingerprint(settings))
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
                               (self.profile, now.astimezone(CHINA_TZ).date().isoformat(), fingerprint(settings)))


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
        status = fetch_welfare_status(session, settings, now)
        now += timedelta(seconds=time.monotonic() - started)
        self.state.record(settings, status, now)
        pending = self.state.flags(settings, now)[1]
        if pending:
            self.ready.set()
            if not before:
                logger.info('TRSS-Yunzai插件已确认今天开启福利寮，等待当前任务结束后优先运行道馆')
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
                        logger.warning(f'TRSS-Yunzai福利寮状态检查失败（{error}），按检测间隔重试')
                        self._last_error, self._last_error_at = error, time.monotonic()
                    # A failed request cannot open the gate or consume the pending trigger.
                next_poll = time.monotonic() + interval
                self._stop.wait(min(1, interval))
