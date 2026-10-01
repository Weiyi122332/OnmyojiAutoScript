"""Guild raid recognition optimizations must stay within the requested tasks."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.GeneralBattle.general_battle import BattleAction, GeneralBattle
from tasks.Dokan.script_task import ScriptTask as DokanTask
from tasks.GameUi.page import page_battle, page_battle_prepare, page_battle_result, page_reward
from tasks.RealmRaid.script_task import ScriptTask as RealmRaidTask
from tasks.RyouToppa.script_task import ScriptTask


class RyouToppaSpeedTest(unittest.TestCase):
    def make_battle_task(self, task_type):
        task = task_type.__new__(task_type)
        task._custom_pages_registered = True
        task.current_count = 0
        task.device = SimpleNamespace(
            stuck_record_add=Mock(), click_record_clear=Mock(),
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

    def test_faster_polling_is_scoped_and_restored_after_battle(self):
        for task_type, interval in (
            (ScriptTask, 0.5), (DokanTask, 0.3),
            (GeneralBattle, 'combat'), (RealmRaidTask, 'combat'),
        ):
            with self.subTest(task=task_type.__module__):
                task = self.make_battle_task(task_type)
                with patch('tasks.Component.GeneralBattle.general_battle.GameUi.detect_page_in',
                           side_effect=[page_battle, page_battle_prepare]):
                    self.assertTrue(task.run_general_battle(GeneralBattleConfig()))
                self.assertEqual(task.device.screenshot_interval_set.call_args_list,
                                 [call(interval), call(None), call()])
                task._handle_prepare.assert_called_once()
                self.assertIsNone(task._battle_context)

    def test_exception_restores_polling_interval(self):
        task = self.make_battle_task(ScriptTask)
        task._handle_in_battle.side_effect = RuntimeError('battle failed')
        with patch('tasks.Component.GeneralBattle.general_battle.GameUi.detect_page_in',
                   return_value=page_battle):
            with self.assertRaisesRegex(RuntimeError, 'battle failed'):
                task.run_general_battle(GeneralBattleConfig())
        self.assertEqual(task.device.screenshot_interval_set.call_args_list,
                         [call(0.5), call()])
        self.assertIsNone(task._battle_context)

    def make_settlement(self, task_type=ScriptTask, last_page=page_reward, is_win=True):
        task = task_type.__new__(task_type)
        task.appear = Mock(return_value=True)
        context = SimpleNamespace(last_page=last_page, is_win=is_win,
                                  reward_no_battle_ts=None)
        return task, context

    def test_list_return_finishes_immediately_and_preserves_win_or_loss(self):
        for last_page in (page_battle_result, page_reward):
            for is_win, expected in ((True, BattleAction.EXIT_WIN),
                                     (False, BattleAction.EXIT_LOSE)):
                with self.subTest(page=last_page.key, win=is_win):
                    task, context = self.make_settlement(last_page=last_page, is_win=is_win)
                    action = task._handle_missing_battle_page(context, GeneralBattleConfig(), None)
                    self.assertEqual(action, expected)
                    task.appear.assert_called_once_with(task.I_TOPPA_RECORD)
                    self.assertIsNone(context.reward_no_battle_ts)

    def test_transitions_before_settlement_do_not_finish_battle(self):
        for last_page in (None, page_battle_prepare, page_battle):
            with self.subTest(page=last_page):
                task, context = self.make_settlement(last_page=last_page)
                action = task._handle_missing_battle_page(context, GeneralBattleConfig(), None)
                self.assertEqual(action, BattleAction.CONTINUE)
                task.appear.assert_not_called()

    def test_missing_list_marker_keeps_existing_timeout_and_loss_result(self):
        task, context = self.make_settlement(is_win=False)
        task.appear.return_value = False
        with patch('tasks.Component.GeneralBattle.general_battle.time.time', return_value=100):
            self.assertEqual(task._handle_missing_battle_page(context, GeneralBattleConfig(), None),
                             BattleAction.CONTINUE)
        with patch('tasks.Component.GeneralBattle.general_battle.time.time', return_value=102.6):
            self.assertEqual(task._handle_missing_battle_page(context, GeneralBattleConfig(), None),
                             BattleAction.EXIT_LOSE)

    def test_continuous_battle_keeps_existing_behavior(self):
        task, context = self.make_settlement()
        config = GeneralBattleConfig(continuous_battle=True)
        self.assertEqual(task._handle_missing_battle_page(context, config, None),
                         BattleAction.CONTINUE)
        task.appear.assert_not_called()

    def test_generic_battles_keep_settlement_timeout(self):
        task, context = self.make_settlement(task_type=GeneralBattle)
        self.assertEqual(task._handle_missing_battle_page(context, GeneralBattleConfig(), None),
                         BattleAction.CONTINUE)
        task.appear.assert_not_called()
        self.assertIsNotNone(context.reward_no_battle_ts)


if __name__ == '__main__':
    unittest.main()
