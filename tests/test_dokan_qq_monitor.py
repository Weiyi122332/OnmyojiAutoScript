"""Plugin status validation, persistence and scheduling without real QQ/game actions."""

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch

from pydantic import ValidationError

from module.config.config import Config
from module.config.config_model import ConfigModel
from module.server.config_manager import ConfigManager
from module.script import ScriptRuntimeController, ScriptRuntimeDecision
from script import Script
from tasks.Script.config_optimization import Optimization
from tasks.Dokan.config import Dokan, QQMessageConfig
from tasks.Dokan.qq_monitor import (CHINA_TZ, DokanQQMonitor, QQDokanState,
                                    fetch_welfare_status, is_query_time)
from tasks.Dokan import page as dokan_pages
from tasks.Dokan.script_task import ScriptTask

NOW = datetime(2026, 10, 9, 20, tzinfo=CHINA_TZ)


class QQMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'state.db'
        self.settings = QQMessageConfig(qq_message_enable=True,
            welfare_plugin_url='http://127.0.0.1:2537/welfare-dojo/today',
            welfare_plugin_token='test-token')

    def status(self, opened=True, now=NOW):
        return {'date': now.date().isoformat(), 'opened': opened}

    def session(self, body=None):
        session = Mock()
        session.get.return_value.json.return_value = self.status() if body is None else body
        return session

    def test_status_uses_get_with_plugin_token_and_no_redirect(self):
        session = self.session()
        self.assertEqual(fetch_welfare_status(session, self.settings, NOW), self.status())
        session.get.assert_called_once_with(self.settings.welfare_plugin_url,
            headers={'Authorization': 'Bearer test-token'}, timeout=(3, 8), allow_redirects=False)
        session.post.assert_not_called()

    def test_invalid_status_never_grants_permission(self):
        for body in ([], {}, {'date': '2026-10-09', 'opened': 'true'},
                     {'date': '2026-10-09', 'opened': 1}, {'date': None, 'opened': True},
                     {'status': 'ok', 'retcode': 0, 'data': {'messages': []}}):
            with self.assertRaises(ValueError):
                fetch_welfare_status(self.session(body), self.settings, NOW)
        session = self.session()
        session.get.return_value.raise_for_status.side_effect = ValueError('HTTP failure')
        with self.assertRaises(ValueError):
            fetch_welfare_status(session, self.settings, NOW)

    def test_yesterday_future_or_noncanonical_date_is_ignored(self):
        for date in ('2026-10-08', '2026-10-10', '2026/10/09', '2026-10-09T20:00:00'):
            self.assertIsNone(fetch_welfare_status(self.session({'date': date, 'opened': True}), self.settings, NOW))
        self.assertEqual(fetch_welfare_status(self.session(), self.settings, NOW), self.status())

    def test_url_and_token_validation_never_sends_a_request(self):
        for url in ('file:///tmp/today', 'http://user:secret@localhost:6099/today',
                    'http://localhost:6099/today?token=secret', 'http://localhost:6099',
                    'http://localhost:6099/today#part', ''):
            settings = self.settings.model_copy(update={'welfare_plugin_url': url})
            session = Mock()
            with self.assertRaises(ValueError):
                fetch_welfare_status(session, settings, NOW)
            session.get.assert_not_called()
        with self.assertRaises(ValueError):
            fetch_welfare_status(Mock(), self.settings.model_copy(update={'welfare_plugin_token': ''}), NOW)

    def test_cached_opening_expires_at_beijing_midnight(self):
        state = QQDokanState('p', self.path)
        before = NOW.replace(hour=23, minute=59, second=59)
        state.record(self.settings, self.status(now=before), before)
        self.assertEqual(state.flags(self.settings, before), (True, True))
        self.assertEqual(state.flags(self.settings, before+timedelta(seconds=1)), (False, False))

    def test_false_status_does_not_write_state_or_trigger(self):
        monitor = DokanQQMonitor('p', self.path)
        monitor.poll_once(self.session(self.status(False)), self.settings, now=NOW)
        self.assertFalse(self.path.exists())
        self.assertFalse(monitor.ready.is_set())

    def test_state_persists_once_per_day_and_profiles_and_endpoints_are_isolated(self):
        state = QQDokanState('大号', self.path)
        state.record(self.settings, self.status(), NOW)
        self.assertEqual(state.flags(self.settings, NOW), (True, True))
        state.consume(self.settings, NOW)
        self.assertEqual(QQDokanState('大号', self.path).flags(self.settings, NOW), (True, False))
        state.record(self.settings, self.status(), NOW)
        self.assertEqual(state.flags(self.settings, NOW), (True, False))
        self.assertEqual(state.flags(self.settings, NOW+timedelta(days=1)), (False, False))
        self.assertEqual(QQDokanState('小号', self.path).flags(self.settings, NOW), (False, False))
        for key, value in [('welfare_plugin_url', 'http://localhost:7000/today'),
                           ('welfare_plugin_token', 'different-token')]:
            self.assertEqual(state.flags(self.settings.model_copy(update={key: value}), NOW), (False, False))
        self.assertNotIn('test-token', self.path.read_bytes().decode('latin-1'))

    def test_disabled_monitor_performs_no_network_or_state_writes(self):
        monitor = DokanQQMonitor('p', self.path)
        session = Mock()
        monitor.poll_once(session, self.settings.model_copy(update={'qq_message_enable': False}), now=NOW)
        monitor.poll_once(session, self.settings, task_enabled=False, now=NOW)
        session.get.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_query_window_default_and_cross_midnight(self):
        for hour, minute, expected in ((19, 59, False), (20, 0, True), (21, 59, True), (22, 0, False)):
            self.assertEqual(is_query_time(self.settings, NOW.replace(hour=hour, minute=minute)), expected)
        self.settings.qq_query_start_time = clock_time(22)
        self.settings.qq_query_end_time = clock_time(2)
        for hour, expected in ((21, False), (22, True), (0, True), (1, True), (2, False)):
            self.assertEqual(is_query_time(self.settings, NOW.replace(hour=hour)), expected)

    def test_outside_window_makes_no_queries_but_keeps_a_pending_trigger(self):
        monitor = DokanQQMonitor('p', self.path)
        session = Mock()
        monitor.poll_once(session, self.settings, now=NOW.replace(hour=19, minute=59))
        fetch_welfare_status(session, self.settings, NOW.replace(hour=22))
        session.get.assert_not_called()
        self.assertFalse(self.path.exists())
        monitor.poll_once(self.session(), self.settings, now=NOW)
        monitor.poll_once(session, self.settings, now=NOW.replace(hour=22))
        session.get.assert_not_called()
        self.assertTrue(monitor.ready.is_set())

    def test_response_crossing_midnight_cannot_grant_yesterdays_permission(self):
        monitor = DokanQQMonitor('p', self.path)
        self.settings.qq_query_start_time = self.settings.qq_query_end_time = clock_time(0)
        with patch('tasks.Dokan.qq_monitor.time.monotonic', side_effect=[0, 2]):
            monitor.poll_once(self.session(), self.settings, now=NOW.replace(hour=23, minute=59, second=59))
        self.assertFalse(self.path.exists())
        self.assertFalse(monitor.ready.is_set())

    def test_matching_stops_queries_until_next_day_including_after_restart(self):
        monitor = DokanQQMonitor('p', self.path)
        monitor.poll_once(self.session(), self.settings, now=NOW)
        idle = Mock()
        monitor.poll_once(idle, self.settings, now=NOW+timedelta(minutes=1))
        restarted = DokanQQMonitor('p', self.path)
        restarted.poll_once(idle, self.settings, now=NOW+timedelta(minutes=2))
        idle.get.assert_not_called()
        self.assertTrue(restarted.ready.is_set())
        tomorrow = NOW+timedelta(days=1)
        fresh = self.session(self.status(now=tomorrow))
        restarted.poll_once(fresh, self.settings, now=tomorrow)
        fresh.get.assert_called_once()
        self.assertTrue(restarted.ready.is_set())

    def test_signal_is_consumed_and_network_failure_cannot_trigger(self):
        monitor = DokanQQMonitor('p', self.path)
        monitor.poll_once(self.session(), self.settings, now=NOW)
        monitor.state.consume(self.settings, NOW)
        monitor.poll_once(Mock(), self.settings, now=NOW)
        self.assertFalse(monitor.ready.is_set())
        failed = Mock()
        failed.get.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            monitor.poll_once(failed, self.settings, now=NOW+timedelta(days=1))
        self.assertEqual(monitor.state.flags(self.settings, NOW+timedelta(days=1)), (False, False))

    def test_ui_defaults_removes_message_filtering_and_redacts_plugin_token(self):
        fields = {item['name']: item for item in ConfigModel().script_task('Dokan')['qq_message_config']}
        self.assertEqual(set(fields), {'qq_message_enable', 'welfare_plugin_url', 'welfare_plugin_token',
                                      'qq_query_start_time', 'qq_query_end_time', 'qq_poll_interval'})
        self.assertFalse(fields['qq_message_enable']['value'])
        self.assertEqual(fields['qq_query_start_time']['type'], 'time')
        self.assertEqual(fields['qq_query_start_time']['value'], '20:00:00')
        self.assertEqual(fields['qq_query_end_time']['value'], '22:00:00')
        self.assertEqual(fields['qq_poll_interval']['value'], 60)
        self.assertEqual(QQMessageConfig(qq_poll_interval=37).qq_poll_interval, 37)
        for interval in (0, 86401):
            with self.assertRaises(ValidationError):
                QQMessageConfig(qq_poll_interval=interval)
        data = {'dokan': {'qq_message_config': self.settings.model_dump()}}
        self.assertEqual(ConfigManager.redact_config(data)['dokan']['qq_message_config']['welfare_plugin_token'], 'XXX')
        self.assertEqual(data['dokan']['qq_message_config']['welfare_plugin_token'], 'test-token')

    def test_worker_uses_real_http_status_endpoint_without_game_access(self):
        calls = []
        body = self.status(now=datetime.now(CHINA_TZ))

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append((self.path, self.headers.get('Authorization')))
                payload = json.dumps(body).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
        thread.start()
        monitor = DokanQQMonitor('p', self.path)
        self.settings.welfare_plugin_url = f'http://127.0.0.1:{server.server_port}/welfare-dojo/today'
        self.settings.qq_query_start_time = self.settings.qq_query_end_time = clock_time(0)
        monitor._load_settings = Mock(return_value=(self.settings, True))
        try:
            monitor.start()
            self.assertTrue(monitor.ready.wait(timeout=3))
            self.assertEqual(calls, [('/welfare-dojo/today', 'Bearer test-token')])
        finally:
            monitor.stop()
            monitor._thread.join(timeout=3)
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)
        self.assertFalse(monitor._thread.is_alive())


class QQSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.task = Script.__new__(Script)
        self.dokan = Dokan()
        self.dokan.scheduler.enable = True
        self.dokan.qq_message_config.qq_message_enable = True
        self.dokan.dokan_config.monday_to_thursday = False
        self.other = SimpleNamespace(command='RyouToppa', next_run=datetime.now()-timedelta(minutes=1))
        self.dokan_task = SimpleNamespace(command='Dokan', next_run=datetime.now()+timedelta(hours=1))
        self.task.__dict__['config'] = SimpleNamespace(model=SimpleNamespace(dokan=self.dokan),
                                                     pending_task=[self.other], waiting_task=[self.dokan_task])
        self.task.dokan_qq_monitor = SimpleNamespace(state=Mock(), ready=Mock(), start=Mock())
        self.task.dokan_qq_monitor.ready.is_set.return_value = False

    def scheduler_config(self, task):
        config = self.task.config
        config.get_next = Mock(return_value=task)
        config.start_watching = Mock()
        config.should_reload = Mock(return_value=False)
        config.script = SimpleNamespace(optimization=Optimization())
        self.task.config_name = 'test'
        self.task.state_queue = None
        self.task._antiban_wake_time = Mock(return_value=None)
        self.task._handle_continuous_task_rest = Mock(return_value=False)
        self.task._reset_continuous_task_rest = Mock()
        return config

    @staticmethod
    def forbid_device_access(task):
        raise AssertionError('Plugin-only status handling accessed the emulator')

    def test_match_prioritizes_dojo_only_at_next_selection(self):
        self.task.dokan_qq_monitor.state.flags.return_value = (True, True)
        self.task.dokan_qq_monitor.ready.is_set.return_value = True
        result = self.task._select_dokan_qq_task(self.other)
        self.assertEqual(result.command, 'Dokan')
        self.assertLessEqual(result.next_run, datetime.now())
        self.assertEqual([item.command for item in self.task.config.pending_task], ['Dokan', 'RyouToppa'])
        self.task.dokan_qq_monitor.state.consume.assert_not_called()

    def test_triggered_dojo_is_reported_running_in_dashboard_schedule(self):
        self.task.dokan_qq_monitor.state.flags.return_value = (True, True)
        self.task.dokan_qq_monitor.ready.is_set.return_value = True
        config = self.task.config
        config.scheduler_update_dt = datetime.now() - timedelta(seconds=1)
        config.get_next = Mock(return_value=self.other)
        config.get_schedule_data = MethodType(Config.get_schedule_data, config)
        self.task.state_queue = Mock()
        self.task._antiban_wake_time = Mock(return_value=None)
        self.task._handle_continuous_task_rest = Mock(return_value=False)

        self.assertEqual(self.task.get_next_task(), 'Dokan')
        schedule = self.task.state_queue.put.call_args.args[0]['schedule']
        self.assertEqual(schedule['running']['name'], 'Dokan')
        self.assertEqual([item['name'] for item in schedule['pending']], ['RyouToppa'])
        self.assertEqual(schedule['waiting'], [])

    def test_unconfirmed_monitor_preserves_normal_selection_and_task_lists(self):
        monitor = self.task.dokan_qq_monitor
        monitor.state.flags.side_effect = AssertionError('No signal should query the trigger cache')
        pending, waiting = self.task.config.pending_task, self.task.config.waiting_task
        for selected in (self.other, self.dokan_task):
            self.assertIs(self.task._select_dokan_qq_task(selected), selected)
            self.assertIs(self.task.config.pending_task, pending)
            self.assertIs(self.task.config.waiting_task, waiting)
        monitor.state.flags.assert_not_called()
        monitor.state.consume.assert_not_called()

    def test_unconfirmed_due_dojo_runs_on_its_normal_schedule_with_monitor_on_or_off(self):
        config = self.scheduler_config(self.dokan_task)
        self.task.runtime = SimpleNamespace(handle_wait_during_idle=Mock())
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                self.dokan.qq_message_config.qq_message_enable = enabled
                self.dokan_task.next_run = datetime.now() - timedelta(seconds=1)
                config.pending_task = [self.dokan_task]
                config.waiting_task = []
                with patch.object(Script, 'device', property(self.forbid_device_access)):
                    self.assertEqual(self.task.get_next_task(), 'Dokan')
                self.assertIs(config.task, self.dokan_task)
        self.task.runtime.handle_wait_during_idle.assert_not_called()
        self.task.dokan_qq_monitor.state.flags.assert_not_called()
        self.task.dokan_qq_monitor.state.consume.assert_not_called()

    def test_reload_keeps_the_original_dojo_deadline_and_queue(self):
        config = self.task.config
        original_next_run = self.dokan_task.next_run
        for _ in range(3):
            config.pending_task = [self.other]
            config.waiting_task = [self.dokan_task]
            self.assertIs(self.task._select_dokan_qq_task(self.other), self.other)
            self.assertEqual(config.pending_task, [self.other])
            self.assertEqual(config.waiting_task, [self.dokan_task])
            self.assertEqual(self.dokan_task.next_run, original_next_run)

    def test_disabled_feature_and_regular_retries_keep_original_selection(self):
        self.dokan.qq_message_config.qq_message_enable = False
        self.assertIs(self.task._select_dokan_qq_task(self.other), self.other)
        self.task.dokan_qq_monitor.state.flags.assert_not_called()
        self.dokan.qq_message_config.qq_message_enable = True
        self.task.dokan_qq_monitor.state.flags.return_value = (True, False)
        self.assertIs(self.task._select_dokan_qq_task(self.other), self.other)

    def test_restart_remains_first_and_cached_count_does_not_replace_game_check(self):
        self.task.dokan_qq_monitor.state.flags.return_value = (True, True)
        self.task.dokan_qq_monitor.ready.is_set.return_value = True
        restart = SimpleNamespace(command='Restart', next_run=datetime.now()-timedelta(seconds=1))
        self.assertIs(self.task._select_dokan_qq_task(restart), restart)
        self.dokan.attack_count_config.attack_date = datetime.now().strftime('%Y-%m-%d')
        self.dokan.attack_count_config.remain_attack_count = 0
        self.assertEqual(self.task._select_dokan_qq_task(self.other).command, 'Dokan')
        self.task.dokan_qq_monitor.state.consume.assert_not_called()

    def test_idle_wait_wakes_immediately_for_message_without_device_actions(self):
        self.task.dokan_qq_monitor.state.flags.return_value = (True, True)
        self.task.dokan_qq_monitor.ready.is_set.return_value = True
        self.task.config.start_watching = Mock()
        self.task.runtime = SimpleNamespace(server_update_wait_until=None)
        self.task._antiban_wake_time = Mock(return_value=None)
        with patch('script.time.sleep') as sleep:
            self.assertFalse(self.task.wait_until(datetime.now()+timedelta(hours=1)))
        sleep.assert_not_called()

    def test_idle_policy_is_unchanged_without_a_confirmed_trigger(self):
        config = self.scheduler_config(self.other)
        for enabled in (False, True):
            for strategy in ('goto_main', 'close_game', 'close_emulator_or_goto_main',
                             'close_emulator_or_close_game'):
                with self.subTest(enabled=enabled, strategy=strategy):
                    self.task.__dict__['config'] = config
                    self.dokan.qq_message_config.qq_message_enable = enabled
                    self.other.next_run = datetime.now() + timedelta(minutes=10)
                    deadline = self.other.next_run
                    config.pending_task = []
                    config.waiting_task = [self.other, self.dokan_task]
                    config.script.optimization = Optimization(when_task_queue_empty=strategy)

                    def normal_idle(future):
                        self.other.next_run = datetime.now() - timedelta(seconds=1)
                        return ScriptRuntimeDecision.READY

                    self.task.runtime = SimpleNamespace(handle_wait_during_idle=Mock(side_effect=normal_idle))
                    with patch.object(Script, 'device', property(self.forbid_device_access)), \
                            patch.object(self.task, 'wait_until') as direct_wait:
                        self.assertEqual(self.task.get_next_task(), 'RyouToppa')
                    self.task.runtime.handle_wait_during_idle.assert_called_once_with(deadline)
                    direct_wait.assert_not_called()

    def test_unconfirmed_monitor_runs_other_due_tasks_without_device_access(self):
        config = self.scheduler_config(self.other)
        self.task.runtime = SimpleNamespace(handle_wait_during_idle=Mock())
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                self.dokan.qq_message_config.qq_message_enable = enabled
                self.other.next_run = datetime.now() - timedelta(seconds=1)
                config.pending_task = [self.other]
                config.waiting_task = [self.dokan_task]
                with patch.object(Script, 'device', property(self.forbid_device_access)):
                    self.assertEqual(self.task.get_next_task(), 'RyouToppa')
        self.task.runtime.handle_wait_during_idle.assert_not_called()

    def test_close_game_idle_policy_closes_the_game_with_monitor_on_or_off(self):
        config = self.scheduler_config(self.other)
        config.script.optimization = Optimization(when_task_queue_empty='close_game',
                                                 close_game_limit_time=clock_time(0))
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                self.dokan.qq_message_config.qq_message_enable = enabled
                self.other.next_run = datetime.now() + timedelta(hours=1)
                config.pending_task = []
                config.waiting_task = [self.other, self.dokan_task]
                device = SimpleNamespace(app_is_running=Mock(return_value=True), app_stop=Mock(),
                                         release_during_wait=Mock())
                self.task.__dict__['device'] = device
                self.task._emulator_down = False
                self.task.runtime = ScriptRuntimeController(self.task)
                self.task.runtime._ensure_emulator_running = Mock()

                def reach_deadline(future):
                    self.other.next_run = datetime.now() - timedelta(seconds=1)
                    return True

                with patch.object(self.task, 'wait_until', side_effect=reach_deadline):
                    self.assertEqual(self.task.get_next_task(), 'RyouToppa')
                device.app_stop.assert_called_once()
                device.release_during_wait.assert_called_once()
                self.task.dokan_qq_monitor.state.consume.assert_not_called()

    def test_expired_or_absent_confirmation_does_not_interrupt_a_normal_wait(self):
        self.scheduler_config(self.other)
        self.task.dokan_qq_monitor.state.flags.return_value = (False, False)
        self.task.dokan_qq_monitor.ready.is_set.return_value = False
        self.task.runtime = SimpleNamespace(server_update_wait_until=None)
        with patch.object(Script, 'device', property(self.forbid_device_access)), \
                patch('script.time.sleep') as sleep:
            self.assertTrue(self.task.wait_until(datetime.now() - timedelta(seconds=2)))
        sleep.assert_not_called()
        self.task.dokan_qq_monitor.state.flags.assert_not_called()

    def test_normal_task_startup_window_preference_is_independent_of_monitor_confirmation(self):
        config = self.scheduler_config(self.dokan_task)
        self.task.resource_precache_enable = False
        self.task.is_first_task = False
        self.task._error_restart_pending = False
        for enabled in (False, True):
            for background, minimized in ((False, False), (False, True), (True, False)):
                with self.subTest(enabled=enabled, background=background, minimized=minimized):
                    self.task.__dict__['config'] = config
                    self.dokan.qq_message_config.qq_message_enable = enabled
                    self.dokan_task.next_run = datetime.now() - timedelta(seconds=1)
                    config.pending_task = [self.dokan_task]
                    config.waiting_task = []
                    config.script.device = SimpleNamespace(run_background_only=background,
                        emulator_window_minimize=minimized, handle='test emulator')
                    events = []
                    platform = SimpleNamespace(show_window_by_name=Mock(side_effect=lambda _: events.append('show')),
                        minimize_by_name=Mock(side_effect=lambda _: events.append('minimize')))

                    def prepare_task(task):
                        events.append(f'prepare:{task}')
                        raise SystemExit('stop before real game actions')

                    self.task.runtime = SimpleNamespace(prepare_task_execution=Mock(side_effect=prepare_task))
                    with patch.object(Script, 'device', property(self.forbid_device_access)), \
                            patch('script.IS_WINDOWS', True), \
                            patch.dict('sys.modules', {'module.device.platform2.platform_windows': platform}), \
                            patch('script.logger.set_file_logger'):
                        with self.assertRaises(SystemExit):
                            self.task.loop()
                    expected_window = [] if background else ['minimize' if minimized else 'show']
                    self.assertEqual(events, [*expected_window, 'prepare:Dokan'])

    def test_manual_dojo_enters_normal_flow_without_opening_confirmation(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                self.dokan.qq_message_config.qq_message_enable = enabled
                task = ScriptTask.__new__(ScriptTask)
                task.config = SimpleNamespace(model=SimpleNamespace(dokan=self.dokan), config_name='p', save=Mock())
                task.before_run = Mock()
                task.set_next_run = Mock()
                task.goto_page = Mock(side_effect=SystemExit('entered normal dojo flow'))
                with patch('tasks.Dokan.qq_monitor.QQDokanState.flags',
                           side_effect=AssertionError('Dojo execution must not require plugin permission')):
                    with self.assertRaisesRegex(SystemExit, 'entered normal dojo flow'):
                        task.run()
                task.goto_page.assert_called_once_with(dokan_pages.page_dokan_map)
                task.set_next_run.assert_not_called()

    def test_sleep_and_server_update_windows_are_not_interrupted_by_pending_message(self):
        self.task.dokan_qq_monitor.state.flags.return_value = (True, True)
        self.task.dokan_qq_monitor.ready.is_set.return_value = True
        self.task.config.start_watching = Mock()
        self.task.config.should_reload = Mock(return_value=True)
        for update, rest in ((datetime.now()+timedelta(hours=1), None),
                             (None, datetime.now()+timedelta(hours=1))):
            self.task.runtime = SimpleNamespace(server_update_wait_until=update)
            self.task._antiban_wake_time = Mock(return_value=rest)
            with patch('script.time.sleep') as sleep:
                self.assertFalse(self.task.wait_until(datetime.now()+timedelta(hours=1)))
            sleep.assert_called_once_with(1)

    def test_stale_or_consumed_signal_keeps_the_normal_selection_and_queue(self):
        monitor = self.task.dokan_qq_monitor
        monitor.ready.is_set.return_value = True
        pending, waiting = self.task.config.pending_task, self.task.config.waiting_task
        for flags in ((False, False), (True, False)):
            with self.subTest(flags=flags):
                monitor.state.flags.return_value = flags
                self.assertIs(self.task._select_dokan_qq_task(self.other), self.other)
                self.assertIs(self.task.config.pending_task, pending)
                self.assertIs(self.task.config.waiting_task, waiting)
        monitor.ready.clear.assert_called()
        monitor.state.consume.assert_not_called()

    def test_status_cache_failure_does_not_interrupt_normal_tasks_or_waits(self):
        self.scheduler_config(self.other)
        monitor = self.task.dokan_qq_monitor
        monitor.ready.is_set.return_value = True
        monitor.state.flags.side_effect = OSError('status cache unavailable')
        self.task.runtime = SimpleNamespace(server_update_wait_until=None)
        with patch.object(Script, 'device', property(self.forbid_device_access)):
            self.assertIs(self.task._select_dokan_qq_task(self.other), self.other)
            self.assertTrue(self.task.wait_until(datetime.now() - timedelta(seconds=2)))
        monitor.ready.clear.assert_called()
        monitor.state.consume.assert_not_called()

    def test_consuming_trigger_failure_does_not_block_dojo_execution(self):
        monitor = self.task.dokan_qq_monitor
        monitor.state.consume.side_effect = OSError('status cache unavailable')
        self.task._consume_dokan_trigger()
        monitor.state.consume.assert_called_once_with(self.dokan.qq_message_config)
        monitor.ready.clear.assert_called_once()
        monitor.ready.is_set.return_value = True
        self.assertIs(self.task._select_dokan_qq_task(self.other), self.other)
        monitor.state.flags.assert_not_called()

    def test_consumed_trigger_does_not_block_the_next_days_new_opening(self):
        monitor = self.task.dokan_qq_monitor
        monitor.ready.is_set.return_value = True
        monitor.state.flags.return_value = (True, True)
        with patch('script.local_now', return_value=NOW):
            self.task._consume_dokan_trigger()
            self.assertIs(self.task._select_dokan_qq_task(self.other), self.other)
        with patch('script.local_now', return_value=NOW + timedelta(days=1)):
            self.assertEqual(self.task._select_dokan_qq_task(self.other).command, 'Dokan')

    def test_confirmed_trigger_launches_dojo_even_if_recording_its_use_fails(self):
        config = self.scheduler_config(self.other)
        config.script.device = SimpleNamespace(run_background_only=True)
        self.task.resource_precache_enable = False
        self.task.is_first_task = False
        self.task._error_restart_pending = False
        monitor = self.task.dokan_qq_monitor
        monitor.ready.is_set.return_value = True
        monitor.state.flags.return_value = (True, True)
        monitor.state.consume.side_effect = OSError('status cache unavailable')
        self.task.runtime = SimpleNamespace(prepare_task_execution=Mock(return_value=ScriptRuntimeDecision.READY))
        self.task.__dict__['device'] = SimpleNamespace(stuck_record_clear=Mock(), click_record_clear=Mock())
        self.task.run = Mock(side_effect=SystemExit('dojo launched'))
        with patch('script.logger.set_file_logger'), \
                patch('script.RuleScatter.begin_task'), patch('script.RuleScatter.end_task'):
            with self.assertRaisesRegex(SystemExit, 'dojo launched'):
                self.task.loop()
        self.task.runtime.prepare_task_execution.assert_called_once_with('Dokan')
        self.task.run.assert_called_once_with('Dokan')
        monitor.state.consume.assert_called_once_with(self.dokan.qq_message_config)
        monitor.ready.clear.assert_called_once()

    def test_pending_trigger_respects_a_disabled_dojo_task(self):
        self.dokan.scheduler.enable = False
        monitor = self.task.dokan_qq_monitor
        monitor.ready.is_set.return_value = True
        monitor.state.flags.return_value = (True, True)
        self.assertIs(self.task._select_dokan_qq_task(self.other), self.other)
        monitor.state.flags.assert_not_called()
        monitor.state.consume.assert_not_called()

    def test_weekday_restriction_consumes_only_the_trigger_without_rewriting_normal_tasks(self):
        self.dokan.dokan_config.monday_to_thursday = True
        monitor = self.task.dokan_qq_monitor
        monitor.ready.is_set.return_value = True
        monitor.state.flags.return_value = (True, True)
        pending, waiting = self.task.config.pending_task, self.task.config.waiting_task
        weekend = datetime(2026, 10, 24, 21)
        with patch('script.datetime') as clock:
            clock.now.return_value = weekend
            self.assertIs(self.task._select_dokan_qq_task(self.other), self.other)
        self.assertIs(self.task.config.pending_task, pending)
        self.assertIs(self.task.config.waiting_task, waiting)
        monitor.state.consume.assert_called_once_with(self.dokan.qq_message_config)


if __name__ == '__main__':
    unittest.main()
