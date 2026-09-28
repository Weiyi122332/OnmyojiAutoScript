"""Task durations stop at their own completion log, even during scheduler idle time."""

import unittest

from module.server.log_stats import LogStatsParser


def log(second: int, message: str) -> str:
    return f"2026-09-28 08:00:{second:02d}.000 | script.py:0001 | INFO | {message}\n"


def task_boundary(name: str) -> list[str]:
    return [
        "═" * 30 + "\n",
        "─" * 20 + f" {name.upper()} " + "─" * 20 + "\n",
        "═" * 30 + "\n",
    ]


class TaskEndStatisticsTest(unittest.TestCase):
    def test_scheduler_end_stops_duration_before_idle_and_next_task(self):
        lines = [log(0, "[Task] AreaBoss (Enable, 5, now)")]
        lines += task_boundary("AreaBoss")
        lines += [
            log(1, "AreaBoss starts"),
            log(5, "Scheduler: End task `AreaBoss`"),
            log(40, "Scheduler is waiting"),
            log(50, "[Task] Orochi (Enable, 5, now)"),
        ]
        lines += task_boundary("Orochi")
        lines += [log(51, "Orochi starts"), log(53, "Scheduler: End task `Orochi`")]

        snapshot = LogStatsParser.parse_lines(lines)

        self.assertEqual(snapshot["total_task_run_count"], 2)
        self.assertEqual(snapshot["tasks"]["AreaBoss"]["runs"][0]["duration_seconds"], 4.0)
        self.assertEqual(snapshot["tasks"]["AreaBoss"]["runs"][0]["end_time"], "2026-09-28 08:00:05.000")
        self.assertEqual(snapshot["tasks"]["Orochi"]["runs"][0]["duration_seconds"], 2.0)

    def test_completed_task_stays_fixed_in_incremental_snapshots(self):
        parser = LogStatsParser()
        lines = [log(0, "[Task] AreaBoss (Enable, 5, now)")]
        lines += task_boundary("AreaBoss")
        lines += [log(1, "AreaBoss starts"), log(5, "Scheduler: End task `AreaBoss`")]
        parser.consume_lines(lines)

        before_idle = parser.snapshot()["tasks"]["AreaBoss"]
        parser.consume_lines([log(40, "Scheduler is waiting")])
        after_idle = parser.snapshot()["tasks"]["AreaBoss"]

        self.assertEqual(before_idle, after_idle)
        self.assertEqual(after_idle["run_count"], 1)

    def test_group_item_ends_before_wrapper_and_idle(self):
        lines = [log(0, "[Task] TaskGroup1 (Enable, 5, now)")]
        lines += task_boundary("TaskGroup1")
        lines += [
            "═" * 20 + " TASK GROUP [1/1]: AREABOSS " + "═" * 20 + "\n",
            log(1, "TASK GROUP [1/1]: AREABOSS"),
            log(3, "Task group: `AreaBoss` finished. AreaBoss"),
            log(5, "Scheduler: End task `TaskGroup1`"),
            log(45, "Scheduler is waiting"),
        ]

        snapshot = LogStatsParser.parse_lines(lines)

        self.assertEqual(set(snapshot["tasks"]), {"AreaBoss"})
        self.assertEqual(snapshot["tasks"]["AreaBoss"]["runs"][0]["duration_seconds"], 2.0)

    def test_group_wrapper_end_closes_item_if_item_finish_log_is_missing(self):
        lines = [log(0, "[Task] TaskGroup1 (Enable, 5, now)")]
        lines += task_boundary("TaskGroup1")
        lines += [
            "═" * 20 + " TASK GROUP [1/1]: AREABOSS " + "═" * 20 + "\n",
            log(1, "TASK GROUP [1/1]: AREABOSS"),
            log(5, "Scheduler: End task `TaskGroup1`"),
            log(45, "Scheduler is waiting"),
        ]

        snapshot = LogStatsParser.parse_lines(lines)

        self.assertEqual(snapshot["tasks"]["AreaBoss"]["runs"][0]["duration_seconds"], 4.0)

    def test_six_realms_subtasks_do_not_include_waiting_between_runs(self):
        lines = [log(0, "[Task] SixRealms (Enable, 5, now)")]
        lines += task_boundary("SixRealms")
        lines += [
            log(1, "SixRealms prepares"),
            "═" * 20 + " MOON SEA " + "═" * 20 + "\n",
            log(2, "Moon Sea starts"),
            log(4, "Moon Sea task ended"),
            log(20, "SixRealms prepares another run"),
            "═" * 20 + " MOON SEA " + "═" * 20 + "\n",
            log(21, "Moon Sea starts"),
            log(23, "Moon Sea task ended"),
            log(40, "SixRealms cleanup"),
            log(45, "Scheduler: End task `SixRealms`"),
            log(50, "Scheduler is waiting"),
        ]

        snapshot = LogStatsParser.parse_lines(lines)

        self.assertEqual(set(snapshot["tasks"]), {"MoonSea"})
        runs = snapshot["tasks"]["MoonSea"]["runs"]
        self.assertEqual([run["duration_seconds"] for run in runs], [3.0, 2.0])
        self.assertEqual([run["end_time"] for run in runs], [
            "2026-09-28 08:00:04.000",
            "2026-09-28 08:00:23.000",
        ])

    def test_six_realms_scheduler_end_closes_unfinished_subtask(self):
        lines = [log(0, "[Task] SixRealms (Enable, 5, now)")]
        lines += task_boundary("SixRealms")
        lines += [
            "═" * 20 + " MOON SEA " + "═" * 20 + "\n",
            log(1, "Moon Sea starts"),
            log(4, "Scheduler: End task `SixRealms`"),
            log(45, "Scheduler is waiting"),
        ]

        snapshot = LogStatsParser.parse_lines(lines)

        self.assertEqual(snapshot["tasks"]["MoonSea"]["runs"][0]["duration_seconds"], 3.0)


if __name__ == "__main__":
    unittest.main()
