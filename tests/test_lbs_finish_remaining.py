"""LBS 刷完剩余次数的限制优先级、识别失败和旧配置兼容。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.config.config_model import ConfigModel
from module.exception import GamePageUnknownError, TaskEnd
from tasks.LBS.config import LBS, LBSConfig, LBSMode
from tasks.LBS.script_task import ScriptTask


class LBSFinishRemainingTest(unittest.TestCase):
    def setUp(self):
        for name in ('logger', 'sleep'):
            patcher = patch('tasks.LBS.script_task.' + name)
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_task(self, mode=LBSMode.SOLO, enabled=True, counts=((2, 38, 40),)):
        task = ScriptTask.__new__(ScriptTask)
        task.config = SimpleNamespace(lbs=LBS(lbs_config=LBSConfig(
            mode=mode, finish_remaining=enabled, limit_count=0,
        )))
        task.device = SimpleNamespace(image=object())
        task.current_count = 0
        task.screenshot = Mock()
        task.O_LBS_COUNT = SimpleNamespace(ocr=Mock(side_effect=counts))
        task.appear = Mock(return_value=True)
        task.click_fire = Mock()
        task.goto_page = Mock()
        task.set_next_run = Mock()

        def battle(*args, **kwargs):
            task.current_count += 1
            return True

        task.run_general_battle = Mock(side_effect=battle)
        task._wait_team_battle = Mock(side_effect=battle)
        return task

    def run_battles(self, task):
        method = task._run_team_match if task.config.lbs.lbs_config.mode == LBSMode.TEAM else task._run_solo
        method(task.config.lbs.lbs_config.limit_count)

    def test_old_time_limit_is_discarded_and_count_limit_is_preserved(self):
        conf = LBSConfig.model_validate({'limit_count': 5, 'limit_time': '00:10:00'})
        self.assertFalse(conf.finish_remaining)
        self.assertEqual(conf.limit_count, 5)
        self.assertNotIn('limit_time', conf.model_dump())
        self.assertNotIn('limit_time', LBSConfig.model_json_schema()['properties'])
        enabled = LBSConfig.model_validate({'finish_remaining': True})
        self.assertTrue(LBSConfig.model_validate_json(enabled.model_dump_json()).finish_remaining)

    def test_solo_and_team_finish_remaining_past_configured_count_limit(self):
        for mode in (LBSMode.SOLO, LBSMode.TEAM):
            with self.subTest(mode=mode):
                task = self.make_task(mode=mode, counts=((2, 38, 40), (1, 39, 40), (0, 40, 40)))
                self.run_battles(task)
                self.assertEqual(task.current_count, 2)
                self.assertEqual(task.O_LBS_COUNT.ocr.call_count, 3)

    def test_normal_modes_run_until_the_configured_count(self):
        for mode in (LBSMode.SOLO, LBSMode.TEAM):
            with self.subTest(mode=mode):
                task = self.make_task(mode=mode, enabled=False,
                                      counts=((3, 37, 40), (2, 38, 40), (1, 39, 40)))
                task.config.lbs.lbs_config.limit_count = 2
                self.run_battles(task)
                self.assertEqual(task.current_count, 2)

    def test_disabled_switch_preserves_count_limit(self):
        for mode in (LBSMode.SOLO, LBSMode.TEAM):
            with self.subTest(mode=mode):
                task = self.make_task(mode=mode, enabled=False)
                self.run_battles(task)
                task.O_LBS_COUNT.ocr.assert_called_once()
                self.assertEqual(task.current_count, 0)

    def test_zero_remaining_stops_without_starting_a_battle(self):
        for mode in (LBSMode.SOLO, LBSMode.TEAM):
            with self.subTest(mode=mode):
                task = self.make_task(mode=mode, counts=((0, 40, 40),))
                self.run_battles(task)
                task.run_general_battle.assert_not_called()
                task._wait_team_battle.assert_not_called()

    def test_transient_failed_read_retries_before_deciding(self):
        task = self.make_task(counts=((0, 0, 0), (2, 38, 40)))
        self.assertFalse(task._reach_exit(limit_count=0))
        self.assertEqual(task.screenshot.call_count, 2)

    def test_unreadable_or_invalid_count_aborts_instead_of_reporting_success(self):
        for count in ((0, 0, 0), (-1, 41, 40), (41, -1, 40)):
            with self.subTest(count=count):
                task = self.make_task(counts=(count,) * 3)
                with self.assertRaisesRegex(GamePageUnknownError, 'remaining challenges'):
                    task.run()
                self.assertEqual(task.screenshot.call_count, 3)
                task.run_general_battle.assert_not_called()
                task.set_next_run.assert_not_called()

    def test_normal_mode_failed_read_still_respects_manual_count(self):
        task = self.make_task(enabled=False, counts=((0, 0, 0),))
        self.assertTrue(task._reach_exit(limit_count=0))
        task.screenshot.assert_called_once()

    def test_drive_mode_stops_at_its_configured_count(self):
        task = self.make_task(mode=LBSMode.DRIVE)
        task.is_in_room = Mock(return_value=True)
        task.room_check_can_fire = Mock(return_value=True)
        task.exit_room = Mock()
        self.assertFalse(task._finish_remaining_enabled())
        task._run_drive_mode(limit_count=2)
        self.assertEqual(task.exit_room.call_count, 2)
        task.O_LBS_COUNT.ocr.assert_not_called()
        task.run_general_battle.assert_not_called()

    def test_run_dispatches_each_mode_without_a_runtime_limit(self):
        for mode, method in ((LBSMode.SOLO, '_run_solo'),
                             (LBSMode.TEAM, '_run_team_match'),
                             (LBSMode.DRIVE, '_run_drive_mode')):
            with self.subTest(mode=mode):
                task = self.make_task(mode=mode)
                task._run_solo = Mock()
                task._run_team_match = Mock()
                task._run_drive_mode = Mock()
                with self.assertRaises(TaskEnd):
                    task.run()
                getattr(task, method).assert_called_once_with(0)
                task.set_next_run.assert_called_once_with(task='LBS', success=True)

    def test_configuration_keeps_the_manual_count_visible(self):
        for mode in LBSMode:
            for enabled in (True, False):
                with self.subTest(mode=mode, enabled=enabled):
                    holder = SimpleNamespace(lbs=LBS(lbs_config=LBSConfig(
                        mode=mode, finish_remaining=enabled, limit_count=7,
                    )))
                    args = {item['name']: item['value'] for item in ConfigModel.script_task(holder, 'LBS')['lbs_config']}
                    self.assertEqual(args['limit_count'], 7)
                    self.assertEqual('finish_remaining' in args, mode != LBSMode.DRIVE)

    def test_switching_back_restores_the_saved_manual_count(self):
        conf = LBSConfig(finish_remaining=True, limit_count=7)
        holder = SimpleNamespace(lbs=LBS(lbs_config=conf))
        ConfigModel.script_task(holder, 'LBS')
        saved = conf.model_dump()
        self.assertEqual(saved['limit_count'], 7)
        self.assertIs(saved['finish_remaining'], True)
        restored = LBSConfig.model_validate_json(conf.model_dump_json())
        restored.finish_remaining = False
        holder.lbs.lbs_config = restored
        args = {item['name']: item['value'] for item in ConfigModel.script_task(holder, 'LBS')['lbs_config']}
        self.assertEqual(args['limit_count'], 7)
        self.assertFalse(restored.finish_remaining_enabled)


if __name__ == '__main__':
    unittest.main()
