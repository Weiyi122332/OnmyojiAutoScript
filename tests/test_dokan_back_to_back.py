"""Battle Again must lead straight into a second dojo selection."""

import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

from tasks.Dokan.script_task import (
    DokanFinishedError,
    DokanNotStartedError,
    ScriptTask,
)


class BackToBackDokanTest(unittest.TestCase):
    def make_map_task(self, remaining=1, found=1, ready=True):
        selection = object()
        task = SimpleNamespace(
            I_RYOU_DOKAN_FINDING_DOKAN=selection,
            I_RYOU_DOKAN_FOUND_DOKAN=object(),
            I_RYOU_DOKAN_CENTER_TOP=object(),
            config=SimpleNamespace(dokan=SimpleNamespace(
                attack_count_config=SimpleNamespace(daily_attack_count=2),
            )),
            found_dokan_cnt=found,
            second_dokan_ready=ready,
            appear=lambda target: target is selection,
            update_remain_attack_count=Mock(return_value=remaining),
            ensure_dokan_created=Mock(side_effect=AssertionError('created dojo twice')),
            find_dokan=Mock(return_value=True),
            wait_until_appear=Mock(return_value=True),
        )
        return task

    def test_battle_again_waits_for_selection_and_preserves_switched_souls(self):
        marker = object()
        task = SimpleNamespace(
            I_RYOU_DOKAN_FINDING_DOKAN=marker,
            device=SimpleNamespace(stuck_record_clear=Mock(), stuck_record_add=Mock()),
            screenshot=Mock(),
            appear=Mock(return_value=True),
            dokan_owner_battle=True,
            attack_priority_selected=True,
            switch_member_soul_done=True,
            second_dokan_ready=False,
        )
        ScriptTask.wait_for_next_dokan_selection(task)
        task.screenshot.assert_called_once_with()
        task.appear.assert_called_once_with(marker)
        task.device.stuck_record_add.assert_called_once_with('PAUSE')
        self.assertEqual(task.device.stuck_record_clear.call_count, 2)
        self.assertTrue(task.second_dokan_ready)
        self.assertFalse(task.dokan_owner_battle)
        self.assertFalse(task.attack_priority_selected)
        self.assertTrue(task.switch_member_soul_done)

    def test_battle_again_requires_an_actual_remaining_attempt(self):
        task = SimpleNamespace(conf=SimpleNamespace(attack_count_config=SimpleNamespace(
            daily_attack_count=2, remain_attack_count=1,
        )))
        self.assertTrue(ScriptTask.can_battle_again(task))
        task.conf.attack_count_config.remain_attack_count = 0
        self.assertFalse(ScriptTask.can_battle_again(task))
        task.conf.attack_count_config.remain_attack_count = 1
        task.conf.attack_count_config.daily_attack_count = 1
        self.assertFalse(ScriptTask.can_battle_again(task))

    def test_no_second_selection_until_page_has_automatically_returned(self):
        task = self.make_map_task(ready=False)
        with self.assertRaises(DokanNotStartedError):
            ScriptTask.run_on_dokan_map(task)
        task.find_dokan.assert_not_called()

    def test_second_selection_starts_in_same_run(self):
        task = self.make_map_task()
        ScriptTask.run_on_dokan_map(task)
        task.ensure_dokan_created.assert_not_called()
        task.find_dokan.assert_called_once_with()
        self.assertFalse(task.second_dokan_ready)

    def test_no_selection_without_remaining_game_attempt(self):
        task = self.make_map_task(remaining=0)
        with self.assertRaises(DokanFinishedError):
            ScriptTask.run_on_dokan_map(task)
        task.find_dokan.assert_not_called()

    def test_no_third_selection(self):
        task = self.make_map_task(found=2)
        with self.assertRaises(DokanFinishedError):
            ScriptTask.run_on_dokan_map(task)
        task.find_dokan.assert_not_called()

    def test_partial_run_retains_scheduler_retry_interval(self):
        interval = timedelta(minutes=2)
        task = SimpleNamespace(
            config=SimpleNamespace(model=SimpleNamespace(dokan=SimpleNamespace(
                dokan_config=SimpleNamespace(dokan_run_time=datetime.now().time()),
            )), dokan=SimpleNamespace(attack_count_config=SimpleNamespace(
                remain_attack_count=1, daily_attack_count=2,
            ), scheduler=SimpleNamespace(failure_interval=interval))),
            set_next_run=Mock(),
        )
        earliest = datetime.now() + interval
        ScriptTask.next_run(task, is_dokan_activated=True)
        latest = datetime.now() + interval
        target = task.set_next_run.call_args.kwargs['target']
        self.assertLessEqual(earliest, target)
        self.assertLessEqual(target, latest)


if __name__ == '__main__':
    unittest.main()
