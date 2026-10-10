"""御魂切换兼容可选确认框、延迟的契灵替换框和有限重试。"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from module.exception import GameStuckError
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul


class SoulConfirmationFlowTest(unittest.TestCase):
    def make_task(self, frames):
        task = SwitchSoul.__new__(SwitchSoul)
        clock = SimpleNamespace(now=1000.0, visible=(), clicks=[])
        frames = iter(frames)
        scenes = {
            'preset': (task.I_SOU_TEAM_PRESENT,),
            'dialog': (task.I_SOU_TEAM_PRESENT, task.I_SOU_SWITCH_DIALOG, task.I_SOU_SWITCH_SURE),
            'detail': (task.I_SOU_TEAM_PRESENT, task.I_SOU_SWITCH_DETAIL, task.I_SOU_SWITCH_SURE),
            'detail_title_only': (task.I_SOU_TEAM_PRESENT, task.I_SOU_SWITCH_DETAIL),
            'spirit': (task.I_SOU_TEAM_PRESENT, task.I_SOU_SPIRIT_REPLACE, task.I_SOU_SWITCH_SURE),
            'spirit_title_only': (task.I_SOU_TEAM_PRESENT, task.I_SOU_SPIRIT_REPLACE),
            'title_only': (task.I_SOU_TEAM_PRESENT, task.I_SOU_SWITCH_DIALOG),
            'button_only': (task.I_SOU_TEAM_PRESENT, task.I_SOU_SWITCH_SURE),
            'blocked': (task.I_SOU_TEAM_PRESENT, task.I_CHECK_BLOCK),
            'blocked_overlay': (task.I_SOU_TEAM_PRESENT, task.I_CHECK_BLOCK,
                                task.I_SOU_SWITCH_DIALOG, task.I_SOU_SWITCH_SURE),
            'unknown': (),
        }

        def screenshot():
            elapsed, scene = next(frames)
            clock.now = 1000.0 + elapsed
            clock.visible = scenes[scene]

        task.screenshot = Mock(side_effect=screenshot)
        task.appear = Mock(side_effect=lambda marker: any(marker is visible for visible in clock.visible))
        task.click = Mock(side_effect=lambda marker: clock.clicks.append((clock.now, marker)))
        selector = Mock(return_value=True)
        return task, clock, selector

    def apply_preset(self, task, clock, selector):
        with patch('module.base.timer.time.time', side_effect=lambda: clock.now), \
                patch('tasks.Component.SwitchSoul.switch_soul.sleep'), \
                patch('tasks.Component.SwitchSoul.switch_soul.logger'):
            task._apply_soul_preset(selector, 'group 1 team 4')

    def count_clicks(self, task, clock, marker):
        return sum(clicked is marker for _, clicked in clock.clicks)

    def test_one_selection_and_confirmation_finish_without_reopening_dialog(self):
        task, clock, selector = self.make_task([
            (0, 'preset'), (0.1, 'dialog'), (0.2, 'dialog'),
            (0.6, 'preset'), (1, 'preset'), (2.2, 'preset'),
        ])
        self.apply_preset(task, clock, selector)
        selector.assert_called_once()
        self.assertEqual(self.count_clicks(task, clock, task.I_SOU_SWITCH_SURE), 1)

    def test_delayed_dialog_is_waited_for_before_confirmation(self):
        task, clock, selector = self.make_task([
            (0, 'preset'), (0.5, 'preset'), (1.5, 'dialog'), (1.6, 'dialog'),
            (2, 'preset'), (2.5, 'preset'), (3.6, 'preset'),
        ])
        self.apply_preset(task, clock, selector)
        selector.assert_called_once()
        self.assertEqual(self.count_clicks(task, clock, task.I_SOU_SWITCH_SURE), 1)

    def test_dialog_listing_shikigami_is_confirmed_before_completion(self):
        task, clock, selector = self.make_task([
            (0, 'preset'), (0.1, 'detail'), (0.2, 'detail'),
            (0.6, 'preset'), (1, 'preset'), (2.2, 'preset'),
        ])
        self.apply_preset(task, clock, selector)
        selector.assert_called_once()
        self.assertEqual(self.count_clicks(task, clock, task.I_SOU_SWITCH_SURE), 1)

    def test_shikigami_dialog_retry_then_spirit_confirmation(self):
        task, clock, selector = self.make_task([
            (0, 'preset'), (0.1, 'detail'), (0.2, 'detail'), (2.4, 'detail'),
            (2.8, 'preset'), (3, 'spirit'), (4.6, 'spirit'),
            (5, 'preset'), (5.4, 'preset'), (6.6, 'preset'),
        ])
        self.apply_preset(task, clock, selector)
        selector.assert_called_once()
        self.assertEqual(self.count_clicks(task, clock, task.I_SOU_SWITCH_SURE), 3)

    def test_shikigami_title_without_button_does_not_click(self):
        task, clock, selector = self.make_task([
            (0, 'preset'), (0.1, 'detail_title_only'),
            (0.2, 'detail_title_only'), (10.4, 'detail_title_only'),
        ])
        with self.assertRaisesRegex(GameStuckError, 'confirmation did not finish'):
            self.apply_preset(task, clock, selector)
        task.click.assert_not_called()

    def test_failed_first_confirmation_is_retried_once(self):
        task, clock, selector = self.make_task([
            (0, 'preset'), (0.1, 'dialog'), (0.2, 'dialog'), (1, 'dialog'),
            (2.4, 'dialog'), (2.8, 'preset'), (3.2, 'preset'), (4.4, 'preset'),
        ])
        self.apply_preset(task, clock, selector)
        selector.assert_called_once()
        self.assertEqual(self.count_clicks(task, clock, task.I_SOU_SWITCH_SURE), 2)

    def test_two_failed_confirmations_raise_without_a_third_click(self):
        task, clock, selector = self.make_task([
            (0, 'preset'), (0.1, 'dialog'), (0.2, 'dialog'), (2.4, 'dialog'),
            (4, 'dialog'), (10.4, 'dialog'),
        ])
        with self.assertRaisesRegex(GameStuckError, 'confirmation did not finish'):
            self.apply_preset(task, clock, selector)
        self.assertEqual(self.count_clicks(task, clock, task.I_SOU_SWITCH_SURE), 2)
        selector.assert_called_once()

    def test_delayed_spirit_dialog_after_brief_normal_list_is_confirmed(self):
        task, clock, selector = self.make_task([
            (0, 'preset'), (0.1, 'dialog'), (0.2, 'dialog'),
            (0.5, 'preset'), (1, 'preset'), (1.2, 'spirit'), (2.4, 'spirit'),
            (2.8, 'preset'), (3.2, 'preset'), (4.4, 'preset'),
        ])
        self.apply_preset(task, clock, selector)
        selector.assert_called_once()
        self.assertEqual(self.count_clicks(task, clock, task.I_SOU_SWITCH_SURE), 2)
        self.assertEqual(clock.clicks[1][0], 1002.4)
        self.assertEqual(clock.now, 1004.4)

    def test_spirit_dialog_without_soul_dialog_is_confirmed(self):
        task, clock, selector = self.make_task([
            (0, 'preset'), (0.1, 'spirit'), (0.2, 'spirit'),
            (0.6, 'preset'), (1, 'preset'), (2.2, 'preset'),
        ])
        self.apply_preset(task, clock, selector)
        selector.assert_called_once()
        self.assertEqual(self.count_clicks(task, clock, task.I_SOU_SWITCH_SURE), 1)

    def test_each_dialog_has_its_own_single_retry(self):
        task, clock, selector = self.make_task([
            (0, 'preset'), (0.1, 'dialog'), (0.2, 'dialog'), (2.4, 'dialog'),
            (2.8, 'preset'), (3, 'spirit'), (4.6, 'spirit'), (6.8, 'spirit'),
            (7.2, 'preset'), (7.6, 'preset'), (8.8, 'preset'),
        ])
        self.apply_preset(task, clock, selector)
        selector.assert_called_once()
        self.assertEqual(self.count_clicks(task, clock, task.I_SOU_SWITCH_SURE), 4)

    def test_stuck_spirit_dialog_raises_after_two_confirmation_clicks(self):
        task, clock, selector = self.make_task([
            (0, 'preset'), (0.1, 'spirit'), (0.2, 'spirit'),
            (2.4, 'spirit'), (4.8, 'spirit'), (10.4, 'spirit'),
        ])
        with self.assertRaisesRegex(GameStuckError, 'confirmation did not finish'):
            self.apply_preset(task, clock, selector)
        self.assertEqual(self.count_clicks(task, clock, task.I_SOU_SWITCH_SURE), 2)
        selector.assert_called_once()

    def test_spirit_title_with_unmatched_button_does_not_click(self):
        task, clock, selector = self.make_task([
            (0, 'preset'), (0.1, 'spirit_title_only'),
            (0.2, 'spirit_title_only'), (10.4, 'spirit_title_only'),
        ])
        with self.assertRaisesRegex(GameStuckError, 'confirmation did not finish'):
            self.apply_preset(task, clock, selector)
        task.click.assert_not_called()

    def test_recognized_title_with_unmatched_button_does_not_report_success(self):
        task, clock, selector = self.make_task([
            (0, 'title_only'), (0.1, 'title_only'), (10.2, 'title_only'),
        ])
        with self.assertRaisesRegex(GameStuckError, 'confirmation did not finish'):
            self.apply_preset(task, clock, selector)
        task.click.assert_not_called()
        selector.assert_not_called()

    def test_direct_switch_without_dialog_finishes_after_one_selection(self):
        task, clock, selector = self.make_task([
            (0, 'preset'), (0.5, 'preset'), (2.1, 'preset'), (3.2, 'preset'),
        ])
        self.apply_preset(task, clock, selector)
        selector.assert_called_once()
        task.click.assert_not_called()

    def test_missing_selection_bounds_attempts_and_raises(self):
        task, clock, selector = self.make_task([
            (0, 'preset'), (2.1, 'preset'), (4.2, 'preset'),
            (6.3, 'preset'), (10.2, 'preset'),
        ])
        selector.return_value = False
        with self.assertRaisesRegex(GameStuckError, 'selection could not be verified'):
            self.apply_preset(task, clock, selector)
        self.assertEqual(selector.call_count, 3)
        task.click.assert_not_called()

    def test_direct_switch_without_a_normal_preset_screen_does_not_finish(self):
        task, clock, selector = self.make_task([
            (0, 'preset'), (2.1, 'unknown'), (3.2, 'unknown'), (10.2, 'unknown'),
        ])
        with self.assertRaisesRegex(GameStuckError, 'selection could not be verified'):
            self.apply_preset(task, clock, selector)
        selector.assert_called_once()
        task.click.assert_not_called()

    def test_direct_switch_with_block_warning_does_not_report_success(self):
        task, clock, selector = self.make_task([
            (0, 'preset'), (3.2, 'blocked'), (10.2, 'blocked'),
        ])
        with self.assertRaisesRegex(GameStuckError, 'selection could not be verified'):
            self.apply_preset(task, clock, selector)
        selector.assert_called_once()

    def test_confirmation_button_without_matching_title_is_not_treated_as_direct_switch(self):
        task, clock, selector = self.make_task([
            (0, 'preset'), (0.1, 'button_only'), (0.2, 'button_only'), (10.4, 'button_only'),
        ])
        with self.assertRaisesRegex(GameStuckError, 'confirmation did not finish'):
            self.apply_preset(task, clock, selector)
        selector.assert_called_once()
        task.click.assert_not_called()

    def test_disappeared_dialog_without_preset_list_does_not_report_success(self):
        task, clock, selector = self.make_task([
            (0, 'preset'), (0.1, 'dialog'), (0.2, 'dialog'),
            (1, 'unknown'), (10.4, 'unknown'),
        ])
        with self.assertRaisesRegex(GameStuckError, 'confirmation did not finish'):
            self.apply_preset(task, clock, selector)
        self.assertEqual(self.count_clicks(task, clock, task.I_SOU_SWITCH_SURE), 1)

    def test_visible_confirmation_button_prevents_early_completion(self):
        task, clock, selector = self.make_task([
            (0, 'preset'), (0.1, 'dialog'), (0.2, 'dialog'),
            (1, 'button_only'), (10.4, 'button_only'),
        ])
        with self.assertRaisesRegex(GameStuckError, 'confirmation did not finish'):
            self.apply_preset(task, clock, selector)
        self.assertEqual(self.count_clicks(task, clock, task.I_SOU_SWITCH_SURE), 1)

    def test_followup_block_warning_is_closed_before_completion(self):
        task, clock, selector = self.make_task([
            (0, 'preset'), (0.1, 'dialog'), (0.2, 'dialog'),
            (1, 'blocked'), (2.5, 'blocked'),
            (2.8, 'preset'), (3.2, 'preset'), (4.4, 'preset'),
        ])
        self.apply_preset(task, clock, selector)
        self.assertEqual(self.count_clicks(task, clock, task.I_SOU_SWITCH_SURE), 1)
        self.assertEqual(self.count_clicks(task, clock, task.I_CHECK_BLOCK), 1)

    def test_stable_preset_list_at_deadline_is_accepted(self):
        task, clock, selector = self.make_task([
            (0, 'preset'), (0.1, 'dialog'), (0.2, 'dialog'),
            (8.8, 'preset'), (9.3, 'preset'), (10.4, 'preset'),
        ])
        self.apply_preset(task, clock, selector)
        selector.assert_called_once()

    def test_block_warning_retries_are_bounded_without_background_confirmation(self):
        task, clock, selector = self.make_task([
            (0, 'preset'), (0.1, 'dialog'), (0.2, 'dialog'),
            (2.5, 'blocked_overlay'), (4.8, 'blocked_overlay'),
            (7, 'blocked_overlay'), (10.4, 'blocked_overlay'),
        ])
        with self.assertRaisesRegex(GameStuckError, 'confirmation did not finish'):
            self.apply_preset(task, clock, selector)
        self.assertEqual(self.count_clicks(task, clock, task.I_SOU_SWITCH_SURE), 1)
        self.assertEqual(self.count_clicks(task, clock, task.I_CHECK_BLOCK), 2)


class SoulConfirmationRouteTest(unittest.TestCase):
    def make_task(self):
        task = SwitchSoul.__new__(SwitchSoul)
        task.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8))
        task.screenshot = Mock()
        task.swipe = Mock()
        task.click = Mock()
        task._apply_soul_preset = Mock()
        task.appear_then_click = Mock(return_value=True)
        task.ocr_appear_click = Mock(return_value=True)
        task.ocr_appear_click_by_rule = Mock(return_value=True)
        task.O_SS_GROUP_NAME = SimpleNamespace(
            keyword='', detect_and_ocr=Mock(return_value=[SimpleNamespace(ocr_text='测试分组')]))
        task.O_SS_TEAM_NAME = SimpleNamespace(
            keyword='', detect_and_ocr=Mock(return_value=[SimpleNamespace(ocr_text='测试队伍')]))
        return task

    def test_numbered_preset_uses_guarded_confirmation(self):
        task = self.make_task()
        with patch('tasks.Component.SwitchSoul.switch_soul.sleep'), \
                patch('tasks.Component.SwitchSoul.switch_soul.logger'):
            task.switch_soul_one(1, 4)
        task._apply_soul_preset.assert_called_once()
        select_team = task._apply_soul_preset.call_args.args[0]
        self.assertTrue(select_team())
        task.appear_then_click.assert_called_once_with(task.I_SOU_SWITCH_4)

    def test_named_preset_uses_same_guarded_confirmation(self):
        task = self.make_task()
        with patch('tasks.Component.SwitchSoul.switch_soul.sleep'), \
                patch('tasks.Component.SwitchSoul.switch_soul.logger'):
            task.switch_soul_by_name('测试分组', '测试队伍')
        task._apply_soul_preset.assert_called_once()
        select_team = task._apply_soul_preset.call_args.args[0]
        self.assertTrue(select_team())
        task.ocr_appear_click_by_rule.assert_called_once_with(task.O_SS_TEAM_NAME, task.I_SOU_CLICK_PRESENT)


class SoulConfirmationImageTest(unittest.TestCase):
    def load_scene(self, name):
        path = Path(__file__).parent / 'fixtures' / 'switch_soul' / f'{name}.png'
        crop = cv2.cvtColor(cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        image[220:510, 400:880] = crop
        return image

    def test_real_error_frame_matches_title_and_confirm_button(self):
        image = self.load_scene('confirmation')
        task = SwitchSoul.__new__(SwitchSoul)
        self.assertTrue(task.I_SOU_SWITCH_DIALOG.template_match(image))
        self.assertTrue(task.I_SOU_SWITCH_SURE.template_match(image))
        self.assertEqual(task.I_SOU_SWITCH_SURE.roi_front[:2], [664, 408])
        self.assertFalse(task.I_SOU_SPIRIT_REPLACE.template_match(image))
        self.assertFalse(task.I_SOU_SWITCH_DETAIL.template_match(image))

    def test_real_shikigami_error_matches_fixed_prefix_and_confirm_button(self):
        image = self.load_scene('shikigami_confirmation')
        task = SwitchSoul.__new__(SwitchSoul)
        self.assertTrue(task.I_SOU_SWITCH_DETAIL.template_match(image))
        self.assertTrue(task.I_SOU_SWITCH_SURE.template_match(image))
        self.assertFalse(task.I_SOU_SWITCH_DIALOG.template_match(image))
        self.assertFalse(task.I_SOU_SPIRIT_REPLACE.template_match(image))

    def test_shikigami_names_are_not_required_for_prefix_recognition(self):
        image = self.load_scene('shikigami_confirmation')
        image[273:303, 590:860] = 0
        image[303:375, 424:860] = 0
        task = SwitchSoul.__new__(SwitchSoul)
        self.assertTrue(task.I_SOU_SWITCH_DETAIL.template_match(image))

    def test_real_spirit_error_matches_specific_title_and_shared_confirm_button(self):
        image = self.load_scene('spirit_replace')
        task = SwitchSoul.__new__(SwitchSoul)
        self.assertTrue(task.I_SOU_SPIRIT_REPLACE.template_match(image))
        self.assertTrue(task.I_SOU_SWITCH_SURE.template_match(image))
        self.assertFalse(task.I_SOU_SWITCH_DIALOG.template_match(image))
        self.assertFalse(task.I_SOU_SWITCH_DETAIL.template_match(image))

    def test_unrelated_daily_gift_does_not_match_switch_confirmation(self):
        image = self.load_scene('daily_gift')
        task = SwitchSoul.__new__(SwitchSoul)
        self.assertFalse(task.I_SOU_SWITCH_DIALOG.template_match(image))
        self.assertFalse(task.I_SOU_SWITCH_SURE.template_match(image))
        self.assertFalse(task.I_SOU_SPIRIT_REPLACE.template_match(image))
        self.assertFalse(task.I_SOU_SWITCH_DETAIL.template_match(image))


if __name__ == '__main__':
    unittest.main()
