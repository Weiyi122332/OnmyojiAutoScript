"""Verify the courtyard retry wait and watchdog cleanup before reentering a dojo."""

import unittest
from unittest.mock import Mock, patch

from module.base.timer import Timer
from module.device.device import Device
from tasks.Dokan import page as pages
from tasks.Dokan.script_task import ScriptTask


class DokanRetryWaitTest(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.events = []
        clock = patch('module.base.timer.time.time', side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        sleeper = patch('tasks.Dokan.script_task.sleep', side_effect=self.sleep)
        self.sleeper = sleeper.start()
        self.addCleanup(sleeper.stop)
        log = patch('tasks.Dokan.script_task.logger')
        log.start()
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
        self.task.goto_page = Mock(side_effect=self.goto_page)

    def goto_page(self, page):
        self.assertFalse(self.task.second_dokan_ready)
        self.task.device.stuck_record_check()
        self.events.append(page)

    def sleep(self, seconds):
        self.assertEqual(self.events, [pages.page_main])
        self.assertEqual(self.task.device.detect_record, {'PAUSE'})
        self.events.append(seconds)
        self.now += seconds
        for _ in range(61):
            self.task.device.stuck_record_check()

    def test_courtyard_wait_precedes_reentry_and_does_not_trip_watchdog(self):
        with patch('tasks.Dokan.script_task.uniform', return_value=85.0):
            self.task.wait_for_next_dokan_selection()
        self.assertEqual(self.events, [pages.page_main, 85.0, pages.page_dokan_map])
        self.assertTrue(self.task.second_dokan_ready)
        self.assertFalse(self.task.dokan_owner_battle)
        self.assertFalse(self.task.attack_priority_selected)
        self.assertTrue(self.task.switch_member_soul_done)
        self.assertEqual(self.task.device.detect_record, set())
        self.assertEqual(self.now, 1085.0)

    def test_random_wait_is_selected_between_70_and_90_seconds(self):
        with patch('tasks.Dokan.script_task.uniform', return_value=70.0) as random_wait:
            self.task.wait_for_next_dokan_selection()
        random_wait.assert_called_once_with(70.0, 90.0)
        self.sleeper.assert_called_once_with(70.0)

    def test_courtyard_navigation_failure_does_not_wait_or_reenter(self):
        self.task.goto_page.side_effect = RuntimeError('courtyard unavailable')
        with self.assertRaisesRegex(RuntimeError, 'courtyard unavailable'):
            self.task.wait_for_next_dokan_selection()
        self.sleeper.assert_not_called()
        self.task.goto_page.assert_called_once_with(pages.page_main)
        self.assertFalse(self.task.second_dokan_ready)

    def test_interrupted_wait_clears_pause_and_does_not_reenter(self):
        self.sleeper.side_effect = RuntimeError('wait interrupted')
        with self.assertRaisesRegex(RuntimeError, 'wait interrupted'):
            self.task.wait_for_next_dokan_selection()
        self.task.goto_page.assert_called_once_with(pages.page_main)
        self.assertEqual(self.task.device.detect_record, set())
        self.assertFalse(self.task.second_dokan_ready)

    def test_failed_reentry_does_not_mark_second_selection_ready(self):
        def goto_page(page):
            self.goto_page(page)
            if page is pages.page_dokan_map:
                raise RuntimeError('dojo unavailable')

        self.task.goto_page.side_effect = goto_page
        with patch('tasks.Dokan.script_task.uniform', return_value=90.0):
            with self.assertRaisesRegex(RuntimeError, 'dojo unavailable'):
                self.task.wait_for_next_dokan_selection()
        self.assertEqual(self.events, [pages.page_main, 90.0, pages.page_dokan_map])
        self.assertFalse(self.task.second_dokan_ready)
        self.assertTrue(self.task.dokan_owner_battle)
        self.assertTrue(self.task.switch_member_soul_done)
        self.assertEqual(self.task.device.detect_record, set())


if __name__ == '__main__':
    unittest.main()
