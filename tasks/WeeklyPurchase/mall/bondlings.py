# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time
from copy import deepcopy

from module.logger import logger
from module.atom.image import RuleImage
from module.atom.ocr import RuleOcr

from tasks.WeeklyPurchase.mall.navbar import MallNavbar
from tasks.Component.Buy.buy import Buy
from tasks.WeeklyPurchase.config import Bondlings as BondlingsConfig


class Bondlings(Buy, MallNavbar):

    def execute_bondlings(self, con: BondlingsConfig = None):
        if not con:
            con = self.config.weekly_purchase.bondlings
        if not con.enable:
            logger.info('Bondlings is disable')
            return
        self._enter_bondlings()

        # 购买石头
        self._bondlings_base(buy_button=self.I_BL_BUY_STONE, remain_number=self.O_BL_RES_STONE, check_class=2,
                             buy_number=con.bondling_stone, buy_max=10, buy_money=30)
        # 购买御魂
        self._bondlings_random_souls(con.random_soul)
        # 购买高级盘
        self._bondlings_base(buy_button=self.I_BL_BUY_HIGH, remain_number=self.O_BL_RES_HIGH, check_class=3,
                             buy_number=con.high_bondling_discs, buy_max=10, buy_money=50)
        # 购买中级盘
        self._bondlings_base(buy_button=self.I_BL_BUY_MEDIUM, remain_number=self.O_BL_RES_MEDIUM, check_class=4,
                             buy_number=con.medium_bondling_discs, buy_max=25, buy_money=20)

    def _bondlings_random_souls(self, buy_number: int):
        """先识别随机御魂，再定位同一商品的兑换按钮和剩余数量。"""
        if buy_number <= 0:
            return
        self.screenshot()
        if not self.appear(self.I_BL_SOULS):
            logger.warning('Random soul product is not visible; skip purchase')
            return

        x, y, _, _ = self.I_BL_SOULS.roi_front
        # 商品图可能随排列变化而移动；只在它下方寻找兑换按钮。
        buy_button = deepcopy(self.I_BL_BUY_SOULS)
        buy_button.roi_back = (x + 45, y + 202, 110, 54)
        remain_number = deepcopy(self.O_BL_RES_SOULS)
        remain_number.roi = [x - 53, y + 15, 31, 34]
        remain_number.area = list(remain_number.roi)
        self._bondlings_base(buy_button=buy_button, remain_number=remain_number, check_class=1,
                             buy_number=buy_number, buy_max=30, buy_money=20)

    def _bondlings_base(self, buy_button: RuleImage, remain_number: RuleOcr, check_class: int,
                       buy_number: int, buy_max: int, buy_money: int):
        """

        :param buy_button: 对应的兑换按钮
        :param remain_number: 对应的检查剩余数量的ocr
        :param check_money: 对应的检查剩余金钱的第一个
        :param buy_number: 购买多少
        :param buy_max: 这一个种类一次性最多购买多少
        :param buy_money: 每一个购买的钱数
        :return:
        """
        logger.hr(buy_button.name, 3)
        if buy_number == 0:
            logger.info('Buy number is 0')
            return
        self.screenshot()

        # 检查是否出现了购买按钮
        if not self.appear(buy_button):
            logger.warning('Buy button is not appear')
            return
        # 检查剩余数量
        _remain = remain_number.ocr(self.device.image)
        if _remain == 0:
            logger.warning('本周契灵御魂已经买光')
            return
        if _remain < buy_number:
            logger.warning(f'Remain number is {_remain}, buy number is {buy_number}')
            buy_number = _remain
        # 检查金钱
        cu, re, total = self.O_BL_CHECK_MONEY.ocr(self.device.image)
        if cu + re != total:
            logger.warning('Check money is error')
            logger.warning(f'cu: {cu}, re: {re}, total: {total}')
            return
        money_enough = cu >= buy_money * buy_number
        if not money_enough:
            logger.warning(f'Money is not enough {cu}')
            # 判断够不够买2个
            if cu < buy_money:
                logger.warning('Money is not enough')
                return
            buy_number = cu // buy_money
        # 购买
        logger.info(f'Buy number is {buy_number}')
        if buy_number >= buy_max:
            buy_cycles_number = buy_number // buy_max
            buy_res_number = buy_number % buy_max
        else:
            buy_cycles_number = None
            buy_res_number = buy_number

        if buy_cycles_number:
            for i in range(buy_cycles_number):
                if self.buy_more(buy_button, buy_max) is False:
                    return False
                self.device.click_record_clear()
                time.sleep(0.5)
        if buy_res_number:
            self.buy_more(buy_button, buy_res_number)
            self.device.click_record_clear()
            time.sleep(0.5)


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = Bondlings(c, d)

    t.execute_bondlings()
