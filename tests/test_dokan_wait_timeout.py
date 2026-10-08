"""Exercise dojo retry waits against the real device watchdog using a fake clock."""

import unittest
from types import MethodType
from unittest.mock import Mock, patch

from module.base.timer import Timer
from module.device.device import Device
from tasks.base_task import BaseTask
from tasks.Dokan.script_task import DokanNotStartedError, ScriptTask


class DokanWaitTimeoutTest(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        clock = patch('module.base.timer.time.time', side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
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
        self.task.wait_until_appear = MethodType(BaseTask.wait_until_appear, self.task)

    def screenshot(self):
        self.now += 1
        self.task.device.stuck_record_check()

    def test_selection_after_one_minute_is_detected_without_watchdog_error(self):
        self.task.appear = Mock(side_effect=lambda target: self.now >= 1085)
        ScriptTask.wait_for_next_dokan_selection(self.task)
        self.assertEqual(self.now, 1085)
        self.assertTrue(self.task.second_dokan_ready)
        self.assertTrue(self.task.switch_member_soul_done)
        self.assertFalse(self.task.dokan_owner_battle)
        self.assertEqual(self.task.device.detect_record, set())

    def test_missing_selection_uses_full_two_minute_timeout(self):
        self.task.appear = Mock(return_value=False)
        with self.assertRaises(DokanNotStartedError):
            ScriptTask.wait_for_next_dokan_selection(self.task)
        self.assertGreaterEqual(self.now, 1120)
        self.assertFalse(self.task.second_dokan_ready)
        self.assertEqual(self.task.device.detect_record, set())

    def test_wait_marker_is_cleared_after_screenshot_error(self):
        self.task.screenshot.side_effect = RuntimeError('screenshot failed')
        with self.assertRaisesRegex(RuntimeError, 'screenshot failed'):
            ScriptTask.wait_for_next_dokan_selection(self.task)
        self.assertFalse(self.task.second_dokan_ready)
        self.assertEqual(self.task.device.detect_record, set())


if __name__ == '__main__':
    unittest.main()
