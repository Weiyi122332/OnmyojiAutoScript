"""Frame-based state, health budgets, confirmation and scoped navigation updates."""
from copy import copy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from module.atom.frame import Click, Ocr, RuleFrame
from module.atom.ocr import RuleOcr
from module.image.runtime import ImageRuntime
from tasks.Chess.assets import ChessAssets
from tasks.Chess.config import ChessConfig
from tasks.Chess.runtime.cache import same_frame
from tasks.Chess.runtime.state import ChessGameState
from tasks.Chess.script_task import ChessLegacyScriptTask, ScriptTask
from tasks.GameUi.game_ui import GameUi


class ChessDetailFrameTest(unittest.TestCase):
    def test_three_layouts_read_round_phase_and_time_once_per_screenshot(self):
        runtime = ImageRuntime({'worker_count': 1})
        self.addCleanup(runtime.shutdown)
        for kind in ('NORMAL', 'MONSTER', 'HYAKKI'):
            with self.subTest(layout=kind):
                task = ScriptTask.__new__(ScriptTask)
                task.chess_state = ChessGameState()
                frame = copy(getattr(ChessAssets, 'F_CHESS_DETAIL_' + kind))
                setattr(task, 'F_CHESS_DETAIL_' + kind, frame)
                image = np.zeros((720, 1280, 3), dtype=np.uint8)
                x, y, w, h = frame.badge_references[0]
                image[y:y+h, x:x+w] = frame.image
                task.device = SimpleNamespace(image=image, image_frame_id=kind)
                task._stage_marker_visible = Mock(return_value=kind == 'HYAKKI')
                def appear(rule, **_):
                    if rule is ChessAssets.I_STAGE_MONSTER:
                        return kind == 'MONSTER'
                    return rule._apply_match_result(runtime._match_rule_payload(image, rule.to_service_payload()))
                task.appear = appear
                with patch.object(RuleOcr, 'ocr', side_effect=[9, '鬼' if kind == 'HYAKKI' else '备', 37]) as ocr:
                    self.assertEqual(task._read_round_number(), 9)
                    self.assertEqual(task._read_chess_mode(), '鬼' if kind == 'HYAKKI' else '备')
                    self.assertEqual(task._read_remaining_time(), 37)
                    self.assertEqual(ocr.call_count, 3)

    def test_digit_requirements_are_typed_and_do_not_skip_digit_ocr(self):
        frame = RuleFrame(roi_badge=(0, 0, 4, 4), roi_back=(0, 0, 50, 50),
                          roi_range=[(5, 5, 8, 8), (20, 20, 8, 8)],
                          badgefile=['not-read.png'], range=[Ocr(mode='Digit'), Click()])
        frame.defer_ocr = True
        task = SimpleNamespace(device=SimpleNamespace(image=np.zeros((50, 50, 3), dtype=np.uint8)),
                               appear=Mock(return_value=True), click=Mock())
        with patch.object(RuleOcr, 'ocr', return_value=9) as ocr:
            self.assertTrue(frame.run(task, [8, 9], True))
            task.click.assert_called_once()
            task.click.reset_mock()
            self.assertFalse(frame.run(task, 10, True))
            task.click.assert_not_called()
            self.assertEqual(tuple(frame.run(task)), (9, (20, 20, 8, 8)))
            self.assertEqual(ocr.call_count, 3)
        for invalid in (True, '9', [], [9, True]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                frame.bind_runframe((invalid,))

    def test_same_frame_cache_expires_on_image_or_frame_identity_change(self):
        class Reader:
            def __init__(self):
                self.device = SimpleNamespace(image=np.zeros((2, 2)), image_frame_id='a')
                self.calls = 0
            @same_frame
            def read(self):
                self.calls += 1
                return self.calls
        reader = Reader()
        self.assertEqual((reader.read(), reader.read()), (1, 1))
        reader.device.image_frame_id = 'b'
        self.assertEqual(reader.read(), 2)
        reader.device.image = np.ones((2, 2))
        self.assertEqual(reader.read(), 3)


class ChessHealthEconomyTest(unittest.TestCase):
    def task(self):
        task = ScriptTask.__new__(ScriptTask)
        task.chess_state = ChessGameState()
        task._lineup_final_level = Mock(return_value=9)
        task._read_round_number = Mock(return_value=10)
        return task

    def test_reserve_thresholds_refresh_quota_and_low_health(self):
        task = self.task()
        self.assertEqual(task._economy_reserve_for_level(6), 50)
        self.assertFalse(task._can_execute_economy_operation(6, 54, 'experience'))
        self.assertTrue(task._can_execute_economy_operation(6, 55, 'experience'))
        self.assertFalse(task._can_execute_economy_operation(6, 56, 'refresh'))
        self.assertTrue(task._can_execute_economy_operation(6, 57, 'refresh'))
        task.chess_state.economy_refresh_counts[10] = 1
        self.assertFalse(task._can_execute_economy_operation(6, 100, 'refresh'))
        task.chess_state.current_health = 59
        self.assertEqual(task._economy_reserve_for_level(6), 40)
        task.chess_state.current_health = 19
        self.assertFalse(task._can_execute_economy_operation(6, 100, 'experience'))
        self.assertTrue(task._can_execute_economy_operation(6, 2, 'refresh'))
        self.assertEqual(task._economy_sequence_for_level(6), ('refresh',))

    def test_partial_refresh_progress_spends_only_one_attempt_and_consumes_quota(self):
        task = self.task()
        task._read_chess_mode = Mock(return_value='备')
        task._read_level = Mock(return_value=6)
        task._read_shop_gold = Mock(return_value=60)
        task.appear = Mock(return_value=True)
        task._economy_action_allowed = Mock(return_value=True)
        task._clear_economy_click_history = Mock()
        task.click = Mock()
        task._shop_slots = Mock(return_value=[])
        task._shop_slot_refresh_snapshot = Mock(return_value={
            i: {'image': np.zeros((4, 4), dtype=np.uint8)} for i in range(1, 6)})
        task._shop_refresh_changed_slots = Mock(return_value=([1], {}))
        clock = [0.0]
        task.screenshot = Mock(side_effect=lambda: clock.__setitem__(0, clock[0] + .7))
        with patch('tasks.Chess.runtime.economy.time.monotonic', side_effect=lambda: clock[0]):
            self.assertEqual(task._click_shop_refresh_and_confirm_slots(False), 'no_progress')
        task.click.assert_called_once()
        self.assertEqual(task.chess_state.economy_refresh_counts[10], 1)

    def test_health_reads_only_the_own_player_after_first_hyakki_once_per_round(self):
        task = self.task()
        task.chess_state.player_name = '本人'
        task.chess_state.first_hyakki_round = 6
        task._shop_assumed_open = False
        task._shop_refresh_marker_visible = Mock(return_value=False)
        task.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8), image_frame_id='hp')
        task.O_NAME_RANGE = SimpleNamespace(roi=(1000, 40, 200, 600), detect_and_ocr=Mock(return_value=[
            SimpleNamespace(ocr_text='本人', box=[[10, 20], [50, 20], [50, 40], [10, 40]]),
            SimpleNamespace(ocr_text='别人', box=[[10, 80], [50, 80], [50, 100], [10, 100]])]))
        with patch.object(RuleOcr, 'ocr', return_value=17) as ocr:
            self.assertEqual(task._read_current_health(), 17)
            self.assertEqual(task._read_current_health(), 17)
            ocr.assert_called_once()
        self.assertEqual(task.chess_state.health_read_round, 10)
        self.assertEqual(task.chess_state.observation.current_health, 17)

    def test_ending_a_game_clears_player_identity_even_on_failure(self):
        task = self.task()
        task.chess_state.player_name = '本人'
        task.chess_state.current_health = 17
        with patch.object(ChessLegacyScriptTask, '_run_round_loop', side_effect=RuntimeError('exit')):
            with self.assertRaises(RuntimeError):
                task._run_round_loop()
        self.assertIsNone(task.chess_state.player_name)
        self.assertIsNone(task.chess_state.current_health)

    def test_combat_screenshot_interval_is_restored_when_the_loop_fails(self):
        task = self.task()
        task.device = Mock()
        task._run_game_by_rounds_without_device_stuck_timeout = Mock(side_effect=RuntimeError('exit'))
        with self.assertRaises(RuntimeError):
            ChessLegacyScriptTask._run_round_loop(task)
        self.assertEqual(task.device.screenshot_interval_set.call_args_list[0].args, ('combat',))
        self.assertEqual(task.device.screenshot_interval_set.call_args_list[-1].args, ())


class ChessConfirmationAndNavigationTest(unittest.TestCase):
    def test_failed_goldfish_move_does_not_change_positions(self):
        task = ScriptTask.__new__(ScriptTask)
        task.chess_state = ChessGameState()
        task.select_lineup_strategy('huangchuan')
        task._board_lineup_names = {'kujira'}
        task._board_actual_positions = {'kujira': 7}
        task._is_preparation_mode = Mock(return_value=True)
        task._board_action_allowed = Mock(return_value=True)
        task._set_position = Mock(side_effect=lambda index: (index*10, 100))
        task._inspect_arakawa_goldfish = Mock(return_value=False)
        task.screenshot = Mock()
        task._record_arakawa_goldfish_position(6, identified=True)
        with patch('tasks.Chess.runtime.hand_operations.Press_and_Drag'):
            self.assertFalse(task._move_arakawa_goldfish(6))
        self.assertEqual(task._arakawa_goldfish_current_position, 6)
        self.assertEqual(task._board_actual_positions, {'kujira': 7})
        self.assertTrue(task._goldfish_relocation_pending)

    def test_preparation_lineup_check_is_read_only_and_runs_once_on_a_valid_board(self):
        task = ScriptTask.__new__(ScriptTask)
        task.chess_state = ChessGameState()
        task._read_round_number = Mock(return_value=9)
        task._read_chess_mode = Mock(return_value='备')
        task._shop_refresh_marker_visible = Mock(return_value=False)
        task._shop_assumed_open = False
        task.appear = Mock(return_value=False)
        task._board_frame_scan = Mock(return_value=[])
        task._reconcile_preparation_lineup = Mock()
        task.screenshot = Mock(side_effect=AssertionError('Inspection must reuse the closed-shop frame'))
        task._check_preparation_lineup_once(9)
        self.assertNotIn(9, task.chess_state.preparation_lineup_checked_rounds)
        task._board_frame_scan.return_value = [{'occupied': True}]
        task._check_preparation_lineup_once(9)
        task._check_preparation_lineup_once(9)
        task._reconcile_preparation_lineup.assert_called_once()

    def test_chess_town_failure_recovers_via_main_and_returns_for_outer_retry(self):
        main = SimpleNamespace(key='page_main')
        town = SimpleNamespace(key='page_town')
        back = SimpleNamespace(source=town, destination=main)
        enter = SimpleNamespace(source=main, destination=town)
        target = SimpleNamespace(source=town, destination=SimpleNamespace(key='page_entertainment'))
        town.transitions, main.transitions = [back], [enter]
        task = ScriptTask.__new__(ScriptTask)
        task.navigator = SimpleNamespace(current_page=town)
        with patch.object(GameUi, '_execute_transition', side_effect=[False, True, True]) as execute:
            self.assertFalse(task._execute_transition(target))
        self.assertEqual([call.args[0] for call in execute.call_args_list], [target, back, enter])

    def test_disabling_sixrealms_waits_without_clicking(self):
        task = ScriptTask.__new__(ScriptTask)
        task.config = SimpleNamespace(chess=SimpleNamespace(chess_config=ChessConfig(sixrealms_selection_enabled=False)))
        task.appear = Mock(side_effect=[True, True, False])
        task.device = Mock()
        task.screenshot = Mock()
        task.click = Mock(side_effect=AssertionError('Selection is disabled'))
        with patch('tasks.Chess.script_task.time.sleep'):
            self.assertTrue(task.select_chess_sixrealms_if_visible())
        task.click.assert_not_called()
        task.device.stuck_record_clear.assert_called_once()


class ChessSaleConfirmationTest(unittest.TestCase):
    def task(self):
        task = ScriptTask.__new__(ScriptTask)
        task.chess_state = ChessGameState()
        task._read_round_number = Mock(return_value=7)
        task._sale_action_allowed = Mock(return_value=True)
        task._hand_card_identity_count = Mock(return_value=1)
        task.close_shikigami_specifics_if_open = Mock(return_value=False)
        task.sell_hand_card = Mock(return_value=True)
        task._confirm_chess_drag = Mock()
        return task

    def test_two_failed_sales_block_only_that_target_until_the_next_round(self):
        task = self.task()
        card = {'type': 'shikigami', 'name': 'onikiri', 'position': (700, 620)}
        clock = [0.0]
        task.screenshot = Mock(side_effect=lambda: clock.__setitem__(0, clock[0] + .8))
        with patch('tasks.Chess.runtime.hand_operations.time.monotonic', side_effect=lambda: clock[0]):
            for _ in range(3):
                self.assertEqual(task._sell_hand_card_confirmed(card), 'blocked')
        self.assertEqual(task.sell_hand_card.call_count, 2)
        self.assertTrue(task._sale_target_blocked(card))
        self.assertFalse(task._sale_target_blocked(dict(card, position=(400, 620))))
        task._read_round_number.return_value = 8
        self.assertFalse(task._sale_target_blocked(card))

    def test_phase_change_after_sale_drag_is_not_reported_as_success(self):
        task = self.task()
        card = {'type': 'shikigami', 'name': 'onikiri', 'position': (700, 620)}
        task.screenshot = Mock(side_effect=lambda: setattr(task._sale_action_allowed, 'return_value', False))
        self.assertEqual(task._sell_hand_card_confirmed(card, ('备',)), 'interrupted')
        task._confirm_chess_drag.assert_not_called()
        self.assertEqual(task.chess_state.sale_failures, {})

    def test_full_hand_sells_an_unassignable_soul_before_a_lineup_card(self):
        task = self.task()
        task.select_lineup_strategy('qijiaoshan')
        task._board_lineup_names = set()
        task._hand_capacity_count = Mock(return_value=10)
        task._soul_hand_cards = Mock(return_value=[{'name': 'poshi', 'category': 'attack', 'position': (700, 620)}])
        task._soul_targets = Mock(return_value=[])
        task._sale_target_blocked = Mock(return_value=False)
        task._sell_hand_card_confirmed = Mock(return_value='success')
        task._ensure_shop_closed = Mock(return_value=True)
        task._ensure_shop_open = Mock(return_value=True)
        task.screenshot = Mock()
        task.sell_one_lineup_hand_card = Mock()
        self.assertEqual(task._free_one_hand_slot_for_purchase(sell_lineup=True), {'type': 'soul', 'name': 'poshi'})
        task.sell_one_lineup_hand_card.assert_not_called()


if __name__ == '__main__':
    unittest.main()
