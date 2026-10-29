"""Exercise ordinary/boss board layouts through the project's real Frame runtime."""

from copy import copy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from module.exception import GameStuckError
from module.image.runtime import ImageRuntime
from tasks.Chess.assets import ChessAssets
from tasks.Chess.runtime.state import ChessGameState
from tasks.Chess.script_task import ScriptTask


class ChessBoardFrameTest(unittest.TestCase):
    def setUp(self):
        self.runtime = ImageRuntime({'worker_count': 1})
        self.addCleanup(self.runtime.shutdown)

    def task(self, boss=False, shift=(0, 0), occupied=None, anchor=True):
        task = ScriptTask.__new__(ScriptTask)
        task.chess_state = ChessGameState(game_number=1)
        task._current_round_no = 9 if boss else 5
        task._is_boss_challenge_round = Mock(return_value=boss)
        task._read_chess_mode = Mock(return_value='备')
        task._shop_refresh_marker_visible = Mock(return_value=False)
        task.F_BOARD_OCCUPANCY = copy(ChessAssets.F_BOARD_OCCUPANCY)
        task.F_BOSS_BOARD_OCCUPANCY = copy(ChessAssets.F_BOSS_BOARD_OCCUPANCY)
        frame = task.F_BOSS_BOARD_OCCUPANCY if boss else task.F_BOARD_OCCUPANCY
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        dx, dy = shift
        if anchor:
            badge = frame.image
            x, y, w, h = frame.badge_references[0]
            image[y+dy:y+dy+h, x+dx:x+dx+w] = badge
        for index, star in (occupied or {}).items():
            front = task.board_occupancy_rules[star-1].image
            x, y, _, _ = frame.roi_ranges[index-1]
            h, w = front.shape[:2]
            image[y+dy:y+dy+h, x+dx:x+dx+w] = front
        task.device = SimpleNamespace(image=image, image_frame_id='board-1')
        task.appear = lambda rule, **_: rule._apply_match_result(
            self.runtime._match_rule_payload(task.device.image, rule.to_service_payload()))
        task.click = Mock(side_effect=AssertionError('Board scans must be read-only'))
        return task, frame

    def test_normal_and_boss_layouts_rebase_occupancy_and_drop_coordinates(self):
        for boss in (False, True):
            with self.subTest(boss=boss):
                task, frame = self.task(boss, (7, -4), {1: 1, 8: 2, 12: 3})
                self.assertEqual(task._read_board_position_count()['occupied_positions'], [1, 8, 12])
                self.assertEqual([task._board_set_star(i) for i in (1, 8, 12)], [1, 2, 3])
                self.assertTrue(task._board_set_is_empty(6))
                self.assertFalse(task._board_set_is_empty(1))
                x, y, w, h = frame.roi_ranges[12+7]
                self.assertEqual(task._set_position(8), (int(x+w/2)+7, int(y+h/2)-4))
                task.click.assert_not_called()

    def test_missing_anchor_does_not_confirm_empty_board_or_successful_recall(self):
        task, _ = self.task(anchor=False)
        self.assertIsNone(task._board_set_has_shikigami(6))
        self.assertFalse(task._board_set_is_empty(6))
        self.assertIsNone(task._board_set_star(6))
        with self.assertRaisesRegex(GameStuckError, 'anchor not found'):
            task._set_position(6)

    def test_board_cache_refreshes_on_new_screenshot(self):
        task, _ = self.task(occupied={6: 1})
        self.assertTrue(task._board_set_has_shikigami(6))
        task.device.image = np.zeros_like(task.device.image)
        task.device.image_frame_id = 'board-2'
        self.assertFalse(task._board_set_is_empty(6))
        self.assertIsNone(task._board_set_star(6))


class ChessGoldfishAndEquipmentTest(unittest.TestCase):
    def task(self):
        task = ScriptTask.__new__(ScriptTask)
        task.chess_state = ChessGameState(game_number=1)
        task.select_lineup_strategy('builtin:huangchuan')
        return task

    def test_preferred_emblem_reserves_a_slot_before_soul_equipping(self):
        task = self.task()
        strategy = dict(task.get_lineup_strategy(), secondary_bond='回响')
        task.get_lineup_strategy = Mock(return_value=strategy)
        task._board_lineup_names = {'arakawa_no_nushi'}
        task._shikigami_attributes = Mock(return_value=(None, 'poshi', None))
        task._set_position = Mock(return_value=(795, 505))
        self.assertTrue(task._keep_lineup_emblem('回响纹章'))
        self.assertEqual(task._soul_targets('wangqie', 'attack', {'arakawa_no_nushi'}), [])
        self.assertEqual(task._emblem_targets('回响纹章', {'arakawa_no_nushi'}), [('arakawa_no_nushi', 11)])
        task._shikigami_attributes.return_value = (None, None, None)
        self.assertEqual(task._soul_targets('wangqie', 'attack', {'arakawa_no_nushi'}), [(11, (795, 505))])

    def test_goldfish_move_updates_swapped_unit_and_preserves_non_population_flag(self):
        task = self.task()
        task._is_preparation_mode = Mock(return_value=True)
        task._board_action_allowed = Mock(return_value=True)
        task._inspect_arakawa_goldfish = Mock(return_value=True)
        task.screenshot = Mock()
        task._set_position = Mock(side_effect=lambda index: (index*10, 100))
        task.device = Mock()
        task._board_lineup_names = {'kujira'}
        task._board_actual_positions = {'kujira': 7}
        task._player_deployed_positions = {7}
        task._record_arakawa_goldfish_position(6, identified=True)
        with patch('tasks.Chess.runtime.hand_operations.Press_and_Drag') as drag:
            self.assertTrue(task._move_arakawa_goldfish(6))
        drag.assert_called_once()
        self.assertEqual(task._board_actual_positions['kujira'], 6)
        self.assertEqual(task._arakawa_goldfish_current_position, 7)
        self.assertFalse(task._board_special_units['arakawa_goldfish']['counts_toward_capacity'])

    def test_goldfish_waits_for_preparation_before_moving(self):
        task = self.task()
        task._is_preparation_mode = Mock(return_value=False)
        with patch('tasks.Chess.runtime.hand_operations.Press_and_Drag') as drag:
            self.assertFalse(task._move_arakawa_goldfish(6))
        self.assertTrue(task._goldfish_relocation_pending)
        drag.assert_not_called()


if __name__ == '__main__':
    unittest.main()
