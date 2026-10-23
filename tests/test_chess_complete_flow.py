"""棋局共用资源的实例隔离、坐标衔接及恢复流程。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from module.atom.long_click import RuleLongClick
from module.atom.image import RuleImage
from module.exception import GameStuckError, TaskEnd
from module.image.runtime import ImageRuntime
from tasks.base_task import BaseTask
from tasks.Chess.assets import ChessAssets
from tasks.Chess.config import ChessConfig
from tasks.Chess.runtime.shared_ui import ChessNetworkRecoveryRequired
from tasks.Chess.runtime.state import ChessGameState
from tasks.Chess.script_task import ChessLegacyScriptTask, ScriptTask
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.GameUi.default_pages import page_chess, page_main, page_reward
from tasks.GameUi.game_ui import GameUi
from tasks.GlobalGame.assets import GlobalGameAssets
from tasks.GlobalGame.config_emergency import FriendInvitation


class ChessScopedRecognitionTest(unittest.TestCase):
    def setUp(self):
        self.runtime = ImageRuntime({'worker_count': 1})
        self.addCleanup(self.runtime.shutdown)
        self.match_patch = patch.object(RuleImage, 'match', autospec=True, side_effect=self.match)
        self.match_patch.start()
        self.addCleanup(self.match_patch.stop)

    def match(self, rule, image, threshold=None, frame_id=None):
        payload = rule.to_service_payload()
        if threshold is not None:
            payload['threshold'] = threshold
        return rule._apply_match_result(self.runtime._match_rule_payload(image, payload))

    def task_with_image(self, template, position=None):
        task = ScriptTask.__new__(ScriptTask)
        x, y = position or template.roi_back[:2]
        front = template.image
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        image[y:y+front.shape[0], x:x+front.shape[1]] = front
        task.device = SimpleNamespace(
            image=image, image_frame_id='frame-1', click=Mock(), long_click=Mock(),
            get_image_batch_cache=Mock(return_value=None),
        )
        task.interval_timer = {}
        task.detect_random_main_costume = Mock(return_value=False)
        return task

    def test_shared_resource_manifest_matches_copied_files(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / 'tasks/Chess/shared_ui/bindings.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest['rules']), 14)
        for entry in manifest['rules']:
            with self.subTest(rule=entry['symbol']):
                rule = getattr(ChessAssets, entry['asset'])
                self.assertEqual(hashlib.sha256((root / rule.file).read_bytes()).hexdigest(), entry['sha256'])
                self.assertGreater(rule.image.size, 0)

    def test_exit_confirmation_click_uses_the_new_match_coordinates(self):
        task = self.task_with_image(ChessAssets.I_SHARED_EXIT_ENSURE, (720, 430))
        original = GeneralBattleAssets.I_EXIT_ENSURE
        before = (original.file, tuple(original.roi_front), tuple(original.roi_back),
                  original.threshold, original.method)
        self.assertTrue(task.appear_then_click(original))
        x, y = task.device.click.call_args.args
        self.assertTrue(720 <= x < 827 and 430 <= y < 476)
        self.assertEqual((original.file, tuple(original.roi_front), tuple(original.roi_back),
                          original.threshold, original.method), before)

    def test_legacy_template_remains_a_fallback_and_clicks_its_own_coordinates(self):
        task = self.task_with_image(GlobalGameAssets.I_UI_REWARD, (480, 160))
        self.assertTrue(task.appear(GlobalGameAssets.I_UI_REWARD, threshold=.999))
        self.assertIs(task._chess_click_rule(GlobalGameAssets.I_UI_REWARD), GlobalGameAssets.I_UI_REWARD)
        task.click(GlobalGameAssets.I_UI_REWARD)
        x, y = task.device.click.call_args.kwargs['x'], task.device.click.call_args.kwargs['y']
        self.assertTrue(480 <= x < 720 and 160 <= y < 225)

    def test_a_new_frame_does_not_reuse_the_previous_fallback_click(self):
        task = self.task_with_image(GlobalGameAssets.I_UI_REWARD, (480, 160))
        self.assertTrue(task.appear(GlobalGameAssets.I_UI_REWARD, threshold=.999))
        task.device.image_frame_id = 'frame-2'
        self.assertIs(task._chess_click_rule(GlobalGameAssets.I_UI_REWARD),
                      task._chess_ui_variants[id(GlobalGameAssets.I_UI_REWARD)][0])

    def test_extended_reward_is_used_by_the_shared_result_flow(self):
        task = self.task_with_image(ChessAssets.I_SHARED_UI_REWARD, (370, 50))
        self.assertTrue(task._advance_chess_result_stage())
        task.device.click.assert_called_once()

    def test_navigation_matchers_use_scoped_main_and_reward_images(self):
        for rule, page in ((ChessAssets.I_SHARED_CHECK_MAIN, page_main),
                           (ChessAssets.I_SHARED_UI_REWARD, page_reward)):
            with self.subTest(page=page.name):
                task = self.task_with_image(rule)
                self.assertTrue(page.recognizer.evaluate(task))

    def test_unknown_page_confirm_click_uses_the_scoped_template(self):
        task = self.task_with_image(ChessAssets.I_SHARED_UI_CONFIRM, (650, 400))
        self.assertTrue(task._execute_action(GlobalGameAssets.I_UI_CONFIRM, skip_first_screenshot=True))
        x, y = task.device.click.call_args.args
        self.assertTrue(650 <= x < 819 and 400 <= y < 447)

    def test_reconnect_button_uses_the_source_template_and_click_region(self):
        task = self.task_with_image(ChessAssets.I_SHARED_CLIENT_CLEAR, (600, 380))
        self.assertTrue(task.appear_then_click(GlobalGameAssets.I_CLIENT_CLEAR))
        x, y = task.device.click.call_args.args
        self.assertTrue(600 <= x < 685 and 380 <= y < 422)

    def test_explicit_long_press_preserves_duration_and_action(self):
        task = self.task_with_image(ChessAssets.I_SHARED_EXIT_ENSURE)
        action = RuleLongClick((20, 30, 5, 5), (20, 30, 5, 5), duration=1000)
        self.assertTrue(task.appear_then_click(GeneralBattleAssets.I_EXIT_ENSURE,
                                               action=action, duration=250))
        self.assertEqual(task.device.long_click.call_args.kwargs['duration'], .25)
        task.device.click.assert_not_called()

    def test_other_tasks_still_receive_the_original_shared_rules(self):
        task = GameUi.__new__(GameUi)
        with patch.object(BaseTask, 'appear', return_value=True) as appear:
            self.assertTrue(task.appear(GeneralBattleAssets.I_EXIT_ENSURE))
        appear.assert_called_once_with(GeneralBattleAssets.I_EXIT_ENSURE)

    def test_scoped_rules_and_batch_cache_are_independent_per_instance(self):
        task = self.task_with_image(ChessAssets.I_SHARED_EXIT_ENSURE)
        other = self.task_with_image(ChessAssets.I_SHARED_EXIT_ENSURE)
        rule, original = task._chess_ui_variants[id(GeneralBattleAssets.I_EXIT_ENSURE)]
        other_rule = other._chess_ui_variants[id(original)][0]
        self.assertIsNot(rule, other_rule)
        rule.roi_front[0] = 999
        self.assertNotEqual(rule.roi_front[0], other_rule.roi_front[0])
        with patch.object(BaseTask, 'prepare_appear_cache') as prepare:
            task.prepare_appear_cache([original])
        self.assertEqual([id(r) for r in prepare.call_args.args[0]], [id(rule), id(original)])


class ChessRecoveryFlowTest(unittest.TestCase):
    def task(self, policy='wait_10s'):
        task = ScriptTask.__new__(ScriptTask)
        task.device = Mock()
        task.config = SimpleNamespace(global_game=SimpleNamespace(emergency=SimpleNamespace(
            when_network_abnormal=policy, friend_invitation=FriendInvitation.ACCEPT,
        )))
        task.chess_state = ChessGameState()
        task.chess_events = Mock()
        return task

    def test_screenshot_finishes_invitation_then_red_popup_before_returning(self):
        task = self.task()
        state = ['invite']
        task.device.image = 'invite'
        task.device.screenshot.side_effect = lambda: setattr(task.device, 'image', state[0])
        task.appear = lambda target, **_: target is GlobalGameAssets.I_G_ACCEPT and task.device.image == 'invite'
        clicks = []
        def click(rule, **kwargs):
            clicks.append(rule)
            if rule is GlobalGameAssets.I_G_ACCEPT:
                state[0] = 'red'
                return True
            if rule is task._chess_close_red and task.device.image == 'red':
                state[0] = 'board'
                return True
            return False
        task.appear_then_click = click
        task.set_next_run = Mock()
        self.assertEqual(task.screenshot(), 'board')
        self.assertEqual(clicks, [GlobalGameAssets.I_G_ACCEPT, task._chess_close_red, task._chess_close_red])
        task.set_next_run.assert_called_once()

    def test_transient_network_warning_refreshes_raw_screenshot(self):
        task = self.task()
        active = [True]
        task.appear = lambda rule: rule is GlobalGameAssets.I_NETWORK_ABNORMAL and active[0]
        task.device.screenshot.side_effect = lambda: active.__setitem__(0, False)
        with patch('tasks.Chess.runtime.shared_ui.time.monotonic', return_value=0):
            task._handle_network()
        task.device.sleep.assert_called_once_with(.25)
        task.device.screenshot.assert_called_once()

    def test_network_wait_respects_existing_ten_second_policy(self):
        task = self.task()
        task.appear = lambda rule: rule is GlobalGameAssets.I_NETWORK_ABNORMAL
        with patch('tasks.Chess.runtime.shared_ui.time.monotonic', side_effect=[0, 10]):
            with self.assertRaises(ChessNetworkRecoveryRequired) as caught:
                task._handle_network()
        self.assertFalse(caught.exception.reconnect)
        self.assertIsInstance(caught.exception, GameStuckError)
        task.device.sleep.assert_not_called()

    def test_restart_policy_does_not_wait(self):
        task = self.task('restart')
        task.appear = lambda rule: rule is GlobalGameAssets.I_NETWORK_ABNORMAL
        with self.assertRaises(ChessNetworkRecoveryRequired):
            task._handle_network()
        task.device.sleep.assert_not_called()

    def test_disconnect_takes_priority_and_requests_reconnect(self):
        task = self.task()
        task.appear = lambda rule: True
        with self.assertRaises(ChessNetworkRecoveryRequired) as caught:
            task._handle_network()
        self.assertTrue(caught.exception.reconnect)

    def test_reconnect_clicks_then_logs_in_and_clears_device_records(self):
        task = self.task()
        login = Mock()
        login.appear.side_effect = [False, True]
        task._create_chess_login = Mock(return_value=login)
        with patch('tasks.Chess.runtime.shared_ui.time.monotonic', return_value=0):
            task._reconnect_chess_network()
        login.appear_then_click.assert_called_once_with(login.I_CLIENT_CLEAR, interval=1)
        login.app_handle_login.assert_called_once()
        self.assertEqual(task.device.stuck_record_clear.call_count, 2)
        self.assertEqual(task.device.click_record_clear.call_count, 2)

    def test_failed_reconnect_uses_the_existing_restart_exception(self):
        task = self.task()
        login = Mock()
        login.appear.return_value = False
        task._create_chess_login = Mock(return_value=login)
        with patch('tasks.Chess.runtime.shared_ui.time.monotonic', side_effect=[0, 31]):
            with self.assertRaisesRegex(GameStuckError, 'reconnect failed'):
                task._reconnect_chess_network()
        login.app_handle_login.assert_not_called()

    def test_successful_reconnect_restarts_task_flow_with_fresh_state(self):
        task = self.task()
        previous_state = task.chess_state
        task.chess_state.game_number = 3
        task.chess_state.board_lineup_names.add('hakurou')
        task._hyakki_turn = SimpleNamespace(key=(3, 2), throws=2)
        task._board_marker_disabled_round = (3, 2)
        task._chess_ui_hits = {1: ('old-frame', object())}
        task._reconnect_chess_network = Mock()
        with patch.object(ChessLegacyScriptTask, 'run', side_effect=[
                ChessNetworkRecoveryRequired('disconnect', reconnect=True), TaskEnd('Chess')]):
            with self.assertRaises(TaskEnd):
                task.run()
        task._reconnect_chess_network.assert_called_once()
        self.assertIsNot(task.chess_state, previous_state)
        self.assertEqual(task.chess_state.game_number, 3)
        self.assertFalse(task.chess_state.board_lineup_names)
        self.assertNotIn('_chess_ui_hits', task.__dict__)
        self.assertNotIn('_hyakki_turn', task.__dict__)
        self.assertNotIn('_board_marker_disabled_round', task.__dict__)
        task.chess_events.reset.assert_called_once()

    def test_repeated_disconnects_cannot_loop_without_restart_limit(self):
        task = self.task()
        task._reconnect_chess_network = Mock()
        error = ChessNetworkRecoveryRequired('disconnect', reconnect=True)
        with patch.object(ChessLegacyScriptTask, 'run', side_effect=error):
            with self.assertRaises(ChessNetworkRecoveryRequired):
                task.run()
        task._reconnect_chess_network.assert_called_once()

    def test_task_coordinator_keeps_constraints_and_finishes_in_the_lobby(self):
        task = self.task()
        task.config.chess = SimpleNamespace(chess_config=ChessConfig(run_count=1))
        task.start_time = datetime.now()
        task._recover_interrupted_chess_game = Mock()
        task.goto_page = Mock()
        task.screenshot = Mock()
        task.run_one_game = Mock(return_value=6)
        task.return_to_chess_lobby = Mock()
        task.set_next_run = Mock()
        with self.assertRaises(TaskEnd):
            task.run()
        task._recover_interrupted_chess_game.assert_called_once()
        task.goto_page.assert_called_once_with(page_chess)
        task.run_one_game.assert_called_once()
        task.return_to_chess_lobby.assert_called_once()
        task.set_next_run.assert_called_once_with(task='Chess', success=True, finish=True)


if __name__ == '__main__':
    unittest.main()
