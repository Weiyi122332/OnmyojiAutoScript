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
                dokan_config=SimpleNamespace(
                    try_start_dokan=True, find_dokan_score=4.6,
                    skip_owner_battle=True),
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
            wait_until_appear=Mock(return_value=True),
            dokan_owner_battle=True,
            first_master_killed=True,
            attack_priority_selected=True,
            switch_member_soul_done=True,
            switch_owner_soul_done=True,
            second_dokan_ready=False,
        )
        ScriptTask.wait_for_next_dokan_selection(task)
        task.wait_until_appear.assert_called_once_with(marker, wait_time=120)
        self.assertTrue(task.second_dokan_ready)
        self.assertFalse(task.dokan_owner_battle)
        self.assertFalse(task.first_master_killed)
        self.assertFalse(task.attack_priority_selected)
        self.assertTrue(task.switch_member_soul_done)
        self.assertTrue(task.switch_owner_soul_done)

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

    def test_unchecked_option_keeps_original_map_guard(self):
        task = self.make_map_task()
        task.config.dokan.dokan_config.skip_owner_battle = False
        with self.assertRaises(DokanNotStartedError):
            ScriptTask.run_on_dokan_map(task)
        task.find_dokan.assert_not_called()

    def test_second_selection_starts_in_same_run(self):
        task = self.make_map_task()
        ScriptTask.run_on_dokan_map(task)
        task.ensure_dokan_created.assert_not_called()
        task.find_dokan.assert_called_once_with(4.6)
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

    def test_selection_timeout_does_not_enable_second_attempt(self):
        task = SimpleNamespace(
            I_RYOU_DOKAN_FINDING_DOKAN=object(),
            wait_until_appear=Mock(return_value=False),
            second_dokan_ready=False,
        )
        with self.assertRaises(DokanNotStartedError):
            ScriptTask.wait_for_next_dokan_selection(task)
        self.assertFalse(task.second_dokan_ready)

    def test_unchecked_option_keeps_original_vote_logic(self):
        names = (
            'I_RYOU_DOKAN_GATHERING', 'I_RYOU_DOKAN_MASTER_BATTLE',
            'I_RYOU_DOKAN_START_CHALLENGE', 'I_RYOU_DOKAN_CD',
            'I_RYOU_DOKAN_ABANDONED_TOPPA_ABANDONED',
            'I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY',
            'I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN',
            'I_RYOU_DOKAN_TODAY_ATTACK_COUNT',
            'I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_DONE', 'I_DOKAN_BOSS_WAITING',
        )
        markers = {name: object() for name in names}
        task = SimpleNamespace(
            **markers,
            conf=SimpleNamespace(
                dokan_config=SimpleNamespace(skip_owner_battle=False),
                attack_count_config=SimpleNamespace(daily_attack_count=2),
            ),
            device=SimpleNamespace(stuck_record_clear=Mock()),
            dokan_owner_battle=False,
            prepare_appear_cache=Mock(),
            appear_then_click=Mock(return_value=False),
            ui_click_until_disappear=Mock(return_value=True),
            wait_for_next_dokan_selection=Mock(),
        )
        task.appear = lambda target, **kwargs: target in (
            task.I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY,
            task.I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN,
        )
        ScriptTask.run_on_dokan(task)
        task.ui_click_until_disappear.assert_called_once_with(
            task.I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN)
        task.wait_for_next_dokan_selection.assert_not_called()
        task.conf.attack_count_config.daily_attack_count = 1
        task.ui_click_until_disappear.reset_mock()
        ScriptTask.run_on_dokan(task)
        task.ui_click_until_disappear.assert_called_once_with(
            task.I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY)
        task.wait_for_next_dokan_selection.assert_not_called()

    def test_unchecked_option_keeps_original_scheduler_interval(self):
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
