"""Close the top-right X on every Chess screenshot, regardless of result state."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from module.atom.image import RuleImage
from module.image.runtime import ImageRuntime
from tasks.base_task import BaseTask
from tasks.Chess.assets import ChessAssets
from tasks.Chess.script_task import ScriptTask


class ChessGlobalCloseTest(unittest.TestCase):
    def setUp(self):
        self.runtime = ImageRuntime({'worker_count': 1})
        self.addCleanup(self.runtime.shutdown)

        def match(rule, frame, threshold=None, frame_id=None):
            payload = rule.to_service_payload()
            if threshold is not None:
                payload['threshold'] = threshold
            return rule._apply_match_result(self.runtime._match_rule_payload(frame, payload))

        matching = patch.object(RuleImage, 'match', autospec=True, side_effect=match)
        matching.start()
        self.addCleanup(matching.stop)

    def task(self, *, with_x):
        task = ScriptTask.__new__(ScriptTask)
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        if with_x:
            rule = ChessAssets.I_SHARE_CLOSE
            template = rule.image
            x, y = rule.roi_front[:2]
            image[y:y + template.shape[0], x:x + template.shape[1]] = template
        task.device = SimpleNamespace(image=image, image_frame_id='battle', click=Mock(),
                                      long_click=Mock(), get_image_batch_cache=Mock(return_value=None))
        task.interval_timer = {}
        task.detect_random_main_costume = Mock(return_value=False)
        return task

    def test_x_is_closed_without_share_or_result_markers_even_during_details_reading(self):
        task = self.task(with_x=True)
        task._chess_details_depth = 1
        self.assertFalse(task.appear(ChessAssets.I_SHARE))
        self.assertFalse(task.appear(task.I_CHESS_EXIT_TO_LOBBY))
        with patch.object(BaseTask, '_burst', side_effect=AssertionError('X must take priority')):
            self.assertTrue(task._burst())
        task.device.click.assert_called_once()
        click = task.device.click.call_args
        x = click.kwargs['x'] if 'x' in click.kwargs else click.args[0]
        y = click.kwargs['y'] if 'y' in click.kwargs else click.args[1]
        self.assertTrue(1202 <= x <= 1242 and 33 <= y <= 73, (x, y))
        self.assertEqual(click.kwargs['control_name'], ChessAssets.I_SHARE_CLOSE.name)

    def test_no_x_keeps_normal_popup_handling_and_does_not_click(self):
        task = self.task(with_x=False)
        with patch.object(BaseTask, '_burst', return_value=False) as normal:
            self.assertFalse(task._burst())
        normal.assert_called_once()
        task.device.click.assert_not_called()

    def test_throttled_x_still_prevents_other_actions_on_the_same_frame(self):
        task = self.task(with_x=True)
        task.click = Mock(return_value=False)
        with patch.object(BaseTask, '_burst', side_effect=AssertionError('Wait for a fresh frame')):
            self.assertTrue(task._burst())
        task.click.assert_called_once_with(ChessAssets.I_SHARE_CLOSE, interval=0.8)
        task.device.click.assert_not_called()

    def test_screenshot_returns_a_fresh_battle_frame_after_closing_x(self):
        task = self.task(with_x=True)
        task._chess_details_depth = 1
        popup = task.device.image
        battle = np.zeros_like(popup)
        frames = iter((popup, battle))

        def capture():
            task.device.image = next(frames)
            task.device.image_frame_id = id(task.device.image)

        task.device.screenshot = Mock(side_effect=capture)
        task._handle_network = Mock()
        with patch.object(BaseTask, '_burst', return_value=False) as normal:
            self.assertIs(task.screenshot(), battle)
        self.assertEqual(task.device.screenshot.call_count, 2)
        task.device.click.assert_called_once()
        self.assertEqual(task.device.click.call_args.kwargs['control_name'], ChessAssets.I_SHARE_CLOSE.name)
        normal.assert_called_once()


if __name__ == '__main__':
    unittest.main()
