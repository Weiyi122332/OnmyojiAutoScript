"""Exercise dojo retry waits against the real device watchdog using a fake clock."""

import unittest
from unittest.mock import Mock, patch

from module.base.timer import Timer
from module.device.device import Device
from tasks.Dokan.script_task import DokanNotStartedError, ScriptTask


class DokanWaitTimeoutTest(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.wall_offset = 0.0
        self.capture_duration = 1.0
        self.capture_started = []
        clock = patch('module.base.timer.time.time', side_effect=lambda: self.now + self.wall_offset)
        clock.start()
        self.addCleanup(clock.stop)
        monotonic = patch('tasks.Dokan.script_task.time.monotonic', side_effect=lambda: self.now)
        monotonic.start()
        self.addCleanup(monotonic.stop)
        sleeper = patch('tasks.Dokan.script_task.sleep', side_effect=self.sleep)
        sleeper.start()
        self.addCleanup(sleeper.stop)
        log = patch('tasks.Dokan.script_task.logger')
        self.log = log.start()
        self.addCleanup(log.stop)
        self.task = ScriptTask.__new__(ScriptTask)
        self.task.device = Device.__new__(Device)
        self.task.device.stuck_timer = Timer(60, count=60).start()
        self.task.device.stuck_timer_long = Timer(300, count=300).start()
        self.task.device.detect_record = set()
        self.task.device.app_is_running = Mock(return_value=True)
        self.task.dokan_owner_battle = True
        self.task.attack_priority_selected = True
        self.task.switch_member_soul_done = True
        self.task.second_dokan_ready = False
        self.task.screenshot = Mock(side_effect=self.screenshot)

    def screenshot(self):
        self.capture_started.append(self.now)
        self.now += self.capture_duration
        self.task.device.stuck_record_check()

    def sleep(self, seconds):
        self.now += seconds

    def test_selection_is_detected_immediately_without_initial_sleep(self):
        self.capture_duration = 0.1
        self.task.appear = Mock(return_value=True)
        ScriptTask.wait_for_next_dokan_selection(self.task)
        self.assertAlmostEqual(self.now, 1000.1)
        self.assertEqual(self.task.screenshot.call_count, 1)
        self.assertTrue(self.task.second_dokan_ready)

    def test_fast_capture_polls_every_two_seconds_and_returns_as_soon_as_visible(self):
        self.capture_duration = 0.1
        self.task.appear = Mock(side_effect=lambda target: self.now >= 1003)
        ScriptTask.wait_for_next_dokan_selection(self.task)
        self.assertAlmostEqual(self.now, 1004.1)
        self.assertEqual(len(self.capture_started), 3)
        for previous, current in zip(self.capture_started, self.capture_started[1:]):
            self.assertAlmostEqual(current - previous, 2.0)

    def test_selection_after_one_minute_is_detected_without_watchdog_error(self):
        self.task.appear = Mock(side_effect=lambda target: self.now >= 1085)
        ScriptTask.wait_for_next_dokan_selection(self.task)
        self.assertEqual(self.now, 1085)
        self.assertTrue(self.task.second_dokan_ready)
        self.assertTrue(self.task.switch_member_soul_done)
        self.assertFalse(self.task.dokan_owner_battle)
        self.assertEqual(self.task.device.detect_record, set())
        self.assertTrue(any('道馆再战等待：' in call.args[0]
                            for call in self.log.info.call_args_list))
        self.assertIn('等待 85.0 秒', self.log.info.call_args.args[0])

    def test_missing_selection_uses_full_two_minute_timeout(self):
        self.task.appear = Mock(return_value=False)
        with self.assertRaises(DokanNotStartedError):
            ScriptTask.wait_for_next_dokan_selection(self.task)
        self.assertEqual(self.now, 1120)
        self.assertFalse(self.task.second_dokan_ready)
        self.assertEqual(self.task.device.detect_record, set())
        self.log.warning.assert_called_once()

    def test_wall_clock_adjustment_does_not_extend_timeout(self):
        def appear(target):
            self.wall_offset -= 60
            return False

        self.task.appear = Mock(side_effect=appear)
        with self.assertRaises(DokanNotStartedError):
            ScriptTask.wait_for_next_dokan_selection(self.task)
        self.assertEqual(self.now, 1120)
        self.assertFalse(self.task.second_dokan_ready)

    def test_capture_overruns_deadline_without_accepting_a_late_selection(self):
        self.capture_duration = 130
        self.task.appear = Mock(return_value=True)
        with self.assertRaises(DokanNotStartedError):
            ScriptTask.wait_for_next_dokan_selection(self.task)
        self.task.appear.assert_not_called()
        self.assertFalse(self.task.second_dokan_ready)
        self.assertEqual(self.task.device.detect_record, set())
        self.assertIn('最近截图 130.00 秒', self.log.warning.call_args.args[0])

    def test_recognition_overruns_deadline_without_accepting_a_late_selection(self):
        def appear(target):
            self.now += 130
            return True

        self.task.appear = Mock(side_effect=appear)
        with self.assertRaises(DokanNotStartedError):
            ScriptTask.wait_for_next_dokan_selection(self.task)
        self.assertFalse(self.task.second_dokan_ready)
        self.assertEqual(self.task.device.detect_record, set())
        self.assertIn('识图 130.00 秒', self.log.warning.call_args.args[0])

    def test_wait_marker_is_cleared_after_screenshot_error(self):
        self.task.screenshot.side_effect = RuntimeError('screenshot failed')
        with self.assertRaisesRegex(RuntimeError, 'screenshot failed'):
            ScriptTask.wait_for_next_dokan_selection(self.task)
        self.assertFalse(self.task.second_dokan_ready)
        self.assertEqual(self.task.device.detect_record, set())


if __name__ == '__main__':
    unittest.main()
