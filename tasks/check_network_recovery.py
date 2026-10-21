import ast
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from tasks.base_task import BaseTask
from tasks.GlobalGame.config_emergency import Emergency
from module.exception import NetworkRecoveryRequired

class NetworkTests(unittest.TestCase):
    def task(self, frames, policy='wait_5s'):
        t = object.__new__(BaseTask)
        t.device = Mock()
        t.config = SimpleNamespace(global_game=SimpleNamespace(emergency=Emergency(when_network_abnormal=policy)))
        state = iter(frames)
        current = [next(state)]
        t.device.screenshot.side_effect = lambda: current.__setitem__(0, next(state))
        t.appear = lambda asset: current[0] == ('error' if asset is t.I_NETWORK_ERROR else 'abnormal')
        return t

    def test_old_config(self):
        self.assertEqual(Emergency(when_network_abnormal='wait_10s').when_network_abnormal, 'wait_5s')

    def test_disappears(self):
        t = self.task(['abnormal', 'clear'])
        t._handle_network()
        t.device.screenshot.assert_called_once()

    def test_changes_to_disconnect(self):
        t = self.task(['abnormal', 'error'])
        with self.assertRaises(NetworkRecoveryRequired) as caught:
            t._handle_network()
        self.assertTrue(caught.exception.reconnect)

    def test_timeout(self):
        t = self.task(['abnormal'])
        with patch('tasks.base_task.monotonic', side_effect=[0, 5]):
            with self.assertRaises(NetworkRecoveryRequired) as caught:
                t._handle_network()
        self.assertFalse(caught.exception.reconnect)

    def test_restart_immediate(self):
        t = self.task(['abnormal'], 'restart')
        with self.assertRaises(NetworkRecoveryRequired):
            t._handle_network()
        t.device.sleep.assert_not_called()
        t.device.screenshot.assert_not_called()

    def test_disconnect_priority(self):
        t = self.task(['error'], 'restart')
        with self.assertRaises(NetworkRecoveryRequired) as caught:
            t._handle_network()
        self.assertTrue(caught.exception.reconnect)

    def test_reconnect_clicks_then_logs_in(self):
        import sys
        import time
        from tasks.Component.Login.service import LoginService
        from tasks.Restart.assets import RestartAssets
        tree = ast.parse(Path('script.py').read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Script')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_handle_task_exception')
        env = {'NetworkRecoveryRequired': NetworkRecoveryRequired, 'time': time}
        exec(compile(ast.Module(body=[method], type_ignores=[]), 'script.py', 'exec'), env)
        runner = Mock()
        login = Mock()
        login.appear.side_effect = [False, True]
        with patch('tasks.Component.Login.service.LoginService', return_value=login):
            env['_handle_task_exception'](runner, NetworkRecoveryRequired(reconnect=True), 'WantedQuests')
        login.appear_then_click.assert_called_once_with(login.I_CLIENT_CLEAR, interval=1)
        login.app_handle_login.assert_called_once()
        runner._request_error_restart.assert_not_called()
        runner.config.task_call.assert_called_once_with('WantedQuests')

    def test_scheduler_restart_has_no_delay(self):
        tree = ast.parse(Path('script.py').read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Script')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_handle_task_exception')
        env = {'NetworkRecoveryRequired': NetworkRecoveryRequired}
        exec(compile(ast.Module(body=[method], type_ignores=[]), 'script.py', 'exec'), env)
        runner = Mock()
        env['_handle_task_exception'](runner, NetworkRecoveryRequired(), 'WantedQuests')
        runner._request_error_restart.assert_called_once_with('WantedQuests')
        runner.config.task_call.assert_called_once_with('WantedQuests')
        runner.device.sleep.assert_not_called()

if __name__ == '__main__':
    unittest.main()
