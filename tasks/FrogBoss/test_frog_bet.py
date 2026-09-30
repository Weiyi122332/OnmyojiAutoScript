"""Missing primary advice uses the majority; each run sends one accurate report."""
import tempfile
import unittest
from datetime import datetime, time, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from module.exception import GameStuckError, TaskEnd
from tasks.FrogBoss.config import Strategy
from tasks.FrogBoss.frog_bet import RunReport, majority_side
from tasks.FrogBoss.frog_oas import OasHistory
from tasks.FrogBoss.frog_rss import CHINA_TIME, RssPrediction, round_start
from tasks.FrogBoss.script_task import ScriptTask


NOW = datetime(2026, 9, 30, 19, 55, tzinfo=CHINA_TIME)


class MajorityTests(unittest.TestCase):
    def test_majority_and_equal_counts(self):
        for left, right, expected in [(30, 10, 'LEFT'), (10, 30, 'RIGHT'), (20, 20, 'RIGHT'), (0, 20, 'RIGHT')]:
            with self.subTest(counts=(left, right)):
                self.assertEqual(majority_side(left, right), expected)
        for left, right in [(0, 0), (None, 10), ('10', 20), (-1, 10), (float('inf'), 10)]:
            with self.subTest(counts=(left, right)), self.assertRaises(ValueError):
                majority_side(left, right)

    def test_fallback_oas_decision_is_recorded_even_with_zero_crowd_weight(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            store.choose('1' * 512, 30, 10, [])
            store.settle('1' * 512, 'RIGHT')
            self.assertEqual(store.reliability('crowd'), 0)
            with patch('tasks.FrogBoss.frog_oas.random.choice', side_effect=AssertionError('fallback must not be random')):
                decision = store.choose('0' * 512, 30, 10, [],
                                        fallback_side='LEFT', fallback_reason='没有有效博主建议')
            self.assertEqual(decision['side'], 'LEFT')
            self.assertEqual(decision['mode'], 'fallback_majority')
            reloaded = OasHistory(store.path)
            self.assertEqual(reloaded.choose('0' * 512, 1, 20, [])['id'], decision['id'])
            result = reloaded.settle('0' * 512, 'LEFT')
            self.assertEqual(result['id'], decision['id'])


class FrogBossRunTests(unittest.TestCase):
    def setUp(self):
        self.task = ScriptTask.__new__(ScriptTask)
        self.scheduler = SimpleNamespace(next_run=NOW.replace(tzinfo=None) + timedelta(hours=2))
        self.frog_config = SimpleNamespace(strategy_frog=Strategy.Rss, before_end_frog=time(0, 10))
        self.notifier = SimpleNamespace(enable=True, provider_name='gocqhttp',
                                        push=Mock(return_value=True), push_image=Mock(return_value=True))
        self.task.config = SimpleNamespace(config_name='oas_test', notifier=self.notifier,
                                          model=SimpleNamespace(frog_boss=SimpleNamespace(
                                              scheduler=self.scheduler, frog_boss_config=self.frog_config)))
        self.task.device = SimpleNamespace(image=np.full((4, 6, 3), 80, dtype=np.uint8))
        self.task.enter_frog_boss = Mock()
        self.task.screenshot = Mock()
        self.task.O_LEFT_COUNT = SimpleNamespace(ocr=Mock(return_value=30))
        self.task.O_RIGHT_COUNT = SimpleNamespace(ocr=Mock(return_value=10))
        self.task.ui_click_until_disappear = Mock()
        self.task.goto_page = Mock()
        self.task.set_next_run = Mock(side_effect=lambda **kwargs: setattr(self.scheduler, 'next_run', kwargs['target']))
        self.task.next_run = Mock()
        self.betted = False
        self.rest = False

        def appear(marker):
            if marker is self.task.I_BETTED:
                return self.betted
            if marker is self.task.I_FROG_BOSS_REST:
                return self.rest
            return marker in (self.task.I_BET_LEFT, self.task.I_BET_RIGHT, self.task.I_GOLD_30_CHECK)

        def confirm(marker, **kwargs):
            if marker is self.task.I_UI_CONFIRM:
                self.betted = True
                return True
            return False

        self.task.appear = Mock(side_effect=appear)
        self.task.appear_then_click = Mock(side_effect=confirm)
        for name, kwargs in [
            ('fetch_prediction', {'return_value': None}),
            ('round_start', {'return_value': round_start(NOW)}),
            ('fingerprint', {'return_value': '0' * 512}),
            ('beijing_now', {'return_value': NOW.replace(tzinfo=None)}),
        ]:
            patcher = patch(f'tasks.FrogBoss.script_task.{name}', **kwargs)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def reset_notifications(self):
        self.notifier.push.reset_mock()
        self.notifier.push_image.reset_mock()

    def run_to_end(self, expected_attempts=1):
        with self.assertRaises(TaskEnd):
            self.task.run()
        self.assertEqual(self.notifier.push.call_count + self.notifier.push_image.call_count, expected_attempts)
        call = self.notifier.push.call_args or self.notifier.push_image.call_args
        return call.kwargs['content']

    def test_rss_fallback_bets_majority_and_reports_once_after_confirmation(self):
        content = self.run_to_end()
        self.task.ui_click_until_disappear.assert_called_once_with(self.task.I_BET_LEFT)
        self.assertIn('运行结果：下注成功', content)
        self.assertIn('下注：左（红），30 万金币', content)
        self.assertIn('人数：左 30 / 右 10', content)
        self.assertIn('实际策略：人数多数（兜底）', content)
        self.assertIn('没有今天本场建议', content)
        self.assertIn('下次运行：', content)
        self.assertIn('实例：oas_test', content)

    def test_valid_primary_advice_takes_priority_over_majority(self):
        self.fetch_prediction.return_value = RssPrediction(
            '右', round_start(NOW), NOW - timedelta(minutes=10), '对弈竞猜', 'https://ds.163.com/feed/example')
        content = self.run_to_end()
        self.task.ui_click_until_disappear.assert_called_once_with(self.task.I_BET_RIGHT)
        self.assertIn('下注：右（蓝）', content)
        self.assertIn('兜底：未使用', content)
        self.assertIn('面灵气喵', content)
        self.assertNotIn('兜底原因', content)

    def test_other_external_strategies_share_the_fallback(self):
        for strategy in [Strategy.Dashen, Strategy.Bilibili, Strategy.Oas]:
            with self.subTest(strategy=strategy), tempfile.TemporaryDirectory() as directory:
                self.frog_config.strategy_frog = strategy
                self.betted = False
                self.reset_notifications()
                self.task.ui_click_until_disappear.reset_mock()
                self.task.oas_history = OasHistory(Path(directory) / 'history.jsonl')
                with patch.object(self.task, 'get_dashen', return_value=None), \
                        patch('tasks.FrogBoss.script_task.fetch_predictions', return_value=[]):
                    content = self.run_to_end()
                self.task.ui_click_until_disappear.assert_called_once_with(self.task.I_BET_LEFT)
                self.assertIn('实际策略：人数多数（兜底）', content)
                if strategy == Strategy.Oas:
                    decision = next(e for e in self.task.oas_history.events if e['kind'] == 'decision')
                    self.assertEqual(decision['mode'], 'fallback_majority')

    def test_dashen_with_no_valid_votes_returns_no_advice(self):
        with patch('tasks.FrogBoss.script_task.requests.get', return_value=Mock(status_code=503)) as get:
            self.assertIsNone(self.task.get_dashen(30, 10))
        self.assertTrue(all(call.kwargs['timeout'] == (3, 5) for call in get.call_args_list))

    def test_already_betted_or_rest_runs_report_without_clicking(self):
        for betted, rest, result in [(True, False, '本场已下注'), (False, True, '活动休息中')]:
            with self.subTest(result=result):
                self.reset_notifications()
                self.betted, self.rest = betted, rest
                content = self.run_to_end()
                self.assertIn(result, content)
                self.assertNotIn('下注成功', content)
                self.task.ui_click_until_disappear.assert_not_called()
                if betted:
                    self.notifier.push_image.assert_called_once()
                    self.notifier.push.assert_not_called()
                else:
                    self.notifier.push_image.assert_not_called()
                    self.assertIsNone(self.task.run_report.screenshot)

    def test_invalid_counts_defer_and_report_without_clicking(self):
        self.task.O_LEFT_COUNT.ocr.return_value = 0
        self.task.O_RIGHT_COUNT.ocr.return_value = 0
        content = self.run_to_end()
        self.assertIn('暂缓下注', content)
        self.assertIn('多数方兜底需要有效', content)
        self.assertNotIn('下注成功', content)
        self.task.ui_click_until_disappear.assert_not_called()
        self.task.next_run.assert_not_called()
        self.task.set_next_run.assert_called_once()

    def test_failure_is_reported_and_notification_error_does_not_mask_it(self):
        self.task.enter_frog_boss.side_effect = GameStuckError('page not found')
        self.notifier.push.side_effect = RuntimeError('push unavailable')
        with self.assertRaisesRegex(GameStuckError, 'page not found'):
            self.task.run()
        self.notifier.push.assert_called_once()
        self.assertIn('运行异常', self.notifier.push.call_args.kwargs['content'])
        self.assertNotIn('下注成功', self.notifier.push.call_args.kwargs['content'])

    def test_global_notification_switch_is_respected(self):
        self.notifier.enable = False
        self.betted = True
        with self.assertRaises(TaskEnd):
            self.task.run()
        self.notifier.push.assert_not_called()
        self.notifier.push_image.assert_not_called()

    def test_summary_is_reset_between_runs(self):
        first = self.run_to_end()
        self.assertIn('兜底原因', first)
        self.reset_notifications()
        second = self.run_to_end()
        self.assertIn('本场已下注', second)
        self.assertNotIn('兜底原因', second)
        self.assertNotIn('30 万金币', second)

    def test_screenshot_freezes_the_confirmed_frame_in_one_combined_message(self):
        before, confirmed, later = [11, 22, 33], [44, 55, 66], [77, 88, 99]

        def screenshot():
            # The next outer-loop screenshot reuses the same mutable RGB buffer.
            color = later if self.task.run_report.screenshot is not None else (
                confirmed if self.betted else before)
            self.task.device.image[:] = color

        self.task.screenshot.side_effect = screenshot
        content = self.run_to_end()
        self.notifier.push.assert_not_called()
        self.notifier.push_image.assert_called_once()
        sent = self.notifier.push_image.call_args.args[0]
        self.assertTrue(sent.startswith(b'\x89PNG\r\n\x1a\n'))
        with Image.open(BytesIO(sent)) as image:
            self.assertEqual(image.mode, 'RGB')
            self.assertEqual(image.size, (6, 4))
            np.testing.assert_array_equal(np.asarray(image), np.full((4, 6, 3), confirmed, dtype=np.uint8))
        np.testing.assert_array_equal(self.task.device.image, np.full((4, 6, 3), later, dtype=np.uint8))
        self.assertIn('下注成功', content)

    def test_image_failure_falls_back_to_text_without_changing_bet_result(self):
        for error in [None, RuntimeError('image push unavailable')]:
            with self.subTest(error=error):
                self.reset_notifications()
                self.betted = False
                self.notifier.push_image.return_value = False
                self.notifier.push_image.side_effect = error
                content = self.run_to_end(expected_attempts=2)
                self.notifier.push_image.assert_called_once()
                self.notifier.push.assert_called_once()
                self.assertIn('截图发送失败', content)
                self.assertIn('下注成功', content)
                self.assertTrue(self.task.run_report.confirmed)

    def test_screenshot_capture_failure_still_reports_a_successful_bet(self):
        with patch('tasks.FrogBoss.script_task.Image.fromarray', side_effect=OSError('cannot encode image')):
            content = self.run_to_end()
        self.notifier.push.assert_called_once()
        self.notifier.push_image.assert_not_called()
        self.assertIsNone(self.task.run_report.screenshot)
        self.assertIn('下注成功', content)

    def test_rest_run_does_not_reuse_a_previous_bet_screenshot(self):
        self.run_to_end()
        self.assertIsNotNone(self.task.run_report.screenshot)
        self.reset_notifications()
        self.betted, self.rest = False, True
        content = self.run_to_end()
        self.notifier.push_image.assert_not_called()
        self.notifier.push.assert_called_once()
        self.assertIsNone(self.task.run_report.screenshot)
        self.assertIn('活动休息中', content)

    def test_other_notification_channels_keep_the_text_summary(self):
        self.notifier.provider_name = 'custom'
        content = self.run_to_end()
        self.notifier.push.assert_called_once()
        self.notifier.push_image.assert_not_called()
        self.assertIn('下注成功', content)
        self.assertIn('当前推送渠道不支持附带截图', content)

    def test_unconfirmed_bet_is_reported_as_planned(self):
        report = RunReport('frog_rss', round_start(NOW), status='运行异常', side='LEFT')
        content = report.content('oas_test')
        self.assertIn('计划下注：左（红）', content)
        self.assertIn('金额未确认', content)
        self.assertNotIn('30 万金币', content)
        self.assertNotIn('下注成功', content)


if __name__ == '__main__':
    unittest.main()
