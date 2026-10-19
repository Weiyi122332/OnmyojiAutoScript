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

            if self.click(self.C_BUY_MORE, interval=5):
                continue

    def _scales_buy_sea_more(self, start_click, number: int = None):
        if not self._scales_buy_confirm(start_click, number, auto_select=False):
            return False
        while 1:
            self.screenshot()
            if self.appear(self.I_SCA_SELECT_1):
                break
            if self.click(self.C_BUY_MORE, interval=3):
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

    def _scales_orochi_new(self, buy_number: int):
        return self._scales_orochi(buy_number)

    def _scales_orochi(self, buy_number: int):
        """
        要求必须是在御魂礼盒界面
        :param buy_number:
        :return:
        """
        logger.hr('Scales orochi', 3)
        if buy_number == 0:
            logger.info('The purchase quantity of Scales orochi is 0')
            return
        self.screenshot()
        # 检查是否出现了购买按钮
        if not self.appear(self.I_SCA_OROCHI_SCALES):
            logger.warning('Scales orochi is not appear')
            return
        # 检查剩余数量
        remain_number = self.O_SCA_NUMBER_OROCHI.ocr(self.device.image)
        if remain_number == 0:
            logger.warning(f'The remaining purchase quantity of xx is {remain_number}')
            return
        if remain_number < buy_number:
            buy_number = remain_number
            logger.warning(f'Remaining purchase quantity is {remain_number}, buy_number is {buy_number}')
        # 检查钱是否够
        cu, res, total = self.O_SCA_RES_OROCHI.ocr(self.device.image)
        if cu + res != total:
            logger.warning('OCR error')
            return
        buy_number = min(buy_number, cu // 50)
        if buy_number <= 0:
            logger.warning('Scales orochi money is not enough')
            return
        self._scales_buy_more(self.I_SCA_OROCHI_SCALES, buy_number)
        time.sleep(0.5)

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

    def _scales_demon(self, buy_number: int, buy_class: DemonClass=DemonClass.ODOKURO, buy_position: int=1):
        """
        要求必须是在御魂礼盒界面
        :param buy_number:
        :param buy_class:
        :param buy_position:
        :return:
        """
        logger.hr('Scales demon', 3)
        if buy_number == 0:
            logger.info('The purchase quantity of Scales demon is 0')
            return
        self.screenshot()
        # 检查是否出现了购买按钮
        if not self.appear(self.I_SCA_DEMON_SOULS):
            logger.warning('Scales demon is not appear')
            return
        # 检查剩余数量
        remain_number = self.O_SCA_NUMBER_DEMON.ocr(self.device.image)
        if remain_number == 0:
            logger.warning(f'The remaining purchase quantity of xx is {remain_number}')
            return
        if remain_number < buy_number:
            buy_number = remain_number
            logger.warning(f'Remaining purchase quantity is {remain_number}, buy_number is {buy_number}')
        # 检查钱是否够
        current_money = self.O_SCA_RES_DEMON.ocr(self.device.image)
        if not isinstance(current_money, int):
            logger.warning('OCR error')
            return
        money_enough = current_money >= 50*buy_number
        if not money_enough:
            logger.warning('Scales demon money is not enough')
            # 判断够不够买2个
            if current_money < 100:
                logger.warning('Scales demon money can not buy two')
                return
            buy_number = current_money // 50
        # 选择购买的御魂和位置
        logger.info(f'Scales demon buy {buy_number} {buy_class} in {buy_position} position')
        match_class = {
            DemonClass.TSUCHIGUMO: self.I_SCA_DEMON_BOSS_1,  # 土蜘蛛
            DemonClass.OBOROGURUMA: self.I_SCA_DEMON_BOSS_2,  # 胧车
            DemonClass.ODOKURO: self.I_SCA_DEMON_BOSS_3,  #
            DemonClass.NAMAZU: self.I_SCA_DEMON_BOSS_4,  # 鲶鱼
            DemonClass.SHINKIRO: self.I_SCA_DEMON_BOSS_5,  # 神木鸟
            DemonClass.GHOSTLY_SONGSTRESS: self.I_SCA_DEMON_BOSS_6,  # 歌姬
            DemonClass.BOSS_7: self.I_SCA_DEMON_BOSS_7,  # 夜荒魂
        }
        match_position = {
            1: self.C_SCA_DEMON_1,
            2: self.C_SCA_DEMON_2,
            3: self.C_SCA_DEMON_3,
            4: self.C_SCA_DEMON_4,
            5: self.C_SCA_DEMON_5,
            6: self.C_SCA_DEMON_6,
        }
        match_number = {
            1: '一',
            2: '二',
            3: '三',
            4: '四',
            5: '五',
            6: '六',
        }
        target_class = match_class[buy_class]
        target_position = match_position[buy_position]
        target_number = match_number[buy_position]
        self._scales_select_demon(target_class)
        # self.ui_click(target_position, self.I_SCA_DEMON_BUY)
        position_deadline = time.monotonic() + 8
        while time.monotonic() < position_deadline:
            self.screenshot()
            result = self.O_SCA_DEMON_POSTION.ocr(self.device.image)
            if target_number in result:
                break
            if self.click(target_position, interval=0.7):
                continue
        else:
            raise GamePageUnknownError('首领御魂部位未能确认')
        # 购买
        # 一次最多可以买20个所以要分开来
        if buy_number >= 20:
            buy_cycles_number = buy_number // 20
            buy_res_number = buy_number % 20
        else:
            buy_cycles_number = None
            buy_res_number = buy_number
        if buy_cycles_number:
            for i in range(buy_cycles_number):
                if self._scales_buy_more(self.I_SCA_DEMON_BUY, 20) is False:
                    return False
                time.sleep(0.5)
        if buy_res_number:
            self._scales_buy_more(self.I_SCA_DEMON_BUY, buy_res_number)
            time.sleep(0.5)

        # 回到御魂礼盒界面
        while 1:
            self.screenshot()
            if self.appear(self.I_SCA_DEMON_SOULS):
                break
            if self.appear_then_click(self.I_UI_BACK_RED, interval=1):
                continue
            if self.click(self.C_SCA_SOULS_BACK, interval=1):
                continue

    def _scales_sea(self, buy_number: int, buy_rule: str='auto'):
        """

        :param buy_number:
        :param buy_rule:
        :return:
        """
        logger.hr('Scales sea', 3)
        if buy_number == 0:
            logger.info('The purchase quantity of Scales sea is 0')
            return
        self.screenshot()
        # 检查是否出现了购买按钮
        if not self.appear(self.I_SCA_PICTURE_BOOK):
            logger.warning('Scales sea is not appear')
            return
        # 检查剩余数量
        remain_number = self.O_SCA_NUMBER_SEA.ocr(self.device.image)
        if remain_number == 0:
            logger.warning(f'The remaining purchase quantity of xx is {remain_number}')
            return
        if remain_number < buy_number:
            buy_number = remain_number
            logger.warning(f'Remaining purchase quantity is {remain_number}, buy_number is {buy_number}')
        # 检查钱是否够
        current_money = self.O_SCA_RES_SEA.ocr(self.device.image)
        if not isinstance(current_money, int):
            logger.warning('OCR error')
            return
        money_enough = current_money >= 200*buy_number
        if not money_enough:
            logger.warning('Scales sea money is not enough')
            # 判断够不够买2个
            if current_money < 400:
                logger.warning('Scales sea money can not buy two')
                return
            buy_number = current_money // 200
        # 购买# 一次最多可以买10个所以要分开来
        logger.info(f'Scales sea buy {buy_number}')
        if buy_number >= 10:
            buy_cycles_number = buy_number // 10
            buy_res_number = buy_number % 10
        else:
            buy_cycles_number = None
            buy_res_number = buy_number
        if buy_cycles_number:
            for i in range(buy_cycles_number):
                if self.config.weekly_purchase.scales.enable_book_auto:
                    result = self._scales_buy_more(self.I_SCA_PICTURE_BOOK, 10, auto_select=True)
                else:
                    result = self._scales_buy_sea_more(self.I_SCA_PICTURE_BOOK, 10)
                if result is False:
                    return False
                time.sleep(0.5)
        if buy_res_number:
            if self.config.weekly_purchase.scales.enable_book_auto:
                self._scales_buy_more(self.I_SCA_PICTURE_BOOK, buy_res_number, auto_select=True)
            else:
                self._scales_buy_sea_more(self.I_SCA_PICTURE_BOOK, buy_res_number)
            time.sleep(0.5)


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('日常1')
    d = Device(c)
    t = Scales(c, d)

    t._scales_orochi_new(10)
