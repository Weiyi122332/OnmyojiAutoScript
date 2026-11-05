"""Chess settlement recovery from an unknown page with a red back button."""
import unittest
from unittest.mock import Mock, patch

from tasks.Chess.assets import ChessAssets
from tasks.Chess.script_task import ScriptTask


class ChessResultRecoveryTest(unittest.TestCase):
    def play(self, frames, *, restart=False):
        task = ScriptTask.__new__(ScriptTask)
        task.device = Mock()
        task.click = Mock(return_value=True)
        task.appear_then_click = Mock(return_value=True)
        task._wait_chess_action_state = Mock(return_value=True)
        frame = -1

        def screenshot():
            nonlocal frame
            frame += 1

        task.screenshot = Mock(side_effect=screenshot)
        task.appear = Mock(side_effect=lambda rule: rule in frames[frame])
        with patch('tasks.GameUi.chess_battle.time.sleep'), \
                patch('tasks.GameUi.chess_battle.time.monotonic', side_effect=lambda: max(0, frame)):
            result = (task._restart_chess_game_from_result() if restart
                      else task.return_to_chess_lobby())
        return task, result

    def test_unknown_page_uses_red_back_then_recognizes_lobby(self):
        task, result = self.play([(ChessAssets.I_BACK_RED,), (ScriptTask.I_CHECK_CHESS,)])
        self.assertTrue(result)
        task.click.assert_called_once_with(ChessAssets.I_BACK_RED, interval=0.8)
        self.assertEqual(task.screenshot.call_count, 2)

    def test_unknown_page_after_share_recovers_before_ranking(self):
        task, result = self.play([
            (ChessAssets.I_SHARE,), (ChessAssets.I_BACK_RED,),
            (ScriptTask.I_CHESS_RANK_GOTO_LOBBY,), (ScriptTask.I_CHECK_CHESS,),
        ])
        self.assertTrue(result)
        self.assertIs(task.click.call_args.args[0], ChessAssets.I_BACK_RED)
        task.appear_then_click.assert_called_once_with(ScriptTask.I_CHESS_RANK_GOTO_LOBBY, interval=1.5)

    def test_recognized_rank_page_takes_priority_over_red_back(self):
        task, result = self.play([
            (ScriptTask.I_CHESS_RANK_GOTO_LOBBY, ChessAssets.I_BACK_RED),
            (ScriptTask.I_CHECK_CHESS,),
        ])
        self.assertTrue(result)
        task.click.assert_not_called()
        task.appear_then_click.assert_called_once_with(ScriptTask.I_CHESS_RANK_GOTO_LOBBY, interval=1.5)

    def test_restart_flow_checks_for_restart_again_after_red_back(self):
        task, result = self.play([
            (ChessAssets.I_BACK_RED,), (ChessAssets.I_RESTART_AGAIN,),
        ], restart=True)
        self.assertTrue(result)
        self.assertEqual([call.args[0] for call in task.click.call_args_list],
                         [ChessAssets.I_BACK_RED, ChessAssets.I_RESTART_AGAIN])

    def test_unknown_page_without_a_red_back_does_not_click(self):
        task = ScriptTask.__new__(ScriptTask)
        task.appear = Mock(return_value=False)
        task.click = Mock()
        self.assertFalse(task._close_unknown_chess_result_page())
        task.click.assert_not_called()
