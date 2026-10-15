"""Dojo offline waits start on an actual Prepare click and reset for the next dojo."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from module.exception import TaskEnd
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.GeneralBattle.general_battle import BattleAction
from tasks.Dokan import page as pages
from tasks.Dokan.config import Dokan
from tasks.Dokan.script_task import DokanFinishedError, DokanPrepareOfflineWait, ScriptTask


class DokanPrepareOfflineWaitTest(unittest.TestCase):
    def setUp(self):
        logger = patch('tasks.Dokan.script_task.logger')
        logger.start()
        self.addCleanup(logger.stop)

    def make_task(self, enabled=True):
        task = ScriptTask.__new__(ScriptTask)
        task.conf = Dokan.model_validate({'dokan_config': {
            'prepare_offline_wait_enable': enabled, 'monday_to_thursday': False,
        }})
        task.config = SimpleNamespace(dokan=task.conf, model=SimpleNamespace(dokan=task.conf), save=Mock())
        task.dokan_owner_battle = False
        task.appear = Mock(return_value=False)
        task._run_battle_behavior_once = Mock()
        task._prepare_click_ready = Mock(return_value=True)
        task.appear_then_click = Mock(side_effect=lambda rule, **kwargs: all(
            rule is not popup for popup in (task.I_DISABLE_7DAYS_DIFF_SOUL, task.I_CONFIRM_CLOSE_DIFF_SOUL)))
        return task

    def prepare(self, task):
        return task._handle_prepare(SimpleNamespace(last_page=None), GeneralBattleConfig())

    def test_old_and_new_profiles_default_to_no_offline_wait(self):
        for data in ({}, {'dokan_config': {'min_people_num': 100}}):
            self.assertFalse(Dokan.model_validate(data).dokan_config.prepare_offline_wait_enable)
        task = self.make_task(enabled=False)
        self.assertEqual(self.prepare(task), BattleAction.CONTINUE)
        self.assertFalse(getattr(task, '_dokan_prepare_offline_wait_done', False))

    def test_only_the_first_actual_prepare_click_requests_a_wait(self):
        task = self.make_task()
        task.appear_then_click.return_value = False
        task.appear_then_click.side_effect = None
        self.assertEqual(self.prepare(task), BattleAction.CONTINUE)
        self.assertFalse(getattr(task, '_dokan_prepare_offline_wait_done', False))

        task.appear_then_click.side_effect = lambda rule, **kwargs: all(
            rule is not popup for popup in (task.I_DISABLE_7DAYS_DIFF_SOUL, task.I_CONFIRM_CLOSE_DIFF_SOUL))
        with self.assertRaises(DokanPrepareOfflineWait):
            self.prepare(task)
        self.assertTrue(task._dokan_prepare_offline_wait_done)
        self.assertEqual(self.prepare(task), BattleAction.CONTINUE)

    def test_prepare_delay_or_popup_does_not_consume_the_first_click(self):
        task = self.make_task()
        task._prepare_click_ready.return_value = False
        self.assertEqual(self.prepare(task), BattleAction.CONTINUE)
        self.assertFalse(getattr(task, '_dokan_prepare_offline_wait_done', False))
        task._prepare_click_ready.return_value = True
        task.appear_then_click.side_effect = lambda rule, **kwargs: rule is task.I_DISABLE_7DAYS_DIFF_SOUL
        self.assertEqual(self.prepare(task), BattleAction.CONTINUE)
        self.assertFalse(getattr(task, '_dokan_prepare_offline_wait_done', False))

    def test_owner_prepare_still_exits_before_clicking_or_requesting_a_wait(self):
        for marker in ('I_RYOU_DOKAN_BATTLE_MASTER_FIRST', 'I_RYOU_DOKAN_BATTLE_MASTER_SECOND'):
            with self.subTest(marker=marker):
                task = self.make_task()
                task.appear.side_effect = lambda rule: rule is getattr(task, marker)
                self.assertEqual(self.prepare(task), BattleAction.QUICK_EXIT)
                task.appear_then_click.assert_not_called()
                self.assertFalse(getattr(task, '_dokan_prepare_offline_wait_done', False))

    @patch('tasks.Dokan.script_task.sleep')
    @patch('tasks.Dokan.script_task.uniform', return_value=62)
    def test_second_dojo_gets_its_own_first_prepare_wait(self, _uniform, _sleep):
        task = self.make_task()
        with self.assertRaises(DokanPrepareOfflineWait):
            self.prepare(task)
        task.device = SimpleNamespace(stuck_record_clear=Mock(), stuck_record_add=Mock())
        task.goto_page = Mock()
        task.switch_member_soul_done = True
        task.wait_for_next_dokan_selection()
        self.assertTrue(task.second_dokan_ready)
        self.assertTrue(task.switch_member_soul_done)
        with self.assertRaises(DokanPrepareOfflineWait):
            self.prepare(task)
        self.assertEqual(self.prepare(task), BattleAction.CONTINUE)

    def make_reconnect_task(self):
        task = self.make_task()
        task._dokan_prepare_offline_wait_done = True
        task.switch_member_soul_done = True
        task.second_dokan_ready = False
        events = []
        task.device = SimpleNamespace(
            app_stop=Mock(side_effect=lambda: events.append('stop')),
            app_start=Mock(side_effect=lambda: events.append('start')),
            wait_app_start_ready=Mock(side_effect=lambda: events.append('ready')),
            stuck_record_clear=Mock(), stuck_record_add=Mock(), click_record_clear=Mock(),
        )
        task.goto_page = Mock(side_effect=lambda page: events.append(page))
        return task, events

    @patch('tasks.Dokan.script_task.LoginService')
    @patch('tasks.Dokan.script_task.sleep')
    def test_close_wait_login_and_reentry_follow_the_requested_order(self, sleeper, login):
        task, events = self.make_reconnect_task()
        sleeper.side_effect = lambda seconds: events.append(('sleep', seconds))
        login.return_value.app_handle_login.side_effect = lambda: events.append('login')
        task._wait_and_reconnect_after_prepare()
        self.assertEqual(events, [
            ('sleep', 1), 'stop', ('sleep', 600), 'start', 'ready', 'login', pages.page_dokan_map,
        ])
        login.assert_called_once_with(config=task.config, device=task.device)
        self.assertTrue(task._dokan_prepare_offline_wait_done)
        self.assertTrue(task.switch_member_soul_done)
        self.assertFalse(task.second_dokan_ready)
        self.assertEqual(task.device.stuck_record_clear.call_count, 3)
        task.device.stuck_record_add.assert_called_once_with('PAUSE')
        task.device.click_record_clear.assert_called_once()

    @patch('tasks.Dokan.script_task.LoginService')
    @patch('tasks.Dokan.script_task.sleep', side_effect=[None, RuntimeError('wait interrupted')])
    def test_interrupted_wait_cleans_pause_without_starting_the_game(self, _sleep, login):
        task, _events = self.make_reconnect_task()
        with self.assertRaisesRegex(RuntimeError, 'wait interrupted'):
            task._wait_and_reconnect_after_prepare()
        task.device.app_stop.assert_called_once()
        self.assertEqual(task.device.stuck_record_clear.call_count, 2)
        task.device.app_start.assert_not_called()
        task.goto_page.assert_not_called()
        login.assert_not_called()

    @patch('tasks.Dokan.script_task.LoginService')
    @patch('tasks.Dokan.script_task.sleep')
    def test_login_failure_does_not_navigate_using_an_unready_game(self, _sleep, login):
        task, _events = self.make_reconnect_task()
        login.return_value.app_handle_login.side_effect = RuntimeError('login unavailable')
        with self.assertRaisesRegex(RuntimeError, 'login unavailable'):
            task._wait_and_reconnect_after_prepare()
        task.goto_page.assert_not_called()

    def test_battle_context_is_cleaned_before_the_offline_wait(self):
        task = self.make_task()
        task._custom_pages_registered = True
        task.current_count = 0
        task.device = SimpleNamespace(stuck_record_add=Mock(), click_record_clear=Mock(),
                                      screenshot_interval_set=Mock(), app_stop=Mock())
        task._build_context = Mock(return_value=SimpleNamespace(
            last_page=None, reward_no_battle_ts=None, quick_exit=False,
        ))
        task._exit_matcher = Mock(return_value=None)
        for name in ('screenshot', '_tick_long_battle', '_tick_timeout',
                     '_sync_prepare_click_timer', '_ensure_battle_stuck_guard'):
            setattr(task, name, Mock())
        with patch('tasks.Component.GeneralBattle.general_battle.GameUi.detect_page_in',
                   return_value=pages.page_battle_prepare):
            with self.assertRaises(DokanPrepareOfflineWait):
                task.run_general_battle(GeneralBattleConfig())
        self.assertIsNone(task._battle_context)
        self.assertEqual(task.device.screenshot_interval_set.call_args_list, [call(None), call()])
        task.device.app_stop.assert_not_called()

    def test_task_resumes_stage_detection_after_the_offline_request(self):
        task = self.make_task()
        task.before_run = Mock()
        task.goto_page = Mock()
        task.screenshot = Mock()
        task._capture_dokan_reward_if_visible = Mock()
        task.get_current_page = Mock(side_effect=[
            pages.page_battle_prepare, pages.page_dokan_map, pages.page_dokan,
        ])
        task.run_on_battle = Mock(side_effect=DokanPrepareOfflineWait)
        task._wait_and_reconnect_after_prepare = Mock()
        task.run_on_dokan_map = Mock()
        task.run_on_dokan = Mock(side_effect=DokanFinishedError)
        task.next_run = Mock()
        task._push_current_run_reward_images = Mock()
        with self.assertRaises(TaskEnd):
            task.run()
        task._wait_and_reconnect_after_prepare.assert_called_once()
        task.run_on_dokan_map.assert_called_once()
        task.run_on_dokan.assert_called_once()
        task.next_run.assert_called_once_with(skip_today=False, is_dokan_activated=True)


if __name__ == '__main__':
    unittest.main()
