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
        self._bondlings_base(self.I_BL_BUY_STONE, self.O_BL_RES_STONE, con.bondling_stone, 30)
        # 购买御魂
        self._bondlings_random_souls(con.random_soul)
        # 购买高级盘
        self._bondlings_base(self.I_BL_BUY_HIGH, self.O_BL_RES_HIGH, con.high_bondling_discs, 50)
        # 购买中级盘
        self._bondlings_base(self.I_BL_BUY_MEDIUM, self.O_BL_RES_MEDIUM, con.medium_bondling_discs, 20)

    def _bondlings_random_souls(self, enabled: bool):
        """先识别随机御魂，再定位同一商品的兑换按钮和剩余数量。"""
        if not enabled:
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
        self._bondlings_base(buy_button, remain_number, enabled, 20)

    def _bondlings_base(self, buy_button: RuleImage, remain_number: RuleOcr,
                       enabled: bool, unit_price: int):
        """启用的契灵商品按实际剩余额度买完。"""
        logger.hr(buy_button.name, 3)
        if not enabled:
            return
        return self.buy_all_remaining(
            buy_button, remain_number, money_ocr=self.O_BL_CHECK_MONEY, unit_price=unit_price)


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = Bondlings(c, d)

    t.execute_bondlings()
