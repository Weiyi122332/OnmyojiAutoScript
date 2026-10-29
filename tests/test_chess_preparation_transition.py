"""System-card recall must stop as soon as preparation ends."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tasks.Chess.runtime.state import ChessGameState
from tasks.Chess.script_task import ScriptTask


DRAG = 'tasks.Chess.runtime.hand_operations.Press_and_Drag'


class ChessPreparationTransitionTest(unittest.TestCase):
    def task(self):
        task = ScriptTask.__new__(ScriptTask)
        task.chess_state = ChessGameState(game_number=1)
        task.select_lineup_strategy('qijiaoshan')
        phase = {'preparation': True}
        task.device = SimpleNamespace()
        task.screenshot = Mock()
        task._is_preparation_mode = Mock(side_effect=lambda: phase['preparation'])
        task._board_action_allowed = Mock(side_effect=lambda: phase['preparation'])
        task._ensure_shop_closed = Mock(return_value=True)
        task._board_set_has_shikigami = Mock(side_effect=lambda index: index == 11)
        task._ensure_hand_room_for_recall = Mock(return_value=True)
        task._hand_capacity_count = Mock(return_value=8)
        task._set_position = Mock(return_value=(792, 506))
        task._board_set_is_empty = Mock(return_value=False)
        task._handle_goldfish_after_board_action_failure = Mock(return_value=False)
        return task, phase

    def test_no_drag_if_preparation_ends_after_the_board_snapshot(self):
        task, phase = self.task()
        task.screenshot.side_effect = lambda: phase.update(preparation=False)
        with patch(DRAG) as drag:
            self.assertIsNone(task._recall_one_system_board_card())
        drag.assert_not_called()

    def test_ending_preparation_during_confirmation_does_not_report_a_recall(self):
        task, phase = self.task()
        name = next(iter(task.shikigami_deploy_positions))
        task._board_lineup_names = {name}
        task._board_actual_positions = {name: 11}
        def wait(condition):
            phase['preparation'] = False
            self.assertTrue(condition())
            return True
        task._wait_chess_action_state = Mock(side_effect=wait)
        with patch(DRAG) as drag:
            self.assertIsNone(task._recall_one_system_board_card())
        drag.assert_called_once()
        task._board_set_is_empty.assert_not_called()
        task._handle_goldfish_after_board_action_failure.assert_not_called()
        self.assertEqual(task._board_lineup_names, {name})
        self.assertEqual(task._board_actual_positions, {name: 11})

    def test_no_second_drag_if_preparation_ends_between_attempts(self):
        task, phase = self.task()
        task._wait_chess_action_state = Mock(return_value=False)
        task._handle_goldfish_after_board_action_failure.side_effect = (
            lambda *a, **k: phase.update(preparation=False) or False)
        with patch(DRAG) as drag:
            self.assertIsNone(task._recall_one_system_board_card())
        drag.assert_called_once()

    def test_deployment_stops_when_the_recall_returns_after_preparation(self):
        for recalled in (None, 11):
            with self.subTest(recalled=recalled):
                task, phase = self.task()
                name = next(iter(task.shikigami_deploy_positions))
                task._is_shop_open = Mock(return_value=False)
                task._detect_pending_arakawa_goldfish = Mock(return_value=False)
                task._read_lineup_capacity_status = Mock(return_value={'full': False})
                task._find_best_shikigami_hand_card = Mock(return_value={
                    'name': name, 'score': 1.0, 'position': (500, 620)})
                task._recall_one_system_board_card = Mock(
                    side_effect=lambda **_: phase.update(preparation=False) or recalled)
                task.deploy_shikigami_hand_card = Mock()
                self.assertEqual(task.deploy_shikigami_from_hand(), [])
                task._find_best_shikigami_hand_card.assert_called_once()
                task.deploy_shikigami_hand_card.assert_not_called()


if __name__ == '__main__':
    unittest.main()
