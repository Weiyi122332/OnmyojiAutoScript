"""选择30万后，仅在图片识别到奖励预览时再次点击关闭。"""

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.exception import TaskEnd
from tasks.FrogBoss.config import Strategy
from tasks.FrogBoss.frog_bet import RunReport
from tasks.FrogBoss.script_task import ScriptTask


class FrogBetFlowTest(unittest.TestCase):
    def make_task(self, frames):
        task = ScriptTask.__new__(ScriptTask)
        task.config = SimpleNamespace(model=SimpleNamespace(frog_boss=SimpleNamespace(
            frog_boss_config=SimpleNamespace(strategy_frog=Strategy.AlwaysRed))))
        task.run_report = RunReport(Strategy.AlwaysRed.value, datetime(2026, 10, 5, 14))
        task.ensure_bet_time = Mock()
        task.read_bet_counts = Mock(return_value=(30, 10))
        task.ui_click_until_disappear = Mock()
        task.capture_bet_screenshot = Mock()
        task.retry_bet = Mock(side_effect=TaskEnd('deferred'))
        task.O_LEFT_COUNT = SimpleNamespace(ocr=Mock(side_effect=AssertionError('unexpected OCR')))
        task.O_RIGHT_COUNT = SimpleNamespace(ocr=Mock(side_effect=AssertionError('unexpected OCR')))
        clock = SimpleNamespace(now=1000.0, visible=(), clicks=[])
        frames = iter(frames)
        scenes = {
            'betting': (),
            'amount': (task.I_GOLD_30,),
            'amount_wait': (task.I_GOLD_30,),
            'coin_without_preview': (task.I_GOLD_30, task.I_GOLD_30_CHECK),
            'preview': (task.I_GOLD_30, task.I_GOLD_30_CHECK, task.I_BET_REWARD_PREVIEW),
            'preview_wait': (task.I_GOLD_30, task.I_GOLD_30_CHECK, task.I_BET_REWARD_PREVIEW),
            'preview_without_coin': (task.I_GOLD_30, task.I_BET_REWARD_PREVIEW),
            'confirm': (task.I_GOLD_30, task.I_BET_SURE),
            'dialog': (task.I_UI_CONFIRM,),
            'small_dialog': (task.I_UI_CONFIRM_SAMLL,),
            'overlap': (task.I_GOLD_30, task.I_BET_SURE, task.I_UI_CONFIRM),
            'betted': (task.I_BETTED,),
            'unknown': (),
        }

        def screenshot():
            elapsed, scene = next(frames)
            clock.now = 1000.0 + elapsed
            clock.visible = scenes[scene]

        def appear(marker):
            return any(marker is visible for visible in clock.visible)

        def click(marker, **kwargs):
            if not appear(marker):
                return False
            clock.clicks.append((clock.now - 1000.0, marker))
            return True

        task.screenshot = Mock(side_effect=screenshot)
        task.appear = Mock(side_effect=appear)
        task.appear_then_click = Mock(side_effect=click)
        return task, clock

    def do_bet(self, task, clock):
        with patch('module.base.timer.time.time', side_effect=lambda: clock.now), \
                patch('tasks.FrogBoss.script_task.round_start', return_value=datetime(2026, 10, 5, 14)), \
                patch('tasks.FrogBoss.script_task.sleep'), \
                patch('tasks.FrogBoss.script_task.logger'):
            task.do_bet()

    def count_clicks(self, clock, marker):
        return sum(clicked is marker for _, clicked in clock.clicks)

    def test_delayed_preview_is_closed_after_image_detection(self):
        task, clock = self.make_task([
            (0, 'betting'), (0.1, 'amount'), (1, 'amount_wait'),
            (4, 'amount_wait'), (8, 'preview'), (8.1, 'preview_wait'),
            (9, 'amount'), (9.1, 'confirm'), (9.5, 'dialog'), (10, 'betted'),
        ])
        self.do_bet(task, clock)
        amount_clicks = [when for when, marker in clock.clicks if marker is task.I_GOLD_30]
        self.assertEqual(len(amount_clicks), 2)
        self.assertAlmostEqual(amount_clicks[0], 0.1)
        self.assertAlmostEqual(amount_clicks[1], 8)
        self.assertEqual(self.count_clicks(clock, task.I_BET_SURE), 1)
        self.assertTrue(task.run_report.confirmed)
        self.assertEqual(task.run_report.amount, 300000)
        task.retry_bet.assert_not_called()
        task.capture_bet_screenshot.assert_called_once()

    def test_existing_preview_is_closed_once_before_confirmation(self):
        task, clock = self.make_task([
            (0, 'betting'), (0.1, 'preview'), (0.2, 'amount'),
            (0.3, 'confirm'), (1, 'dialog'), (2, 'betted'),
        ])
        self.do_bet(task, clock)
        self.assertEqual(self.count_clicks(clock, task.I_GOLD_30), 1)
        self.assertEqual(self.count_clicks(clock, task.I_BET_SURE), 1)
        self.assertTrue(task.run_report.confirmed)

    def test_confirmation_wait_does_not_reopen_amount_preview(self):
        task, clock = self.make_task([
            (0, 'betting'), (0.1, 'amount'), (0.3, 'preview'), (0.5, 'amount'),
            (0.6, 'confirm'), (1, 'unknown'), (3, 'confirm'), (4, 'unknown'),
            (6, 'dialog'), (8, 'betted'),
        ])
        self.do_bet(task, clock)
        self.assertEqual(self.count_clicks(clock, task.I_GOLD_30), 2)
        self.assertTrue(all(when < 0.6 for when, marker in clock.clicks if marker is task.I_GOLD_30))
        self.assertTrue(task.run_report.confirmed)

    def test_confirm_click_does_not_fall_through_to_another_click_in_same_frame(self):
        task, clock = self.make_task([
            (0, 'betting'), (0.1, 'amount'), (0.3, 'preview'), (0.5, 'amount'), (1, 'overlap'),
            (2, 'dialog'), (3, 'betted'),
        ])
        self.do_bet(task, clock)
        self.assertEqual([marker for when, marker in clock.clicks if when == 1], [task.I_BET_SURE])
        self.assertEqual(self.count_clicks(clock, task.I_GOLD_30), 2)

    def test_unconfirmed_amount_times_out_without_formal_bet(self):
        task, clock = self.make_task([
            (0, 'betting'), (0.1, 'amount'), (4, 'amount_wait'), (10.2, 'amount_wait'),
        ])
        with self.assertRaises(TaskEnd):
            self.do_bet(task, clock)
        self.assertEqual(self.count_clicks(clock, task.I_GOLD_30), 1)
        self.assertEqual(self.count_clicks(clock, task.I_BET_SURE), 0)
        self.assertIsNone(task.run_report.amount)
        self.assertFalse(task.run_report.confirmed)
        task.retry_bet.assert_called_once_with('30万档位选择或奖励预览关闭未完成，取消本次下注')
        task.capture_bet_screenshot.assert_not_called()

    def test_unavailable_amount_button_does_not_confirm_default_amount(self):
        task, clock = self.make_task([
            (0, 'betting'), (0.1, 'unknown'), (10.2, 'unknown'),
        ])
        with self.assertRaises(TaskEnd):
            self.do_bet(task, clock)
        self.assertEqual(clock.clicks, [])
        self.assertFalse(task.run_report.confirmed)
        task.retry_bet.assert_called_once()

    def test_bet_confirmation_timeout_keeps_result_unconfirmed(self):
        task, clock = self.make_task([
            (0, 'betting'), (0.1, 'amount'), (0.3, 'preview'), (0.5, 'amount'),
            (0.6, 'confirm'), (2, 'unknown'), (10.6, 'unknown'),
        ])
        with self.assertRaises(TaskEnd):
            self.do_bet(task, clock)
        self.assertEqual(self.count_clicks(clock, task.I_GOLD_30), 2)
        self.assertFalse(task.run_report.confirmed)
        task.retry_bet.assert_called_once_with('下注结果未确认，稍后重新检查')
        task.capture_bet_screenshot.assert_not_called()

    def test_confirmed_bet_at_timeout_is_accepted(self):
        task, clock = self.make_task([
            (0, 'betting'), (0.1, 'amount'), (0.3, 'preview'), (0.5, 'amount'),
            (0.6, 'confirm'), (10.6, 'betted'),
        ])
        self.do_bet(task, clock)
        self.assertTrue(task.run_report.confirmed)
        task.retry_bet.assert_not_called()

    def test_small_confirmation_dialog_is_supported(self):
        task, clock = self.make_task([
            (0, 'betting'), (0.1, 'amount'), (0.3, 'preview'), (0.5, 'amount'), (0.6, 'confirm'),
            (1, 'small_dialog'), (2, 'betted'),
        ])
        self.do_bet(task, clock)
        self.assertEqual(self.count_clicks(clock, task.I_UI_CONFIRM_SAMLL), 1)
        self.assertEqual(self.count_clicks(clock, task.I_GOLD_30), 2)
        self.assertTrue(task.run_report.confirmed)

    def test_coin_image_alone_does_not_trigger_second_click(self):
        task, clock = self.make_task([
            (0, 'betting'), (0.1, 'amount'), (1, 'coin_without_preview'),
            (4, 'coin_without_preview'), (10.2, 'coin_without_preview'),
        ])
        with self.assertRaises(TaskEnd):
            self.do_bet(task, clock)
        self.assertEqual(self.count_clicks(clock, task.I_GOLD_30), 1)
        self.assertEqual(self.count_clicks(clock, task.I_BET_SURE), 0)
        self.assertIsNone(task.run_report.amount)

    def test_preview_must_disappear_before_formal_bet(self):
        task, clock = self.make_task([
            (0, 'betting'), (0.1, 'amount'), (1, 'preview'),
            (4, 'preview_wait'), (10.2, 'preview_wait'),
        ])
        with self.assertRaises(TaskEnd):
            self.do_bet(task, clock)
        self.assertEqual(self.count_clicks(clock, task.I_GOLD_30), 2)
        self.assertEqual(self.count_clicks(clock, task.I_BET_SURE), 0)
        self.assertFalse(task.run_report.confirmed)

    def test_preview_without_expected_coin_is_not_dismissed_as_30w(self):
        task, clock = self.make_task([
            (0, 'betting'), (0.1, 'amount'), (1, 'preview_without_coin'), (10.2, 'preview_without_coin'),
        ])
        with self.assertRaises(TaskEnd):
            self.do_bet(task, clock)
        self.assertEqual(self.count_clicks(clock, task.I_GOLD_30), 1)
        self.assertEqual(self.count_clicks(clock, task.I_BET_SURE), 0)

    def test_unexpected_preview_during_confirmation_blocks_background_clicks(self):
        task, clock = self.make_task([
            (0, 'betting'), (0.1, 'amount'), (0.3, 'preview'), (0.5, 'amount'),
            (1, 'preview'),
        ])
        with self.assertRaises(TaskEnd):
            self.do_bet(task, clock)
        self.assertEqual(self.count_clicks(clock, task.I_GOLD_30), 2)
        self.assertEqual(self.count_clicks(clock, task.I_BET_SURE), 0)
        task.retry_bet.assert_called_once_with('奖励预览仍在显示，取消确认下注')


if __name__ == '__main__':
    unittest.main()
