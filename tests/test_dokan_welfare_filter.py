"""The welfare guild switch must never challenge a different emblem."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.exception import TaskEnd
from tasks.Dokan.script_task import DokanRefreshLimitError, ScriptTask


class FakeDokanSelection:
    def __init__(self, people: int, has_xin: bool, only_welfare: bool = True):
        self.found_dokan_cnt = 0
        self.has_xin = has_xin
        self.only_welfare = only_welfare
        self.selected_item = None
        self.I_RIGHTPAD_POINT_BOUNTY = SimpleNamespace(roi_back=(1077, 0, 171, 602))
        self.I_RIGHTPAD_XIN_ICON = SimpleNamespace(roi_back=(1110, 20, 110, 610))
        self.I_CENTER_POINT_PEOPLE_NUMBER = SimpleNamespace(
            roi_back=(0, 0, 1280, 720), roi_front=(400, 420, 20, 20)
        )
        self.I_CENTER_CHALLENGE = object()
        self.I_CENTER_GUANZHU_XIUXI = object()
        self.I_CHALLENGE_ENSURE = object()
        self.I_REFRESH_ENSURE = object()
        self.C_DOKAN_REFRESH = object()
        self.S_DOKAN_LIST_UP = object()
        self.O_DOKAN_RIGHTPAD_BOUNTY = SimpleNamespace(
            roi=None,
            ocr=Mock(side_effect=AssertionError('welfare mode read bounty'))
            if only_welfare else Mock(return_value='449万')
        )
        self.O_DOKAN_CENTER_PEOPLE_NUMBER = SimpleNamespace(
            roi=None, detect_text=Mock(return_value=f'{people}人')
        )
        self.device = SimpleNamespace(image=None, click_record_clear=Mock())
        self.config = SimpleNamespace(
            dokan=SimpleNamespace(
                dokan_config=SimpleNamespace(
                    only_welfare_guild=only_welfare,
                    min_people_num=150,
                    min_bounty=9999 if only_welfare else 0,
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

    def find_all_element(self, item, offset):
        return [(1125, 126, 27, 29), (1125, 418, 27, 29)]

    def appear(self, target):
        if target is self.I_RIGHTPAD_XIN_ICON:
            return self.has_xin and target.roi_back[1] == 328
        if target is self.I_CENTER_POINT_PEOPLE_NUMBER:
            return True
        if target is self.I_CENTER_GUANZHU_XIUXI:
            if self.only_welfare:
                raise AssertionError('welfare mode checked owner level')
            return True
        return False

    def ui_click_until_appear_or_timeout(self, target, stop, **kwargs):
        self.selected_item = target.roi_back
        return True


class WelfareGuildFilterTest(unittest.TestCase):
    @patch('tasks.Dokan.script_task.sleep', return_value=None)
    def test_switch_off_keeps_existing_selection(self, _sleep):
        selection = FakeDokanSelection(people=170, has_xin=False, only_welfare=False)
        self.assertTrue(ScriptTask.find_dokan(selection))
        self.assertEqual(selection.selected_item[1], 116)
        selection.O_DOKAN_RIGHTPAD_BOUNTY.ocr.assert_called_once()

    @patch('tasks.Dokan.script_task.sleep', return_value=None)
    def test_only_xin_emblem_with_enough_defenders_is_challenged(self, _sleep):
        selection = FakeDokanSelection(people=170, has_xin=True)
        self.assertTrue(ScriptTask.find_dokan(selection, score=0))
        self.assertEqual(selection.selected_item[1], 408)
        selection.config.dokan.attack_count_config.del_attack_count.assert_called_once()
        selection.O_DOKAN_RIGHTPAD_BOUNTY.ocr.assert_not_called()

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
