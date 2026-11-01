"""Limited weekly goods buy out stock; unlimited goods retain requested counts."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from module.atom.ocr import RuleOcr
from module.config.config_model import ConfigModel
from tasks.WeeklyPurchase.config import WeeklyPurchase
from tasks.WeeklyPurchase.script_task import ScriptTask


class PurchaseConfigurationTest(unittest.TestCase):
    def test_old_positive_quantities_become_enabled_without_retaining_a_limit(self):
        legacy = {
            'scales': {'orochi_scales': 1, 'demon_souls': 50, 'picture_book_scrap': 0},
            'special_room': {'medium_bondling_discs': '10', 'low_bondling_discs': 73},
            'bondlings': {'random_soul': 50, 'bondling_stone': 0,
                         'high_bondling_discs': 3, 'medium_bondling_discs': 25},
            'medal_room': {'challenge_pass': 10, 'red_daruma': 75, 'broken_amulet': 123},
            'guild_store': {'skin_ticket': 5},
            'friendship_points': {'red_daruma': 23, 'broken_amulet': 101},
        }
        task = WeeklyPurchase.model_validate(legacy)
        for group, fields in legacy.items():
            for name, quantity in fields.items():
                value = getattr(getattr(task, group), name)
                if name in ('red_daruma', 'broken_amulet'):
                    self.assertIs(type(value), int)
                    self.assertEqual(value, quantity)
                else:
                    self.assertIs(value, int(quantity) > 0)
        page = ConfigModel(weekly_purchase=task).script_task('WeeklyPurchase')
        self.assertEqual(next(field for field in page['scales']
                              if field['name'] == 'orochi_scales')['type'], 'boolean')
        self.assertEqual(next(field for field in page['friendship_points']
                              if field['name'] == 'red_daruma')['type'], 'integer')


class BuyRemainingStockTest(unittest.TestCase):
    def setUp(self):
        self.task = ScriptTask.__new__(ScriptTask)
        self.task.device = SimpleNamespace(image=None)
        self.task.screenshot = Mock()
        self.task.appear = Mock(return_value=True)
        self.task.buy_more = Mock(return_value=True)
        self.task._cancel_buy_dialog = Mock()
        patcher = patch('tasks.Component.Buy.buy.time.sleep')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_failed_or_non_decreasing_stock_does_not_repeat_a_purchase(self):
        for readings, expected_calls in (([None], 0), ([-1], 0), (['40'], 0),
                                         ([40, 40], 1), ([40, 41], 1), ([40, None], 1)):
            with self.subTest(readings=readings):
                self.task.buy_more.reset_mock()
                read = Mock(side_effect=readings)
                self.assertFalse(self.task.buy_all_remaining(self.task.I_SP_BUY_TOTEM, read))
                self.assertEqual(self.task.buy_more.call_count, expected_calls)

    def test_failed_transaction_closes_the_quantity_dialog_and_stops(self):
        self.task.buy_more.return_value = False
        self.assertFalse(self.task.buy_all_remaining(
            self.task.I_SP_BUY_TOTEM, Mock(return_value=40)))
        self.task.buy_more.assert_called_once_with(self.task.I_SP_BUY_TOTEM)
        self.task._cancel_buy_dialog.assert_called_once()

    def test_invalid_money_or_balance_below_one_item_prevents_purchase(self):
        for balance in (None, '1000', (10, 20, 100), 49):
            with self.subTest(balance=balance):
                self.task.buy_more.reset_mock()
                money = Mock(spec=RuleOcr)
                money.ocr.return_value = balance
                self.assertFalse(self.task.buy_all_remaining(
                    self.task.I_SP_BUY_TOTEM, Mock(return_value=40), money, 50))
                self.task.buy_more.assert_not_called()

    def test_sold_out_goods_and_missing_buttons_are_not_clicked(self):
        self.assertTrue(self.task.buy_all_remaining(
            self.task.I_SP_BUY_TOTEM, Mock(return_value=0)))
        self.task.appear.return_value = False
        self.assertFalse(self.task.buy_all_remaining(
            self.task.I_SP_BUY_TOTEM, Mock(return_value=40)))
        self.task.buy_more.assert_not_called()


class RequestedQuantityTest(unittest.TestCase):
    def test_unlimited_goods_follow_the_input_including_multiple_transactions(self):
        for quantity, batches in ((1, [1]), (23, [23]), (150, [99, 51])):
            with self.subTest(quantity=quantity):
                task = ScriptTask.__new__(ScriptTask)
                task.device = SimpleNamespace(image=None)
                task.screenshot = Mock()
                task.appear = Mock(return_value=True)
                task._special_check_remain = Mock(side_effect=AssertionError('unlimited goods have no weekly stock'))
                task.buy_more = Mock(return_value=True)
                money = Mock(spec=RuleOcr)
                money.ocr.return_value = 100000
                with patch('tasks.WeeklyPurchase.mall.friendship_points.time.sleep'):
                    task.buy_mall_more(task.I_FS_BROKEN, False, money, quantity, 99, 100)
                self.assertEqual(task.buy_more.call_args_list,
                                 [call(task.I_FS_BROKEN, batch) for batch in batches])


class OtherLimitedShopsTest(unittest.TestCase):
    def test_thousand_things_selects_the_maximum_for_each_quantity_dialog(self):
        for method in ('tt_buy_mystery_amulet', 'tt_buy_black_daruma_scrap', 'tt_buy_ap'):
            with self.subTest(method=method):
                task = ScriptTask.__new__(ScriptTask)
                task.screenshot = Mock()
                task.appear = Mock(return_value=True)
                task.tt_check_money = Mock(return_value=True)
                task.ocr_appear = Mock(side_effect=AssertionError('must not wait for a fixed quantity'))
                actions = Mock()
                task.appear_then_click = actions.select
                task.tt_get_reward = actions.confirm
                with patch('tasks.WeeklyPurchase.thousand_things.time.sleep'):
                    self.assertTrue(getattr(task, method)())
                self.assertEqual(actions.mock_calls, [
                    call.select(task.I_TT_BUY_UP, interval=0.5),
                    call.confirm(task.I_TT_BUY_CONFIRM),
                ])

    def test_honor_uses_the_same_live_stock_for_each_purchase(self):
        for method, button in (('_honor_mystery_amulet', 'I_HONOR_BLUE'),
                               ('_honor_black_daruma_scrap', 'I_HONOR_BLACK')):
            with self.subTest(method=method):
                task = ScriptTask.__new__(ScriptTask)
                task.device = SimpleNamespace(image=None)
                task.screenshot = Mock()
                task.appear = Mock(return_value=True)
                task._special_check_remain = Mock(side_effect=[8, 3, 0])
                task.buy_more = Mock(return_value=True)
                task.O_MALL_RESOURCE_4 = Mock(spec=RuleOcr)
                task.O_MALL_RESOURCE_4.ocr.return_value = 100000
                with patch('tasks.Component.Buy.buy.time.sleep'):
                    self.assertTrue(getattr(task, method)(True))
                self.assertEqual(task.buy_more.call_args_list,
                                 [call(getattr(task, button))] * 2)

    def test_shrine_maximum_is_selected_before_confirming_the_updated_price(self):
        from tasks.Component.Buy.assets import BuyAssets
        task = ScriptTask.__new__(ScriptTask)
        task.screenshot = Mock()
        task.appear = Mock(return_value=True)
        task.shrine_check_money = Mock(return_value=True)
        actions = Mock()
        task.ui_click = actions.open
        task.appear_then_click = actions.select
        task.ui_get_reward = actions.confirm
        task.ui_click_until_disappear = Mock()
        with patch('tasks.WeeklyPurchase.shrine.time.sleep'):
            task.shrine_white_four()
        task.shrine_check_money.assert_called_once_with(200)
        self.assertEqual(actions.mock_calls, [
            call.open(task.I_S_WHITE_FOUR, task.I_S_CHECK_WHITE_FOUR),
            call.select(BuyAssets.I_BUY_PLUS, interval=0.4),
            call.open(task.I_S_BUY_WHITE_FOUR, task.I_S_CONFIRM_WHITE_FOUR),
            call.confirm(task.I_S_CONFIRM_WHITE_FOUR),
        ])


if __name__ == '__main__':
    unittest.main()
