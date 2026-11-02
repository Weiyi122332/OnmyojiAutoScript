"""Retry transient purchase notices and locate each product before reading stock."""

from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from tasks.Component.Buy.buy import Buy, wait_for_purchase_ready
from tasks.WeeklyPurchase.config import MedalRoom
from tasks.WeeklyPurchase.script_task import ScriptTask


class ScanClock:
    def __init__(self):
        self.now = 0

    def timer(self, limit):
        started = self.now
        timer = SimpleNamespace(reached=lambda: self.now - started >= limit)
        timer.start = lambda: timer
        return timer

    def screenshot(self):
        self.now += 0.25

    def sleep(self, seconds):
        self.now += seconds


class StockVisibilityTest(unittest.TestCase):
    def test_both_purchase_dialogs_stop_scanning_after_three_seconds(self):
        for method in ('buy_one', 'buy_more'):
            with self.subTest(method=method):
                clock = ScanClock()
                task = ScriptTask.__new__(ScriptTask)
                task.screenshot = Mock(side_effect=clock.screenshot)
                task.appear = Mock(return_value=False)
                task.appear_then_click = Mock(return_value=False)
                task.click = Mock()
                args = [task.I_ME_AP, task.I_ME_CHECK_AP] if method == 'buy_one' else [task.I_SP_BUY_LOW]
                with patch('tasks.Component.Buy.buy.Timer', side_effect=clock.timer), \
                        patch('tasks.Component.Buy.buy.time.sleep') as sleep:
                    self.assertFalse(getattr(task, method)(*args))
                self.assertEqual(clock.now, 3)
                sleep.assert_not_called()
                task.click.assert_not_called()

    def test_missing_product_is_scanned_for_three_seconds_without_idle_sleep(self):
        clock = ScanClock()
        task = ScriptTask.__new__(ScriptTask)
        task.screenshot = Mock(side_effect=clock.screenshot)
        task.appear = Mock(return_value=False)
        read = Mock()
        with patch('tasks.Component.Buy.buy.Timer', side_effect=clock.timer), \
                patch('tasks.Component.Buy.buy.time.sleep') as sleep:
            self.assertIsNone(wait_for_purchase_ready(task, task.I_SP_BUY_LOW, read))
        self.assertEqual(clock.now, 3)
        self.assertGreater(task.screenshot.call_count, 1)
        sleep.assert_not_called()
        read.assert_not_called()

    def test_ready_product_continues_immediately_and_retries_unknown_stock(self):
        for readings, expected_time in (([50], 0.25), ([None, None, 50], 0.75)):
            with self.subTest(readings=readings):
                clock = ScanClock()
                task = ScriptTask.__new__(ScriptTask)
                task.screenshot = Mock(side_effect=clock.screenshot)
                task.appear = Mock(return_value=True)
                with patch('tasks.Component.Buy.buy.Timer', side_effect=clock.timer), \
                        patch('tasks.Component.Buy.buy.time.sleep') as sleep:
                    self.assertEqual(wait_for_purchase_ready(
                        task, task.I_SP_BUY_LOW, Mock(side_effect=readings)), 50)
                self.assertEqual(clock.now, expected_time)
                sleep.assert_not_called()

    def test_hundred_discs_are_bought_in_two_fifties_after_a_three_second_notice(self):
        clock = ScanClock()
        state = SimpleNamespace(screen='shop', stock=100, quantity=1, notice_until=0)
        task = ScriptTask.__new__(ScriptTask)
        task.device = SimpleNamespace(image=None)
        task.screenshot = Mock(side_effect=clock.screenshot)
        task.buy_more = lambda *args: Buy.buy_more(task, *args)
        purchases = []
        covered_scans = []

        def appear(rule, **kwargs):
            if rule is task.I_SP_BUY_LOW:
                if clock.now < state.notice_until:
                    covered_scans.append(clock.now)
                    return False
                return state.screen == 'shop'
            return rule is task.I_BUY_PLUS and state.screen == 'dialog'

        def open_or_maximize(rule, **kwargs):
            if rule is task.I_SP_BUY_LOW:
                state.screen = 'dialog'
            else:
                self.assertIs(rule, task.I_BUY_PLUS)
                state.quantity = min(50, state.stock)
            return True

        def purchase(rule, **kwargs):
            self.assertIs(rule, task.C_BUY_MORE)
            purchases.append(state.quantity)
            state.stock -= state.quantity
            state.screen = 'reward'
            state.notice_until = clock.now + 3
            return True

        def dismiss_reward():
            if state.screen == 'reward':
                state.screen = 'shop'
                return True
            return False

        def read_stock(_rule):
            self.assertEqual(state.screen, 'shop')
            self.assertGreaterEqual(clock.now, state.notice_until)
            return state.stock

        task.appear = Mock(side_effect=appear)
        task.appear_then_click = Mock(side_effect=open_or_maximize)
        task.click = Mock(side_effect=purchase)
        task.ui_reward_appear_click = Mock(side_effect=dismiss_reward)
        task._special_check_remain = Mock(side_effect=read_stock)
        with patch('tasks.Component.Buy.buy.Timer', side_effect=clock.timer), \
                patch('tasks.Component.Buy.buy.time.sleep', side_effect=clock.sleep) as sleep:
            self.assertTrue(task._special_low(True))
        self.assertEqual(purchases, [50, 50])
        self.assertGreater(len(covered_scans), 1)
        self.assertTrue(all(call.args[0] < 3 for call in sleep.call_args_list))

    def test_medal_ap_is_located_before_reading_its_stock(self):
        task = ScriptTask.__new__(ScriptTask)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        task.device = SimpleNamespace(image=frame)
        task.screenshot = Mock()
        task._enter_medal = Mock(return_value=True)
        task.buy_check_money = Mock(return_value=True)
        task.I_ME_AP = deepcopy(task.I_ME_AP)
        task.O_SP_RES_NUMBER = deepcopy(task.O_SP_RES_NUMBER)
        image = task.I_ME_AP.image
        height, width = image.shape[:2]
        x, y = 842, 150
        frame[y:y + height, x:x + width] = image
        task.appear = lambda rule: rule.template_match(frame)
        purchased = []
        task.buy_one = Mock(side_effect=lambda *args: purchased.append(args) or True)
        expected_roi = [x + width // 2 - 96, y - 40, 192, 40]

        def read(rule, _frame):
            self.assertEqual(rule.roi, expected_roi)
            return '本周剩余0' if purchased else '本周剩余1'

        with patch('module.atom.ocr.RuleOcr.ocr', new=read), \
                patch('tasks.Component.Buy.buy.time.sleep'):
            task.execute_medal(MedalRoom(enable=True, ap_100=True))
        task.buy_one.assert_called_once_with(task.I_ME_AP, task.I_ME_CHECK_AP)

    def test_blank_or_unrelated_ocr_is_unknown_instead_of_sold_out(self):
        task = ScriptTask.__new__(ScriptTask)
        task.device = SimpleNamespace(image=None)
        task.O_SP_RES_NUMBER = deepcopy(task.O_SP_RES_NUMBER)
        for text, expected in (('', None), (None, None), ('任务完成', None),
                               ('本周剩余0', 0), ('本周剩余50', 50)):
            with self.subTest(text=text), patch.object(task.O_SP_RES_NUMBER, 'ocr', return_value=text):
                self.assertEqual(task._special_check_remain(task.I_SP_BUY_LOW), expected)


if __name__ == '__main__':
    unittest.main()
