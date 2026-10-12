"""契灵盘子不足时先勾选今日不再提示，再继续挑战。"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from module.exception import GameStuckError
from tasks.BondlingFairyland.script_task import ScriptTask


class LowPlateDialogTest(unittest.TestCase):
    def make_task(self, frames):
        task = ScriptTask.__new__(ScriptTask)
        clock = SimpleNamespace(now=1000.0, scene=None, clicks=[])
        frames = iter(frames)
        scenes = {
            'closed': (),
            'fire': (task.I_BALL_FIRE,),
            'unchecked': (task.I_LOW_PLATE_DIALOG, task.I_LOW_PLATE_SKIP_TODAY,
                          task.I_LOW_PLATE_CONTINUE),
            'checked': (task.I_LOW_PLATE_DIALOG, task.I_LOW_PLATE_CONTINUE),
            'title_only': (task.I_LOW_PLATE_DIALOG,),
        }

        def screenshot():
            elapsed, scene = next(frames)
            clock.now = 1000.0 + elapsed
            clock.scene = scenes[scene]

        task.screenshot = Mock(side_effect=screenshot)
        task.appear = Mock(side_effect=lambda rule, **kwargs: any(
            rule is marker for marker in clock.scene))
        task.click = Mock(side_effect=lambda rule: clock.clicks.append(rule))

        def appear_then_click(rule, **kwargs):
            if task.appear(rule):
                task.click(rule)
                return True
            return False

        task.appear_then_click = Mock(side_effect=appear_then_click)
        screenshot()
        return task, clock

    def handle(self, task, clock):
        with patch('module.base.timer.time.time', side_effect=lambda: clock.now), \
                patch('tasks.BondlingFairyland.script_task.sleep'), \
                patch('tasks.BondlingFairyland.script_task.logger'):
            return task._handle_low_plate_dialog()

    def test_no_dialog_keeps_original_flow(self):
        task, clock = self.make_task([(0, 'fire')])
        task.screenshot.reset_mock()
        self.assertFalse(self.handle(task, clock))
        task.click.assert_not_called()
        task.screenshot.assert_not_called()

    def test_unchecked_option_is_selected_before_continue(self):
        task, clock = self.make_task([
            (0, 'unchecked'), (0.2, 'checked'), (0.4, 'closed'),
        ])
        self.assertTrue(self.handle(task, clock))
        self.assertEqual(clock.clicks, [task.I_LOW_PLATE_SKIP_TODAY, task.I_LOW_PLATE_CONTINUE])

    def test_checked_option_is_not_toggled_off(self):
        task, clock = self.make_task([(0, 'checked'), (0.2, 'closed')])
        self.assertTrue(self.handle(task, clock))
        self.assertEqual(clock.clicks, [task.I_LOW_PLATE_CONTINUE])

    def test_failed_checkbox_click_is_retried_before_continue(self):
        task, clock = self.make_task([
            (0, 'unchecked'), (2.1, 'unchecked'), (2.3, 'checked'),
            (4.2, 'checked'), (4.4, 'closed'),
        ])
        self.assertTrue(self.handle(task, clock))
        self.assertEqual(clock.clicks, [task.I_LOW_PLATE_SKIP_TODAY,
                                      task.I_LOW_PLATE_SKIP_TODAY, task.I_LOW_PLATE_CONTINUE])

    def test_persistent_unchecked_option_does_not_continue(self):
        task, clock = self.make_task([
            (0, 'unchecked'), (2.1, 'unchecked'), (4.2, 'unchecked'), (10.1, 'unchecked'),
        ])
        with self.assertRaisesRegex(GameStuckError, 'Low plate warning'):
            self.handle(task, clock)
        self.assertEqual(clock.clicks, [task.I_LOW_PLATE_SKIP_TODAY, task.I_LOW_PLATE_SKIP_TODAY])

    def test_persistent_dialog_retries_continue_only_once(self):
        task, clock = self.make_task([
            (0, 'checked'), (2.1, 'checked'), (4.2, 'checked'), (10.1, 'checked'),
        ])
        with self.assertRaisesRegex(GameStuckError, 'Low plate warning'):
            self.handle(task, clock)
        self.assertEqual(clock.clicks, [task.I_LOW_PLATE_CONTINUE, task.I_LOW_PLATE_CONTINUE])

    def test_title_without_controls_does_not_click(self):
        task, clock = self.make_task([(0, 'title_only'), (10.1, 'title_only')])
        with self.assertRaises(GameStuckError):
            self.handle(task, clock)
        task.click.assert_not_called()

    def test_solo_challenge_handles_warning_before_checking_fire_button(self):
        task, clock = self.make_task([
            (0, 'closed'), (0.1, 'fire'), (0.2, 'unchecked'),
            (0.4, 'checked'), (2.3, 'checked'), (2.5, 'closed'), (2.7, 'closed'),
        ])
        with patch('module.base.timer.time.time', side_effect=lambda: clock.now), \
                patch('tasks.BondlingFairyland.script_task.sleep'), \
                patch('tasks.BondlingFairyland.script_task.logger'):
            task.run_alone()
        self.assertEqual(clock.clicks, [task.I_BALL_FIRE, task.I_LOW_PLATE_SKIP_TODAY,
                                      task.I_LOW_PLATE_CONTINUE])

    def test_saved_warning_matches_all_controls_at_correct_positions(self):
        path = Path(__file__).parent / 'fixtures/bondling/low_plate_warning.png'
        crop = cv2.cvtColor(cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR),
                            cv2.COLOR_BGR2RGB)
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        image[214:506, 390:884] = crop
        task = ScriptTask.__new__(ScriptTask)
        for rule, expected in (
            (task.I_LOW_PLATE_DIALOG, [435, 256, 284, 29]),
            (task.I_LOW_PLATE_SKIP_TODAY, [544, 344, 34, 34]),
            (task.I_LOW_PLATE_CONTINUE, [664, 408, 180, 64]),
        ):
            with self.subTest(rule=rule.name):
                self.assertTrue(rule.template_match(image))
                self.assertEqual(rule.roi_front, expected)

    def test_other_confirmation_dialog_is_not_treated_as_low_plate_warning(self):
        path = Path(__file__).parent / 'fixtures/battle_exit/retry_confirmation.png'
        crop = cv2.cvtColor(cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR),
                            cv2.COLOR_BGR2RGB)
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        image[220:510, 400:880] = crop
        task = ScriptTask.__new__(ScriptTask)
        self.assertFalse(task.I_LOW_PLATE_DIALOG.template_match(image))
        self.assertFalse(task.I_LOW_PLATE_CONTINUE.template_match(image))


if __name__ == '__main__':
    unittest.main()
