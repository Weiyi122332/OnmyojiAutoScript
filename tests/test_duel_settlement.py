"""Duel settlement clicks allow one retry after 2s, followed by a 5s timeout."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from module.exception import GamePageUnknownError
from tasks.Duel.script_task import ScriptTask
from tasks.GameUi.page import page_duel


class DuelSettlementTest(unittest.TestCase):
    def make_task(self, frames):
        task = ScriptTask.__new__(ScriptTask)
        clock = SimpleNamespace(now=1000.0, frame=None, clicks=[])
        frames = iter(frames)

        def screenshot():
            elapsed, clock.frame = next(frames)
            clock.now = 1000.0 + elapsed

        def appear(target, **kwargs):
            visible = {
                'win': (task.I_D_VICTORY,),
                'lose': (task.I_D_FAIL,),
                'main': (task.I_CHECK_DUEL, task.I_D_HELP),
            }.get(clock.frame, ())
            return any(target is marker for marker in visible)

        def click(*args, **kwargs):
            self.assertIn(clock.frame, ('win', 'lose'))
            clock.clicks.append(clock.now - 1000.0)
            return True

        task.screenshot = Mock(side_effect=screenshot)
        task.appear = Mock(side_effect=appear)
        task.appear_then_click = Mock(return_value=False)
        task.check_and_get_reward = Mock()
        task.click = Mock(side_effect=click)
        task.goto_page = Mock()
        task.ui_click = Mock(side_effect=AssertionError('unexpected battle operation'))
        task.duel_exit_battle = Mock(side_effect=AssertionError('unexpected battle exit'))
        task.reset_device = Mock()
        return task, clock

    def wait_battle(self, task, clock):
        safe_area = object()
        with patch('module.base.timer.time.time', side_effect=lambda: clock.now), \
                patch('tasks.Duel.script_task.monotonic', side_effect=lambda: clock.now), \
                patch('tasks.Duel.script_task.sleep'), \
                patch('tasks.Duel.script_task.logger'), \
                patch('tasks.Duel.script_task.random_click', return_value=safe_area):
            result = task.wait_battle()
        return result, safe_area

    def test_first_click_exits_without_retry(self):
        task, clock = self.make_task([(0, 'win'), (1.9, 'main')])
        result, _ = self.wait_battle(task, clock)
        self.assertTrue(result)
        self.assertEqual(clock.clicks, [0])
        task.goto_page.assert_not_called()

    def test_win_and_loss_retry_once_after_two_seconds(self):
        for frame, expected_result in (('win', True), ('lose', False)):
            with self.subTest(result=frame):
                task, clock = self.make_task([
                    (0, frame), (1, frame), (1.9, frame), (2, frame),
                    (3, frame), (5, frame), (6.9, frame), (6.99, 'main'),
                ])
                result, safe_area = self.wait_battle(task, clock)
                self.assertIs(result, expected_result)
                self.assertEqual(task.click.call_args_list,
                                 [call(safe_area)] * 2)
                self.assertEqual(clock.clicks, [0, 2])
                self.assertEqual(task.screenshot.call_count, 8)
                task.goto_page.assert_not_called()

    def test_brief_transition_is_not_clicked(self):
        task, clock = self.make_task([
            (0, 'win'), (1, 'unknown'), (2, 'unknown'), (4, 'main'),
        ])
        result, _ = self.wait_battle(task, clock)
        self.assertTrue(result)
        task.click.assert_called_once()
        task.goto_page.assert_not_called()

    def test_navigation_fallback_still_handles_unknown_transition(self):
        task, clock = self.make_task([(0, 'win'), (2, 'unknown'), (5.1, 'unknown')])
        result, _ = self.wait_battle(task, clock)
        self.assertTrue(result)
        task.click.assert_called_once()
        task.goto_page.assert_called_once_with(page_duel)

    def test_transient_marker_miss_does_not_allow_a_third_click(self):
        task, clock = self.make_task([
            (0, 'win'), (1, 'unknown'), (2, 'win'),
            (3, 'unknown'), (4, 'win'), (6, 'main'),
        ])
        result, _ = self.wait_battle(task, clock)
        self.assertTrue(result)
        self.assertEqual(clock.clicks, [0, 2])
        task.goto_page.assert_not_called()

    def test_timeout_is_five_seconds_after_actual_retry(self):
        for frame in ('win', 'lose'):
            for last_frame in (frame, 'unknown'):
                with self.subTest(result=frame, last_frame=last_frame):
                    task, clock = self.make_task([
                        (0, frame), (1, frame), (2.8, frame),
                        (5, frame), (7.7, frame), (7.8, last_frame),
                    ])
                    with self.assertRaisesRegex(GamePageUnknownError, 'after one retry'):
                        self.wait_battle(task, clock)
                    self.assertEqual(task.click.call_count, 2)
                    self.assertEqual(task.screenshot.call_count, 6)
                    self.assertAlmostEqual(clock.clicks[1], 2.8)
                    task.goto_page.assert_not_called()

    def test_main_at_timeout_boundary_is_success(self):
        task, clock = self.make_task([(0, 'win'), (2, 'win'), (7, 'main')])
        result, _ = self.wait_battle(task, clock)
        self.assertTrue(result)
        self.assertEqual(clock.clicks, [0, 2])
        task.goto_page.assert_not_called()


if __name__ == '__main__':
    unittest.main()
