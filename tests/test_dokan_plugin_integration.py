"""Load the plugin entry and query its HTTP status from the Python monitor."""

import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path

import requests

from tasks.Dokan.config import QQMessageConfig
from tasks.Dokan.qq_monitor import CHINA_TZ, DokanQQMonitor


@unittest.skipUnless(shutil.which('node'), 'Node.js is required for the plugin integration test')
class PluginIntegrationTests(unittest.TestCase):
    def test_plugin_event_status_authentication_and_oas_daily_trigger(self):
        with tempfile.TemporaryDirectory() as directory:
            config = dict(group_id='123', member_id='456', api_token='test-token',
                          keywords='福利寮已开', excluded_keywords='未开启')
            Path(directory, 'plugin.json').write_text(json.dumps(config), 'utf-8')
            fixture = Path(__file__).resolve().parents[1] / 'plugins/trss-welfare-dojo/tests/framework-fixture.mjs'
            process = subprocess.Popen([shutil.which('node'), str(fixture), directory],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                addresses = json.loads(process.stdout.readline())
                port = addresses['port']
                base = f'http://127.0.0.1:{port}'
                event_base = f"http://127.0.0.1:{addresses['event_port']}"
                settings = QQMessageConfig(qq_message_enable=True,
                    welfare_plugin_url=base + '/welfare-dojo/today',
                    welfare_plugin_token='test-token',
                    qq_query_start_time=clock_time(0), qq_query_end_time=clock_time(0))
                monitor = DokanQQMonitor('p', Path(directory, 'oas.db'))
                now = datetime.now(CHINA_TZ)
                with requests.Session() as session:
                    session.trust_env = False
                    self.assertEqual(session.get(settings.welfare_plugin_url, timeout=3).status_code, 401)
                    monitor.poll_once(session, settings, now=now)
                    self.assertFalse(monitor.ready.is_set())
                    message = dict(post_type='message', message_type='group', group_id=123, user_id=456,
                                   self_id=789, time=int(now.timestamp()), message_id=1,
                                   message=[{'type': 'text', 'text': '福利寮已开'}])
                    for invalid in (dict(user_id=999), dict(time=int((now-timedelta(days=1)).timestamp()))):
                        session.post(event_base + '/event', json={**message, **invalid}, timeout=3).raise_for_status()
                        monitor.poll_once(session, settings, now=now)
                        self.assertFalse(monitor.ready.is_set())
                    session.post(event_base + '/event', json=message, timeout=3).raise_for_status()
                    response = session.get(settings.welfare_plugin_url,
                        headers={'Authorization': 'Bearer test-token'}, timeout=3)
                    self.assertEqual(response.json(), {'date': now.date().isoformat(), 'opened': True})
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')
                    monitor.poll_once(session, settings, now=now)
                    self.assertTrue(monitor.ready.is_set())
                    monitor.state.consume(settings, now)
                    restarted = DokanQQMonitor('p', Path(directory, 'oas.db'))
                    self.assertEqual(restarted.state.flags(settings, now), (True, False))
            finally:
                process.terminate()
                process.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()
