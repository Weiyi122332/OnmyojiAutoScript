"""NapCat detection, persistence and scheduler arbitration without QQ or game actions."""

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pydantic import ValidationError

from module.config.config_model import ConfigModel
from module.server.config_manager import ConfigManager
from script import Script
from tasks.Dokan.config import Dokan, QQMessageConfig
from tasks.Dokan.qq_monitor import (CHINA_TZ, DokanQQMonitor, QQDokanState,
                                    fetch_group_messages, is_query_time, latest_trigger_message, message_text)
from tasks.Dokan.script_task import ScriptTask
from module.exception import TaskEnd

NOW = datetime(2026, 10, 8, 20, tzinfo=CHINA_TZ)


class QQMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'state.db'
        self.settings = QQMessageConfig(qq_message_enable=True, napcat_api_url='http://127.0.0.1:3000',
                                        napcat_access_token='test-token', qq_group_id='123', qq_member_id='456',
                                        qq_keywords='福利寮已开|可以打了', qq_excluded_keywords='未开启|道馆取消')

    def event(self, text='福利寮已开', **fields):
        result = dict(group_id=123, user_id=456, message_type='group', time=NOW.timestamp(),
                      message_id=1, message=[{'type': 'text', 'data': {'text': text}}])
        result.update(fields)
        return result

    def session(self, *pages):
        session = Mock()
        session.post.side_effect = [Mock(json=Mock(return_value={
            'status': 'ok', 'retcode': 0, 'data': {'messages': page}})) for page in pages]
        return session

    def test_group_sender_day_and_timestamp_filter(self):
        invalid = [dict(group_id=999), dict(user_id=999), dict(message_type='private'),
                   dict(anonymous={'id': 1}), dict(post_type='notice'),
                   dict(time=(NOW - timedelta(days=1)).timestamp()),
                   dict(time=(NOW + timedelta(seconds=1)).timestamp()), dict(time=NOW.timestamp()*1000),
                   dict(time=float('nan')), dict(time=None), dict(time='bad')]
        for fields in invalid:
            self.assertIsNone(latest_trigger_message([self.event(**fields)], self.settings, NOW))
        self.assertTrue(latest_trigger_message([self.event()], self.settings, NOW)[2])

    def test_only_text_segments_and_raw_cq_text_match(self):
        nontext = self.event(message=[{'type': 'image', 'data': {'file': '福利寮已开'}},
                                     {'type': 'reply', 'data': {'id': '福利寮已开'}}])
        self.assertIsNone(latest_trigger_message([nontext], self.settings, NOW))
        self.assertEqual(message_text({'message': '[CQ:reply,id=福利寮已开]普通文字&amp;'}), '普通文字&')
        event = self.event(message=None, raw_message='福利寮已开')
        self.assertTrue(latest_trigger_message([event], self.settings, NOW)[2])
        self.assertTrue(latest_trigger_message([self.event(message='可以打了')], self.settings, NOW)[2])

    def test_beijing_midnight_ignores_last_nights_message_and_accepts_todays_utc_previous_date(self):
        today = NOW.replace(hour=0, minute=5)
        yesterday = self.event(time=(today-timedelta(minutes=6)).timestamp())
        self.assertIsNone(latest_trigger_message([yesterday], self.settings, today))
        current = self.event(time=today.replace(minute=0).timestamp())
        # Beijing midnight is still the previous calendar day in UTC.
        self.assertEqual(datetime.utcfromtimestamp(current['time']).date(), (today-timedelta(days=1)).date())
        self.assertTrue(latest_trigger_message([yesterday, current], self.settings, today)[2])
        session = self.session([yesterday])
        self.assertIsNone(fetch_group_messages(session, self.settings, today))

    def test_cached_opening_expires_at_beijing_midnight_even_before_next_query(self):
        state = QQDokanState('p', self.path)
        yesterday = NOW.replace(hour=23, minute=59, second=59)
        message = self.event(time=yesterday.timestamp())
        state.record(self.settings, latest_trigger_message([message], self.settings, yesterday), yesterday)
        self.assertEqual(state.flags(self.settings, yesterday), (True, True))
        self.assertEqual(state.flags(self.settings, yesterday+timedelta(seconds=1)), (False, False))

    def test_exclusion_and_later_cancellation_override_opening(self):
        open_event = self.event(time=NOW.timestamp()-10)
        cancel = self.event('道馆取消', message_id=2)
        self.assertFalse(latest_trigger_message([cancel, open_event], self.settings, NOW)[2])
        self.assertFalse(latest_trigger_message([self.event('福利寮已开，但未开启')], self.settings, NOW)[2])
        reopen = self.event('可以打了', time=NOW.timestamp(), message_id=3)
        cancel['time'] -= 5
        self.assertTrue(latest_trigger_message([cancel, open_event, reopen], self.settings, NOW)[2])

    def test_history_auth_pagination_bounded_and_no_redirect(self):
        ordinary = self.event('普通消息', time=NOW.timestamp()-10, message_id=22)
        session = self.session([ordinary], [self.event(time=NOW.timestamp()-20)])
        self.assertTrue(fetch_group_messages(session, self.settings, NOW)[2])
        first, second = session.post.call_args_list
        self.assertEqual(first.args[0], 'http://127.0.0.1:3000/get_group_msg_history')
        self.assertEqual(second.kwargs['json']['message_seq'], '22')
        self.assertEqual(first.kwargs['headers'], {'Authorization': 'Bearer test-token'})
        self.assertFalse(first.kwargs['allow_redirects'])
        self.assertEqual(first.kwargs['timeout'], (3, 8))
        self.settings.qq_history_max_pages = 1
        session = self.session([ordinary])
        self.assertIsNone(fetch_group_messages(session, self.settings, NOW))
        self.assertEqual(session.post.call_count, 1)

    def test_history_uses_latest_cancellation_and_stops_at_previous_day_or_repeated_cursor(self):
        session = self.session([self.event('道馆取消'), self.event(time=NOW.timestamp()-10)])
        self.assertFalse(fetch_group_messages(session, self.settings, NOW)[2])
        ordinary = self.event('普通消息')
        session = self.session([ordinary], [ordinary])
        self.assertIsNone(fetch_group_messages(session, self.settings, NOW))
        self.assertEqual(session.post.call_count, 2)
        session = self.session([self.event(time=(NOW-timedelta(days=1)).timestamp())])
        self.assertIsNone(fetch_group_messages(session, self.settings, NOW))
        self.assertEqual(session.post.call_count, 1)

    def test_invalid_http_response_does_not_grant_permission(self):
        for body in ({'status': 'failed', 'retcode': 1}, {'status': 'ok', 'retcode': 0, 'data': None}, []):
            session = Mock()
            session.post.return_value.json.return_value = body
            with self.assertRaises(ValueError):
                fetch_group_messages(session, self.settings, NOW)
        for url in ('file:///tmp', 'http://user:secret@localhost:3000', 'http://localhost:3000/?token=secret'):
            self.settings.napcat_api_url = url
            with self.assertRaises(ValueError):
                fetch_group_messages(Mock(), self.settings, NOW)

    def test_missing_fields_never_call_api(self):
        for field in ('qq_group_id', 'qq_member_id', 'qq_keywords'):
            settings = self.settings.model_copy(update={field: ''})
            session = Mock()
            with self.assertRaises(ValueError):
                fetch_group_messages(session, settings, NOW)
            session.post.assert_not_called()

    def test_state_persists_once_per_day_and_profiles_and_config_are_isolated(self):
        state = QQDokanState('大号', self.path)
        state.record(self.settings, latest_trigger_message([self.event()], self.settings, NOW), NOW)
        self.assertEqual(state.flags(self.settings, NOW), (True, True))
        state.consume(self.settings, NOW)
        self.assertEqual(QQDokanState('大号', self.path).flags(self.settings, NOW), (True, False))
        state.record(self.settings, latest_trigger_message([self.event(message_id=2)], self.settings, NOW), NOW)
        self.assertEqual(state.flags(self.settings, NOW), (True, False))
        self.assertEqual(state.flags(self.settings, NOW+timedelta(days=1)), (False, False))
        self.assertEqual(QQDokanState('小号', self.path).flags(self.settings, NOW), (False, False))
        self.assertEqual(state.flags(self.settings.model_copy(update={'qq_member_id':'999'}), NOW), (False, False))
        self.assertNotIn('test-token', self.path.read_bytes().decode('latin-1'))

    def test_latest_cancellation_in_first_query_blocks_trigger(self):
        monitor = DokanQQMonitor('p', self.path)
        monitor.poll_once(self.session([self.event(time=NOW.timestamp()-1), self.event('道馆取消')]),
                          self.settings, now=NOW)
        self.assertEqual(monitor.state.flags(self.settings, NOW), (False, False))
        self.assertFalse(monitor.ready.is_set())

    def test_disabled_monitor_performs_no_network_or_state_writes(self):
        monitor = DokanQQMonitor('p', self.path)
        session = Mock()
        disabled = self.settings.model_copy(update={'qq_message_enable': False})
        monitor.poll_once(session, disabled, now=NOW)
        monitor.poll_once(session, self.settings, task_enabled=False, now=NOW)
        session.post.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_default_query_window_and_cross_midnight_settings(self):
        for hour, minute, expected in ((19, 59, False), (20, 0, True), (21, 59, True), (22, 0, False)):
            self.assertEqual(is_query_time(self.settings, NOW.replace(hour=hour, minute=minute)), expected)
        self.settings.qq_query_start_time = clock_time(22)
        self.settings.qq_query_end_time = clock_time(2)
        for hour, expected in ((21, False), (22, True), (0, True), (1, True), (2, False)):
            self.assertEqual(is_query_time(self.settings, NOW.replace(hour=hour)), expected)

    def test_outside_query_window_never_calls_api_but_keeps_previously_matched_trigger(self):
        monitor = DokanQQMonitor('p', self.path)
        session = Mock()
        monitor.poll_once(session, self.settings, now=NOW.replace(hour=19, minute=59))
        fetch_group_messages(session, self.settings, NOW.replace(hour=22))
        session.post.assert_not_called()
        self.assertFalse(self.path.exists())
        monitor.poll_once(self.session([self.event()]), self.settings, now=NOW)
        monitor.poll_once(session, self.settings, now=NOW.replace(hour=22))
        session.post.assert_not_called()
        self.assertTrue(monitor.ready.is_set())

    def test_pagination_does_not_issue_another_request_after_query_window_ends(self):
        clock = [0.0]
        session, response = Mock(), Mock()
        response.json.return_value = {'status': 'ok', 'retcode': 0, 'data': {'messages': [self.event('普通消息')]}}

        def respond(*args, **kwargs):
            clock[0] = 2.0
            return response

        session.post.side_effect = respond
        with patch('tasks.Dokan.qq_monitor.time.monotonic', side_effect=lambda: clock[0]):
            self.assertIsNone(fetch_group_messages(session, self.settings, NOW.replace(hour=21, minute=59, second=59)))
        self.assertEqual(session.post.call_count, 1)

    def test_matching_stops_all_queries_until_next_day_even_after_restart(self):
        monitor = DokanQQMonitor('p', self.path)
        monitor.poll_once(self.session([self.event()]), self.settings, now=NOW)
        idle_session = Mock()
        monitor.poll_once(idle_session, self.settings, now=NOW+timedelta(minutes=1))
        restarted = DokanQQMonitor('p', self.path)
        restarted.poll_once(idle_session, self.settings, now=NOW+timedelta(minutes=2))
        idle_session.post.assert_not_called()
        self.assertTrue(restarted.ready.is_set())
        tomorrow = NOW+timedelta(days=1)
        fresh_session = self.session([self.event(time=tomorrow.timestamp())])
        restarted.poll_once(fresh_session, self.settings, now=tomorrow)
        self.assertEqual(fresh_session.post.call_count, 1)
        self.assertTrue(restarted.ready.is_set())

    def test_poll_signal_consume_and_failure_do_not_start_game(self):
        monitor = DokanQQMonitor('p', self.path)
        monitor.poll_once(self.session([self.event()]), self.settings, now=NOW)
        self.assertTrue(monitor.ready.is_set())
        monitor.state.consume(self.settings, NOW)
        monitor.poll_once(self.session([self.event()]), self.settings, now=NOW)
        self.assertFalse(monitor.ready.is_set())
        session = Mock()
        session.post.side_effect = TimeoutError()
        monitor.poll_once(session, self.settings, now=NOW)
        session.post.assert_not_called()
        self.assertEqual(monitor.state.flags(self.settings, NOW), (True, False))
        with self.assertRaises(TimeoutError):
            monitor.poll_once(session, self.settings, now=NOW+timedelta(days=1))

    def test_ui_custom_interval_defaults_and_export_redaction(self):
        model = ConfigModel()
        fields = {item['name']: item for item in model.script_task('Dokan')['qq_message_config']}
        self.assertFalse(fields['qq_message_enable']['value'])
        self.assertEqual(fields['qq_keywords']['type'], 'multi_line')
        self.assertEqual(fields['qq_query_start_time']['type'], 'time')
        self.assertEqual(fields['qq_query_start_time']['value'], '20:00:00')
        self.assertEqual(fields['qq_query_end_time']['value'], '22:00:00')
        self.assertEqual(fields['qq_poll_interval']['value'], 60)
        self.assertEqual(QQMessageConfig(qq_poll_interval=37).qq_poll_interval, 37)
        for interval in (0, 86401):
            with self.assertRaises(ValidationError):
                QQMessageConfig(qq_poll_interval=interval)
        data = {'dokan': {'qq_message_config': self.settings.model_dump()}}
        redacted = ConfigManager.redact_config(data)['dokan']['qq_message_config']
        for name in ('napcat_access_token', 'qq_group_id', 'qq_member_id'):
            self.assertEqual(redacted[name], 'XXX')
        self.assertEqual(data['dokan']['qq_message_config']['napcat_access_token'], 'test-token')

    def test_worker_queries_real_http_endpoint_and_signals_without_game_access(self):
        calls = []
        event = self.event(time=datetime.now(CHINA_TZ).timestamp()-1)

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                calls.append((self.path, self.headers.get('Authorization'),
                              json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                body = json.dumps({'status': 'ok', 'retcode': 0, 'data': {'messages': [event]}}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
        thread.start()
        monitor = DokanQQMonitor('p', self.path)
        self.settings.napcat_api_url = f'http://127.0.0.1:{server.server_port}'
        self.settings.qq_query_start_time = self.settings.qq_query_end_time = clock_time(0)
        monitor._load_settings = Mock(return_value=(self.settings, True))
        try:
            monitor.start()
            self.assertTrue(monitor.ready.wait(timeout=3))
            self.assertEqual(calls[0][0], '/get_group_msg_history')
            self.assertEqual(calls[0][1], 'Bearer test-token')
            self.assertEqual(calls[0][2]['group_id'], '123')
            self.assertEqual(len(calls), 1)
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
        self.task.dokan_qq_monitor = SimpleNamespace(state=Mock(), ready=Mock())

    def test_match_prioritizes_dojo_only_at_next_selection(self):
        self.task.dokan_qq_monitor.state.flags.return_value = (True, True)
        result = self.task._select_dokan_qq_task(self.other)
        self.assertEqual(result.command, 'Dokan')
        self.assertLessEqual(result.next_run, datetime.now())
        self.assertEqual([item.command for item in self.task.config.pending_task], ['Dokan', 'RyouToppa'])
        self.task.dokan_qq_monitor.state.consume.assert_not_called()

    def test_waiting_for_message_preserves_other_tasks_and_waits_when_dojo_is_only_task(self):
        self.task.dokan_qq_monitor.state.flags.return_value = (False, False)
        self.assertIs(self.task._select_dokan_qq_task(self.dokan_task), self.other)
        self.task.config.pending_task = []
        self.task.config.waiting_task = [self.dokan_task]
        result = self.task._select_dokan_qq_task(self.dokan_task)
        self.assertGreater(result.next_run, datetime.now())

    def test_disabled_feature_and_regular_retries_keep_original_selection(self):
        self.dokan.qq_message_config.qq_message_enable = False
        self.assertIs(self.task._select_dokan_qq_task(self.other), self.other)
        self.task.dokan_qq_monitor.state.flags.assert_not_called()
        self.dokan.qq_message_config.qq_message_enable = True
        self.task.dokan_qq_monitor.state.flags.return_value = (True, False)
        self.assertIs(self.task._select_dokan_qq_task(self.other), self.other)

    def test_restart_remains_first_and_no_trigger_after_daily_attempts_exhausted(self):
        self.task.dokan_qq_monitor.state.flags.return_value = (True, True)
        restart = SimpleNamespace(command='Restart', next_run=datetime.now()-timedelta(seconds=1))
        self.assertIs(self.task._select_dokan_qq_task(restart), restart)
        self.dokan.attack_count_config.attack_date = datetime.now().strftime('%Y-%m-%d')
        self.dokan.attack_count_config.remain_attack_count = 0
        self.assertIs(self.task._select_dokan_qq_task(self.other), self.other)
        self.task.dokan_qq_monitor.state.consume.assert_called_once()

    def test_idle_wait_wakes_immediately_for_message_without_device_actions(self):
        self.task.dokan_qq_monitor.state.flags.return_value = (True, True)
        self.task.dokan_qq_monitor.ready.is_set.return_value = True
        self.task.config.start_watching = Mock()
        self.task.runtime = SimpleNamespace(server_update_wait_until=None)
        self.task._antiban_wake_time = Mock(return_value=None)
        with patch('script.time.sleep') as sleep:
            self.assertFalse(self.task.wait_until(datetime.now()+timedelta(hours=1)))
        sleep.assert_not_called()

    def test_manual_dojo_without_permission_ends_before_game_navigation(self):
        task = ScriptTask.__new__(ScriptTask)
        task.config = SimpleNamespace(model=SimpleNamespace(dokan=self.dokan), config_name='p')
        task.before_run = Mock()
        task.set_next_run = Mock()
        task.goto_page = Mock()
        with patch('tasks.Dokan.script_task.QQDokanState') as state:
            state.return_value.flags.return_value = (False, False)
            with self.assertRaises(TaskEnd):
                task.run()
        task.goto_page.assert_not_called()
        task.set_next_run.assert_called_once()

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


if __name__ == '__main__':
    unittest.main()
