"""Random souls must be identified before using a shop's generic exchange buttons."""

from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from module.atom.ocr import RuleOcr
from tasks.Component.Buy.buy import Buy
from tasks.WeeklyPurchase.assets import WeeklyPurchaseAssets
from tasks.WeeklyPurchase.mall.bondlings import Bondlings


class BondlingsSoulProductTest(unittest.TestCase):
    def setUp(self):
        self.task = Bondlings.__new__(Bondlings)
        self.frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.task.device = SimpleNamespace(image=self.frame, click_record_clear=Mock())
        self.task.screenshot = Mock()
        self.task.buy_more = Mock()
        self.task.I_BL_SOULS = deepcopy(WeeklyPurchaseAssets.I_BL_SOULS)
        self.task.I_BL_BUY_SOULS = deepcopy(WeeklyPurchaseAssets.I_BL_BUY_SOULS)
        self.task.O_BL_RES_SOULS = deepcopy(WeeklyPurchaseAssets.O_BL_RES_SOULS)
        self.task.O_BL_RES_SOULS.ocr = Mock(side_effect=[100, 0])
        self.task.O_BL_CHECK_MONEY = Mock(spec=RuleOcr)
        self.task.O_BL_CHECK_MONEY.ocr.return_value = (4000, 0, 4000)
        self.task.appear = lambda rule: rule.template_match(self.frame)
        sleep = patch('tasks.WeeklyPurchase.mall.bondlings.time.sleep')
        sleep.start()
        self.addCleanup(sleep.stop)

    def paste(self, rule, x, y):
        image = rule.image
        height, width = image.shape[:2]
        self.frame[y:y + height, x:x + width] = image

    def stock_shop(self, soul_column=None):
        # All four items have visually identical exchange buttons.
        for column in range(4):
            self.paste(self.task.I_BL_BUY_SOULS, 197 + column * 281, 476)
        if soul_column is not None:
            self.paste(self.task.I_BL_SOULS, 143 + soul_column * 281, 266)

    def test_generic_exchange_buttons_without_the_soul_product_do_not_buy(self):
        self.stock_shop()
        self.task._bondlings_random_souls(50)
        self.task.buy_more.assert_not_called()
        self.task.O_BL_CHECK_MONEY.ocr.assert_not_called()

    def test_moved_soul_product_uses_its_own_button_without_mutating_shared_rules(self):
        self.stock_shop(soul_column=2)
        original_button_roi = tuple(self.task.I_BL_BUY_SOULS.roi_back)
        original_remain_roi = list(self.task.O_BL_RES_SOULS.roi)
        self.task._bondlings_random_souls(1)
        button, = self.task.buy_more.call_args.args
        self.assertGreater(button.roi_front[0], 700)
        self.assertLess(button.roi_front[0], 850)
        self.assertEqual(tuple(self.task.I_BL_BUY_SOULS.roi_back), original_button_roi)
        self.assertEqual(self.task.O_BL_RES_SOULS.roi, original_remain_roi)

    def test_actual_stock_is_bought_without_a_fixed_batch_or_total_limit(self):
        self.stock_shop(soul_column=0)
        self.task.O_BL_RES_SOULS.ocr.side_effect = [100, 61, 13, 0]
        self.task._bondlings_random_souls(True)
        self.assertEqual(len(self.task.buy_more.call_args_list), 3)
        self.assertTrue(all(len(call.args) == 1 for call in self.task.buy_more.call_args_list))

    def test_last_single_item_is_not_dropped(self):
        self.stock_shop(soul_column=0)
        self.task.O_BL_RES_SOULS.ocr.side_effect = [61, 1, 0]
        self.task._bondlings_random_souls(True)
        self.assertEqual(len(self.task.buy_more.call_args_list), 2)
        self.assertTrue(all(len(call.args) == 1 for call in self.task.buy_more.call_args_list))

    def test_stock_and_currency_still_limit_the_purchase(self):
        for stock, money, expected in (([7, 0], [1677], 1), ([100, 98], [45, 5], 1), ([0], [], 0)):
            with self.subTest(stock=stock, money=money):
                self.stock_shop(soul_column=0)
                self.task.buy_more.reset_mock()
                self.task.O_BL_RES_SOULS.ocr.side_effect = stock
                self.task.O_BL_CHECK_MONEY.ocr.side_effect = [(value, 4000 - value, 4000) for value in money]
                self.task._bondlings_random_souls(True)
                self.assertEqual(self.task.buy_more.call_count, expected)

    def test_disabled_purchase_does_not_inspect_or_click_products(self):
        self.task._bondlings_random_souls(0)
        self.task.screenshot.assert_not_called()
        self.task.buy_more.assert_not_called()


class BuyExactQuantityTest(unittest.TestCase):
    def test_read_quantity_and_use_the_maximum_button_before_correcting_the_remainder(self):
        for target in (1, 20, 30):
            with self.subTest(target=target):
                task = Buy.__new__(Buy)
                task.device = SimpleNamespace(image=None, click_record_clear=Mock())
                task.screenshot = Mock()
                task.appear = lambda rule, **kwargs: rule is task.I_BUY_PLUS
                task.ui_reward_appear_click = Mock(return_value=True)
                quantity = [1]
                task.O_BUY_NUMBER = SimpleNamespace(ocr=lambda image: quantity[0])
                task._read_buy_quantity = lambda: quantity[0]

                def set_quantity(rule, **kwargs):
                    if rule is task.I_BUY_PLUS:
                        quantity[0] = 30
                    else:
                        self.assertIs(rule, task.I_BUY_SUB)
                        quantity[0] -= 1
                    return True

                task.appear_then_click = Mock(side_effect=set_quantity)
                timer = SimpleNamespace(start=lambda: None, reached=lambda: True, reset=lambda: None)
                timer.start = lambda: timer
                with patch('tasks.Component.Buy.buy.Timer', return_value=timer), \
                        patch('tasks.Component.Buy.buy.time.sleep'):
                    task.buy_more(WeeklyPurchaseAssets.I_BL_BUY_SOULS, target)
                self.assertEqual(quantity[0], target)
                expected = [] if target == 1 else [task.I_BUY_PLUS] + [task.I_BUY_SUB] * (30 - target)
                self.assertEqual([call.args[0] for call in task.appear_then_click.call_args_list], expected)


if __name__ == '__main__':
    unittest.main()
