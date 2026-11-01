# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time

from module.logger import logger
from module.exception import GamePageUnknownError

from tasks.Component.Buy.buy import Buy
from tasks.WeeklyPurchase.mall.navbar import MallNavbar
from tasks.WeeklyPurchase.config import Scales as ScalesConfig
from tasks.Utils.config_enum import DemonClass


class Scales(Buy, MallNavbar):

    def execute_scales(self, con: ScalesConfig=None):
        if not con:
            con = self.config.weekly_purchase.scales
        if not con.enable:
            logger.info('Scales is not enable')
            return
        self._enter_scales()

        # 朴素的御魂
        self._scales_orochi_new(con.orochi_scales)
        # 首领御魂
        self._scales_demon(con.demon_souls, con.demon_class, con.demon_position)
        # 海国御魂
        self._scales_sea(con.picture_book_scrap, con.picture_book_rule)

    def _scales_buy_confirm(self, start_click, number: int = None, auto_select: bool | None = None):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            self.screenshot()
            if self.appear(self.I_BUY_PLUS):
                break
            if self.appear(self.I_SCA_SELECT_1) and self.appear(self.I_SCA_SELECT_2):
                return False
            if self.appear_then_click(start_click, interval=1):
                continue
        else:
            logger.warning('Soul purchase dialog did not open')
            return False
        if auto_select is not None:
            game_auto_select = not self.appear(self.I_SCA_SEA_AUTO_OFF)
            if game_auto_select != auto_select:
                logger.warning('海汐礼盒自动选择与脚本配置不一致，请先在游戏内完成御魂排序')
                self._cancel_buy_dialog()
                return False
        # 设置购买的数量
        if number is None:
            self.appear_then_click(self.I_BUY_PLUS, interval=0.4)
            time.sleep(0.5)
            self.appear_then_click(self.I_BUY_PLUS, interval=0.4)
        elif not self._set_buy_quantity(number):
            self._cancel_buy_dialog()
            return False
        return True

    def _scales_buy_more(self, start_click, number: int = None, auto_select: bool | None = None):
        # 重写
        if not self._scales_buy_confirm(start_click, number, auto_select):
            return False

        # 购买确认
        attempts = 5
        while 1:
            self.screenshot()
            if self.appear(self.I_SCA_SIX_STAR) or self.appear(self.I_SCA_REWARD):
                logger.info('Scales buy success')
                time.sleep(1)
                while 1:
                    self.screenshot()
                    if not self.appear(self.I_SCA_SIX_STAR):
                        break
                    if self.click(self.C_SCA_SOULS_GET, interval=1):
                        continue
                # 收获购买的东西
                logger.info('Scales get success')
                break

            if attempts <= 0:
                logger.warning('Soul purchase was not completed; stop confirming')
                return False
            if self.click(self.C_BUY_MORE, interval=5):
                attempts -= 1
                continue

    def _scales_buy_sea_more(self, start_click, number: int = None):
        if not self._scales_buy_confirm(start_click, number, auto_select=False):
            return False
        attempts = 5
        while 1:
            self.screenshot()
            if self.appear(self.I_SCA_SELECT_1):
                break
            if attempts <= 0:
                logger.warning('Sea soul purchase was not completed; stop confirming')
                return False
            if self.click(self.C_BUY_MORE, interval=3):
                attempts -= 1
                continue
        logger.info('Scales start select souls')
        # 选择魂
        while 1:
            self.screenshot()
            if self.appear(self.I_SCA_SIX_STAR):
                logger.info('Scales buy success')
                time.sleep(1.8)
                while 1:
                    self.screenshot()
                    if not self.appear(self.I_SCA_SIX_STAR):
                        break
                    if self.click(self.C_SCA_SOULS_GET, interval=1.6):
                        continue
                # 收获购买的东西
                logger.info('Scales get success')
                break

            if self.appear_then_click(self.I_SCA_SELECT_1, interval=1.6):
                continue

    def _scales_orochi_new(self, enabled: bool):
        return self._scales_orochi(enabled)

    def _scales_orochi(self, enabled: bool):
        """启用后按实际剩余额度兑换朴素御魂。"""
        logger.hr('Scales orochi', 3)
        if not enabled:
            return
        return self.buy_all_remaining(
            self.I_SCA_OROCHI_SCALES, self.O_SCA_NUMBER_OROCHI,
            money_ocr=self.O_SCA_RES_OROCHI, unit_price=50,
            purchase=self._scales_buy_more)

    def _scales_select_demon(self, target_class):
        """新版首领列表有五列，先进入列表，再滚动查找商品图。"""
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            self.screenshot()
            if self.appear(self.I_SCA_DEMON_CLOSE):
                break
            self.appear_then_click(self.I_SCA_DEMON_SOULS, interval=1)
        else:
            raise GamePageUnknownError('首领御魂列表未打开')
        for attempt in range(4):
            self.screenshot()
            if self.appear(target_class):
                self.ui_click(target_class, self.I_SCA_DEMON_BUY)
                return
            if attempt < 3:
                self.swipe(self.S_SCA_DEMON_LIST, interval=0.5)
                time.sleep(0.5)
        raise GamePageUnknownError(f'首领御魂商品未找到: {target_class.name}')

    def _scales_demon(self, enabled: bool, buy_class: DemonClass=DemonClass.ODOKURO, buy_position: int=1):
        """按实际剩余额度兑换选定首领和号位的御魂。"""
        logger.hr('Scales demon', 3)
        if not enabled:
            return
        match_class = {
            DemonClass.TSUCHIGUMO: self.I_SCA_DEMON_BOSS_1,
            DemonClass.OBOROGURUMA: self.I_SCA_DEMON_BOSS_2,
            DemonClass.ODOKURO: self.I_SCA_DEMON_BOSS_3,
            DemonClass.NAMAZU: self.I_SCA_DEMON_BOSS_4,
            DemonClass.SHINKIRO: self.I_SCA_DEMON_BOSS_5,
            DemonClass.GHOSTLY_SONGSTRESS: self.I_SCA_DEMON_BOSS_6,
            DemonClass.BOSS_7: self.I_SCA_DEMON_BOSS_7,
        }
        match_position = {
            1: self.C_SCA_DEMON_1, 2: self.C_SCA_DEMON_2, 3: self.C_SCA_DEMON_3,
            4: self.C_SCA_DEMON_4, 5: self.C_SCA_DEMON_5, 6: self.C_SCA_DEMON_6,
        }
        target_class = match_class[buy_class]
        target_position = match_position[buy_position]
        target_number = {1: '一', 2: '二', 3: '三', 4: '四', 5: '五', 6: '六'}[buy_position]

        def purchase(_button):
            self._scales_select_demon(target_class)
            position_deadline = time.monotonic() + 8
            while time.monotonic() < position_deadline:
                self.screenshot()
                if target_number in self.O_SCA_DEMON_POSTION.ocr(self.device.image):
                    break
                self.click(target_position, interval=0.7)
            else:
                raise GamePageUnknownError('首领御魂部位未能确认')
            if self._scales_buy_more(self.I_SCA_DEMON_BUY) is False:
                return False
            # 剩余额度显示在类别页，每次购买后回到同一页面再读取。
            while True:
                self.screenshot()
                if self.appear(self.I_SCA_DEMON_SOULS):
                    return True
                if self.appear_then_click(self.I_UI_BACK_RED, interval=1):
                    continue
                self.click(self.C_SCA_SOULS_BACK, interval=1)

        return self.buy_all_remaining(
            self.I_SCA_DEMON_SOULS, self.O_SCA_NUMBER_DEMON,
            money_ocr=self.O_SCA_RES_DEMON, unit_price=50, purchase=purchase)

    def _scales_sea(self, enabled: bool, buy_rule: str='auto'):
        """启用后按实际剩余额度兑换海汐御魂。"""
        logger.hr('Scales sea', 3)
        if not enabled:
            return
        if self.config.weekly_purchase.scales.enable_book_auto:
            purchase = lambda button: self._scales_buy_more(button, auto_select=True)
        else:
            purchase = self._scales_buy_sea_more
        return self.buy_all_remaining(
            self.I_SCA_PICTURE_BOOK, self.O_SCA_NUMBER_SEA,
            money_ocr=self.O_SCA_RES_SEA, unit_price=200, purchase=purchase)


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('日常1')
    d = Device(c)
    t = Scales(c, d)

    t._scales_orochi_new(10)
