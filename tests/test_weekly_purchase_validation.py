"""Purchase limits and failure cases found while checking the current shops."""

from collections import deque
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from module.exception import GamePageUnknownError
from module.device.device import Device
from module.atom.ocr import RuleOcr
from tasks.Component.Buy.buy import Buy
from tasks.WeeklyPurchase.assets import WeeklyPurchaseAssets as Assets
from tasks.WeeklyPurchase.config import FriendshipPoints, HonorRoom, MedalRoom
from tasks.WeeklyPurchase.mall.scales import Scales
from tasks.WeeklyPurchase.script_task import ScriptTask


def task_without_device():
    task = ScriptTask.__new__(ScriptTask)
    task.device = SimpleNamespace(image=None, click_record_clear=Mock())
    task.screenshot = Mock()
    task.appear = Mock(return_value=True)
    task.buy_more = Mock(return_value=True)
    task._cancel_buy_dialog = Mock()
    return task


class PurchaseLimitsTest(unittest.TestCase):
    def setUp(self):
        self.task = task_without_device()
        sleep = patch('tasks.WeeklyPurchase.mall.special.time.sleep')
        sleep.start()
        self.addCleanup(sleep.stop)

    def test_totem_uses_maximum_button_for_full_and_remaining_stock(self):
        for remaining in (40, 17):
            with self.subTest(remaining=remaining):
                self.task.buy_more.reset_mock()
                self.task._special_check_remain = Mock(side_effect=[remaining, 0])
                self.task._special_totom(True)
                self.task.buy_more.assert_called_once_with(self.task.I_SP_BUY_TOTEM)

    def test_totem_does_not_open_a_purchase_without_stock(self):
        self.task._special_check_remain = Mock(return_value=0)
        self.task._special_totom(True)
        self.task.buy_more.assert_not_called()

    def test_totem_reaches_purchase_using_the_up_arrow_without_single_increments(self):
        task = self.task
        state = SimpleNamespace(open=False, quantity=1, purchased=False)
        task._special_check_remain = Mock(side_effect=[40, 0])
        task.buy_more = lambda *args, **kwargs: Buy.buy_more(task, *args, **kwargs)
        task._set_buy_quantity = Mock(side_effect=AssertionError('must use the maximum button'))

        def appear(rule, **kwargs):
            if rule is task.I_SP_BUY_TOTEM:
                return not state.open
            return rule is task.I_BUY_PLUS and state.open

        def click_image(rule, **kwargs):
            if rule is task.I_SP_BUY_TOTEM:
                state.open = True
            elif rule is task.I_BUY_PLUS:
                self.assertTrue(state.open)
                state.quantity = 40
            else:
                self.fail(f'Unexpected quantity button: {rule}')
            return True

        def confirm(rule, **kwargs):
            self.assertIs(rule, task.C_BUY_MORE)
            self.assertEqual(state.quantity, 40)
            state.purchased = True
            return True

        task.appear = Mock(side_effect=appear)
        task.appear_then_click = Mock(side_effect=click_image)
        task.click = Mock(side_effect=confirm)
        task.ui_reward_appear_click = Mock(side_effect=lambda: state.purchased)
        task._special_totom(True)

        self.assertTrue(state.purchased)
        task._set_buy_quantity.assert_not_called()
        task.click.assert_called_once_with(task.C_BUY_MORE, interval=2)
        self.assertEqual([call.args[0] for call in task.appear_then_click.call_args_list],
                         [task.I_SP_BUY_TOTEM, task.I_BUY_PLUS, task.I_BUY_PLUS])

    def test_hundred_disc_buys_all_live_stock_without_fixed_batches(self):
        self.task._special_check_remain = Mock(side_effect=[100, 55, 7, 0])
        self.task._special_low(True)
        self.assertEqual([call.args for call in self.task.buy_more.call_args_list],
                         [(self.task.I_SP_BUY_LOW,)] * 3)

    def test_failed_batch_does_not_attempt_the_remainder(self):
        self.task._special_check_remain = Mock(return_value=100)
        self.task.buy_more.return_value = False
        self.task._special_low(True)
        self.assertEqual(self.task.buy_more.call_count, 1)

    def test_medal_soul_checks_medals_instead_of_gold(self):
        self.task._enter_medal = Mock(return_value=True)
        self.task.buy_mall_one = Mock()
        self.task.execute_medal(MedalRoom(enable=True, random_soul=True))
        self.assertIs(self.task.buy_mall_one.call_args.kwargs['money_ocr'], self.task.O_MALL_RESOURCE_3)

    def test_failed_category_navigation_does_not_buy_in_another_shop(self):
        for category, config in (('honor', HonorRoom(enable=True, mystery_amulet=True)),
                                 ('friendship', FriendshipPoints(enable=True, white_daruma=True)),
                                 ('medal', MedalRoom(enable=True, black_daruma=True))):
            with self.subTest(category=category):
                task = task_without_device()
                setattr(task, '_enter_' + category, Mock(return_value=False))
                task.buy_mall_one = Mock()
                task._honor_mystery_amulet = Mock()
                getattr(task, 'execute_' + category)(config)
                task.buy_mall_one.assert_not_called()
                task._honor_mystery_amulet.assert_not_called()

    def test_friendship_can_buy_one_affordable_item(self):
        money = SimpleNamespace(ocr=Mock(return_value=100))
        self.task.buy_mall_more(self.task.I_FS_BROKEN, False, money, 10, 99, 100)
        self.assertEqual(self.task.buy_more.call_args.args[1], 1)

    def test_orochi_buys_live_stock_and_stops_when_currency_is_exhausted(self):
        for stock, balances, purchases in (([40, 3, 0], [2434, 584], 2),
                                            ([40, 39], [75, 25], 1), ([0], [], 0)):
            with self.subTest(stock=stock, balances=balances):
                self.task.O_SCA_NUMBER_OROCHI = SimpleNamespace(ocr=Mock(side_effect=stock))
                self.task.O_SCA_RES_OROCHI = Mock(spec=RuleOcr)
                self.task.O_SCA_RES_OROCHI.ocr.side_effect = [(money, 8000 - money, 8000) for money in balances]
                self.task._scales_buy_more = Mock(return_value=True)
                self.task._scales_orochi_new(True)
                self.assertEqual([call.args for call in self.task._scales_buy_more.call_args_list],
                                 [(self.task.I_SCA_OROCHI_SCALES,)] * purchases)

    def test_sea_keeps_buying_until_even_the_final_single_box_is_gone(self):
        self.task.config = SimpleNamespace(weekly_purchase=SimpleNamespace(scales=SimpleNamespace(enable_book_auto=False)))
        self.task.O_SCA_NUMBER_SEA = SimpleNamespace(ocr=Mock(side_effect=[30, 19, 1, 0]))
        self.task.O_SCA_RES_SEA = Mock(spec=RuleOcr)
        self.task.O_SCA_RES_SEA.ocr.return_value = 10197
        self.task._scales_buy_sea_more = Mock(return_value=True)
        self.task._scales_sea(True)
        self.assertEqual([call.args for call in self.task._scales_buy_sea_more.call_args_list],
                         [(self.task.I_SCA_PICTURE_BOOK,)] * 3)

    def test_sea_auto_mode_is_checked_before_payment(self):
        self.task.appear.side_effect = lambda rule: rule in (self.task.I_BUY_PLUS, self.task.I_SCA_SEA_AUTO_OFF)
        self.task._cancel_buy_dialog = Mock()
        self.task._set_buy_quantity = Mock()
        self.assertFalse(self.task._scales_buy_confirm(self.task.I_SCA_PICTURE_BOOK, 10, auto_select=True))
        self.task._cancel_buy_dialog.assert_called_once()
        self.task._set_buy_quantity.assert_not_called()

    def test_soul_purchase_failure_does_not_click_confirmation(self):
        self.task._scales_buy_confirm = Mock(return_value=False)
        self.task.click = Mock()
        self.assertFalse(self.task._scales_buy_more(self.task.I_SCA_OROCHI_SCALES, 10))
        self.task.click.assert_not_called()

    def test_soul_payment_failure_stops_before_the_repeated_click_guard(self):
        for method in ('_scales_buy_more', '_scales_buy_sea_more'):
            with self.subTest(method=method):
                task = task_without_device()
                task._scales_buy_confirm = Mock(return_value=True)
                task.appear.return_value = False
                task.click = Mock(return_value=True)
                self.assertFalse(getattr(task, method)(task.I_SCA_PICTURE_BOOK))
                self.assertGreater(task.click.call_count, 0)
                self.assertLess(task.click.call_count, 10)

    def test_missing_boss_stops_after_three_scrolls(self):
        target = self.task.I_SCA_DEMON_BOSS_1
        self.task.appear.side_effect = lambda rule: rule is self.task.I_SCA_DEMON_CLOSE
        self.task.swipe = Mock(return_value=True)
        self.task.ui_click = Mock()
        with self.assertRaises(GamePageUnknownError):
            self.task._scales_select_demon(target)
        self.assertEqual(self.task.swipe.call_count, 3)
        self.task.ui_click.assert_not_called()

    def test_demon_reselects_the_boss_until_its_actual_stock_is_empty(self):
        self.task.O_SCA_NUMBER_DEMON = SimpleNamespace(ocr=Mock(side_effect=[50, 17, 0]))
        self.task.O_SCA_RES_DEMON = Mock(spec=RuleOcr)
        self.task.O_SCA_RES_DEMON.ocr.return_value = 10000
        self.task.O_SCA_DEMON_POSTION = SimpleNamespace(ocr=Mock(return_value='一'))
        self.task._scales_select_demon = Mock()
        self.task._scales_buy_more = Mock(return_value=True)
        self.assertTrue(self.task._scales_demon(True))
        self.assertEqual(self.task._scales_select_demon.call_count, 2)
        self.assertEqual([call.args for call in self.task._scales_buy_more.call_args_list],
                         [(self.task.I_SCA_DEMON_BUY,)] * 2)

    def test_enabled_guild_skin_tickets_do_not_require_a_separate_quantity(self):
        self.task.check_remain = Mock(side_effect=[5, 2, 0])
        self.task.O_GUILD_TOTAL = Mock(spec=RuleOcr)
        self.task.O_GUILD_TOTAL.ocr.return_value = 1000
        self.assertTrue(self.task._guild_skin_ticket())
        self.assertEqual([call.args for call in self.task.buy_more.call_args_list],
                         [(self.task.I_GUILD_SKIN,)] * 2)


class QuantityRecognitionTest(unittest.TestCase):
    def test_quantity_uses_the_up_arrow_then_corrects_without_a_false_click_limit(self):
        for target, maximum in ((40, 40), (23, 50), (20, 30)):
            with self.subTest(target=target, maximum=maximum):
                task = task_without_device()
                quantity = [1]
                task.device.click_record = deque(maxlen=15)
                task.device.click_record_clear.side_effect = task.device.click_record.clear
                task._read_buy_quantity = Mock(side_effect=lambda: quantity[0])

                def select_quantity(rule, **kwargs):
                    task.device.click_record.append(str(rule))
                    Device.click_record_check(task.device)
                    if rule is task.I_BUY_PLUS:
                        quantity[0] = maximum
                    elif rule is task.I_BUY_SUB:
                        quantity[0] -= 1
                    else:
                        self.fail(f'Unexpected quantity button: {rule}')
                    return True

                task.appear_then_click = Mock(side_effect=select_quantity)
                timer = SimpleNamespace(reached=lambda: True, reset=lambda: None)
                timer.start = lambda: timer
                with patch('tasks.Component.Buy.buy.Timer', return_value=timer):
                    self.assertTrue(task._set_buy_quantity(target))
                self.assertEqual(quantity[0], target)
                self.assertEqual([call.args[0] for call in task.appear_then_click.call_args_list],
                                 [task.I_BUY_PLUS] + [task.I_BUY_SUB] * (maximum - target))

    def test_number_roi_follows_the_quantity_button(self):
        task = task_without_device()
        task.I_BUY_ADD = deepcopy(task.I_BUY_ADD)
        task.I_BUY_ADD.roi_front = [673, 455, 51, 54]
        task.O_BUY_NUMBER = deepcopy(task.O_BUY_NUMBER)
        rois = []

        def ocr(rule, image):
            rois.append(rule.roi)
            return 1

        with patch('module.atom.ocr.RuleOcr.ocr', new=ocr):
            self.assertEqual(task._read_buy_quantity(), 1)
        self.assertEqual(rois, [[578, 455, 52, 54]])

    def test_unknown_or_stalled_quantity_never_reaches_purchase_confirmation(self):
        for readings in ((None, None, None), (2, 2, 2, 2)):
            with self.subTest(readings=readings):
                task = task_without_device()
                task._read_buy_quantity = Mock(side_effect=readings)
                task.appear_then_click = Mock(return_value=True)
                timer = SimpleNamespace(reached=lambda: True, reset=lambda: None)
                timer.start = lambda: timer
                with patch('tasks.Component.Buy.buy.Timer', return_value=timer):
                    self.assertFalse(task._set_buy_quantity(3))
                if readings[0] is None:
                    task.appear_then_click.assert_not_called()
                task.device.click_record_clear.assert_not_called()

    def test_existing_quantity_above_target_is_reduced(self):
        task = task_without_device()
        task._read_buy_quantity = Mock(side_effect=[3, 2, 1])
        task.appear_then_click = Mock(return_value=True)
        timer = SimpleNamespace(reached=lambda: True, reset=lambda: None)
        timer.start = lambda: timer
        with patch('tasks.Component.Buy.buy.Timer', return_value=timer):
            self.assertTrue(task._set_buy_quantity(1))
        self.assertTrue(all(call.args[0] is task.I_BUY_SUB for call in task.appear_then_click.call_args_list))

    def test_hundred_disc_is_recognized_near_the_top_after_scrolling_to_bottom(self):
        rule = deepcopy(Assets.I_SP_BUY_LOW)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        image = rule.image
        height, width = image.shape[:2]
        frame[134:134 + height, 621:621 + width] = image
        self.assertTrue(rule.template_match(frame))


if __name__ == '__main__':
    unittest.main()
