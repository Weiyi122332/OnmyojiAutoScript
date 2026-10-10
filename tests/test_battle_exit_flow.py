"""退出战斗及失败后再战的弹窗识别、操作顺序和有限重试。"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from module.exception import GameStuckError
from tasks.GameUi.page import page_battle_prepare, page_battle_result
from tasks.RealmRaid.script_task import BattleAction, ScriptTask


class BattleExitFlowTest(unittest.TestCase):
    def setUp(self):
        for name in ('tasks.Component.GeneralBattle.general_battle.logger',
                     'tasks.RealmRaid.script_task.logger', 'time.sleep'):
            patcher = patch(name)
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_task(self, frames):
        task = ScriptTask.__new__(ScriptTask)
        clock = SimpleNamespace(now=1000.0, scene=frames[0][1], clicks=[])
        frames = iter(frames)
        scenes = {
            'prepare': (task.I_EXIT,),
            'exit_dialog': (task.I_EXIT, task.I_EXIT_DIALOG, task.I_EXIT_ENSURE),
            'exit_unknown': (task.I_EXIT, task.I_EXIT_ENSURE),
            'exit_title_only': (task.I_EXIT, task.I_EXIT_DIALOG),
            'loss': (task.I_FIRE_AGAIN,),
            'loss_over_exit': (task.I_FALSE, task.I_FIRE_AGAIN, task.I_EXIT_DIALOG),
            'win_over_exit': (task.I_WIN, task.I_EXIT_DIALOG, task.I_EXIT_ENSURE),
            'de_win_over_exit': (task.I_DE_WIN, task.I_EXIT_DIALOG, task.I_EXIT_ENSURE),
            'retry_unchecked': (task.I_FIRE_AGAIN, task.I_FIRE_AGAIN_DIALOG,
                                task.I_FIRE_AGAIN_CONFIRM, task.I_SHOW_AGAIN),
            'retry_checked': (task.I_FIRE_AGAIN, task.I_FIRE_AGAIN_DIALOG, task.I_FIRE_AGAIN_CONFIRM),
            'retry_unknown': (task.I_FIRE_AGAIN, task.I_FIRE_AGAIN_CONFIRM),
            'retry_title_only': (task.I_FIRE_AGAIN, task.I_FIRE_AGAIN_DIALOG),
            'unknown': (),
        }

        def screenshot():
            elapsed, clock.scene = next(frames)
            clock.now = 1000.0 + elapsed

        task.screenshot = Mock(side_effect=screenshot)
        task.appear = Mock(side_effect=lambda marker: any(marker is visible for visible in scenes[clock.scene]))
        task.click = Mock(side_effect=lambda marker: clock.clicks.append(marker))
        task.wait_until_appear = Mock(side_effect=AssertionError('unbounded wait'))
        task.ui_click_until_disappear = Mock(side_effect=AssertionError('unbounded confirmation clicks'))
        return task, clock

    def exit_battle(self, task, clock):
        with patch('module.base.timer.time.time', side_effect=lambda: clock.now), \
                patch('tasks.Component.GeneralBattle.general_battle.GameUi.get_current_page',
                      side_effect=lambda _: page_battle_result if clock.scene == 'loss' else page_battle_prepare):
            return task.exit_battle()

    def fire_again(self, task, clock):
        with patch('module.base.timer.time.time', side_effect=lambda: clock.now):
            return task.fire_again()

    def test_exit_button_then_confirmation_returns_to_loss_screen(self):
        task, clock = self.make_task([
            (0, 'prepare'), (0.4, 'exit_dialog'), (2.2, 'exit_dialog'), (2.6, 'loss'),
        ])
        self.assertTrue(self.exit_battle(task, clock))
        self.assertEqual(clock.clicks, [task.I_EXIT, task.I_EXIT_ENSURE])

    def test_existing_exit_dialog_is_confirmed_without_clicking_background_exit(self):
        task, clock = self.make_task([(0, 'exit_dialog'), (0.4, 'loss')])
        self.assertTrue(self.exit_battle(task, clock))
        self.assertEqual(clock.clicks, [task.I_EXIT_ENSURE])

    def test_settlement_over_exit_dialog_finishes_without_clicking_background(self):
        for scene in ('loss_over_exit', 'win_over_exit', 'de_win_over_exit'):
            with self.subTest(scene=scene):
                task, clock = self.make_task([(0, scene), (10.2, scene)])
                self.assertTrue(self.exit_battle(task, clock))
                task.click.assert_not_called()

    def test_exit_confirmation_can_finish_with_loss_over_residual_dialog(self):
        task, clock = self.make_task([
            (0, 'prepare'), (0.4, 'exit_dialog'), (2.2, 'exit_dialog'), (2.6, 'loss_over_exit'),
        ])
        self.assertTrue(self.exit_battle(task, clock))
        self.assertEqual(clock.clicks, [task.I_EXIT, task.I_EXIT_ENSURE])
        context = SimpleNamespace(reward_no_battle_ts=123, is_win=True)
        self.assertEqual(task._handle_result(context, SimpleNamespace(quick_exit=True)), BattleAction.EXIT_LOSE)
        self.assertFalse(context.is_win)
        self.assertEqual(clock.clicks, [task.I_EXIT, task.I_EXIT_ENSURE])

    def test_failed_exit_confirmation_retries_once(self):
        task, clock = self.make_task([
            (0, 'exit_dialog'), (1, 'exit_dialog'), (2.2, 'exit_dialog'), (2.6, 'loss'),
        ])
        self.assertTrue(self.exit_battle(task, clock))
        self.assertEqual(clock.clicks, [task.I_EXIT_ENSURE, task.I_EXIT_ENSURE])

    def test_stuck_exit_dialog_times_out_without_returning_to_background_button(self):
        task, clock = self.make_task([
            (0, 'exit_dialog'), (2.2, 'exit_dialog'), (5, 'exit_dialog'), (10.2, 'exit_dialog'),
        ])
        with self.assertRaisesRegex(GameStuckError, 'Battle exit did not finish'):
            self.exit_battle(task, clock)
        self.assertEqual(clock.clicks, [task.I_EXIT_ENSURE, task.I_EXIT_ENSURE])

    def test_unknown_confirmation_does_not_click_exit_behind_it(self):
        task, clock = self.make_task([
            (0, 'exit_unknown'), (2.2, 'exit_unknown'), (10.2, 'exit_unknown'),
        ])
        with self.assertRaisesRegex(GameStuckError, 'Battle exit did not finish'):
            self.exit_battle(task, clock)
        task.click.assert_not_called()

    def test_exit_title_without_confirm_button_does_not_click_background(self):
        task, clock = self.make_task([(0, 'exit_title_only'), (10.2, 'exit_title_only')])
        with self.assertRaises(GameStuckError):
            self.exit_battle(task, clock)
        task.click.assert_not_called()

    def test_exit_without_confirmation_dialog_is_supported(self):
        task, clock = self.make_task([(0, 'prepare'), (0.4, 'loss')])
        self.assertTrue(self.exit_battle(task, clock))
        self.assertEqual(clock.clicks, [task.I_EXIT])

    def test_unresponsive_exit_button_is_clicked_at_most_twice(self):
        task, clock = self.make_task([
            (0, 'prepare'), (2.2, 'prepare'), (5, 'prepare'), (10.2, 'prepare'),
        ])
        with self.assertRaises(GameStuckError):
            self.exit_battle(task, clock)
        self.assertEqual(clock.clicks, [task.I_EXIT, task.I_EXIT])

    def test_non_battle_page_does_not_start_exit_flow(self):
        task, clock = self.make_task([(0, 'loss')])
        self.assertFalse(self.exit_battle(task, clock))
        task.click.assert_not_called()
        task.screenshot.assert_not_called()

    def test_retry_selects_suppression_once_before_confirming(self):
        task, clock = self.make_task([
            (0, 'loss'), (0.4, 'retry_unchecked'), (0.8, 'retry_unchecked'),
            (2.2, 'retry_unchecked'), (2.6, 'prepare'),
        ])
        self.assertTrue(self.fire_again(task, clock))
        self.assertEqual(clock.clicks, [task.I_FIRE_AGAIN, task.I_SHOW_AGAIN, task.I_FIRE_AGAIN_CONFIRM])

    def test_current_retry_popup_can_be_resumed_without_reopening(self):
        task, clock = self.make_task([
            (0, 'retry_unchecked'), (0.4, 'retry_unchecked'), (0.8, 'prepare'),
        ])
        self.assertTrue(self.fire_again(task, clock))
        self.assertEqual(clock.clicks, [task.I_SHOW_AGAIN, task.I_FIRE_AGAIN_CONFIRM])

    def test_checked_suppression_option_is_not_toggled(self):
        task, clock = self.make_task([(0, 'retry_checked'), (0.4, 'prepare')])
        self.assertTrue(self.fire_again(task, clock))
        self.assertEqual(clock.clicks, [task.I_FIRE_AGAIN_CONFIRM])

    def test_retry_without_dialog_reaches_prepare_directly(self):
        task, clock = self.make_task([(0, 'loss'), (0.4, 'prepare')])
        self.assertTrue(self.fire_again(task, clock))
        self.assertEqual(clock.clicks, [task.I_FIRE_AGAIN])

    def test_retry_confirmation_gets_one_retry_without_toggling_suppression(self):
        task, clock = self.make_task([
            (0, 'retry_unchecked'), (0.4, 'retry_unchecked'), (1, 'retry_unchecked'),
            (2.6, 'retry_unchecked'), (3, 'prepare'),
        ])
        self.assertTrue(self.fire_again(task, clock))
        self.assertEqual(clock.clicks,
                         [task.I_SHOW_AGAIN, task.I_FIRE_AGAIN_CONFIRM, task.I_FIRE_AGAIN_CONFIRM])

    def test_stuck_retry_popup_times_out_after_two_confirmation_clicks(self):
        task, clock = self.make_task([
            (0, 'retry_unchecked'), (0.4, 'retry_unchecked'), (2.6, 'retry_unchecked'),
            (5, 'retry_unchecked'), (10.2, 'retry_unchecked'),
        ])
        with self.assertRaisesRegex(GameStuckError, 'Realm raid retry did not reach battle'):
            self.fire_again(task, clock)
        self.assertEqual(clock.clicks,
                         [task.I_SHOW_AGAIN, task.I_FIRE_AGAIN_CONFIRM, task.I_FIRE_AGAIN_CONFIRM])

    def test_unknown_retry_popup_does_not_click_button_behind_it(self):
        task, clock = self.make_task([(0, 'retry_unknown'), (2.2, 'retry_unknown'), (10.2, 'retry_unknown')])
        with self.assertRaises(GameStuckError):
            self.fire_again(task, clock)
        task.click.assert_not_called()

    def test_retry_without_confirm_button_does_not_reopen_background_retry(self):
        task, clock = self.make_task([(0, 'retry_title_only'), (10.2, 'retry_title_only')])
        with self.assertRaises(GameStuckError):
            self.fire_again(task, clock)
        task.click.assert_not_called()

    def test_missing_retry_button_has_a_finite_wait(self):
        task, clock = self.make_task([(0, 'unknown'), (2.2, 'unknown'), (10.2, 'unknown')])
        with self.assertRaises(GameStuckError):
            self.fire_again(task, clock)
        task.click.assert_not_called()

    def test_unresponsive_retry_button_is_clicked_at_most_twice(self):
        task, clock = self.make_task([(0, 'loss'), (2.2, 'loss'), (5, 'loss'), (10.2, 'loss')])
        with self.assertRaises(GameStuckError):
            self.fire_again(task, clock)
        self.assertEqual(clock.clicks, [task.I_FIRE_AGAIN, task.I_FIRE_AGAIN])


class BattleExitImageTest(unittest.TestCase):
    def load_scene(self, name, folder='battle_exit'):
        path = Path(__file__).parent / 'fixtures' / folder / f'{name}.png'
        crop = cv2.cvtColor(cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        image[220:510, 400:880] = crop
        return image

    def test_error_screenshot_matches_battle_exit_dialog_and_button(self):
        image = self.load_scene('exit_confirmation')
        task = ScriptTask.__new__(ScriptTask)
        self.assertTrue(task.I_EXIT_DIALOG.template_match(image))
        self.assertTrue(task.I_EXIT_ENSURE.template_match(image))
        self.assertFalse(task.I_FIRE_AGAIN_DIALOG.template_match(image))

    def test_adb_screenshot_matches_retry_dialog_checkbox_and_button(self):
        image = self.load_scene('retry_confirmation')
        task = ScriptTask.__new__(ScriptTask)
        self.assertTrue(task.I_FIRE_AGAIN_DIALOG.template_match(image))
        self.assertTrue(task.I_FIRE_AGAIN_CONFIRM.template_match(image))
        self.assertTrue(task.I_SHOW_AGAIN.template_match(image))
        self.assertFalse(task.I_EXIT_DIALOG.template_match(image))

    def test_other_confirmation_title_does_not_match_battle_prompts(self):
        image = self.load_scene('confirmation', folder='switch_soul')
        task = ScriptTask.__new__(ScriptTask)
        self.assertTrue(task.I_EXIT_ENSURE.template_match(image))
        self.assertFalse(task.I_EXIT_DIALOG.template_match(image))
        self.assertFalse(task.I_FIRE_AGAIN_DIALOG.template_match(image))


if __name__ == '__main__':
    unittest.main()
