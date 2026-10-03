"""Task notification settings route messages independently of global channels."""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.config.config_model import ConfigModel
from module.notify.task_notify import resolve_task_notifier
from module.server.config_manager import ConfigManager
from tasks.Component.config_notify import TaskNotifyConfig
from tasks.Dokan.config import Dokan
from tasks.Dokan.script_task import ScriptTask as DokanTask
from tasks.FrogBoss.config import FrogBoss
from tasks.FrogBoss.frog_bet import RunReport
from tasks.FrogBoss.script_task import ScriptTask as FrogBossTask


def channel(user_id):
    return f'provider: gocqhttp\nendpoint: http://127.0.0.1:5700\nuser_id: {user_id}\naccess_token: test-token'


class TaskNotificationConfigTests(unittest.TestCase):
    def test_both_pages_expose_independent_switch_and_multiline_configuration(self):
        model = ConfigModel()
        for name in ('Dokan', 'FrogBoss'):
            with self.subTest(task=name):
                fields = {item['name']: item for item in model.script_task(name)['notification_config']}
                self.assertEqual(fields['task_notify_enable']['type'], 'boolean')
                self.assertTrue(fields['task_notify_enable']['value'])
                self.assertEqual(fields['task_notify_config']['type'], 'multi_line')
                self.assertEqual(fields['task_notify_config']['value'], '')
        model.dokan.notification_config.task_notify_config = channel(111)
        self.assertEqual(model.frog_boss.notification_config.task_notify_config, '')
        restored = ConfigModel.model_validate_json(model.model_dump_json())
        self.assertEqual(restored.dokan.notification_config.task_notify_config, channel(111))

    def test_existing_configs_and_template_keep_global_notification_behavior(self):
        template = json.loads((Path(__file__).resolve().parents[1] / 'config/template.json').read_text('utf-8'))
        for name in ('dokan', 'frog_boss'):
            self.assertEqual(template[name]['notification_config'], TaskNotifyConfig().model_dump())
            template[name].pop('notification_config')
        restored = ConfigModel.model_validate(template)
        self.assertEqual(restored.dokan.notification_config, TaskNotifyConfig())
        self.assertEqual(restored.frog_boss.notification_config, TaskNotifyConfig())
        self.assertNotIn('notification_config', restored.ryou_toppa.model_dump())

    def test_export_redacts_both_task_channels_without_changing_settings(self):
        original = {
            name: {'notification_config': {'task_notify_enable': True, 'task_notify_config': channel(user_id)}}
            for name, user_id in [('dokan', 111), ('frog_boss', 222)]
        }
        redacted = ConfigManager.redact_config(original)
        for name in original:
            self.assertEqual(redacted[name]['notification_config']['task_notify_config'], 'XXX')
            self.assertTrue(redacted[name]['notification_config']['task_notify_enable'])
            self.assertIn('test-token', original[name]['notification_config']['task_notify_config'])


class TaskNotificationRoutingTests(unittest.TestCase):
    def setUp(self):
        self.global_notifier = SimpleNamespace(enable=True, push=Mock(), push_images=Mock(), push_image=Mock())
        self.config = SimpleNamespace(config_name='oas_test', notifier=self.global_notifier)

    def test_blank_configuration_inherits_global_switch_and_channel(self):
        for enabled in (False, True):
            self.global_notifier.enable = enabled
            for settings in (None, TaskNotifyConfig(), TaskNotifyConfig(task_notify_config=' \n ')):
                with self.subTest(enabled=enabled, settings=settings):
                    self.assertIs(resolve_task_notifier(self.config, settings), self.global_notifier)

    def test_task_switch_disables_push_even_when_global_push_is_enabled(self):
        for configured in ('', channel(111)):
            notifier = resolve_task_notifier(
                self.config, TaskNotifyConfig(task_notify_enable=False, task_notify_config=configured))
            self.assertFalse(notifier.enable)
            self.assertFalse(notifier.push(title='disabled'))
            self.global_notifier.push.assert_not_called()

    def test_custom_channels_work_with_global_switch_off_and_do_not_share_targets(self):
        self.global_notifier.enable = False
        response = Mock()
        response.json.return_value = {'status': 'ok'}
        with patch('module.notify.notify.requests.post', return_value=response) as post:
            for recipient in (111, 222):
                notifier = resolve_task_notifier(self.config, TaskNotifyConfig(task_notify_config=channel(recipient)))
                self.assertTrue(notifier.enable)
                self.assertTrue(notifier.push_images([b'png'], title='test'))
                self.assertEqual(post.call_args.kwargs['json']['user_id'], recipient)
                self.assertEqual(post.call_args.kwargs['headers'], {'Authorization': 'Bearer test-token'})
            self.assertEqual(post.call_count, 2)
        self.global_notifier.push_images.assert_not_called()
        self.assertFalse(self.global_notifier.enable)

    def test_invalid_custom_channel_never_falls_back_to_global_target(self):
        for yaml_config in ('provider: [', 'provider: null', 'provider: no-such-provider'):
            with self.subTest(config=yaml_config):
                notifier = resolve_task_notifier(self.config, TaskNotifyConfig(task_notify_config=yaml_config))
                self.assertFalse(notifier.enable)
                self.assertIsNot(notifier, self.global_notifier)

    def test_dojo_reward_uses_task_channel_and_deletes_only_successfully_sent_images(self):
        self.global_notifier.enable = False
        task = DokanTask.__new__(DokanTask)
        task.config = self.config
        task.conf = Dokan(notification_config=TaskNotifyConfig(task_notify_config=channel(111)))
        response = Mock()
        response.json.return_value = {'status': 'ok'}
        with tempfile.TemporaryDirectory() as directory:
            task._dokan_reward_run_directory = Path(directory) / 'run'
            task._dokan_reward_run_directory.mkdir()
            screenshot = task._dokan_reward_run_directory / 'reward.png'
            screenshot.write_bytes(b'png')
            with patch('tasks.Dokan.script_task.count_blue_tickets_in_png', return_value=3), \
                    patch('module.notify.notify.requests.post', return_value=response) as post:
                task._push_current_run_reward_images()
            payload = post.call_args.kwargs['json']
            self.assertEqual(payload['user_id'], 111)
            self.assertIn('蓝票合计：3 张', payload['message'][0]['data']['text'])
            self.assertFalse(screenshot.exists())
        self.global_notifier.push_images.assert_not_called()

    def test_disabled_dojo_notification_keeps_screenshots_and_skips_refresh_alert(self):
        task = DokanTask.__new__(DokanTask)
        task.config = self.config
        task.conf = Dokan(notification_config=TaskNotifyConfig(task_notify_enable=False))
        with tempfile.TemporaryDirectory() as directory:
            task._dokan_reward_run_directory = Path(directory)
            screenshot = Path(directory) / 'reward.png'
            screenshot.write_bytes(b'png')
            with patch('tasks.Dokan.script_task.count_blue_tickets_in_png', return_value=0):
                task._push_current_run_reward_images()
                task._push_dokan_refresh_limit_notification()
            self.assertTrue(screenshot.exists())
        self.global_notifier.push.assert_not_called()
        self.global_notifier.push_images.assert_not_called()

    def test_dojo_refresh_alert_uses_same_independent_channel_as_rewards(self):
        self.global_notifier.enable = False
        task = DokanTask.__new__(DokanTask)
        task.config = self.config
        task.conf = Dokan(notification_config=TaskNotifyConfig(task_notify_config=channel(111)))
        with patch('module.notify.notify.Notifier.push', autospec=True, return_value=True) as push:
            task._push_dokan_refresh_limit_notification()
        self.assertEqual(push.call_args.args[0].config['user_id'], 111)
        self.assertEqual(push.call_args.kwargs['title'], '道馆达到最大刷新次数')
        self.global_notifier.push.assert_not_called()

    def test_frog_summary_uses_its_own_channel_with_global_switch_off(self):
        self.global_notifier.enable = False
        task = FrogBossTask.__new__(FrogBossTask)
        self.config.model = SimpleNamespace(
            frog_boss=FrogBoss(notification_config=TaskNotifyConfig(task_notify_config=channel(222))))
        task.config = self.config
        task.run_report = RunReport('frog_majority', datetime(2026, 10, 3, 18))
        task.run_report.screenshot = b'png'
        response = Mock()
        response.json.return_value = {'status': 'ok'}
        with patch('module.notify.notify.requests.post', return_value=response) as post:
            task.push_run_report()
        self.assertEqual(post.call_args.kwargs['json']['user_id'], 222)
        self.assertIn('对弈竞猜运行结果', post.call_args.kwargs['json']['message'][0]['data']['text'])
        self.global_notifier.push_image.assert_not_called()
        self.global_notifier.push.assert_not_called()

    def test_frog_task_switch_suppresses_result_without_disabling_global_push(self):
        task = FrogBossTask.__new__(FrogBossTask)
        self.config.model = SimpleNamespace(
            frog_boss=FrogBoss(notification_config=TaskNotifyConfig(task_notify_enable=False)))
        task.config = self.config
        task.push_run_report()
        self.assertTrue(self.global_notifier.enable)
        self.global_notifier.push.assert_not_called()
        self.global_notifier.push_image.assert_not_called()


if __name__ == '__main__':
    unittest.main()
