"""参考仓库 7cc93181 的容量、升星和超时修复，以及召回前腾位。"""

import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from module.exception import GameStuckError
from module.atom.click import RuleClick
from tasks.Chess.config import ChessConfig
from tasks.Chess.runtime.activity_watchdog import ChessActivityWatchdog, ChessInactiveError
from tasks.Chess.runtime.hyakki_draft import HyakkiTurn
from tasks.Chess.runtime.state import ChessGameState
from tasks.Chess.script_task import ScriptTask


DRAG = 'tasks.Chess.runtime.hand_operations.Press_and_Drag'
SHOP_CLICK = RuleClick((100, 100, 20, 20), (100, 100, 20, 20), name='test_shop_slot')


class ChessCapacityFixTest(unittest.TestCase):
    def task(self):
        task = ScriptTask.__new__(ScriptTask)
        task.chess_state = ChessGameState(game_number=1)
        task._current_round_no = 5
        task.device = Mock()
        task.screenshot = Mock()
        task._is_preparation_mode = Mock(return_value=True)
        task._is_boss_challenge_round = Mock(return_value=False)
        task._ensure_shop_closed = Mock(return_value=True)
        task._set_position = Mock(return_value=(877, 398))
        task._board_set_has_shikigami = Mock(side_effect=lambda index: index == 11)
        task._hand_capacity_count = Mock(return_value=10)
        task.emergency_cleanup_hand = Mock(return_value=None)
        task._wait_chess_action_state = Mock(return_value=True)
        return task

    def test_capacity_counts_unknown_card_anchors_without_identity_ocr(self):
        task = ScriptTask.__new__(ScriptTask)
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        badge = task.frame_badges['card'][0]
        height, width = badge.shape[:2]
        for x in range(200, 1100, 90):
            image[550:550+height, x:x+width] = badge
        task.device = SimpleNamespace(image=image)
        task._soul_hand_cards = Mock(return_value=[])
        task._frame_card_scan = Mock(side_effect=AssertionError('Capacity must not require identities'))
        self.assertEqual(task._hand_capacity_count(), 10)
        task._frame_card_scan.assert_not_called()

    def test_full_hand_defers_recall_without_dragging_or_stuck_error(self):
        task = self.task()
        with patch(DRAG) as drag:
            self.assertIsNone(task._recall_one_system_board_card())
        task.emergency_cleanup_hand.assert_called_once()
        drag.assert_not_called()
        task._wait_chess_action_state.assert_not_called()

    def test_recall_only_drags_after_cleanup_frees_space(self):
        task = self.task()
        task._hand_capacity_count.side_effect = [10, 9, 9]
        order = []
        task.emergency_cleanup_hand.side_effect = lambda: order.append('cleanup')
        with patch(DRAG, side_effect=lambda *a, **k: order.append('drag')):
            self.assertEqual(task._recall_one_system_board_card(), 11)
        self.assertEqual(order, ['cleanup', 'drag'])

    def test_recall_with_space_preserves_existing_behavior(self):
        task = self.task()
        task._hand_capacity_count.return_value = 9
        with patch(DRAG) as drag:
            self.assertEqual(task._recall_one_system_board_card(), 11)
        drag.assert_called_once()
        task.emergency_cleanup_hand.assert_not_called()

    def test_phase_change_during_cleanup_stops_the_recall(self):
        task = self.task()
        task._is_preparation_mode.side_effect = [True, False]
        with patch(DRAG) as drag:
            self.assertIsNone(task._recall_one_system_board_card())
        drag.assert_not_called()

    def test_bulk_recall_also_defers_if_cleanup_cannot_free_space(self):
        task = self.task()
        task._read_shikigami_count = Mock(return_value={'current': 3, 'total': 3})
        with patch(DRAG) as drag:
            self.assertFalse(task.recall_all_board_cards())
        drag.assert_not_called()

    def test_board_card_registered_by_script_is_protected(self):
        task = self.task()
        task._player_deployed_positions = {11}
        with patch(DRAG) as drag:
            self.assertIsNone(task._recall_one_system_board_card())
        task.emergency_cleanup_hand.assert_not_called()
        drag.assert_not_called()

    def shop_task(self):
        task = self.task()
        task._recognize_shop_slot = Mock(return_value={'source': 'frame', 'score': 1})
        task._is_purchase_allowed = Mock(return_value=True)
        task._can_afford_shop_shikigami = Mock(return_value=True)
        task._lineup_hand_card_match_count = Mock(return_value=0)
        task._confirm_shop_purchase = Mock(return_value=True)
        task._free_one_hand_slot_for_purchase = Mock(return_value={'type': 'emergency_cleanup'})
        task.ui_click_until_disappear = Mock(return_value=True)
        return task

    def test_full_hand_is_cleaned_before_the_purchase_click(self):
        task = self.shop_task()
        task._hand_capacity_count.side_effect = [10, 9]
        order = []
        task._free_one_hand_slot_for_purchase.side_effect = lambda **_: order.append('cleanup') or {'type': 'emergency_cleanup'}
        task.ui_click_until_disappear.side_effect = lambda *a, **k: order.append('buy') or True
        self.assertTrue(task._buy_shop_slot(1, SHOP_CLICK, 'hakurou'))
        self.assertEqual(order, ['cleanup', 'buy'])

    def test_purchase_is_bounded_if_hand_remains_full_after_cleanup(self):
        task = self.shop_task()
        task._free_one_hand_slot_for_purchase.side_effect = [
            {'type': 'emergency_cleanup'}, {'type': 'lineup'},
        ]
        self.assertFalse(task._buy_shop_slot(1, SHOP_CLICK, 'hakurou'))
        self.assertEqual(task._free_one_hand_slot_for_purchase.call_count, 2)
        task.ui_click_until_disappear.assert_not_called()


class ChessStarConfirmationTest(unittest.TestCase):
    def task(self, hand_stars, board_stars=None):
        task = ScriptTask.__new__(ScriptTask)
        task.chess_state = ChessGameState()
        task.select_lineup_strategy('huangchuan')
        task.device = Mock()
        task._ensure_shop_closed = Mock(return_value=True)
        task._set_position = Mock(return_value=(461, 505))
        task._read_shikigami_count = Mock(return_value={'current': 3, 'total': 3})
        task._lineup_hand_card_match_count = Mock(return_value=1)
        task._lineup_hand_stars = Mock(side_effect=hand_stars)
        task._board_set_has_shikigami = Mock(return_value=True)
        task.close_shikigami_specifics_if_open = Mock(return_value=False)
        task.observed_confirmation = []
        if board_stars is not None:
            task._board_lineup_names = {'kujira'}
            task._board_set_star = Mock(side_effect=board_stars)
        def wait(condition):
            for _ in range(4):
                result = condition()
                task.observed_confirmation.append(result)
                if result:
                    return True
            return False
        task._wait_chess_action_state = wait
        return task

    def test_hand_upgrade_with_same_count_needs_two_confirming_frames(self):
        task = self.task([(1,), (2,), (2,), (2,)])
        with patch(DRAG):
            self.assertTrue(task.deploy_shikigami_hand_card('kujira', (425, 620)))
        self.assertEqual(task.observed_confirmation, [False, True])

    def test_board_upgrade_can_confirm_without_hand_count_decrease(self):
        task = self.task([(1,)] * 4, [1, 2, 2])
        with patch(DRAG):
            self.assertTrue(task.deploy_shikigami_hand_card('kujira', (425, 620)))
        self.assertEqual(task.observed_confirmation, [False, True])

    def test_a_single_star_spike_does_not_confirm_deployment(self):
        task = self.task([(1,)] * 5, [1, 2, 1, 1, 1])
        with patch(DRAG):
            self.assertFalse(task.deploy_shikigami_hand_card('kujira', (425, 620)))
        self.assertEqual(task.observed_confirmation, [False] * 4)


class ChessHyakkiPreferenceTest(unittest.TestCase):
    def test_preference_off_allows_random_targets_without_waiting_for_all_locks(self):
        task = ScriptTask.__new__(ScriptTask)
        task._hyakki_all_locks_gone = Mock(return_value=False)
        candidates = [{'name': 'poshi', 'center': (300, 200)}]
        self.assertEqual(task._hyakki_target_pool(candidates, set(), False), candidates)
        task._hyakki_all_locks_gone.assert_not_called()

    def test_preference_off_still_runs_throw_with_own_lock_gate(self):
        task = ScriptTask.__new__(ScriptTask)
        task.config = SimpleNamespace(chess=SimpleNamespace(chess_config=ChessConfig(hyakki_draft_enabled=False)))
        task.chess_state = ChessGameState(game_number=1)
        task._current_round_no = 5
        task._hyakki_turn = HyakkiTurn((1, 5), unlocked_at=0, absent_frames=2, wait_seconds=0)
        task._hyakki_own_lock = Mock(return_value=.1)
        task._hyakki_needed_souls = Mock(side_effect=AssertionError('Preference is off'))
        task._read_chess_mode = Mock(return_value='鬼')
        task.screenshot = Mock()
        task.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8), click=Mock())
        task.hyakki_soul_fronts = {}
        candidates = [{'name': 'poshi', 'center': (300, 200), 'score': 1}]
        with patch('tasks.Chess.runtime.hyakki_draft.find_souls', return_value=candidates), \
                patch('tasks.Chess.runtime.hyakki_draft.time.monotonic', return_value=10):
            task._handle_hyakki_draft()
        task.device.click.assert_called_once_with(x=300, y=350, control_name='CHESS_HYAKKI_THROW')
        self.assertEqual(task._hyakki_turn.throws, 1)


class ChessActivityWatchdogTest(unittest.TestCase):
    def test_profile_is_restored_even_if_the_task_raises(self):
        previous = sys.getprofile()
        with patch('tasks.Chess.runtime.activity_watchdog.threading.Thread') as thread:
            with self.assertRaises(RuntimeError):
                with ChessActivityWatchdog() as watchdog:
                    self.assertEqual(sys.getprofile(), watchdog._profile)
                    raise RuntimeError('task failed')
        self.assertIs(sys.getprofile(), previous)
        thread.return_value.join.assert_called_once_with(timeout=2)

    def test_return_from_device_input_resets_inactivity_time(self):
        watchdog = ChessActivityWatchdog()
        watchdog.previous_profile = Mock()
        watchdog.last_activity = 0
        frame = SimpleNamespace(f_code=SimpleNamespace(
            co_filename='D:/OAS/module/device/control.py', co_name='click',
        ))
        with patch('tasks.Chess.runtime.activity_watchdog.time.monotonic', return_value=42):
            watchdog._profile(frame, 'return', None)
        self.assertEqual(watchdog.last_activity, 42)
        watchdog.previous_profile.assert_called_once_with(frame, 'return', None)

    def test_timeout_uses_existing_game_stuck_error_and_only_fires_once(self):
        watchdog = ChessActivityWatchdog(timeout=300)
        watchdog.stop_event = Mock()
        watchdog.stop_event.wait.return_value = False
        watchdog.last_activity = 0
        watchdog._raise_timeout = Mock()
        with patch('tasks.Chess.runtime.activity_watchdog.time.monotonic', return_value=300):
            watchdog._watch()
        watchdog._raise_timeout.assert_called_once()
        with self.assertRaises(GameStuckError):
            raise ChessInactiveError()


if __name__ == '__main__':
    unittest.main()
