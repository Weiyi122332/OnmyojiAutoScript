# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time
from copy import deepcopy

from tasks.GameUi.page import random_click
from typing import Union

from module.atom.image import RuleImage
from module.atom.ocr import RuleOcr
from module.atom.click import RuleClick
from module.logger import logger
from module.base.timer import Timer

from tasks.base_task import BaseTask
from tasks.Component.Buy.assets import BuyAssets

class Buy(BaseTask, BuyAssets):

    def _read_buy_quantity(self) -> int | None:
        """购买框随商品描述上下移动，数字区域跟随加号按钮定位。"""
        if not self.appear(self.I_BUY_ADD):
            return None
        x, y, _, height = self.I_BUY_ADD.roi_front
        number = deepcopy(self.O_BUY_NUMBER)
        number.roi = [x - 95, y, 52, height]
        current = number.ocr(self.device.image)
        return current if isinstance(current, int) and current > 0 else None

    def _set_buy_quantity(self, number: int) -> bool:
        if number <= 0:
            return False
        failed_reads = 0
        number_record = []
        ocr_timer = Timer(0.4).start()
        while True:
            self.screenshot()
            if not ocr_timer.reached():
                continue
            ocr_timer.reset()
            current = self._read_buy_quantity()
            if current is None:
                failed_reads += 1
                if failed_reads >= 3:
                    logger.warning('Purchase quantity could not be read; cancel purchase')
                    return False
                continue
            failed_reads = 0
            if current == number:
                return True
            number_record.append(current)
            if len(number_record) >= 4:
                if len(set(number_record[-4:])) == 1:
                    logger.warning(f'Purchase quantity stopped at {current}, expected {number}')
                    return False
                number_record.pop(0)
            button = self.I_BUY_ADD if current < number else self.I_BUY_SUB
            self.appear_then_click(button, interval=0.4)

    def _cancel_buy_dialog(self):
        # 各商店购买框均居中；右侧留白不覆盖商品或确认按钮。
        self.click(RuleClick(roi_front=(1050,580,40,30), roi_back=(1050,580,40,30),
                             name='BUY_CANCEL_DIALOG'))

    def buy_one(self, start_click: Union[RuleImage, RuleOcr, RuleClick],
                check_image: RuleImage):
        """
        购买一个物品
        :param check_image: 购买确认时候的图片
        :param start_click: 开始点击
        :return:
        """
        while 1:
            self.screenshot()

            if self.appear(check_image):
                break

            if isinstance(start_click, RuleImage):
                if self.appear_then_click(start_click, interval=1):
                    continue
            elif isinstance(start_click, RuleOcr):
                if self.ocr_appear_click(start_click, interval=1):
                    continue
            elif isinstance(start_click, RuleClick):
                if self.click(start_click, interval=1):
                    continue
        while 1:
            self.screenshot()

            if self.appear(self.I_BUY_RMB):
                # 用人民币购买的，就取消
                logger.warning('OAS do not support buy with RMB')
                while 1:
                    self.screenshot()
                    if not self.appear(self.I_BUY_RMB):
                        break
                    if self.click(self.C_BUY_CANCEL, interval=1):
                        continue
                return False

            if self.appear(self.I_BUY_SUCCESS):
                self.ui_click_until_smt_disappear(random_click(), self.I_BUY_SUCCESS, interval=0.8)
                logger.info('Get reward success')
                break

            if self.ui_reward_appear_click():
                while 1:
                    self.screenshot()
                    # 等待动画结束
                    if not self.appear(self.I_UI_REWARD, threshold=0.6):
                        logger.info('Get reward success')
                        break
                    # 一直点击
                    if self.ui_reward_appear_click():
                        continue
                break

            if self.click(self.C_BUY_ONE, interval=2.8):
                continue

        return True

    def buy_more(self, start_click: Union[RuleImage, RuleOcr, RuleClick],
                 number: int = None):
        """
        购买多个物品
        :param start_click:
        :param number: 不指定就是拉满
        :return:
        """
        try_click_count = 0
        while 1:
            self.screenshot()

            if self.appear(self.I_BUY_PLUS):
                break
            if try_click_count >= 5:
                logger.warning(f'Buy_more failed, try_click_count: {try_click_count}')
                logger.warning('Close the purchase')
                return

            if isinstance(start_click, RuleImage):
                if self.appear_then_click(start_click, interval=1):
                    try_click_count += 1
                    continue
            elif isinstance(start_click, RuleOcr):
                if self.ocr_appear_click(start_click, interval=1):
                    try_click_count += 1
                    continue
            elif isinstance(start_click, RuleClick):
                if self.click(start_click, interval=1):
                    try_click_count += 1
                    continue
        # 设置购买的数量
        if number is None:
            self.appear_then_click(self.I_BUY_PLUS, interval=0.4)
            time.sleep(0.5)
            self.appear_then_click(self.I_BUY_PLUS, interval=0.4)
        elif not self._set_buy_quantity(number):
            self._cancel_buy_dialog()
            return False

        buy_more_mx_click = 5

        # 购买确认
        while 1:
            self.screenshot()

            if self.ui_reward_appear_click():
                time.sleep(0.5)
                while 1:
                    self.screenshot()
                    # 等待动画结束
                    if not self.appear(self.I_UI_REWARD, threshold=0.6):
                        logger.info('Get reward success')
                        break
                    # 一直点击
                    if self.ui_reward_appear_click():
                        continue
                break

            if buy_more_mx_click <= 0:
                logger.warning('Buy more click times limit')
                return False

            # 如果这个购买已达上限
            if self.appear(self.I_UI_CONFIRM_SAMLL):
                self.ui_click_until_disappear(self.I_UI_CONFIRM_SAMLL, interval=1)
                logger.warning('Buy number limit')
                return False

            if self.click(self.C_BUY_MORE, interval=2):
                buy_more_mx_click -= 1
                continue

    def buy_check_money(self, target: RuleOcr, minimum: int):
        """
        检查钱是否足够
        :param target:
        :param minimum:
        :return:
        """
        self.screenshot()
        if not isinstance(target, RuleOcr):
            logger.error('Target is not RuleOcr')
            return False
        current = target.ocr(self.device.image)
        if not isinstance(current, int):
            logger.warning('OCR current money failed')
            return False
        if current >= minimum:
            logger.info('Money is enough')
            return True
        logger.info('Money is not enough')
        return False



if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = Buy(c, d)

