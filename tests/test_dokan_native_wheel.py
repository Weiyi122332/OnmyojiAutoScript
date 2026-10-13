"""Wheel selection preserves screening order, cadence, and unseen-page handling."""

import unittest
from random import Random
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.device.method.mumu_mouse import MuMuWheelClient, MuMuWheelError, MuMuWheelPreconditionError
from module.config.config_model import ConfigModel
from module.exception import TaskEnd
from tasks.Dokan.config import Dokan, DokanConfig
from tasks.Dokan.list_scroll import choose_wheel_count, scroll_dokan_list, wheel_intervals
from tasks.Dokan.script_task import DokanFinishedError, DokanNotStartedError, DokanRefreshLimitError, ScriptTask
import tasks.Dokan.page as pages
from test_dokan_welfare_filter import FakeDokanSelection


class Clock:
    def __init__(self):
        self.now = 0.0

    def sleep(self, seconds):
        self.now += seconds


class DokanWheelTimingTest(unittest.TestCase):
    def test_random_gaps_and_whole_batches_fit_user_ranges(self):
        random = Random(501)
        for count in (9, 5, 6):
            durations = set()
            with patch('tasks.Dokan.list_scroll.uniform', side_effect=random.uniform):
                for _ in range(200):
                    intervals = wheel_intervals(count)
                    self.assertEqual(len(intervals), count - 1)
                    self.assertTrue(all(0.05 - 1e-9 <= gap <= 0.15 + 1e-9 for gap in intervals))
                    lower = 0.75 if count == 9 else (count - 1) * 0.05
                    self.assertGreaterEqual(sum(intervals), lower - 1e-9)
                    self.assertLessEqual(sum(intervals), 1.0 + 1e-9)
                    durations.add(round(sum(intervals), 5))
            self.assertGreater(len(durations), 100)

    def test_first_count_is_nine_and_second_count_can_be_five_or_six(self):
        with patch('tasks.Dokan.list_scroll.randint', side_effect=[5, 6]) as choose:
            self.assertEqual(choose_wheel_count(1), 9)
            choose.assert_not_called()
            self.assertEqual(choose_wheel_count(2), 5)
            self.assertEqual(choose_wheel_count(2), 6)
            self.assertTrue(all(call.args == (5, 6) for call in choose.call_args_list))

    def test_connection_time_is_outside_batch_and_settling_is_after_last_notch(self):
        clock = Clock()
        events = []
        client = SimpleNamespace(check_scroll=Mock(), connect=lambda: clock.sleep(3),
                                 prepare_scroll=lambda *point: clock.sleep(0.15),
                                 scroll=lambda *point: events.append((clock.now, point)))
        with patch('tasks.Dokan.list_scroll.time.monotonic', side_effect=lambda: clock.now), \
                patch('tasks.Dokan.list_scroll.time.sleep', side_effect=clock.sleep):
            duration = scroll_dokan_list(client, 9)
        self.assertEqual(len(events), 9)
        self.assertEqual(events[0], (3.15, (1165, 400)))
        self.assertAlmostEqual(duration, events[-1][0] - events[0][0])
        self.assertAlmostEqual(clock.now - events[-1][0], 1.0)

    def test_adb_delivery_time_is_included_in_randomized_inter_event_gaps(self):
        clock = Clock()
        events = []

        def send(*point):
            events.append(clock.now)
            clock.sleep(0.04)

        client = SimpleNamespace(check_scroll=Mock(), connect=lambda: None,
                                 prepare_scroll=lambda *point: None, scroll=send)
        with patch('tasks.Dokan.list_scroll.time.monotonic', side_effect=lambda: clock.now), \
                patch('tasks.Dokan.list_scroll.time.sleep', side_effect=clock.sleep), \
                patch('tasks.Dokan.list_scroll.wheel_intervals', return_value=[0.1] * 8):
            duration = scroll_dokan_list(client, 9)
        self.assertEqual(len(events), 9)
        self.assertAlmostEqual(events[-1] - events[0], 0.8)
        self.assertAlmostEqual(duration, 0.84)
        self.assertAlmostEqual(clock.now - duration, 1.0)


class DokanWheelSelectionTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.events, self.screens = [], []
        self.client = SimpleNamespace(check_scroll=Mock(), connect=Mock(), prepare_scroll=Mock(), close=Mock(),
                                      scroll=Mock(side_effect=self.record_event))
        self.selection = FakeDokanSelection(people=170, has_xin=False)
        self.selection.config.dokan.dokan_config.native_wheel_enable = True
        self.selection._wait_for_dokan_list_ready.side_effect = self.record_screen
        for target, kwargs in (
            ('tasks.Dokan.script_task.MuMuWheelClient', {'return_value': self.client}),
            ('tasks.Dokan.script_task.logger', {}),
            ('tasks.Dokan.list_scroll.time.monotonic', {'side_effect': lambda: self.clock.now}),
            ('tasks.Dokan.list_scroll.time.sleep', {'side_effect': self.clock.sleep}),
            ('tasks.Dokan.list_scroll.randint', {'side_effect': [5, 6] * 20}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def record_event(self, *point):
        self.events.append((self.clock.now, point))

    def record_screen(self):
        self.screens.append((len(self.events), self.clock.now))
        return True

    def test_every_refresh_checks_three_screens_with_nine_then_five_or_six_events(self):
        with self.assertRaises(DokanRefreshLimitError):
            ScriptTask.find_dokan(self.selection)
        self.assertEqual(len(self.events), 10 * 14 + 10 * 15)
        self.assertEqual(len(self.screens), 20 * 3)
        start = 0
        for refresh in range(20):
            second_count = 5 if refresh % 2 == 0 else 6
            end = start + 9 + second_count
            screens = self.screens[refresh * 3:refresh * 3 + 3]
            self.assertEqual([screen[0] - start for screen in screens], [0, 9, 9 + second_count])
            self.assertAlmostEqual(screens[1][1] - self.events[start + 8][0], 1.0)
            self.assertAlmostEqual(screens[2][1] - self.events[end - 1][0], 1.0)
            for batch in (self.events[start:start + 9], self.events[start + 9:end]):
                self.assertTrue(all(0.05 - 1e-9 <= current[0] - previous[0] <= 0.15 + 1e-9
                                    for previous, current in zip(batch, batch[1:])))
            start = end
        self.selection.swipe.assert_not_called()
        self.selection.O_DOKAN_CENTER_PEOPLE_NUMBER.detect_text.assert_not_called()
        self.client.close.assert_not_called()
        self.assertEqual(self.client.prepare_scroll.call_count, 40)
        self.client.check_scroll.assert_called_once_with(1165, 400)
        self.assertTrue(all(call.args == (1165, 400)
                            for call in self.client.prepare_scroll.call_args_list))

    def test_success_on_second_screen_does_not_scroll_to_bottom(self):
        def screen():
            self.record_screen()
            self.selection.has_xin = len(self.events) == 9
            return True

        self.selection._wait_for_dokan_list_ready.side_effect = screen
        self.assertTrue(ScriptTask.find_dokan(self.selection))
        self.assertEqual(len(self.events), 9)
        self.selection.config.dokan.attack_count_config.del_attack_count.assert_called_once()
        self.client.close.assert_not_called()

    def test_success_on_first_screen_checks_once_without_sending_mouse_input(self):
        self.selection.has_xin = True
        self.assertTrue(ScriptTask.find_dokan(self.selection))
        self.client.connect.assert_not_called()
        self.client.check_scroll.assert_called_once_with(1165, 400)
        self.client.prepare_scroll.assert_not_called()
        self.client.scroll.assert_not_called()
        self.client.close.assert_not_called()

    def test_interrupted_batch_is_not_retried_or_refreshed(self):
        self.client.scroll.side_effect = [None, None, MuMuWheelError('disconnected')]
        with self.assertRaises(DokanNotStartedError):
            ScriptTask.find_dokan(self.selection)
        self.assertEqual(self.client.scroll.call_count, 3)
        self.assertEqual(self.selection._wait_for_dokan_list_ready.call_count, 1)
        self.selection.swipe.assert_not_called()
        self.selection.ui_click.assert_not_called()
        self.client.close.assert_not_called()

    def test_mouse_positioning_failure_during_execution_stops_without_another_precheck(self):
        self.client.prepare_scroll.side_effect = MuMuWheelError('mouse positioning failed')
        with self.assertRaises(DokanNotStartedError):
            ScriptTask.find_dokan(self.selection)
        self.client.scroll.assert_not_called()
        self.assertEqual(self.selection._wait_for_dokan_list_ready.call_count, 1)
        self.client.check_scroll.assert_called_once()
        self.selection.swipe.assert_not_called()

    def test_precheck_failure_uses_original_swipes_for_all_refreshes(self):
        self.client.check_scroll.side_effect = MuMuWheelPreconditionError('missing root')
        with self.assertRaises(DokanRefreshLimitError):
            ScriptTask.find_dokan(self.selection)
        self.client.check_scroll.assert_called_once_with(1165, 400)
        self.client.prepare_scroll.assert_not_called()
        self.client.scroll.assert_not_called()
        self.assertEqual(self.selection.swipe.call_count, 20 * 3)
        self.assertEqual(self.selection._wait_for_dokan_list_ready.call_count, 20 * 3)
        self.assertEqual(self.selection.ui_click.call_count, 20)
        self.client.close.assert_called_once()
        self.assertTrue(self.selection.config.dokan.dokan_config.native_wheel_enable)

    def test_touch_fallback_still_checks_the_next_screen_before_challenging(self):
        self.client.check_scroll.side_effect = MuMuWheelPreconditionError('service unavailable')
        self.selection.swipe.side_effect = lambda _: setattr(self.selection, 'has_xin', True)
        self.assertTrue(ScriptTask.find_dokan(self.selection))
        self.selection.swipe.assert_called_once_with(self.selection.S_DOKAN_LIST_UP)
        self.assertEqual(self.selection._wait_for_dokan_list_ready.call_count, 2)
        self.client.scroll.assert_not_called()
        self.selection.config.dokan.attack_count_config.del_attack_count.assert_called_once()

    def test_two_challenges_share_the_startup_check(self):
        self.client.check_scroll.side_effect = [None, MuMuWheelPreconditionError('must not recheck')]
        target = 9

        def screen():
            self.record_screen()
            self.selection.has_xin = len(self.events) == target
            return True

        self.selection._wait_for_dokan_list_ready.side_effect = screen
        self.assertTrue(ScriptTask.find_dokan(self.selection))
        target = 18
        self.assertTrue(ScriptTask.find_dokan(self.selection))
        self.assertEqual(len(self.events), 18)
        self.assertEqual(len(self.screens), 4)
        self.selection.swipe.assert_not_called()
        self.assertEqual(self.client.prepare_scroll.call_count, 2)
        self.client.check_scroll.assert_called_once()

    def test_failed_startup_check_is_reused_for_both_challenges(self):
        self.client.check_scroll.side_effect = MuMuWheelPreconditionError('missing root')
        self.selection.has_xin = True
        self.assertTrue(ScriptTask.find_dokan(self.selection))
        self.assertTrue(ScriptTask.find_dokan(self.selection))
        self.client.check_scroll.assert_called_once()
        self.client.scroll.assert_not_called()
        self.client.close.assert_called_once()

    def test_task_checks_before_navigation_and_checks_again_on_the_next_run(self):
        task = ScriptTask.__new__(ScriptTask)
        dokan = Dokan()
        dokan.dokan_config.native_wheel_enable = True
        dokan.dokan_config.monday_to_thursday = False
        task.config = SimpleNamespace(model=SimpleNamespace(dokan=dokan), dokan=dokan,
                                      config_name='test', save=Mock())
        task.device = self.selection.device
        task.before_run = Mock()
        task.screenshot = Mock()
        task._capture_dokan_reward_if_visible = Mock()
        task.next_run = Mock()
        task._push_current_run_reward_images = Mock()
        task._push_dokan_refresh_limit_notification = Mock()
        events = []
        self.client.check_scroll.side_effect = lambda *point: events.append('check')
        task.goto_page = Mock(side_effect=lambda page: events.append(('navigate', page)))
        task.get_current_page = Mock()
        for run_index in range(2):
            task.get_current_page.side_effect = [pages.page_dokan_map, pages.page_dokan_map]
            selected = []

            def select_again():
                selected.append(task._prepare_dokan_list_scroll())
                if len(selected) == 2:
                    raise DokanFinishedError

            task.run_on_dokan_map = Mock(side_effect=select_again)
            with self.assertRaises(TaskEnd):
                task.run()
            self.assertEqual(selected, [self.client, self.client])
            self.assertEqual(self.client.check_scroll.call_count, run_index + 1)
            self.assertEqual(self.client.close.call_count, run_index + 1)
            self.assertIsNone(task._dokan_wheel_client)
        self.assertEqual(events[:2], ['check', ('navigate', pages.page_dokan_map)])

    def test_non_root_adb_uses_touch_without_querying_service_or_writing_wheel_input(self):
        self.selection.device.adb = Mock()
        self.selection.device.adb.shell.return_value = '2000'
        native = MuMuWheelClient(self.selection.device)
        with patch('tasks.Dokan.script_task.MuMuWheelClient', return_value=native):
            with self.assertRaises(DokanRefreshLimitError):
                ScriptTask.find_dokan(self.selection)
        self.selection.device.adb.shell.assert_called_once_with(['id', '-u'], timeout=5)
        self.assertEqual(self.selection.swipe.call_count, 20 * 3)
        self.assertIsNone(native._input)

    def test_unstable_second_screen_is_not_skipped(self):
        self.selection._wait_for_dokan_list_ready.side_effect = [True, False, False]
        with self.assertRaises(DokanNotStartedError):
            ScriptTask.find_dokan(self.selection)
        self.assertEqual(len(self.events), 9)
        self.selection.ui_click.assert_not_called()
        self.client.close.assert_not_called()


class DokanWheelConfigurationTest(unittest.TestCase):
    def test_existing_configs_default_to_disabled(self):
        self.assertFalse(DokanConfig.model_validate({}).native_wheel_enable)

    def test_legacy_wheel_setting_is_migrated_without_exporting_its_old_name(self):
        model = DokanConfig.model_validate({'scrcpy_wheel_enable': True})
        self.assertTrue(model.native_wheel_enable)
        self.assertNotIn('scrcpy_wheel_enable', model.model_dump())

    def test_explicit_native_setting_takes_priority_over_legacy_value(self):
        model = DokanConfig.model_validate({'scrcpy_wheel_enable': True, 'native_wheel_enable': False})
        self.assertFalse(model.native_wheel_enable)

    def test_dynamic_configuration_page_exports_boolean_switch(self):
        model = ConfigModel()
        switch = next(item for item in model.script_task('Dokan')['dokan_config']
                      if item['name'] == 'native_wheel_enable')
        self.assertEqual(switch['type'], 'boolean')
        self.assertFalse(switch['value'])
        model.dokan.dokan_config.native_wheel_enable = True
        switch = next(item for item in model.script_task('Dokan')['dokan_config']
                      if item['name'] == 'native_wheel_enable')
        self.assertTrue(switch['value'])


if __name__ == '__main__':
    unittest.main()
