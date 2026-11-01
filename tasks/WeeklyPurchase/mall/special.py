# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time
import re

from module.logger import logger
from module.atom.image import RuleImage

from tasks.GameUi.page import page_main, page_guild
from tasks.WeeklyPurchase.mall.navbar import MallNavbar
from tasks.Component.Buy.buy import Buy
from tasks.WeeklyPurchase.assets import WeeklyPurchaseAssets
from tasks.WeeklyPurchase.config import SpecialRoom


class Special(Buy, MallNavbar):

    def execute_special(self, con: SpecialRoom = None):
        if not con:
            con = self.config.weekly_purchase.special_room
        if not con.enable:
            logger.info('Special room is not enable')
            return
        if not self._enter_special():
            logger.warning('Enter special mall failed')
            return
        # 向下滑找到购买的物品
        totem_bought, medium_bought, low_bought = False, False, False
        while 1:
            self.screenshot()
            if not totem_bought and self.appear(self.I_SP_BUY_TOTEM):
                self._special_totom(con.totem_pass)
                totem_bought = True
            if not medium_bought and self.appear(self.I_SP_BUY_MEDIUM):
                self._special_medium(con.medium_bondling_discs)
                medium_bought = True
            if not low_bought and self.appear(self.I_SP_BUY_LOW):
                self._special_low(con.low_bondling_discs)
                low_bought = True

            if totem_bought and medium_bought and low_bought:
                logger.info('All bought')
                break
            if self.appear(self.I_SP_SWIPE_CHECK):
                # 如果滑动到底了
                logger.info('Swipe to bottom')
                break

            if self.swipe(self.S_SP_DOWN, interval=2):
                time.sleep(2)

    def _special_totom(self, totem_pass: bool):
        """
        购买御灵，要求必须下滑出现御灵
        :return:
        """
        logger.hr('Buy totem', 3)
        if not totem_pass:
            logger.info('Buy totem is disabled')
            return
        return self.buy_all_remaining(
            self.I_SP_BUY_TOTEM, lambda: self._special_check_remain(self.I_SP_BUY_TOTEM))

    def _special_medium(self, enabled: bool = True):
        """
        购买中级盘，要求必须下滑出现中级盘
        :return:
        """
        logger.hr('Buy medium', 3)
        if not enabled:
            logger.info('Buy medium is disabled')
            return
        return self.buy_all_remaining(
            self.I_SP_BUY_MEDIUM, lambda: self._special_check_remain(self.I_SP_BUY_MEDIUM))

    def _special_low(self, enabled: bool = True):
        """
        购买低级盘，要求必须下滑出现低级盘
        :return:
        """
        logger.hr('Buy low', 3)
        if not enabled:
            logger.info('Buy low is disabled')
            return
        return self.buy_all_remaining(
            self.I_SP_BUY_LOW, lambda: self._special_check_remain(self.I_SP_BUY_LOW))

    def _special_check_remain(self, target: RuleImage):
        """
        检查这个种类的剩余， 要求必须这个出现在当前的页面
        :param target:
        :return:
        """
        upper_midpoint = target.roi_front[0] + target.roi_front[2] // 2, target.roi_front[1]
        # 重设roi
        roi = self.O_SP_RES_NUMBER.roi
        self.O_SP_RES_NUMBER.roi[0] = upper_midpoint[0] - roi[2] // 2
        self.O_SP_RES_NUMBER.roi[1] = upper_midpoint[1] - roi[3]
        # logger.info(f'图片的ROI是: {target.roi_front}')
        # logger.info(f'上中点是：{upper_midpoint}')
        # logger.info(f'数字的ROI是: {self.O_SP_RES_NUMBER.roi}')
        txt = self.O_SP_RES_NUMBER.ocr(self.device.image)
        txt = txt.replace('？', '2').replace('?', '2').replace(':', '；').replace('火', '次').replace('教', '数').replace('刺', '剩').replace('头', '买')
        match = re.search(r'(\d+)', txt)
        result = int(match.group(1)) if match else 0
        logger.info(f'Remain [{result}]')
        return result


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = Special(c, d)

    t.execute_special()
