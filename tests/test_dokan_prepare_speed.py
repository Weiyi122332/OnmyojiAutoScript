"""Dojo battles poll for the next prepare page without changing other tasks."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.GeneralBattle.general_battle import BattleAction, GeneralBattle
from tasks.Dokan.script_task import ScriptTask
from tasks.GameUi.page import page_battle, page_battle_prepare


class DokanPrepareSpeedTest(unittest.TestCase):
    def make_task(self, task_type):
        task = task_type.__new__(task_type)
        task._custom_pages_registered = True
        task.current_count = 0
        task.device = SimpleNamespace(
            stuck_record_add=Mock(),
            click_record_clear=Mock(),
            screenshot_interval_set=Mock(),
        )
        task._build_context = Mock(return_value=SimpleNamespace(
            last_page=None, reward_no_battle_ts=None, quick_exit=False,
        ))
        task._exit_matcher = Mock(return_value=None)
        task.screenshot = Mock()
        task._tick_long_battle = Mock()
        task._tick_timeout = Mock()
        task._sync_prepare_click_timer = Mock()
        task._ensure_battle_stuck_guard = Mock()
        task._handle_in_battle = Mock(return_value=BattleAction.CONTINUE)
        task._handle_prepare = Mock(return_value=BattleAction.EXIT_WIN)
        return task

    def test_dojo_uses_faster_polling_and_restores_interval_on_exit(self):
        for task_type, battle_interval in ((ScriptTask, 0.3), (GeneralBattle, 'combat')):
            with self.subTest(task=task_type.__name__):
                task = self.make_task(task_type)
                with patch('tasks.Component.GeneralBattle.general_battle.GameUi.detect_page_in',
                           side_effect=[page_battle, page_battle_prepare]):
                    self.assertTrue(task.run_general_battle(GeneralBattleConfig()))

                self.assertEqual(task.device.screenshot_interval_set.call_args_list,
                                 [call(battle_interval), call(None), call()])
                task._handle_prepare.assert_called_once()
                self.assertIsNone(task._battle_context)

    def test_interval_is_restored_when_battle_handler_fails(self):
        task = self.make_task(ScriptTask)
        task._handle_in_battle.side_effect = RuntimeError('battle handler failed')
        with patch('tasks.Component.GeneralBattle.general_battle.GameUi.detect_page_in',
                   return_value=page_battle):
            with self.assertRaisesRegex(RuntimeError, 'battle handler failed'):
                task.run_general_battle(GeneralBattleConfig())

        self.assertEqual(task.device.screenshot_interval_set.call_args_list,
                         [call(0.3), call()])


if __name__ == '__main__':
    unittest.main()
