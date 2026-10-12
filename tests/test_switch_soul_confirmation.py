"""Soul switching uses the original preset and confirmation controls."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.Component.CostumeShikigami.assets import CostumeShikigamiAssets


class SoulControlFlowTest(unittest.TestCase):
    def make_task(self, frames):
        task = SwitchSoul.__new__(SwitchSoul)
        state = SimpleNamespace(scene=None, clicks=[])
        frames = iter(frames)
        task.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8))
        task.O_SS_GROUP_NAME = SimpleNamespace(
            keyword='', detect_and_ocr=Mock(return_value=[SimpleNamespace(ocr_text='test_group')]))
        task.O_SS_TEAM_NAME = SimpleNamespace(
            keyword='', detect_and_ocr=Mock(return_value=[SimpleNamespace(ocr_text='test_team')]))
        task.screenshot = Mock(side_effect=lambda: setattr(state, 'scene', next(frames)))
        task.swipe = Mock()
        task.click = Mock(side_effect=lambda rule, *args, **kwargs: state.clicks.append(rule))

        def appear(rule, **kwargs):
            if rule is task.I_SOU_SWITCH_SURE:
                return state.scene == 'confirm'
            if rule is task.I_CHECK_BLOCK:
                return state.scene == 'blocked'
            if rule is task.I_SOU_SWITCH_DETAIL:
                return state.scene == 'title_only'
            if rule is task.I_SOU_SWITCH_4:
                return state.scene in ('preset', 'title_only')
            return False

        def appear_then_click(rule, *args, **kwargs):
            if not appear(rule):
                return False
            task.click(rule)
            return True

        task.appear = Mock(side_effect=appear)
        task.appear_then_click = Mock(side_effect=appear_then_click)
        task.ocr_appear_click = Mock(return_value=True)
        task.ocr_appear_click_by_rule = Mock(
            side_effect=lambda target, action, **kwargs: state.clicks.append(action) or True)
        return task, state

    def run_numbered(self, task):
        with patch('tasks.Component.SwitchSoul.switch_soul.sleep'), \
                patch('tasks.Component.SwitchSoul.switch_soul.logger'):
            task.switch_soul_one(1, 4)

    def run_named(self, task):
        with patch('tasks.Component.SwitchSoul.switch_soul.sleep'), \
                patch('tasks.Component.SwitchSoul.switch_soul.logger'):
            task.switch_soul_by_name('test_group', 'test_team')

    def test_direct_numbered_switch_finishes_without_a_confirmation_click(self):
        task, state = self.make_task(['preset'] * 6)
        self.run_numbered(task)
        self.assertEqual(state.clicks, [task.C_SOU_GROUP_1, task.C_SOU_GROUP_1,
                                      task.I_SOU_SWITCH_4, task.I_SOU_SWITCH_4, task.I_SOU_SWITCH_4])

    def test_confirmation_control_is_clicked_without_reading_dialog_title(self):
        task, state = self.make_task([
            'preset', 'preset', 'preset', 'confirm', 'preset', 'preset', 'preset',
        ])
        self.run_numbered(task)
        self.assertEqual(state.clicks.count(task.I_SOU_SWITCH_SURE), 1)
        task.click.assert_any_call(task.I_SOU_SWITCH_SURE, 3)
        self.assertFalse(any(call.args[0] is task.I_SOU_SWITCH_DETAIL
                             for call in task.appear.call_args_list))

    def test_block_control_is_closed_during_confirmation(self):
        task, state = self.make_task([
            'preset', 'preset', 'preset', 'confirm', 'blocked', 'preset', 'preset', 'preset',
        ])
        self.run_numbered(task)
        self.assertEqual(state.clicks.count(task.I_CHECK_BLOCK), 1)
        self.assertEqual(state.clicks.count(task.I_SOU_SWITCH_SURE), 2)

    def test_late_confirmation_is_closed_by_original_fallback(self):
        task, state = self.make_task(['preset'] * 5 + ['confirm', 'preset'])
        self.run_numbered(task)
        self.assertEqual(state.clicks.count(task.I_SOU_SWITCH_SURE), 1)

    def test_title_marker_does_not_start_a_confirmation_wait(self):
        task, state = self.make_task(['preset', 'preset'] + ['title_only'] * 4)
        self.run_numbered(task)
        self.assertEqual(state.clicks.count(task.I_SOU_SWITCH_4), 3)
        self.assertNotIn(task.I_SOU_SWITCH_SURE, state.clicks)
        self.assertTrue(all(call.args[0] is task.I_SOU_SWITCH_SURE
                            for call in task.appear.call_args_list))

    def test_named_switch_confirms_using_the_button_only(self):
        task, state = self.make_task(['preset'] * 7 + [
            'preset', 'confirm', 'preset', 'preset', 'preset', 'preset',
        ])
        self.run_named(task)
        self.assertEqual(state.clicks.count(task.I_SOU_SWITCH_SURE), 1)
        self.assertEqual(task.ocr_appear_click_by_rule.call_count, 4)
        task.ocr_appear_click_by_rule.assert_called_with(
            task.O_SS_TEAM_NAME, task.I_SOU_CLICK_PRESENT, interval=1.5)

    def test_named_switch_also_finishes_without_confirmation(self):
        task, state = self.make_task(['preset'] * 12)
        self.run_named(task)
        self.assertNotIn(task.I_SOU_SWITCH_SURE, state.clicks)
        self.assertEqual(task.ocr_appear_click_by_rule.call_count, 4)


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


    def test_theme_five_confirm_matches_current_modal(self):
        image = self.load_scene('shikigami_confirmation')
        rule = CostumeShikigamiAssets.I_SOU_SWITCH_SURE_5
        self.assertTrue(rule.template_match(image))
        self.assertEqual(rule.roi_front, [668, 401, 180, 61])


if __name__ == '__main__':
    unittest.main()
