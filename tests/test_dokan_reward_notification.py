"""Dokan rewards are captured during battle and sent when that task run ends."""

import base64
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.config.config_model import ConfigModel
from module.exception import TaskEnd
from module.notify.notify import Notifier
from tasks.Component.GeneralBattle.general_battle import BattleAction, GeneralBattle
from tasks.Dokan.config import DokanConfig
from tasks.Dokan.script_task import DokanFinishedError, DokanNotStartedError, ScriptTask


class DokanRewardNotificationTest(unittest.TestCase):
    def setUp(self):
        ready = patch.object(ScriptTask, '_wait_for_dokan_reward_ready', return_value=True)
        self.wait_for_reward = ready.start()
        self.addCleanup(ready.stop)

    def test_dokan_config_exposes_reward_push_checkbox(self):
        field = next(item for item in ConfigModel().script_task('Dokan')['dokan_config']
                     if item['name'] == 'push_reward_images')
        self.assertEqual(field['type'], 'boolean')
        self.assertTrue(field['value'])
        self.assertTrue(DokanConfig().push_reward_images)

    def test_reward_is_captured_once_before_it_is_closed(self):
        task = ScriptTask.__new__(ScriptTask)
        task.appear = Mock(side_effect=lambda marker: marker is task.I_RYOU_DOKAN_BATTLE_OVER)
        task._save_reward_image = Mock()
        context = SimpleNamespace(battle_key='dokan_member', continuous_count=1)
        order = []
        self.wait_for_reward.side_effect = lambda: order.append('ready') or True
        task._save_reward_image.side_effect = lambda _: order.append('capture')

        with patch.object(GeneralBattle, '_handle_reward', side_effect=lambda *_: order.append('close')):
            task._handle_reward(context, None)
            task._handle_reward(context, None)
            context.continuous_count = 2
            task._handle_reward(context, None)

        self.assertEqual(order, ['ready', 'capture', 'close', 'close', 'ready', 'capture', 'close'])
        self.assertEqual(task._save_reward_image.call_count, 2)

    def test_interrupted_reward_wait_does_not_capture_mark_or_close_the_page(self):
        task = ScriptTask.__new__(ScriptTask)
        task.appear = Mock(side_effect=lambda marker: marker is task.I_RYOU_DOKAN_BATTLE_OVER)
        task._save_reward_image = Mock()
        context = SimpleNamespace(battle_key='dokan_member', continuous_count=1)
        self.wait_for_reward.return_value = False
        with patch.object(GeneralBattle, '_handle_reward', return_value=BattleAction.CONTINUE) as close:
            self.assertEqual(task._handle_reward(context, None), BattleAction.CONTINUE)
            task._save_reward_image.assert_not_called()
            self.assertFalse(getattr(task, '_dokan_reward_captured_outside_battle', False))
            close.assert_not_called()
            self.wait_for_reward.return_value = True
            task._handle_reward(context, None)
            task._save_reward_image.assert_called_once_with(context)
            close.assert_called_once()

    def test_other_reward_pages_do_not_trigger_dokan_capture(self):
        task = ScriptTask.__new__(ScriptTask)
        task.appear = Mock(return_value=False)
        task._save_reward_image = Mock()
        context = SimpleNamespace(battle_key='dokan_member', continuous_count=1)
        with patch.object(GeneralBattle, '_handle_reward', return_value=BattleAction.CONTINUE) as close:
            task._handle_reward(context, None)
        task._save_reward_image.assert_not_called()
        close.assert_called_once()

    def test_settlement_reward_outside_battle_is_captured_once_per_screen(self):
        task = ScriptTask.__new__(ScriptTask)
        visible = [True]
        task.appear = Mock(side_effect=lambda marker: visible[0] and marker is task.I_RYOU_DOKAN_BATTLE_OVER)
        task._save_reward_image = Mock()

        task._capture_dokan_reward_if_visible()
        task._capture_dokan_reward_if_visible()
        self.assertEqual(task._save_reward_image.call_count, 1)
        task._save_reward_image.assert_called_with(None)

        visible[0] = False
        task._capture_dokan_reward_if_visible()
        visible[0] = True
        task._capture_dokan_reward_if_visible()
        self.assertEqual(task._save_reward_image.call_count, 2)

    def test_battle_reward_is_not_saved_again_by_outer_dokan_loop(self):
        task = ScriptTask.__new__(ScriptTask)
        task.appear = Mock(side_effect=lambda marker: marker is task.I_RYOU_DOKAN_BATTLE_OVER)
        task._save_reward_image = Mock()
        context = SimpleNamespace(battle_key='dokan_member', continuous_count=1)

        task._capture_dokan_reward_if_visible(context)
        task._capture_dokan_reward_if_visible()

        task._save_reward_image.assert_called_once_with(context)

    def test_reward_title_image_remains_a_fallback(self):
        task = ScriptTask.__new__(ScriptTask)
        task.appear = Mock(side_effect=lambda marker: marker is task.I_UI_REWARD)
        task._save_reward_image = Mock()

        task._capture_dokan_reward_if_visible()

        task._save_reward_image.assert_called_once_with(None)

    def test_reward_details_overlay_is_not_captured(self):
        task = ScriptTask.__new__(ScriptTask)
        task.appear = Mock(side_effect=lambda marker: marker in (
            task.I_RYOU_DOKAN_BATTLE_OVER, task.I_REWARD_PARTICULARS))
        task._save_reward_image = Mock()

        task._capture_dokan_reward_if_visible()

        task._save_reward_image.assert_not_called()

    def test_two_settlements_in_one_run_send_one_dated_message_then_delete_images(self):
        notifier = SimpleNamespace(enable=True, push_images=Mock(return_value=True))
        task = ScriptTask.__new__(ScriptTask)
        task.config = SimpleNamespace(config_name='oas1', notifier=notifier)
        task.conf = SimpleNamespace(dokan_config=SimpleNamespace(push_reward_images=True))
        image_data = iter((b'first', b'second'))
        task.device = SimpleNamespace(
            image_save=Mock(side_effect=lambda path: Path(path).write_bytes(next(image_data))))

        with tempfile.TemporaryDirectory() as temporary_dir:
            with patch('tasks.Dokan.script_task.DOKAN_REWARD_SCREENSHOT_DIR', Path(temporary_dir)):
                task._save_reward_image(SimpleNamespace(battle_key='dokan_member'))
                task._save_reward_image(None)
                notifier.push_images.assert_not_called()
                screenshots = sorted(task._reward_screenshot_directory().glob('*.png'))
                self.assertEqual(len(screenshots), 2)
                task._push_current_run_reward_images()
                self.assertEqual(list(task._reward_screenshot_directory().glob('*.png')), [])

        notifier.push_images.assert_called_once()
        self.assertEqual(notifier.push_images.call_args.args[0], [b'first', b'second'])
        self.assertEqual(notifier.push_images.call_args.kwargs['title'],
                         f"{datetime.now():%Y-%m-%d} 道馆结算奖励")

    def test_failed_push_keeps_current_run_images(self):
        task = ScriptTask.__new__(ScriptTask)
        notifier = SimpleNamespace(enable=True, push_images=Mock(return_value=False))
        task.config = SimpleNamespace(config_name='oas1', notifier=notifier)
        task.conf = SimpleNamespace(dokan_config=SimpleNamespace(push_reward_images=True))
        task.device = SimpleNamespace(image_save=Mock(side_effect=lambda path: Path(path).write_bytes(b'png')))
        with tempfile.TemporaryDirectory() as temporary_dir:
            with patch('tasks.Dokan.script_task.DOKAN_REWARD_SCREENSHOT_DIR', Path(temporary_dir)):
                task._save_reward_image(None)
                task._push_current_run_reward_images()
                self.assertEqual(len(list(task._reward_screenshot_directory().glob('*.png'))), 1)
        notifier.push_images.assert_called_once()

    def test_next_run_does_not_include_previous_run_screenshots(self):
        notifier = SimpleNamespace(enable=True, push_images=Mock(return_value=True))
        previous = ScriptTask.__new__(ScriptTask)
        previous.config = SimpleNamespace(config_name='oas1', notifier=notifier)
        previous.device = SimpleNamespace(image_save=Mock(side_effect=lambda path: Path(path).write_bytes(b'previous')))
        current = ScriptTask.__new__(ScriptTask)
        current.config = previous.config
        current.conf = SimpleNamespace(dokan_config=SimpleNamespace(push_reward_images=True))
        current.device = SimpleNamespace(image_save=Mock(side_effect=lambda path: Path(path).write_bytes(b'current')))
        with tempfile.TemporaryDirectory() as temporary_dir:
            with patch('tasks.Dokan.script_task.DOKAN_REWARD_SCREENSHOT_DIR', Path(temporary_dir)):
                previous._save_reward_image(None)
                current._save_reward_image(None)
                current._push_current_run_reward_images()
                self.assertEqual(len(list(previous._reward_screenshot_directory().glob('*.png'))), 1)
        self.assertEqual(notifier.push_images.call_args.args[0], [b'current'])

    def test_unchecked_reward_push_keeps_local_screenshots(self):
        task = ScriptTask.__new__(ScriptTask)
        notifier = SimpleNamespace(enable=True, push_images=Mock(return_value=True))
        task.config = SimpleNamespace(config_name='oas1', notifier=notifier)
        task.conf = SimpleNamespace(dokan_config=SimpleNamespace(push_reward_images=False))
        task.device = SimpleNamespace(image_save=Mock(side_effect=lambda path: Path(path).write_bytes(b'png')))
        with tempfile.TemporaryDirectory() as temporary_dir:
            with patch('tasks.Dokan.script_task.DOKAN_REWARD_SCREENSHOT_DIR', Path(temporary_dir)):
                task._save_reward_image(None)
                task._push_current_run_reward_images()
                self.assertEqual(len(list(task._reward_screenshot_directory().glob('*.png'))), 1)
        notifier.push_images.assert_not_called()

    def test_automatic_task_end_pushes_even_with_one_daily_attempt_remaining(self):
        for ending in (DokanFinishedError, DokanNotStartedError):
            with self.subTest(ending=ending):
                task = ScriptTask.__new__(ScriptTask)
                attack_count = SimpleNamespace(
                    remain_attack_count=1, init_attack_count=Mock())
                dokan = SimpleNamespace(
                    dokan_config=SimpleNamespace(monday_to_thursday=False),
                    attack_count_config=attack_count)
                task.config = SimpleNamespace(model=SimpleNamespace(dokan=dokan), save=Mock())
                task.before_run = Mock()
                task.goto_page = Mock()
                task.screenshot = Mock()
                task._capture_dokan_reward_if_visible = Mock()
                task.get_current_page = Mock(side_effect=ending)
                task.next_run = Mock()
                task._push_current_run_reward_images = Mock()

                with self.assertRaises(TaskEnd):
                    task.run()

                task._push_current_run_reward_images.assert_called_once_with()

    def test_screenshot_error_does_not_interrupt_battle(self):
        task = ScriptTask.__new__(ScriptTask)
        task.device = SimpleNamespace(image_save=Mock(side_effect=OSError('write failed')))
        task.config = SimpleNamespace(config_name='oas1')
        context = SimpleNamespace(battle_key='dokan_member', continuous_count=1)
        with tempfile.TemporaryDirectory() as temporary_dir:
            with patch('tasks.Dokan.script_task.DOKAN_REWARD_SCREENSHOT_DIR', Path(temporary_dir)):
                task._save_reward_image(context)
                self.assertEqual(list(Path(temporary_dir).rglob('*.png')), [])

    def test_settlement_screenshot_has_its_own_filename(self):
        task = ScriptTask.__new__(ScriptTask)
        task.device = SimpleNamespace(image_save=Mock(side_effect=lambda path: Path(path).write_bytes(b'png')))
        task.config = SimpleNamespace(config_name='oas1')

        with tempfile.TemporaryDirectory() as temporary_dir:
            with patch('tasks.Dokan.script_task.DOKAN_REWARD_SCREENSHOT_DIR', Path(temporary_dir)):
                task._save_reward_image(None)
            files = list(Path(temporary_dir).rglob('*_dokan_settlement.png'))
            self.assertEqual(len(files), 1)

    def test_gocqhttp_posts_all_images_in_one_message(self):
        notifier = Notifier.__new__(Notifier)
        notifier.enable = True
        notifier.provider_name = 'gocqhttp'
        notifier.config_name = 'OAS1'
        notifier.config = {
            'endpoint': 'http://127.0.0.1:5700',
            'user_id': 12345,
            'message_type': 'private',
            'access_token': 'test-token',
        }
        response = Mock()
        response.json.return_value = {'status': 'ok'}

        with patch('module.notify.notify.requests.post', return_value=response) as post:
            self.assertTrue(notifier.push_images([b'first', b'second'], '2026-09-30 道馆结算奖励'))

        args, kwargs = post.call_args
        self.assertEqual(args[0], 'http://127.0.0.1:5700/send_msg')
        self.assertEqual(kwargs['headers'], {'Authorization': 'Bearer test-token'})
        self.assertEqual(kwargs['json']['user_id'], 12345)
        segments = kwargs['json']['message']
        self.assertEqual(segments[0]['data']['text'], 'OAS1 2026-09-30 道馆结算奖励')
        self.assertEqual([base64.b64decode(segment['data']['file'].removeprefix('base64://'))
                          for segment in segments[1:]], [b'first', b'second'])

    def test_gocqhttp_failure_does_not_claim_delivery(self):
        notifier = Notifier.__new__(Notifier)
        notifier.enable = True
        notifier.provider_name = 'gocqhttp'
        notifier.config_name = 'OAS1'
        notifier.config = {'endpoint': 'http://127.0.0.1:5700', 'user_id': 12345}
        response = Mock()
        response.json.return_value = {'status': 'failed'}
        with patch('module.notify.notify.requests.post', return_value=response):
            self.assertFalse(notifier.push_images([b'png'], '道馆奖励'))

    def test_unsupported_notification_provider_does_not_claim_image_delivery(self):
        notifier = Notifier.__new__(Notifier)
        notifier.enable = True
        notifier.provider_name = 'bark'
        with patch('module.notify.notify.requests.post') as post:
            self.assertFalse(notifier.push_images([b'png bytes'], '道馆奖励'))
        post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
