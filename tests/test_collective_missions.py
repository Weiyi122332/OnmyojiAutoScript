"""集体任务切换后的状态、识别重试及提交窗口检查。"""

import unittest
import numpy as np
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from module.exception import TaskEnd
from tasks.CollectiveMissions.config import MC
from tasks.CollectiveMissions.page import page_collective_missions
from tasks.CollectiveMissions.script_task import ScriptTask
from tasks.GameUi.page import page_main


class CollectiveMissionsTest(unittest.TestCase):
    def setUp(self):
        logger = patch('tasks.CollectiveMissions.script_task.logger')
        logger.start()
        self.addCleanup(logger.stop)
        sleep = patch('tasks.CollectiveMissions.script_task.sleep')
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)

    def make_selection_task(self, names):
        task = ScriptTask.__new__(ScriptTask)
        task.current_mission = MC.FEED  # 模拟上次识别留下的结果。
        task.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8),
                                      click_record_clear=Mock())

        def screenshot():
            # 模拟任务切换或文字动画改变名称区域。
            task.device.image[135, 333, 0] += 1

        task.screenshot = Mock(side_effect=screenshot)
        task.O_CM_2 = SimpleNamespace(
            roi=(333, 135, 92, 44), ocr_single_line=Mock(side_effect=names),
            ocr=Mock(side_effect=AssertionError('full text detection is too expensive')))
        task.appear_then_click = Mock(return_value=True)
        return task

    def select(self, task, target=MC.GR1, max_switch=2):
        with patch('tasks.CollectiveMissions.script_task.random.randint', side_effect=[2, max_switch]), \
                patch('tasks.CollectiveMissions.script_task.random.uniform', return_value=0.6):
            return task.select_and_update_cur_mission(target)

    def test_target_after_last_allowed_switch_is_recognized(self):
        task = self.make_selection_task(['御魂一', '养成', '御灵一'])
        self.assertTrue(self.select(task))
        self.assertEqual(task.current_mission, MC.GR1)
        self.assertEqual(task.appear_then_click.call_count, 2)
        self.assertEqual(task.screenshot.call_count, 3)

    def test_selection_limit_does_not_leave_previous_feed_mission(self):
        task = self.make_selection_task(['御魂一', '养成', '御灵二'])
        self.assertFalse(self.select(task))
        self.assertIsNone(task.current_mission)
        self.assertEqual(task.appear_then_click.call_count, 2)
        self.assertEqual(task.O_CM_2.ocr_single_line.call_count, 3)

    def test_blank_ocr_retries_without_switching_away_from_target(self):
        task = self.make_selection_task(['', ' ', '御灵一'])
        self.assertTrue(self.select(task))
        task.appear_then_click.assert_not_called()
        self.assertEqual(task.current_mission, MC.GR1)
        self.assertEqual(self.sleep.call_args_list, [call(0.4), call(0.4)])

    def test_three_blank_reads_abort_without_using_stale_mission(self):
        task = self.make_selection_task(['', '', ''])
        self.assertFalse(self.select(task))
        self.assertIsNone(task.current_mission)
        task.appear_then_click.assert_not_called()
        self.assertEqual(task.screenshot.call_count, 3)

    def test_unchanged_blank_name_is_only_recognized_once(self):
        task = self.make_selection_task([''])
        task.screenshot = Mock()
        self.assertFalse(self.select(task))
        task.O_CM_2.ocr_single_line.assert_called_once()
        task.O_CM_2.ocr.assert_not_called()
        self.assertEqual(task.screenshot.call_count, 3)
        self.assertIsNone(task.current_mission)

    def test_changes_outside_name_region_do_not_repeat_ocr(self):
        task = self.make_selection_task([''])

        def screenshot():
            task.device.image[0, 0, 0] += 1

        task.screenshot.side_effect = screenshot
        self.assertFalse(self.select(task))
        task.O_CM_2.ocr_single_line.assert_called_once()
        task.O_CM_2.ocr.assert_not_called()
        self.assertEqual(task.screenshot.call_count, 3)

    def test_blank_ocr_after_switch_clears_previous_feed_mission(self):
        task = self.make_selection_task(['养成', '', '', ''])
        self.assertFalse(self.select(task))
        self.assertIsNone(task.current_mission)
        task.appear_then_click.assert_called_once()

    def test_recognized_but_unsupported_mission_can_be_switched(self):
        task = self.make_selection_task(['御魂三', '御灵一'])
        self.assertTrue(self.select(task))
        self.assertEqual(task.current_mission, MC.GR1)
        task.appear_then_click.assert_called_once()

    def test_locked_mission_does_not_run_as_fallback(self):
        task = self.make_selection_task(['养成', '养成', '养成'])
        self.assertFalse(self.select(task, max_switch=15))
        self.assertIsNone(task.current_mission)
        self.assertEqual(task.appear_then_click.call_count, 2)

    def test_missing_switch_button_aborts(self):
        task = self.make_selection_task(['养成'])
        task.appear_then_click.return_value = False
        self.assertFalse(self.select(task))
        self.assertIsNone(task.current_mission)
        task.device.click_record_clear.assert_not_called()

    def make_run_task(self, selected, current):
        task = ScriptTask.__new__(ScriptTask)
        task.config = SimpleNamespace(collective_missions=SimpleNamespace(
            missions_config=SimpleNamespace(missions_select=MC.GR1)))
        task.current_mission = current
        task.goto_page = Mock()
        task.get_task_reward = Mock()
        task.is_finish = Mock(return_value=False)
        task.select_and_update_cur_mission = Mock(return_value=selected)
        task.set_next_run = Mock()
        task._feed = Mock(return_value=True)
        task._donate = Mock(return_value=True)
        task._soul = Mock(return_value=True)
        return task

    def test_run_requires_both_selection_success_and_matching_target(self):
        for selected, current in ((False, MC.FEED), (False, MC.GR1), (True, MC.FEED), (True, None)):
            with self.subTest(selected=selected, current=current):
                task = self.make_run_task(selected, current)
                with self.assertRaises(TaskEnd):
                    task.run()
                task._feed.assert_not_called()
                task._donate.assert_not_called()
                task._soul.assert_not_called()
                self.assertEqual(task.goto_page.call_args_list,
                                 [call(page_collective_missions), call(page_main)])
                task.set_next_run.assert_called_once_with(task='CollectiveMissions', success=False)

    def test_run_propagates_submission_success_or_failure_to_schedule(self):
        for success in (True, False):
            with self.subTest(success=success):
                task = self.make_run_task(True, MC.GR1)
                task._donate.return_value = success
                with self.assertRaises(TaskEnd):
                    task.run()
                task._donate.assert_called_once()
                task._feed.assert_not_called()
                task._soul.assert_not_called()
                task.set_next_run.assert_called_once_with(task='CollectiveMissions', success=success)

    def make_window_task(self, frames):
        task = ScriptTask.__new__(ScriptTask)
        clock = SimpleNamespace(now=1000.0, visible=())
        frames = iter(frames)

        def screenshot():
            elapsed, clock.visible = next(frames)
            clock.now = 1000.0 + elapsed

        task.screenshot = Mock(side_effect=screenshot)
        task.appear = Mock(side_effect=lambda target: any(target is marker for marker in clock.visible))
        task.click = Mock(return_value=True)
        task.ui_click = Mock(side_effect=AssertionError('unbounded window opening'))
        return task, clock

    def open_window(self, task, clock, expected):
        with patch('tasks.CollectiveMissions.script_task.time.monotonic', side_effect=lambda: clock.now):
            return task._open_submission(expected)

    def test_delayed_expected_window_is_opened_once(self):
        for expected in (ScriptTask.I_CM_PRESENT, ScriptTask.I_SL_SUBMIT, ScriptTask.I_FEED_HEAP):
            with self.subTest(expected=expected):
                task, clock = self.make_window_task([(0, ()), (1, ()), (2, (expected,))])
                self.assertTrue(self.open_window(task, clock, expected))
                task.click.assert_called_once_with(task.C_CM_1)

    def test_existing_expected_window_does_not_get_clicked_again(self):
        expected = ScriptTask.I_CM_PRESENT
        task, clock = self.make_window_task([(0, (expected,))])
        self.assertTrue(self.open_window(task, clock, expected))
        task.click.assert_not_called()

    def test_material_window_is_rejected_by_feed_flow(self):
        task, clock = self.make_window_task([(0, ()), (1, (ScriptTask.I_CM_PRESENT,))])
        with patch('tasks.CollectiveMissions.script_task.time.monotonic', side_effect=lambda: clock.now):
            self.assertFalse(task._feed())
        task.click.assert_called_once_with(task.C_CM_1)
        task.ui_click.assert_not_called()

    def test_window_timeout_stops_after_one_opening_click(self):
        task, clock = self.make_window_task([(0, ()), (4.9, ()), (5, ())])
        self.assertFalse(self.open_window(task, clock, task.I_FEED_HEAP))
        task.click.assert_called_once_with(task.C_CM_1)
        self.assertEqual(task.screenshot.call_count, 3)

    def test_expected_window_at_timeout_boundary_is_accepted(self):
        expected = ScriptTask.I_CM_PRESENT
        task, clock = self.make_window_task([(0, ()), (5, (expected,))])
        self.assertTrue(self.open_window(task, clock, expected))
        task.click.assert_called_once_with(task.C_CM_1)

    def test_all_handlers_stop_before_submission_when_window_check_fails(self):
        for handler in ('_donate', '_soul', '_feed'):
            with self.subTest(handler=handler):
                task = ScriptTask.__new__(ScriptTask)
                task._open_submission = Mock(return_value=False)
                task.get_reward_and_close = Mock()
                task.ui_click = Mock(side_effect=AssertionError('unexpected submission'))
                self.assertFalse(getattr(task, handler)())
                task.get_reward_and_close.assert_not_called()
                task.ui_click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
