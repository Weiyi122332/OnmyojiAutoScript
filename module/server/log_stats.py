# This Python file uses the following encoding: utf-8
from __future__ import annotations

import asyncio
import copy
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path.cwd().resolve()
LOG_ROOT = (PROJECT_ROOT / "log").resolve()
POLL_INTERVAL_SECONDS = 1.0
HISTORICAL_CACHE_TTL = timedelta(hours=1)
_LOG_FILE_RE = re.compile(r"^(?P<day>\d{4}-\d{2}-\d{2})_(?P<script>.+)\.txt$")

_TIMESTAMP_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\s+\|")
_TASK_LINE_RE = re.compile(r"\[Task\]\s+(?P<task>[A-Za-z0-9_]+)\s+\(")
_EQ_LINE_RE = re.compile(r"^═{15,}\s*$")
_EQ_TITLE_LINE_RE = re.compile(r"^═{10,}\s+(?P<title>.*?)\s+═{10,}\s*$")
_TITLE_LINE_RE = re.compile(r"^─{10,}\s*(?P<title>.*?)\s*─{10,}\s*$")
_TASK_ENDED_RE = re.compile(r"^(?P<title>.+?)\s+task ended\b", re.IGNORECASE)
_SCHEDULER_TASK_END_RE = re.compile(r"^Scheduler:\s*End task\s+`(?P<task>[A-Za-z0-9_]+)`", re.IGNORECASE)
_TASK_GROUP_RE = re.compile(r"^TASKGROUP(?:[1-5])?$", re.IGNORECASE)
_TASK_GROUP_ITEM_RE = re.compile(
    r"^TASK GROUP \[\d+/\d+\]:\s*(?P<task>[A-Za-z0-9_]+)$", re.IGNORECASE
)
_TASK_GROUP_ITEM_FINISHED_RE = re.compile(
    r"^Task group:\s*`(?P<task>[A-Za-z0-9_]+)` finished\b", re.IGNORECASE
)
_TASK_GROUP_ITEM_RAISED_RE = re.compile(
    r"^Task group(?:\s+`[^`]+`)?\s*:\s*`(?P<task>[A-Za-z0-9_]+)` raised\b",
    re.IGNORECASE,
)
_TASK_GROUP_FINISHED_RE = re.compile(
    r"^Task group(?:\s+`[^`]+`)? finished(?: with error)?\b", re.IGNORECASE
)
_BATTLE_TITLE = "GENERAL BATTLE START"
_START_TITLE = "START"
_SIX_REALMS_TITLE = "SIXREALMS"
_SIX_REALMS_TASK_NAMES = {
    "MOONSEA": "MoonSea",
    "PEACOCKKINGDOM": "PeacockKingdom",
}
_TASK_ROOT = Path(__file__).resolve().parents[2] / "tasks"
_TASK_NAMES = {
    path.name.upper(): path.name
    for path in _TASK_ROOT.iterdir()
    if path.is_dir()
} if _TASK_ROOT.is_dir() else {}


@dataclass
class BattleState:
    start_time: datetime | None = None
    last_time: datetime | None = None


@dataclass
class TaskRunState:
    name: str
    start_time: datetime | None = None
    last_time: datetime | None = None
    battle_count: int = 0
    battle_total_duration_seconds: float = 0.0


@dataclass
class RuntimeState:
    saw_start_boundary: bool = False
    pre_start_first: datetime | None = None
    region_last: datetime | None = None
    session_start: datetime | None = None
    total_duration: float = 0.0


@dataclass
class HistoricalStatsCacheEntry:
    expires_at: datetime
    payload: dict[str, Any]


class LogStatsParser:
    def __init__(self) -> None:
        self.summary: dict[str, dict[str, Any]] = {}
        self.runtime = RuntimeState()
        self._pending_task_name: str | None = None
        self._pending_task_start_name: str | None = None
        self._pending_battle_start = False
        self._active_task: TaskRunState | None = None
        self._active_battle: BattleState | None = None
        self._six_realms_active = False
        self._six_realms_start_time: datetime | None = None
        self._six_realms_last_time: datetime | None = None
        self._six_realms_seen_subtask = False
        self._active_group_item_name: str | None = None

    def consume_lines(self, lines: list[str]) -> None:
        index = 0
        total = len(lines)
        while index < total:
            line = lines[index].rstrip("\r\n")

            if self._is_task_boundary(lines, index):
                title = self._extract_boundary_title(lines[index + 1])
                self._handle_task_boundary(title)
                index += 3
                continue

            equal_title = self._extract_equal_boundary_title(line)
            if equal_title is not None and self._handle_equal_boundary(equal_title):
                index += 1
                continue

            if self._is_battle_boundary(line):
                if not self._six_realms_active:
                    self._handle_battle_boundary()
                index += 1
                continue

            self._consume_regular_line(line)
            index += 1

    def snapshot(self, script_name: str = "", tail_lines: list[str] | None = None) -> dict[str, Any]:
        parser = copy.deepcopy(self)
        if tail_lines:
            parser.consume_lines(tail_lines)
        parser._close_active_battle()
        parser._close_active_task()

        tasks = parser._build_tasks_payload()
        return {
            "script_name": script_name,
            "total_runtime_seconds": parser._current_total_runtime(),
            "total_task_run_count": sum(task["run_count"] for task in tasks.values()),
            "total_battle_count": sum(
                0 if task["battle"] is None else int(task["battle"]["count"])
                for task in tasks.values()
            ),
            "tasks": tasks,
        }

    @classmethod
    def parse_lines(cls, lines: list[str], script_name: str = "") -> dict[str, Any]:
        parser = cls()
        parser.consume_lines(lines)
        return parser.snapshot(script_name=script_name)

    @staticmethod
    def _is_task_boundary(lines: list[str], index: int) -> bool:
        if index + 2 >= len(lines):
            return False
        return bool(
            _EQ_LINE_RE.match(lines[index].strip())
            and _TITLE_LINE_RE.match(lines[index + 1].strip())
            and _EQ_LINE_RE.match(lines[index + 2].strip())
        )

    @staticmethod
    def _extract_boundary_title(line: str) -> str:
        matched = _TITLE_LINE_RE.match(line.strip())
        return matched.group("title").strip() if matched else ""

    @staticmethod
    def _extract_equal_boundary_title(line: str) -> str | None:
        matched = _EQ_TITLE_LINE_RE.match(line.strip())
        if not matched:
            return None
        title = matched.group("title").strip()
        return title or None

    @staticmethod
    def _extract_timestamp(line: str) -> datetime | None:
        matched = _TIMESTAMP_RE.match(line.strip())
        if not matched:
            return None
        return datetime.strptime(matched.group("ts"), "%Y-%m-%d %H:%M:%S.%f")

    @staticmethod
    def _extract_task_ended_title(line: str) -> str | None:
        message = line.rsplit("|", 1)[-1].strip()
        matched = _TASK_ENDED_RE.match(message)
        return matched.group("title").strip() if matched else None

    @staticmethod
    def _is_battle_boundary(line: str) -> bool:
        matched = _TITLE_LINE_RE.match(line.strip())
        if not matched:
            return False
        return matched.group("title").strip().upper() == _BATTLE_TITLE

    @staticmethod
    def _normalize_title(title: str) -> str:
        return re.sub(r"\s+", "", title).upper()

    @classmethod
    def _is_six_realms_title(cls, title: str) -> bool:
        return cls._normalize_title(title) == _SIX_REALMS_TITLE

    @classmethod
    def _format_six_realms_task_name(cls, title: str) -> str:
        stripped = re.sub(r"\s+", " ", title.strip())
        normalized = cls._normalize_title(stripped)
        if normalized in _SIX_REALMS_TASK_NAMES:
            return _SIX_REALMS_TASK_NAMES[normalized]
        return stripped.title() if stripped.isupper() else stripped

    def _handle_task_boundary(self, title: str) -> None:
        self._close_active_battle()
        self._close_active_task()
        self._reset_six_realms_state()
        self._active_group_item_name = None
        if title.upper() == _START_TITLE:
            self._handle_start_boundary()
            self._pending_task_start_name = None
            return
        if _TASK_GROUP_RE.fullmatch(title):
            # The wrapper schedules the group, but statistics belong to its items.
            self._pending_task_name = None
            self._pending_task_start_name = None
            return
        if self._is_six_realms_title(title):
            self._six_realms_active = True
            self._pending_task_name = None
            self._pending_task_start_name = None
            return
        self._pending_task_start_name = self._pending_task_name or title
        self._pending_task_name = None

    def _handle_equal_boundary(self, title: str) -> bool:
        group_item = _TASK_GROUP_ITEM_RE.fullmatch(title)
        if group_item is not None:
            self._close_active_battle()
            self._close_active_task()
            self._reset_six_realms_state()
            task_name = _TASK_NAMES.get(group_item.group("task").upper(), group_item.group("task"))
            self._active_group_item_name = task_name
            if self._is_six_realms_title(task_name):
                self._six_realms_active = True
                self._pending_task_start_name = None
            else:
                self._pending_task_start_name = task_name
            return True

        if not self._six_realms_active:
            return False

        task_name = self._format_six_realms_task_name(title)
        self._close_active_battle()
        self._close_active_task()
        self._active_task = TaskRunState(
            name=task_name,
            start_time=self._six_realms_start_time if not self._six_realms_seen_subtask else None,
            last_time=self._six_realms_last_time if not self._six_realms_seen_subtask else None,
        )
        self._six_realms_seen_subtask = True
        self._pending_battle_start = True
        return True

    def _reset_six_realms_state(self) -> None:
        self._six_realms_active = False
        self._six_realms_start_time = None
        self._six_realms_last_time = None
        self._six_realms_seen_subtask = False

    def _handle_start_boundary(self) -> None:
        runtime = self.runtime
        if not runtime.saw_start_boundary:
            runtime.saw_start_boundary = True
            runtime.total_duration = self._append_duration(
                runtime.total_duration,
                runtime.pre_start_first,
                runtime.region_last,
            )
        else:
            runtime.total_duration = self._append_duration(
                runtime.total_duration,
                runtime.session_start,
                runtime.region_last,
            )
        runtime.session_start = None
        runtime.region_last = None

    def _handle_battle_boundary(self) -> None:
        self._close_active_battle()
        if self._active_task is not None:
            self._pending_battle_start = True

    def _consume_regular_line(self, line: str) -> None:
        matched = _TASK_LINE_RE.search(line)
        if matched:
            self._pending_task_name = matched.group("task").strip()

        ts = self._extract_timestamp(line)
        if ts is None:
            return

        self._consume_runtime_timestamp(ts)
        self._consume_six_realms_timestamp(ts)

        if self._pending_task_start_name:
            self._active_task = TaskRunState(name=self._pending_task_start_name, start_time=ts, last_time=ts)
            self._pending_task_start_name = None
        elif self._active_task is not None:
            if self._active_task.start_time is None:
                self._active_task.start_time = ts
            self._active_task.last_time = ts

        if self._pending_battle_start and self._active_task is not None:
            self._active_battle = BattleState(start_time=ts, last_time=ts)
            self._pending_battle_start = False
        elif self._active_battle is not None:
            self._active_battle.last_time = ts

        task_ended_title = self._extract_task_ended_title(line)
        if task_ended_title is not None:
            self._handle_task_ended(task_ended_title)

        message = line.rsplit("|", 1)[-1].strip()
        self._handle_task_group_message(message)
        self._handle_scheduler_task_end(message)

    def _handle_scheduler_task_end(self, message: str) -> None:
        matched = _SCHEDULER_TASK_END_RE.match(message)
        if matched is None:
            return

        task_name = matched.group("task")
        if self._is_six_realms_title(task_name) and self._six_realms_active:
            self._close_active_battle()
            self._close_active_task()
            self._reset_six_realms_state()
            return

        if _TASK_GROUP_RE.fullmatch(task_name) and self._active_group_item_name is not None:
            self._close_active_battle()
            self._close_active_task()
            self._reset_six_realms_state()
            self._active_group_item_name = None
            return

        if self._active_task is None or self._normalize_title(task_name) != self._normalize_title(self._active_task.name):
            return
        self._close_active_battle()
        self._close_active_task()

    def _handle_task_group_message(self, message: str) -> None:
        if self._active_group_item_name is None:
            return
        item_end = _TASK_GROUP_ITEM_FINISHED_RE.match(message)
        if item_end is None:
            item_end = _TASK_GROUP_ITEM_RAISED_RE.match(message)
        item_matches = (
            item_end is not None
            and self._normalize_title(item_end.group("task"))
            == self._normalize_title(self._active_group_item_name)
        )
        if item_matches or _TASK_GROUP_FINISHED_RE.match(message):
            self._close_active_battle()
            self._close_active_task()
            self._reset_six_realms_state()
            self._active_group_item_name = None

    def _consume_runtime_timestamp(self, ts: datetime) -> None:
        runtime = self.runtime
        runtime.region_last = ts
        if not runtime.saw_start_boundary:
            if runtime.pre_start_first is None:
                runtime.pre_start_first = ts
            return
        if runtime.session_start is None:
            runtime.session_start = ts

    def _consume_six_realms_timestamp(self, ts: datetime) -> None:
        if not self._six_realms_active or self._six_realms_seen_subtask:
            return
        if self._six_realms_start_time is None:
            self._six_realms_start_time = ts
        self._six_realms_last_time = ts

    def _handle_task_ended(self, title: str) -> None:
        if not self._six_realms_active or self._active_task is None:
            return
        if self._normalize_title(title) != self._normalize_title(self._active_task.name):
            return
        self._close_active_battle()
        self._close_active_task()
        self._six_realms_start_time = None
        self._six_realms_last_time = None

    def _close_active_battle(self) -> None:
        if self._active_task is None or self._active_battle is None:
            self._active_battle = None
            self._pending_battle_start = False
            return

        start_time = self._active_battle.start_time
        end_time = self._active_battle.last_time
        if start_time is not None and end_time is not None and end_time >= start_time:
            duration = round((end_time - start_time).total_seconds(), 3)
            self._active_task.battle_count += 1
            self._active_task.battle_total_duration_seconds = round(
                self._active_task.battle_total_duration_seconds + duration,
                3,
            )

        self._active_battle = None
        self._pending_battle_start = False

    def _close_active_task(self) -> None:
        if self._active_task is None:
            self._pending_task_start_name = None
            return

        start_time = self._active_task.start_time
        end_time = self._active_task.last_time
        if start_time is None or end_time is None or end_time < start_time:
            self._active_task = None
            self._pending_task_start_name = None
            return

        duration = round((end_time - start_time).total_seconds(), 3)
        task_data = self.summary.setdefault(
            self._active_task.name,
            {
                "run_count": 0,
                "total_duration_seconds": 0.0,
                "battle_count": 0,
                "battle_total_duration_seconds": 0.0,
                "runs": [],
            },
        )
        task_data["run_count"] += 1
        task_data["total_duration_seconds"] = round(task_data["total_duration_seconds"] + duration, 3)
        task_data["battle_count"] += self._active_task.battle_count
        task_data["battle_total_duration_seconds"] = round(
            task_data["battle_total_duration_seconds"] + self._active_task.battle_total_duration_seconds,
            3,
        )
        task_data["runs"].append(
            {
                "start_time": start_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                "end_time": end_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                "duration_seconds": duration,
                "battle": self._build_battle_payload(
                    self._active_task.battle_count,
                    self._active_task.battle_total_duration_seconds,
                ),
            }
        )

        self._active_task = None
        self._pending_task_start_name = None

    def _build_tasks_payload(self) -> dict[str, dict[str, Any]]:
        cleaned_tasks: dict[str, dict[str, Any]] = {}
        for task_name, task_data in self.summary.items():
            cleaned_tasks[task_name] = {
                "run_count": int(task_data.get("run_count", 0)),
                "total_duration_seconds": round(float(task_data.get("total_duration_seconds", 0.0)), 3),
                "battle": self._build_battle_payload(
                    int(task_data.get("battle_count", 0)),
                    float(task_data.get("battle_total_duration_seconds", 0.0)),
                ),
                "runs": task_data.get("runs", []),
            }
        return cleaned_tasks

    def _current_total_runtime(self) -> float:
        runtime = self.runtime
        if runtime.saw_start_boundary:
            total_duration = self._append_duration(runtime.total_duration, runtime.session_start, runtime.region_last)
        else:
            total_duration = self._append_duration(0.0, runtime.pre_start_first, runtime.region_last)
        return round(total_duration, 3)

    @staticmethod
    def _build_battle_payload(count: int, total_duration_seconds: float) -> dict[str, Any] | None:
        if count <= 0:
            return None
        return {
            "count": int(count),
            "avg_duration_seconds": round(total_duration_seconds / count, 3),
        }

    @staticmethod
    def _append_duration(total_duration: float, start_time: datetime | None, end_time: datetime | None) -> float:
        if start_time is None or end_time is None or end_time < start_time:
            return total_duration
        return round(total_duration + (end_time - start_time).total_seconds(), 3)


@dataclass
class TodayLogCache:
    day: str
    path: Path
    position: int = 0
    signature: tuple[int, int] = (0, 0)
    parser: LogStatsParser = field(default_factory=LogStatsParser)
    tail_lines: list[str] = field(default_factory=list)
    snapshot: dict[str, Any] = field(default_factory=dict)


class LogStatsService:
    def __init__(self) -> None:
        self._today_cache: dict[str, TodayLogCache] = {}
        self._historical_cache: dict[tuple[str, str], HistoricalStatsCacheEntry] = {}

    @staticmethod
    def _normalize_script_name(script_name: str) -> str:
        name = str(script_name or "").strip()
        return name.split("_", 1)[0] if "_" in name else name

    def build_stats(self, script_name: str, target_day: date) -> dict[str, Any]:
        normalized = self._normalize_script_name(script_name)
        if target_day == date.today():
            return self._build_today_stats(normalized)
        return self._build_historical_stats(normalized, target_day)

    def list_available_dates(self, script_name: str) -> dict[str, Any]:
        normalized = self._normalize_script_name(script_name)
        dates: set[str] = set()
        if LOG_ROOT.exists():
            for path in LOG_ROOT.iterdir():
                if not path.is_file():
                    continue

                matched = _LOG_FILE_RE.match(path.name)
                if not matched:
                    continue

                day_text = matched.group("day")
                try:
                    date.fromisoformat(day_text)
                except ValueError:
                    continue

                if matched.group("script") != normalized:
                    continue
                dates.add(day_text)

        return {
            "script_name": normalized,
            "dates": sorted(dates, reverse=True),
        }

    async def stream_events(self, script_name: str, target_day: date):
        normalized = self._normalize_script_name(script_name)
        snapshot = self.build_stats(normalized, target_day)
        yield self._encode_sse("snapshot", snapshot)

        last_signature = self._today_log_signature(normalized)
        last_snapshot = copy.deepcopy(snapshot)
        while True:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            current_signature = self._today_log_signature(normalized)
            if current_signature == last_signature:
                continue
            last_signature = current_signature
            current_snapshot = self.build_stats(normalized, target_day)
            payload = self._build_update_payload(normalized, last_snapshot, current_snapshot)
            if payload is None:
                continue
            last_snapshot = copy.deepcopy(current_snapshot)
            yield self._encode_sse("update", payload)

    def _build_historical_stats(self, script_name: str, target_day: date) -> dict[str, Any]:
        self._cleanup_historical_cache()
        cache_key = (script_name, target_day.isoformat())
        cached = self._historical_cache.get(cache_key)
        if cached is not None and cached.expires_at > datetime.now():
            return copy.deepcopy(cached.payload)

        payload = self._parse_log_file(self._log_path(script_name, target_day))
        self._historical_cache[cache_key] = HistoricalStatsCacheEntry(
            expires_at=datetime.now() + HISTORICAL_CACHE_TTL,
            payload=copy.deepcopy(payload),
        )
        return payload

    def _build_today_stats(self, script_name: str) -> dict[str, Any]:
        cache = self._refresh_today_cache(script_name)
        return copy.deepcopy(cache.snapshot)

    def _cleanup_historical_cache(self) -> None:
        now = datetime.now()
        expired_keys = [
            key for key, entry in self._historical_cache.items()
            if entry.expires_at <= now
        ]
        for key in expired_keys:
            del self._historical_cache[key]

    def _build_update_payload(
        self,
        script_name: str,
        previous_snapshot: dict[str, Any],
        current_snapshot: dict[str, Any],
    ) -> dict[str, Any] | None:
        previous_tasks = previous_snapshot.get("tasks", {}) if isinstance(previous_snapshot, dict) else {}
        current_tasks = current_snapshot.get("tasks", {}) if isinstance(current_snapshot, dict) else {}

        changed_tasks: dict[str, Any] = {}
        for task_name, task_data in current_tasks.items():
            if previous_tasks.get(task_name) != task_data:
                changed_tasks[task_name] = task_data

        removed_tasks = sorted(name for name in previous_tasks.keys() if name not in current_tasks)

        totals_changed = any(
            previous_snapshot.get(field) != current_snapshot.get(field)
            for field in ("total_runtime_seconds", "total_task_run_count", "total_battle_count")
        )
        if not totals_changed and not changed_tasks and not removed_tasks:
            return None

        return {
            "script_name": script_name,
            "total_runtime_seconds": current_snapshot.get("total_runtime_seconds", 0),
            "total_task_run_count": current_snapshot.get("total_task_run_count", 0),
            "total_battle_count": current_snapshot.get("total_battle_count", 0),
            "changed_tasks": changed_tasks,
            "removed_tasks": removed_tasks,
        }

    def _parse_log_file(self, path: Path) -> dict[str, Any]:
        script_name = self._extract_script_name_from_path(path)
        if not path.exists():
            return self._empty_stats(script_name)

        with path.open("r", encoding="utf-8", errors="ignore") as file:
            lines = file.readlines()
        return self._parse_lines(lines, script_name=script_name)

    @staticmethod
    def _extract_script_name_from_path(path: Path) -> str:
        parts = path.stem.split("_", 1)
        return parts[1] if len(parts) == 2 else path.stem

    @staticmethod
    def _parse_lines(lines: list[str], script_name: str = "") -> dict[str, Any]:
        payload = LogStatsParser.parse_lines(lines, script_name=script_name)
        return {
            "script_name": payload.get("script_name", script_name),
            "total_runtime_seconds": round(float(payload.get("total_runtime_seconds", 0.0)), 3),
            "total_task_run_count": int(payload.get("total_task_run_count", 0)),
            "total_battle_count": int(payload.get("total_battle_count", 0)),
            "tasks": payload.get("tasks", {}),
        }

    def _today_log_signature(self, script_name: str) -> tuple[int, int]:
        today_file = self._today_log_path(script_name)
        if not today_file.exists():
            return (0, 0)
        stat = today_file.stat()
        return (int(stat.st_size), int(stat.st_mtime_ns))

    @staticmethod
    def _log_path(script_name: str, target_day: date) -> Path:
        return LOG_ROOT / f"{target_day.isoformat()}_{script_name}.txt"

    def _today_log_path(self, script_name: str) -> Path:
        return self._log_path(script_name, date.today())

    def _refresh_today_cache(self, script_name: str) -> TodayLogCache:
        today = date.today().isoformat()
        today_file = self._today_log_path(script_name)
        cache = self._today_cache.get(script_name)

        if cache is not None and cache.day != today:
            cache = None

        if not today_file.exists():
            empty_cache = self._new_today_cache(today, today_file, script_name)
            self._today_cache[script_name] = empty_cache
            return empty_cache

        stat = today_file.stat()
        signature = (int(stat.st_size), int(stat.st_mtime_ns))
        if cache is not None and cache.path == today_file and cache.signature == signature:
            return cache

        should_reset = (
            cache is None
            or cache.path != today_file
            or stat.st_size < cache.position
        )
        if should_reset:
            cache = self._new_today_cache(today, today_file, script_name)

        with today_file.open("r", encoding="utf-8", errors="ignore") as file:
            if cache.position > 0:
                file.seek(cache.position)
            new_lines = file.readlines()
            cache.position = file.tell()

        merged_lines = cache.tail_lines + new_lines
        confirmed_lines, cache.tail_lines = self._split_confirmed_lines(merged_lines)
        if confirmed_lines:
            cache.parser.consume_lines(confirmed_lines)

        cache.signature = signature
        cache.snapshot = cache.parser.snapshot(script_name=script_name, tail_lines=cache.tail_lines)
        self._today_cache[script_name] = cache
        return cache

    def _new_today_cache(self, today: str, today_file: Path, script_name: str) -> TodayLogCache:
        return TodayLogCache(
            day=today,
            path=today_file,
            snapshot=self._empty_stats(script_name),
        )

    @staticmethod
    def _split_confirmed_lines(lines: list[str]) -> tuple[list[str], list[str]]:
        if not lines:
            return [], []

        if len(lines) >= 3 and LogStatsParser._is_task_boundary(lines, len(lines) - 3):
            return lines, []

        tail_size = 0
        if _EQ_LINE_RE.match(lines[-1].strip()):
            tail_size = 1
        if (
            len(lines) >= 2
            and _EQ_LINE_RE.match(lines[-2].strip())
            and _TITLE_LINE_RE.match(lines[-1].strip())
        ):
            tail_size = 2

        if tail_size <= 0:
            return lines, []
        return lines[:-tail_size], lines[-tail_size:]

    @staticmethod
    def _empty_stats(script_name: str) -> dict[str, Any]:
        return {
            "script_name": script_name,
            "total_runtime_seconds": 0,
            "total_task_run_count": 0,
            "total_battle_count": 0,
            "tasks": {},
        }

    @staticmethod
    def _compact_json(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def _encode_sse(self, event: str, payload: dict[str, Any]) -> str:
        return f"event: {event}\ndata: {self._compact_json(payload)}\n\n"


log_stats_service = LogStatsService()
