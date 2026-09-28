"""Task-group log statistics use the executed tasks as their public keys."""

import unittest

from module.server.log_stats import LogStatsParser


def log(second: int, message: str) -> str:
    return f"2026-09-28 08:00:{second:02d}.000 | group_runner.py:0001 | INFO | {message}\n"


def task_boundary(name: str) -> list[str]:
    return [
        "═" * 30 + "\n",
        "─" * 20 + f" {name.upper()} " + "─" * 20 + "\n",
        "═" * 30 + "\n",
    ]


def item_boundary(index: int, total: int, name: str) -> str:
    return "═" * 20 + f" TASK GROUP [{index}/{total}]: {name.upper()} " + "═" * 20 + "\n"


class TaskGroupStatisticsTest(unittest.TestCase):
    def test_group_items_replace_wrapper_and_merge_with_independent_runs(self):
        lines = [log(0, "[Task] TaskGroup1 (Enable, 5, now)")]
        lines += task_boundary("TaskGroup1")
        lines += [
            log(1, "Task group `日常组` (TaskGroup1) starts, 3 task(s)"),
            item_boundary(1, 3, "AreaBoss"),
            log(2, "TASK GROUP [1/3]: AREABOSS"),
            "─" * 20 + " GENERAL BATTLE START " + "─" * 20 + "\n",
            log(3, "Battle started"),
            log(5, "Task group: `AreaBoss` finished. AreaBoss"),
            item_boundary(2, 3, "Orochi"),
            log(6, "TASK GROUP [2/3]: OROCHI"),
            log(8, "Task group `日常组`: `Orochi` raised RuntimeError"),
            item_boundary(3, 3, "WantedQuests"),
            log(9, "TASK GROUP [3/3]: WANTEDQUESTS"),
            log(11, "Task group: `WantedQuests` finished. WantedQuests"),
            log(12, "Task group `日常组` finished with error: [...]"),
            log(13, "[Task] Orochi (Enable, 5, now)"),
        ]
        lines += task_boundary("Orochi")
        lines += [log(14, "Independent Orochi run"), log(16, "Scheduler: End task `Orochi`")]

        snapshot = LogStatsParser.parse_lines(lines, script_name="demo")

        self.assertEqual(set(snapshot["tasks"]), {"AreaBoss", "Orochi", "WantedQuests"})
        self.assertEqual(snapshot["total_task_run_count"], 4)
        self.assertEqual(snapshot["tasks"]["Orochi"]["run_count"], 2)
        self.assertEqual(snapshot["tasks"]["AreaBoss"]["battle"]["count"], 1)
        self.assertEqual(snapshot["tasks"]["WantedQuests"]["runs"][0]["duration_seconds"], 2.0)

    def test_empty_group_is_not_a_statistical_task(self):
        lines = [log(0, "[Task] TaskGroup2 (Enable, 5, now)")]
        lines += task_boundary("TaskGroup2")
        lines += [log(1, "Task group has no tasks"), log(2, "Scheduler: End task `TaskGroup2`")]

        snapshot = LogStatsParser.parse_lines(lines)

        self.assertEqual(snapshot["tasks"], {})
        self.assertEqual(snapshot["total_task_run_count"], 0)

    def test_incremental_lines_keep_the_current_group_item(self):
        parser = LogStatsParser()
        first_chunk = [log(0, "[Task] TaskGroup1 (Enable, 5, now)")]
        first_chunk += task_boundary("TaskGroup1")
        first_chunk += [item_boundary(1, 2, "AreaBoss"), log(1, "TASK GROUP [1/2]: AREABOSS")]
        parser.consume_lines(first_chunk)

        while_running = parser.snapshot()
        self.assertEqual(set(while_running["tasks"]), {"AreaBoss"})

        parser.consume_lines([
            log(3, "Task group: `AreaBoss` finished. AreaBoss"),
            item_boundary(2, 2, "Orochi"),
            log(4, "TASK GROUP [2/2]: OROCHI"),
            log(6, "Task group: `Orochi` finished. Orochi"),
        ])
        completed = parser.snapshot()
        self.assertEqual(set(completed["tasks"]), {"AreaBoss", "Orochi"})
        self.assertEqual(completed["total_task_run_count"], 2)

    def test_grouped_six_realms_keeps_existing_subtask_breakdown(self):
        lines = [log(0, "[Task] TaskGroup3 (Enable, 5, now)")]
        lines += task_boundary("TaskGroup3")
        lines += [
            item_boundary(1, 1, "SixRealms"),
            log(1, "TASK GROUP [1/1]: SIXREALMS"),
            "═" * 20 + " MOON SEA " + "═" * 20 + "\n",
            log(2, "Moon Sea started"),
            log(3, "Moon Sea task ended"),
            "═" * 20 + " PEACOCK KINGDOM " + "═" * 20 + "\n",
            log(4, "Peacock Kingdom started"),
            log(5, "Peacock Kingdom task ended"),
            log(6, "Task group: `SixRealms` finished. SixRealms"),
        ]

        snapshot = LogStatsParser.parse_lines(lines)

        self.assertEqual(set(snapshot["tasks"]), {"MoonSea", "PeacockKingdom"})
        self.assertEqual(snapshot["total_task_run_count"], 2)


if __name__ == "__main__":
    unittest.main()
