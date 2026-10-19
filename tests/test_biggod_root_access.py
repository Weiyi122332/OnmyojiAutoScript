"""大神签到的 su 超时仍应尝试 adb root，无法获取权限时正常返回失败。"""

import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tasks.AutoCheckinBigGod.script_task import ScriptTask


class BigGodRootAccessTest(unittest.TestCase):
    def setUp(self):
        for name in ('logger', 'time.sleep'):
            patcher = patch('tasks.AutoCheckinBigGod.script_task.' + name)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.task = ScriptTask.__new__(ScriptTask)
        self.task._frida_root_mode = None
        self.task._adb_shell = Mock()
        self.task._adb_cmd_result = Mock(return_value=SimpleNamespace(
            stdout='restarting adbd as root', stderr='', returncode=0,
        ))

    def test_existing_adb_root_does_not_probe_su(self):
        self.task._adb_shell.return_value = 'uid=0(root)'
        self.assertEqual(self.task._ensure_root_access(), 'adb')
        self.task._adb_shell.assert_called_once_with(['id'])
        self.task._adb_cmd_result.assert_not_called()

    def test_working_su_does_not_restart_adb(self):
        self.task._adb_shell.side_effect = ['uid=2000(shell)', 'uid=0(root)']
        self.assertEqual(self.task._ensure_root_access(), 'su')
        self.task._adb_shell.assert_called_with(['su', '-c', 'id'])
        self.task._adb_cmd_result.assert_not_called()

    def test_su_timeout_or_execution_error_falls_back_to_adb_root(self):
        for error in (subprocess.TimeoutExpired(['su', '-c', 'id'], 15), OSError('su unavailable')):
            with self.subTest(error=type(error).__name__):
                self.task._frida_root_mode = None
                self.task._adb_shell.reset_mock()
                self.task._adb_cmd_result.reset_mock()
                self.task._adb_shell.side_effect = ['uid=2000(shell)', error, 'uid=0(root)']
                self.assertEqual(self.task._ensure_root_access(), 'adb')
                self.task._adb_cmd_result.assert_called_once_with(['root'], timeout=10)
                calls = self.task._adb_shell.call_count
                self.assertEqual(self.task._ensure_root_access(), 'adb')
                self.assertEqual(self.task._adb_shell.call_count, calls)

    def test_no_available_root_returns_failure_instead_of_raising(self):
        def shell(command, **kwargs):
            if command[0] == 'su':
                raise subprocess.TimeoutExpired(command, 15)
            return 'uid=2000(shell)'

        self.task._adb_shell.side_effect = shell
        self.task._adb_cmd_result.return_value = SimpleNamespace(
            stdout='', stderr='adbd cannot run as root in production builds', returncode=1,
        )
        self.assertIsNone(self.task._ensure_root_access())
        self.assertIsNone(self.task._frida_root_mode)
        self.task._adb_cmd_result.assert_called_once_with(['root'], timeout=10)

    def test_root_commands_use_the_selected_su_or_adb_method(self):
        for mode, command in (('su', ['su', '-c', 'id']), ('adb', ['id'])):
            with self.subTest(mode=mode):
                self.task._frida_root_mode = mode
                self.task._adb_shell.reset_mock()
                self.task._adb_shell.return_value = 'uid=0(root)'
                self.assertEqual(self.task._adb_root_shell('id', timeout=7), 'uid=0(root)')
                self.task._adb_shell.assert_called_once_with(command, timeout=7)
                self.task._adb_cmd_result.assert_not_called()


if __name__ == '__main__':
    unittest.main()
