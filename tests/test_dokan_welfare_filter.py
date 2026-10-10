"""Welfare dojo selection must never challenge a different emblem."""

import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.exception import TaskEnd
from module.device.device import Device
from tasks.Dokan.script_task import DokanRefreshLimitError, ScriptTask


class FakeDokanSelection:
    def __init__(self, people: int, has_xin: bool):
        self.found_dokan_cnt = 0
        self.has_xin = has_xin
        self.selected_item = None
        self.I_RIGHTPAD_POINT_BOUNTY = SimpleNamespace(roi_back=(1077, 0, 171, 602))
        self.I_RIGHTPAD_XIN_ICON = SimpleNamespace(
            roi_back=(1110, 20, 110, 610), roi_front=[0, 0, 45, 50], is_xin=True)
        self.I_CENTER_POINT_PEOPLE_NUMBER = SimpleNamespace(
            roi_back=(0, 0, 1280, 720), roi_front=(400, 420, 20, 20)
        )
        self.I_CENTER_CHALLENGE = object()
        self.I_CHALLENGE_ENSURE = object()
        self.I_REFRESH_ENSURE = object()
        self.C_DOKAN_REFRESH = object()
        self.S_DOKAN_LIST_UP = object()
        self.O_DOKAN_CENTER_PEOPLE_NUMBER = SimpleNamespace(
            roi=None, detect_text=Mock(return_value=f'{people}人')
        )
        self.device = SimpleNamespace(image=None, click_record_clear=Mock())
        self.config = SimpleNamespace(
            dokan=SimpleNamespace(
                dokan_config=SimpleNamespace(
                    min_people_num=150,
                    find_dokan_refresh_count=1,
                ),
                attack_count_config=SimpleNamespace(del_attack_count=Mock()),
            ),
            save=Mock(),
        )
        self.ui_click = Mock()
        self.ui_click_until_disappear = Mock()
        self.swipe = Mock()
        self.screenshot = Mock()
        self._wait_for_dokan_list_ready = Mock(return_value=True)
        self.prepare_appear_cache = Mock()

    def find_all_element(self, item, offset):
        return [(1125, 126, 27, 29), (1125, 418, 27, 29)]

    def appear(self, target):
        if getattr(target, 'is_xin', False):
            return self.has_xin and target.roi_back[1] == 328
        if target is self.I_CENTER_POINT_PEOPLE_NUMBER:
            return True
        return False

    def ui_click_until_appear_or_timeout(self, target, stop, **kwargs):
        self.selected_item = target.roi_back
        return True


class WelfareGuildFilterTest(unittest.TestCase):
    def test_non_xin_candidates_share_a_frame_without_per_item_screenshots_or_ocr(self):
        selection = FakeDokanSelection(people=170, has_xin=False)
        with patch('tasks.Dokan.script_task.logger'):
            with self.assertRaises(DokanRefreshLimitError):
                ScriptTask.find_dokan(selection)
        selection.screenshot.assert_not_called()
        selection.O_DOKAN_CENTER_PEOPLE_NUMBER.detect_text.assert_not_called()
        self.assertIsNone(selection.selected_item)
        rules = selection.prepare_appear_cache.call_args_list[0].args[0]
        self.assertEqual([rule.roi_back for rule in rules],
                         [(1110, 36, 100, 95), (1110, 328, 100, 95)])
        self.assertIsNot(rules[0], rules[1])

    def test_candidate_losing_xin_emblem_before_click_is_never_selected(self):
        selection = FakeDokanSelection(people=170, has_xin=True)
        selection.screenshot.side_effect = lambda: setattr(selection, 'has_xin', False)
        with patch('tasks.Dokan.script_task.logger'):
            with self.assertRaises(DokanRefreshLimitError):
                ScriptTask.find_dokan(selection)
        self.assertIsNone(selection.selected_item)
        selection.O_DOKAN_CENTER_PEOPLE_NUMBER.detect_text.assert_not_called()
        selection.config.dokan.attack_count_config.del_attack_count.assert_not_called()

    def test_moving_list_is_not_scanned_or_clicked(self):
        selection = FakeDokanSelection(people=170, has_xin=True)
        selection._wait_for_dokan_list_ready.return_value = False
        with patch('tasks.Dokan.script_task.logger'):
            with self.assertRaises(DokanRefreshLimitError):
                ScriptTask.find_dokan(selection)
        selection.prepare_appear_cache.assert_not_called()
        self.assertIsNone(selection.selected_item)
        selection.O_DOKAN_CENTER_PEOPLE_NUMBER.detect_text.assert_not_called()

    def test_no_xin_list_can_reach_twenty_refreshes_without_click_watchdog_error(self):
        selection = FakeDokanSelection(people=170, has_xin=False)
        selection.device = Device.__new__(Device)
        selection.device.click_record = deque(maxlen=20)

        def record_control(name):
            selection.device.click_record_add(name)
            selection.device.click_record_check()

        selection.swipe.side_effect = lambda *args: record_control('list swipe')
        selection.ui_click.side_effect = lambda click, *args, **kwargs: record_control(str(click))
        with patch('tasks.Dokan.script_task.logger'):
            with self.assertRaises(DokanRefreshLimitError):
                ScriptTask.find_dokan(selection)
        self.assertEqual(selection.swipe.call_count, 60)

    @patch('tasks.Dokan.script_task.sleep', return_value=None)
    def test_only_xin_emblem_with_enough_defenders_is_challenged(self, _sleep):
        selection = FakeDokanSelection(people=170, has_xin=True)
        self.assertTrue(ScriptTask.find_dokan(selection))
        self.assertEqual(selection.selected_item[1], 408)
        selection.config.dokan.attack_count_config.del_attack_count.assert_called_once()

    @patch('tasks.Dokan.script_task.sleep', return_value=None)
    def test_defender_threshold_is_halved_after_configured_refreshes(self, _sleep):
        selection = FakeDokanSelection(people=76, has_xin=True)
        selection.config.dokan.dokan_config.min_people_num = 151

        self.assertTrue(ScriptTask.find_dokan(selection))

        refreshes = [call for call in selection.ui_click.call_args_list
                     if call.args[0] is selection.C_DOKAN_REFRESH]
        self.assertEqual(len(refreshes), 2)
        selection.config.dokan.attack_count_config.del_attack_count.assert_called_once()

    @patch('tasks.Dokan.script_task.sleep', return_value=None)
    def test_twenty_refreshes_stop_without_challenging_ineligible_dojos(self, _sleep):
        for people, has_xin in ((170, False), (74, True)):
            with self.subTest(people=people, has_xin=has_xin):
                selection = FakeDokanSelection(people, has_xin)
                with self.assertRaises(DokanRefreshLimitError):
                    ScriptTask.find_dokan(selection)
                refreshes = [call for call in selection.ui_click.call_args_list
                             if call.args[0] is selection.C_DOKAN_REFRESH]
                self.assertEqual(len(refreshes), 20)
                selection.config.dokan.attack_count_config.del_attack_count.assert_not_called()
                self.assertFalse(any(call.args[0] is selection.I_CENTER_CHALLENGE
                                     for call in selection.ui_click.call_args_list))
                self.assertEqual(selection.I_RIGHTPAD_XIN_ICON.roi_back,
                                 (1110, 20, 110, 610))

    def test_refresh_limit_ends_today_and_sends_alert(self):
        task = ScriptTask.__new__(ScriptTask)
        notifier = SimpleNamespace(enable=True, push=Mock(return_value=True))
        dokan = SimpleNamespace(
            dokan_config=SimpleNamespace(monday_to_thursday=False),
            attack_count_config=SimpleNamespace(init_attack_count=Mock()),
        )
        task.config = SimpleNamespace(model=SimpleNamespace(dokan=dokan), save=Mock(), notifier=notifier)
        task.before_run = Mock()
        task.goto_page = Mock()
        task.screenshot = Mock()
        task._capture_dokan_reward_if_visible = Mock()
        task.get_current_page = Mock(side_effect=DokanRefreshLimitError)
        task.next_run = Mock()
        task._push_current_run_reward_images = Mock()

        with self.assertRaises(TaskEnd):
            task.run()

        task.next_run.assert_called_once_with(skip_today=True, is_dokan_activated=False)
        notifier.push.assert_called_once()
        self.assertEqual(notifier.push.call_args.kwargs['title'], '道馆达到最大刷新次数')
        self.assertIn('20次', notifier.push.call_args.kwargs['content'])
        task._push_current_run_reward_images.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
