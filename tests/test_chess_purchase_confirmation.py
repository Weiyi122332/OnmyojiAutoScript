"""Reference fixes for Frame shop clicks, purchase confirmation and detail overlays."""

from collections import deque
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from module.device.device import Device
from module.image.runtime import ImageRuntime
from tasks.base_task import BaseTask
from tasks.Chess.assets import ChessAssets
from tasks.Chess.config import ChessConfig
from tasks.Chess.runtime.state import ChessGameState
from tasks.Chess.script_task import ScriptTask


class ChessPurchaseConfirmationTest(unittest.TestCase):
    def task(self, scenes):
        task = ScriptTask.__new__(ScriptTask)
        state = {'step': -1, 'clock': 0.0, 'shop': True, 'scene': scenes[0]}
        def screenshot():
            state['step'] += 1
            state['clock'] += .6
            state['scene'] = scenes[min(state['step'], len(scenes)-1)]
        task.screenshot = Mock(side_effect=screenshot)
        task._is_purchase_allowed = Mock(return_value=True)
        task.appear = Mock(return_value=False)
        task._is_shop_open = Mock(side_effect=lambda: state['shop'])
        task._recognize_shop_slot = Mock(side_effect=lambda *a, **k:
                                         {'name': 'onikiri'} if state['scene'][0] else None)
        task._lineup_hand_card_match_count = Mock(side_effect=lambda _: state['scene'][1])
        return task, state

    def confirm(self, task, state):
        with patch('tasks.Chess.runtime.economy.time.monotonic', side_effect=lambda: state['clock']), \
                patch('tasks.Chess.runtime.economy.time.sleep'):
            return task._confirm_shop_purchase(4, None, 'onikiri', 1)

    def test_success_requires_two_frames_of_shop_disappearance_and_hand_increase(self):
        task, state = self.task([(True, 1), (False, 2), (False, 2)])
        self.assertTrue(self.confirm(task, state))
        self.assertEqual(task.screenshot.call_count, 3)

    def test_shop_disappearance_alone_is_not_a_purchase(self):
        task, state = self.task([(False, 1)])
        self.assertFalse(self.confirm(task, state))

    def test_hand_increase_without_shop_disappearance_is_not_a_purchase(self):
        task, state = self.task([(True, 2)])
        self.assertFalse(self.confirm(task, state))

    def test_one_frame_of_success_is_not_enough(self):
        task, state = self.task([(False, 2), (True, 2)])
        self.assertFalse(self.confirm(task, state))

    def test_closing_the_shop_does_not_count_as_a_success(self):
        task, state = self.task([(False, 2)])
        state['shop'] = False
        self.assertFalse(self.confirm(task, state))
        task._lineup_hand_card_match_count.assert_not_called()

    def test_purchase_click_budget_remains_three_across_cleanup_retries(self):
        task = ScriptTask.__new__(ScriptTask)
        task.chess_state = ChessGameState()
        task.device = Device.__new__(Device)
        task.device.click_record = deque(maxlen=15)
        task._recognize_shop_slot = Mock(return_value={'name': 'onikiri', 'source': 'frame', 'score': 1})
        task._is_purchase_allowed = Mock(return_value=True)
        task._can_afford_shop_shikigami = Mock(return_value=True)
        task._hand_capacity_count = Mock(return_value=8)
        task._lineup_hand_card_match_count = Mock(return_value=0)
        task.appear = Mock(return_value=False)
        task.screenshot = Mock()
        task._free_one_hand_slot_for_purchase = Mock(side_effect=[
            {'type': 'other'}, {'type': 'lineup'}])
        _, targets = ChessAssets.F_STORE_CARD.range_targets((720, 1280, 3), allow_missing_image=True)
        click_rule = targets[5]
        def click(rule, **_):
            task.device.handle_control_check(rule)
            return True
        task.click = Mock(side_effect=click)
        self.assertFalse(task._buy_shop_slot(2, click_rule, 'onikiri'))
        self.assertEqual(task.click.call_count, 3)
        self.assertEqual(task._free_one_hand_slot_for_purchase.call_count, 2)
        self.assertEqual(len(task.device.click_record), 3)

    def test_failed_bidirectional_confirmation_keeps_click_guard_history(self):
        task = ScriptTask.__new__(ScriptTask)
        task._recognize_shop_slot = Mock(return_value={'name': 'onikiri', 'source': 'frame', 'score': 1})
        task._is_purchase_allowed = Mock(return_value=True)
        task._can_afford_shop_shikigami = Mock(return_value=True)
        task._hand_capacity_count = Mock(return_value=8)
        task._lineup_hand_card_match_count = Mock(return_value=0)
        task.ui_click_until_disappear = Mock(return_value=True)
        task._confirm_shop_purchase = Mock(return_value=False)
        task.device = SimpleNamespace(click_record_remove=Mock())
        self.assertFalse(task._buy_shop_slot(4, object(), 'onikiri'))
        task.device.click_record_remove.assert_not_called()


class ChessFrameShopClickTest(unittest.TestCase):
    def test_many_card_frames_supply_their_own_range_six_click_targets(self):
        task = ScriptTask.__new__(ScriptTask)
        task._reuse_image_match_results = True
        runtime = ImageRuntime({'worker_count': 1})
        self.addCleanup(runtime.shutdown)
        frame = ChessAssets.F_STORE_CARD
        bx, by, _, _ = frame.badge_references[0]
        rx, ry, _, _ = frame.roi_ranges[-2]
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        expected = [('hakurou', 480), ('onikiri', 667), ('ootakemaru', 1042)]
        badge = task.frame_badges['store'][0]
        for name, ax in expected:
            dx = ax - bx
            h, w = badge.shape[:2]
            image[by:by+h, ax:ax+w] = badge
            portrait = cv2.cvtColor(task.frame_portraits['store'][name], cv2.COLOR_GRAY2RGB)
            h, w = portrait.shape[:2]
            image[ry:ry+h, rx+dx:rx+dx+w] = portrait
        device = SimpleNamespace(image=image, image_frame_id='store-range-six',
                                 _image_batch_cache_frame_id=None, _image_batch_cache={})
        for name in ('reset_image_batch_cache', 'get_image_batch_cache', 'update_image_batch_cache'):
            setattr(device, name, MethodType(getattr(Device, name), device))
        task.device = device
        task.click = Mock(side_effect=AssertionError('Scanning must not click'))
        task.runframe = Mock(wraps=task.runframe)
        client = SimpleNamespace(match_rule=lambda rule_data, image=None, **_: runtime._match_rule_payload(
            device.image if image is None else image, rule_data))
        with patch('module.atom.image.get_image_client', return_value=client), \
                patch('module.atom.ocr.RuleOcr.ocr', return_value=''):
            cards = task._frame_card_scan('store')
            slots = dict(task._shop_slots())
        self.assertEqual([card['name'] for card in cards], [name for name, _ in expected])
        self.assertEqual(slots[4].roi_front, (530, 57, 175, 237))
        self.assertEqual(slots[4].name, 'CHESS_STORE_SLOT_4_RANGE_6')
        self.assertEqual(slots[5].roi_front, (343, 57, 175, 237))
        self.assertEqual(len(slots), 5)
        self.assertFalse(hasattr(ChessAssets, 'C_SHIKIGAMI_4'))
        self.assertEqual(task.runframe.call_count, 3)
        task.click.assert_not_called()


class ChessDetailsAndBoardAvailabilityTest(unittest.TestCase):
    def task(self):
        task = ScriptTask.__new__(ScriptTask)
        task.chess_state = ChessGameState()
        scene = {'details': True}
        task.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8), screenshot=Mock())
        task._handle_network = Mock()
        task.appear_then_click = Mock(return_value=False)
        task.appear = Mock(side_effect=lambda rule: rule is ChessAssets.I_SHIKIGAMI_SPECIFICS and scene['details'])
        task.click = Mock(side_effect=lambda *a, **k: scene.update(details=False) or True)
        return task, scene

    def test_screenshot_closes_unexpected_details_and_refreshes_the_frame(self):
        task, scene = self.task()
        with patch.object(BaseTask, '_burst', return_value=False):
            task.screenshot()
        self.assertFalse(scene['details'])
        task.click.assert_called_once_with(ChessAssets.C_CLICK_CLOSE_SPECIFICS_AREA, interval=.8)
        self.assertEqual(task.device.screenshot.call_count, 2)

    def test_intentional_details_remain_open_and_exception_restores_exemption(self):
        task, scene = self.task()
        with patch.object(BaseTask, '_burst', return_value=False):
            with self.assertRaises(RuntimeError):
                with task._allow_chess_details():
                    task.screenshot()
                    self.assertTrue(scene['details'])
                    raise RuntimeError('inspection failed')
        self.assertEqual(task._chess_details_depth, 0)
        task.click.assert_not_called()

    def test_goldfish_inspection_explicitly_preserves_then_closes_details(self):
        task, _ = self.task()
        task._is_preparation_mode = Mock(return_value=True)
        task._set_position = Mock(return_value=(902, 505))
        task.device.click_record_remove = Mock()
        task.close_shikigami_specifics_if_open = Mock()
        def wait(_):
            self.assertEqual(task._chess_details_depth, 1)
            return True
        task._wait_chess_action_state = Mock(side_effect=wait)
        self.assertTrue(task._inspect_arakawa_goldfish(12))
        self.assertEqual(task._chess_details_depth, 0)
        task.close_shikigami_specifics_if_open.assert_called_once()

    def test_unavailable_board_preserves_registered_lineup(self):
        task = ScriptTask.__new__(ScriptTask)
        task.chess_state = ChessGameState()
        task.select_lineup_strategy('pinganjing')
        task._board_frame_scan = Mock(return_value=[])
        task._board_lineup_names = {'aoandon'}
        task._board_actual_positions = {'aoandon': 1}
        self.assertIsNone(task._read_board_position_count())
        self.assertIsNone(task._board_set_has_shikigami(1))
        self.assertFalse(task._board_set_is_empty(1))
        self.assertEqual(task._reconcile_lineup_after_hyakki_round(), [])
        self.assertEqual(task._board_lineup_names, {'aoandon'})
        self.assertEqual(task._board_actual_positions, {'aoandon': 1})

    def test_battle_frame_is_unavailable_for_occupancy_detection(self):
        task = ScriptTask.__new__(ScriptTask)
        task._read_chess_mode = Mock(return_value='战')
        self.assertEqual(task._board_frame_scan(), [])

    def test_board_scan_does_not_read_through_an_unclosed_shop(self):
        task = ScriptTask.__new__(ScriptTask)
        task._read_chess_mode = Mock(return_value='备')
        task._shop_refresh_marker_visible = Mock(return_value=True)
        task._ensure_shop_closed = Mock(return_value=False)
        self.assertEqual(task._board_frame_scan(), [])
        task._ensure_shop_closed.assert_called_once()

    def test_old_builtin_haiguo_identity_migrates_without_changing_custom_lineups(self):
        config = ChessConfig(lineup_bond='自定义阵容', custom_lineup='builtin:haiguo')
        self.assertEqual(config.custom_lineup, 'builtin:huangchuan')
        config = ChessConfig(lineup_bond='自定义阵容', custom_lineup='custom:haiguo')
        self.assertEqual(config.custom_lineup, 'custom:haiguo')


if __name__ == '__main__':
    unittest.main()
