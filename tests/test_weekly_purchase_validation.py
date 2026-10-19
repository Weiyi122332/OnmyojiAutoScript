"""Purchase limits and failure cases found while checking the current shops."""

from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from module.exception import GamePageUnknownError
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
    return task


class PurchaseLimitsTest(unittest.TestCase):
    def setUp(self):
        self.task = task_without_device()
        sleep = patch('tasks.WeeklyPurchase.mall.special.time.sleep')
        sleep.start()
        self.addCleanup(sleep.stop)

    def test_totem_buys_only_remaining_tickets(self):
        self.task._special_check_remain = Mock(return_value=17)
        self.task._special_totom(True)
        self.assertEqual(self.task.buy_more.call_args.args[1], 17)

    def test_hundred_disc_batches_never_use_unspecified_maximum(self):
        self.task._special_check_remain = Mock(return_value=100)
        self.task._special_low(73)
        self.assertEqual([call.args[1] for call in self.task.buy_more.call_args_list], [50, 23])

    def test_failed_batch_does_not_attempt_the_remainder(self):
        self.task._special_check_remain = Mock(return_value=100)
        self.task.buy_more.return_value = False
        self.task._special_low(73)
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

    def test_orochi_respects_requested_stock_and_affordable_quantity(self):
        for requested, stock, money, expected in ((10, 40, 2434, 10), (10, 3, 2434, 3),
                                                   (10, 40, 75, 1)):
            with self.subTest(requested=requested, stock=stock, money=money):
                self.task.O_SCA_NUMBER_OROCHI = SimpleNamespace(ocr=Mock(return_value=stock))
                self.task.O_SCA_RES_OROCHI = SimpleNamespace(ocr=Mock(return_value=(money, 8000 - money, 8000)))
                self.task._scales_buy_more = Mock()
                self.task._scales_orochi_new(requested)
                self.task._scales_buy_more.assert_called_once_with(self.task.I_SCA_OROCHI_SCALES, expected)

    def test_sea_keeps_the_final_single_box_and_explicit_batch_sizes(self):
        self.task.config = SimpleNamespace(weekly_purchase=SimpleNamespace(scales=SimpleNamespace(enable_book_auto=False)))
        self.task.O_SCA_NUMBER_SEA = SimpleNamespace(ocr=Mock(return_value=30))
        self.task.O_SCA_RES_SEA = SimpleNamespace(ocr=Mock(return_value=10197))
        self.task._scales_buy_sea_more = Mock(return_value=True)
        self.task._scales_sea(21)
        self.assertEqual([call.args[1] for call in self.task._scales_buy_sea_more.call_args_list], [10, 10, 1])

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

    def test_missing_boss_stops_after_three_scrolls(self):
        target = self.task.I_SCA_DEMON_BOSS_1
        self.task.appear.side_effect = lambda rule: rule is self.task.I_SCA_DEMON_CLOSE
        self.task.swipe = Mock(return_value=True)
        self.task.ui_click = Mock()
        with self.assertRaises(GamePageUnknownError):
            self.task._scales_select_demon(target)
        self.assertEqual(self.task.swipe.call_count, 3)
        self.task.ui_click.assert_not_called()


class QuantityRecognitionTest(unittest.TestCase):
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
