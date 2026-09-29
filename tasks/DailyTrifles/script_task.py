# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import random
from time import sleep

import difflib
from datetime import time, datetime, timedelta
from module.atom.click import RuleClick
from module.atom.image import RuleImage
from module.ocr.common import BoxedResult

from tasks.Component.config_base import Time
from tasks.DailyTrifles.page import page_store_gift_room, page_friends_luck, page_guild_wish

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main, page_summon, page_guild, page_mall, page_mall_recommend, page_friends, page_courtyard_affairs
from tasks.DailyTrifles.config import DailyTriflesConfig
from tasks.DailyTrifles.assets import DailyTriflesAssets
from tasks.Component.Summon.summon import Summon

from module.logger import logger
from module.exception import GameStuckError, TaskEnd
from module.base.timer import Timer
from tasks.DailyTrifles.config import SummonType
import re
from typing import Any, Optional, List, Callable


class ScriptTask(GameUi, Summon, DailyTriflesAssets):

    def run(self):
        con = self.config.daily_trifles.trifles_config
        # 每日召唤
        if con.one_summon:
            self.run_one_summon()
        if con.courtyard_affairs:
            self.run_courtyard_affairs()
        if con.pickup_email:
            self.run_pickup_email()
        if self.config.daily_trifles.guild_donate.enable:
            self.run_guild_donate()
        # 吉闻
        if con.luck_msg:
            self.run_luck_msg()
        # 商店签到 or 购买寿司
        if con.store_sign or con.buy_sushi_count > 0:
            self.run_store()
        self.config.save()
        self.plan_next_dt()
        raise TaskEnd('DailyTrifles')

    def run_one_summon(self):
        logger.hr('daily summon', 2)
        if self.config.daily_trifles.today_is_done('summon'):
            logger.info('Today is done, skip')
            return
        self.goto_page(page_summon)
        config = self.config.daily_trifles.trifles_config
        if config.summon_type == SummonType.default:
            self.summon_one(draw_mystery_pattern=config.draw_mystery_pattern)
            self.check_time()
        elif config.summon_type == SummonType.recall:
            self.summon_recall()
        self.back_summon_main()
        self.config.daily_trifles.done_record.summon_dt = datetime.now()

    def check_time(self):
        config = self.config.daily_trifles.trifles_config
        now = datetime.now()
        next_run = now + self.config.daily_trifles.scheduler.success_interval
        # 检查是否跨月（next_run的月份与当前月份不同）
        if next_run.month != now.month:
            # 跨月重置神秘图案触发状态
            if not config.draw_mystery_pattern:
                config.draw_mystery_pattern = True
                logger.info(
                    f"reset draw_mystery_pattern to True, next_run: {next_run}")
        else:
            # 如果还是在同一月份，则没必要再绘制神秘图案
            config.draw_mystery_pattern = False
        self.config.save()

    def summon_recall(self):
        """
        确保在召唤界面,每日召唤一次
        召唤结束后回到 召唤主界面
        :return:
        """
        list = [self.O_SELECT_SM2, self.O_SELECT_SM3, self.O_SELECT_SM4]
        count = 0
        while True:
            count += 1

            for i in range(len(list)):
                sleep(1)
                self.goto_page(page_summon)
                self.appear_then_click(self.I_UI_BACK_RED, interval=1)
                x, y = list[i].coord()
                self.device.click(x, y)
                sleep(1)
                self.screenshot()
                if self.appear(self.I_RECALL_TICKET):
                    break
                logger.info("Select preset group RECALL")

            self.screenshot()
            if self.appear(self.I_RECALL_TICKET):
                break
            if count >= 3:
                self.config.notifier.push(title='今忆召唤抽卡失败', content='每日任务,今忆召唤抽卡失败!!!')
                return

        logger.info('Summon one RECALL')
        self.wait_until_appear(self.I_RECALL_TICKET)
        while True:
            ticket_info = self.O_RECALL_TICKET_AREA.ocr(self.device.image)
            # 处理 None 和空字符串
            if ticket_info is None or ticket_info == '':
                ticket_info = 0
            else:
                # 使用正则表达式提取字符串中的数字
                match = re.search(r'\d+', ticket_info)
                if match:
                    ticket_info = int(match.group())
                else:
                    logger.warning(f'Invalid ticket_info value: {ticket_info}, expected a numeric string')
                    ticket_info = 0  # 将无效值设置为默认值 0
            if ticket_info <= 0:
                logger.warning('There is no any one RECALL ticket')
                return
            # 某些情况下滑动异常
            self.S_RANDOM_SWIPE_1.name = 'S_RANDOM_SWIPE'
            self.S_RANDOM_SWIPE_2.name = 'S_RANDOM_SWIPE'
            self.S_RANDOM_SWIPE_3.name = 'S_RANDOM_SWIPE'
            self.S_RANDOM_SWIPE_4.name = 'S_RANDOM_SWIPE'
            while 1:
                self.screenshot()
                if self.appear(self.I_RECALL_ONE_TICKET):
                    break
                if self.appear_then_click(self.I_RECALL_TICKET, interval=1):
                    continue

            # 画一张票
            sleep(1)
            while 1:
                self.screenshot()
                if self.appear(self.I_RECALL_SM_CONFIRM, interval=0.6):
                    self.ui_click_until_disappear(self.I_RECALL_SM_CONFIRM)
                    break
                if self.appear(self.I_SM_CONFIRM_2, interval=0.6):
                    self.ui_click_until_disappear(self.I_SM_CONFIRM_2)
                    break
                if self.appear(self.I_RECALL_ONE_TICKET, interval=1):
                    # 某些时候会点击到 “语言召唤”
                    if self.appear_then_click(self.I_UI_CANCEL, interval=0.8):
                        continue
                    self.summon()
                    continue
            logger.info('Summon one success')

    def run_guild_donate(self):
        logger.hr('guild donate', 2)
        if self.config.daily_trifles.today_is_done('guild_donate'):
            logger.info('Today is done, skip')
            return
        self.goto_page(page_guild_wish)
        timeout_timer = Timer(2).start()
        while not timeout_timer.reached():
            self.screenshot()
            if self.appear(self.I_DT_GW_THANKS):
                self.ui_click(self.I_DT_GW_THANKS, self.I_DT_GW_THANKED, interval=0.8)
                timeout_timer.reset()
                continue
        self.appear_then_click(self.I_UI_BACK_RED)
        donate_datas: list = [
            (self.config.daily_trifles.guild_donate.guild_member_list_v,
             lambda : self.switch_select(self.I_DT_GW_GUILD_MEMBER_SELECTED, self.I_DT_GW_FRIEND_SELECTED, self.I_DT_GW_SELECT_GUILD_MEMBER),
             self.config.daily_trifles.guild_donate.name_check),
            (self.config.daily_trifles.guild_donate.friend_list_v,
             lambda : self.switch_select(self.I_DT_GW_FRIEND_SELECTED, self.I_DT_GW_GUILD_MEMBER_SELECTED, self.I_DT_GW_SELECT_FRIEND),
             self.config.daily_trifles.guild_donate.name_check)
        ]
        all_done = True
        for name_list, switch_func, name_check in donate_datas:
            all_done = all_done and self.donate(name_list, switch_func, name_check)
        if self.config.daily_trifles.guild_donate.auto_get_rewards:
            self.guild_donate_get_reward()
        self.config.daily_trifles.done_record.guild_donate_finish = all_done
        self.goto_page(page_main)

    def guild_donate_get_reward(self):
        """领取捐赠碎片的奖励"""
        timeout_timer = Timer(3).start()
        has_reward = False
        while not timeout_timer.reached():
            self.screenshot()
            if self.appear(self.I_UI_BACK_RED, interval=0.6):
                break
            if self.appear(self.I_DT_GW_DONATE_RECORD_RED):
                self.ui_click(self.I_DT_GW_DONATE_RECORD, self.I_UI_BACK_RED, interval=1.2)
                has_reward = True
                continue
        if not has_reward:
            logger.info('No reward can get, exit')
            return
        timeout_timer.reset()
        while not timeout_timer.reached():
            self.screenshot()
            if self.appear_then_click(self.I_UI_CONFIRM, interval=0.6):
                continue
            if self.appear(self.I_DT_GW_DONATE_RECORD_THANKS):  # 受赠界面的一键感谢
                self.ui_get_reward(self.I_DT_GW_DONATE_RECORD_THANKS)
                timeout_timer.reset()
                continue
            if self.appear(self.I_DT_GW_DONATE_RED, interval=2.5):  # 赠予界面的一键领取
                self.ui_click(self.I_DT_GW_GIVE, self.I_DT_GW_ONE_COLLECT)
                self.appear_then_click(self.I_DT_GW_ONE_COLLECT, interval=0.6)
                timeout_timer.reset()
                continue
        self.ui_click_until_disappear(self.I_UI_BACK_RED)

    def donate(self, name_list: List[str], switch_func: Callable, name_check: bool) -> bool:
        """执行碎片捐赠流程

        :param name_list: 待捐赠碎皮的名称列表
        :param switch_func: 切换好友/阴阳寮/...的方法
        :param name_check: 是否使用ocr检查用户名
        :return: 是否全部捐赠成功 (出现检索名称后为空或者碎皮不足都是False, 仅全部捐成功才是True)
        """
        all_done = True
        for name in name_list:
            switch_func()
            self.swipe(self.S_DT_GW_OPEN_SEARCH, interval=1.2)  # 向下滑动拉出搜索框
            # 从按照交换搜索切换到按名称搜索
            self.switch_select(self.I_DT_GW_SEARCH_BY_NAME, self.I_DT_GW_SEARCH_BY_SWAP, self.I_DT_GW_SELECT_BY_NAME)
            self.appear_then_click(self.I_DT_GW_CLEAR_SEARCH)  # 清除搜索框内容
            self.ui_click(self.C_DT_GW_INPUT_SEARCH, self.I_DT_GW_CONFIRM, interval=1.5)  # 点击搜索框
            self.click(self.C_DT_GW_CLICK_INPUT)  # 点击名称输入框
            self.device.adb.send_keys(name)  # 输入名称
            self.ui_click_until_disappear(self.I_DT_GW_CONFIRM, interval=1.5)  # 点击确定
            donate_btn = self.I_DT_GW_DONATE
            if name_check:  # 若有多个相同前缀名称, 则需要取出一样的或最相近的名称
                name_roi = self.find_target_name(name)
                if name_roi is None:
                    logger.warning(f'{name} check failed, maybe not wish or not find')
                    all_done = False
                    continue
                # 设置赠与按钮back与对应name同一行
                donate_btn.roi_back = [name_roi[0], name_roi[1] - 15, max(name_roi[2] + 700, 1280),
                                       max(name_roi[3] + 60, 720)]
            self.I_DT_GW_FULL.roi_back = donate_btn.roi_back  # 设置已捐满标志back区域和赠与按钮同一行
            self.I_DT_GW_INSUFFICIENT.roi_back = donate_btn.roi_back  # 设置碎片不足标志back区域和赠与按钮同一行
            donate_ret = self.process_donate(donate_btn, name)
            all_done = all_done and donate_ret  # 有一次没成功则all_done永远False
        return all_done

    def process_donate(self, donate_btn: RuleImage, name: str) -> bool:
        """捐赠式神碎片

        :param name: 被捐方名称
        :param donate_btn: 赠与按钮
        :return: 捐赠是否成功
        """
        timeout_timer = Timer(3).start()
        while not timeout_timer.reached():
            self.screenshot()
            if self.appear_then_click(self.I_UI_CONFIRM, interval=0.6):
                continue
            if self.appear(self.I_DT_GW_SEARCH_EMPTY):
                logger.warning('Maybe not wish or not find, skip')
                if self.config.daily_trifles.guild_donate.notify_enable:
                    self.config.notifier.push(title='好友搜索失败', content=f'{name} 搜索失败, 没有搜索到对应用户, 无法捐赠')
                return False
            if self.appear_then_click(donate_btn, interval=0.6):
                timeout_timer.reset()
                continue
            if self.appear(self.I_DT_GW_INSUFFICIENT, interval=0.6):
                logger.warning('Not enough fragment to donate, skip')
                if self.config.daily_trifles.guild_donate.notify_enable:
                    self.config.notifier.push(title='捐赠碎片不足', content=f'捐给{name}的碎片不足, 请上线查看')
                return False
            if self.appear(self.I_DT_GW_FULL, interval=1.2):
                logger.info(f'Donate success!')
                return True
        return False

    def find_target_name(self, name) -> List[int]:
        """寻找目标名称
        :param name: 名称
        :return: [x, y, w, h]
        """
        timeout_timer = Timer(3).start()
        name_roi: List[int] = None
        # TODO: 这里只找了第一页, 若相似名称过多后续需要添加翻页继续找功能
        while not timeout_timer.reached():
            self.screenshot()
            if self.appear(self.I_DT_GW_SEARCH_EMPTY):  # 空的直接退出
                if self.config.daily_trifles.guild_donate.notify_enable:
                    self.config.notifier.push(title='好友搜索失败', content=f'没有搜索到对应用户 {name}, 无法捐赠')
                return None
            text_results = self.O_DT_GW_NAME.detect_and_ocr(self.device.image)
            mx_similarity = 0.5
            for result in text_results:
                if result.ocr_text == name:
                    return self.extract_roi(result)  # 名称一模一样则直接返回
                similarity = difflib.SequenceMatcher(None, result.ocr_text, name).ratio()
                if similarity > mx_similarity:
                    mx_similarity = similarity
                    name_roi = self.extract_roi(result)
            if name_roi is None:
                continue
            return name_roi  # 找到了直接退出
        return name_roi

    def extract_roi(self, result: BoxedResult) -> list[int]:
        """从ocr结果提取对应的roi坐标"""
        x = self.O_DT_GW_NAME.roi[0] + result.box[0, 0]
        y = self.O_DT_GW_NAME.roi[1] + result.box[0, 1]
        w, h = result.box[1, 0] - result.box[0, 0], result.box[2, 1] - result.box[0, 1]
        return [x, y, w, h]

    def switch_select(self, target: RuleImage, other: RuleImage, select: RuleImage):
        """切换选中的元素"""
        while True:
            self.screenshot()
            if self.appear(target):
                break
            if self.appear_then_click(select, interval=0.6):
                continue
            if self.appear_then_click(other, interval=1.8):
                continue

    def run_luck_msg(self):
        logger.hr('luck msg', 2)
        if self.config.daily_trifles.today_is_done('luck_msg'):
            logger.info('Today is done, skip')
            return
        self.goto_page(page_friends_luck)
        logger.info('Start luck msg')
        check_timer = Timer(2)
        check_timer.start()
        while 1:
            self.screenshot()

            if self.appear_then_click(self.I_CLICK_BLESS, interval=1):
                continue
            if self.appear_then_click(self.I_ONE_CLICK_BLESS, interval=1):
                continue
            if self.ui_reward_appear_click():
                logger.info('Get reward of luck msg')
                break
            if check_timer.reached():
                logger.warning('There is no any luck msg')
                break

        self.goto_page(page_main)
        self.config.daily_trifles.done_record.luck_msg_dt = datetime.now()

    def run_store(self):
        self.close_gift_daily_popup()
        if self.check_store_all_done():
            logger.info('Store all done, skip')
            return
        self.goto_page(page_mall_recommend, confirm_wait=3, accepted_pages=(page_mall,))
        if self.config.daily_trifles.trifles_config.store_sign:
            self.run_store_sign()
        if self.config.daily_trifles.trifles_config.buy_sushi_count > 0:
            self.run_buy_sushi()
        self.goto_page(page_main)

    def run_store_sign(self):
        logger.hr('store sign', 2)
        if self.config.daily_trifles.today_is_done('store_sign'):
            logger.info('Today is done, skip')
            return
        self.config.daily_trifles.done_record.store_sign_dt = datetime.now()
        self.goto_page(page_store_gift_room)
        self.screenshot()
        self.appear_then_click(self.I_GIFT_RECOMMEND, interval=1)
        logger.info('Enter store sign')
        sleep(1)  # 等个动画
        self.screenshot()
        if not self.appear(self.I_GIFT_SIGN):
            logger.warning('There is no gift sign')
        elif self.ui_get_reward(self.I_GIFT_SIGN, click_interval=2.5):
            logger.info('Get reward of gift sign')
        self.close_gift_daily_popup()

    def close_gift_daily_popup(self):
        self.screenshot()
        if not self.appear(self.I_GIFT_DAILY_POPUP):
            return
        image_height, image_width = self.device.image.shape[:2]
        title_x = self.I_GIFT_DAILY_POPUP.roi_front[0]
        # 标题比弹窗左边缘靠右约 30 像素，留出 40 像素确保点击区在弹窗外。
        side_margin = max(1, min(title_x - 40, image_width // 4))
        click_width = max(1, side_margin * 3 // 4)
        side = random.choice(('left', 'right'))
        side_x = side_margin - click_width if side == 'left' else image_width - side_margin
        close_area = (side_x, image_height // 4, click_width, image_height // 2)
        self.click(RuleClick(roi_front=close_area, roi_back=close_area,
                            name=f'gift_daily_popup_close_{side}'))
        sleep(0.5)
        self.screenshot()
        if self.appear(self.I_GIFT_DAILY_POPUP):
            raise GameStuckError('Daily gift popup did not close')

    def run_buy_sushi(self):
        logger.hr('store sushi', 2)
        if self.config.daily_trifles.today_is_done('sushi'):
            logger.info('Today is done, skip')
            return
        self.close_gift_daily_popup()
        # 进入Special
        special_timer = Timer(15).start()
        while not special_timer.reached():
            from tasks.WeeklyPurchase.assets import WeeklyPurchaseAssets
            self.screenshot()
            if self.appear(self.I_STORE_COST_TYPE_JADE):
                break
            if (self.appear(WeeklyPurchaseAssets.I_MALL_SUNDRY_CHECK)
                    and self.appear(WeeklyPurchaseAssets.I_SIDE_CHECK_SPECIAL)):
                break
            if self.appear_then_click(WeeklyPurchaseAssets.I_MALL_SUNDRY, interval=1):
                continue
        else:
            raise GameStuckError('Cannot enter the Special store to buy sushi')


        target_count = self.config.daily_trifles.trifles_config.buy_sushi_count
        next_price_after_target = 60 + 20 * target_count

        def read_price(base_element, timeout: float = 8) -> int:
            """从商品或确认按钮右侧读取价格；识别不可靠时停止购买。"""
            timer = Timer(timeout).start()
            last_text = None
            while not timer.reached():
                self.screenshot()
                if not self.appear(base_element):
                    continue
                x, y, width, height = base_element.roi_front
                if base_element is self.I_STORE_COST_TYPE_JADE:
                    self.O_STORE_SUSHI_PRICE.roi = (x + width, y + height - 49, 65, 50)
                else:
                    self.O_STORE_SUSHI_PRICE.roi = (x + width, y + height - 30, 60, 30)
                last_text = self.O_STORE_SUSHI_PRICE.detect_text(self.device.image)
                try:
                    price = int(str(last_text).strip())
                except (TypeError, ValueError):
                    continue
                if 60 <= price <= 60 + 20 * max(10, target_count) and (price - 60) % 20 == 0:
                    return price
            raise GameStuckError(f'Cannot recognize sushi price beside {base_element.name}: {last_text!r}')

        def dismiss_purchase_reward(appear_timeout: float = 3, close_timeout: float = 8) -> bool:
            """购买确认框关闭后，先等待并关闭购买奖励弹窗。"""
            appear_timer = Timer(appear_timeout).start()
            while not appear_timer.reached():
                self.screenshot()
                if not self.appear(self.I_UI_REWARD, threshold=0.6):
                    continue

                logger.info('Sushi purchase reward appeared, dismissing popup')
                close_timer = Timer(close_timeout).start()
                while not close_timer.reached():
                    self.screenshot()
                    if not self.appear(self.I_UI_REWARD, threshold=0.6):
                        logger.info('Sushi purchase reward dismissed')
                        return True
                    self.ui_reward_appear_click()
                raise GameStuckError('Sushi purchase reward popup did not close')

            logger.info('No sushi purchase reward popup detected; verifying the next price')
            return False

        # 第一次 60 勾玉，之后每次增加 20。确认购买只点击一次，并核实下次价格。
        while True:
            self.screenshot()
            if self.appear(self.I_STORE_COST_TYPE_JADE):
                # 上次异常后确认框仍可能留在屏幕上，直接从确认框恢复。
                price = read_price(self.I_STORE_COST_TYPE_JADE)
                if price >= next_price_after_target:
                    icon_x, icon_y = self.I_STORE_COST_TYPE_JADE.roi_front[:2]
                    self.device.click(max(20, icon_x - 350), max(20, icon_y - 150),
                                      control_name='sushi_purchase_dialog_outside')
                    close_timer = Timer(3).start()
                    while not close_timer.reached():
                        self.screenshot()
                        if not self.appear(self.I_STORE_COST_TYPE_JADE):
                            break
                    else:
                        raise GameStuckError('Sushi purchase dialog did not close')
                    break
            else:
                price = read_price(self.I_SPECIAL_SUSHI)
                if price >= next_price_after_target:
                    break
                logger.info(f'Sushi purchase {(price - 60) // 20 + 1}/{target_count}: expect {price} Jade')
                self.click(self.I_SPECIAL_SUSHI)
                modal_price = read_price(self.I_STORE_COST_TYPE_JADE)
                if modal_price != price:
                    raise GameStuckError(f'Sushi price changed unexpectedly: item={price}, confirm={modal_price}')

            logger.info(f'Sushi purchase {(price - 60) // 20 + 1}/{target_count}: confirm {price} Jade')
            self.click(self.I_STORE_COST_TYPE_JADE)
            timer = Timer(8).start()
            while not timer.reached():
                self.screenshot()
                if not self.appear(self.I_STORE_COST_TYPE_JADE):
                    break
            else:
                raise GameStuckError('Sushi purchase dialog did not close after one click')

            # 先领取奖励并回到商店，再读取价格；涨价幅度用于核实本次购买。
            dismiss_purchase_reward()
            next_price = read_price(self.I_SPECIAL_SUSHI)
            if next_price != price + 20:
                raise GameStuckError(f'Sushi price did not increase by 20: {price} -> {next_price}')
            logger.info(f'Bought Sushi With {price} Jade; next price {next_price} Jade')
        self.config.daily_trifles.done_record.sushi_dt = datetime.now()

    def run_courtyard_affairs(self):
        """庭院事务"""
        logger.hr('courtyard affairs', 2)
        self.goto_page(page_main)
        timeout_timer = Timer(3).start()
        while not timeout_timer.reached():
            self.screenshot()
            if self.appear(self.I_ENTER_COURTYARD_AFFAIRS, interval=1.2):
                self.goto_page(page_courtyard_affairs)
                timeout_timer.reset()
                break
        if timeout_timer.reached():
            logger.info('Not have courtyard affairs, exit')
            return
        while True:
            self.screenshot()
            if self.appear(self.I_CHECK_IN_DAILY, interval=0.5):
                break
            if self.appear_then_click(self.I_ENTER_DAILY, interval=1):
                continue
        self.appear_then_click(self.I_ONE_COMPLETE, interval=1)
        self.goto_page(page_main)
        self.config.daily_trifles.done_record.courtyard_affairs_dt = datetime.now()

    def run_pickup_email(self):
        """领取邮件"""
        logger.hr('pick up email', 2)
        self.goto_page(page_main)
        timeout_timer = Timer(3).start()
        while not timeout_timer.reached():
            self.screenshot()
            if self.appear_then_click(self.I_DT_HARVEST_MAIL_COPY2, interval=1.2) or \
                    self.appear_then_click(self.I_HARVEST_MAIL, interval=1.2) or \
                    self.appear_then_click(self.I_HARVEST_MAIL_COPY, interval=1.2):
                continue
            if self.appear_then_click(self.I_HARVEST_MAIL_CONFIRM, interval=1):
                continue
            if self.appear_then_click(self.I_HARVEST_MAIL_ALL, interval=2):
                timeout_timer.reset()
                continue
            if self.appear_then_click(self.I_READ_ALL_MAIL, interval=3):
                continue
        self.goto_page(page_main)
        self.config.daily_trifles.done_record.pickup_email_dt = datetime.now()

    def plan_next_dt(self):
        # 定时领体力（每天 12-14、20-22 时内各有 20 体力）
        now = datetime.now()
        # 如果时间在00:00-12:00之间则设定时间为当日 12 时
        if now.time() < time(12, 0):
            self.custom_next_run(task='DailyTrifles', custom_time=Time(12, 0), time_delta=0)
        # 如果时间在12:00-20:00之间则设定时间为当日 20 时
        elif time(12, 0) <= now.time() < time(20, 0):
            self.custom_next_run(task='DailyTrifles', custom_time=Time(20, 0), time_delta=0)
        # 如果时间在20:00-23:59之间则设定时间为次日 12 时
        else:
            self.custom_next_run(task='DailyTrifles', custom_time=Time(12, 0), time_delta=1)

    def check_store_all_done(self) -> bool:
        """判断商店任务是否都做完了, 做完了则不再进入商店"""
        if self.config.daily_trifles.trifles_config.store_sign and not self.config.daily_trifles.today_is_done('store_sign'):
            return False
        if self.config.daily_trifles.trifles_config.buy_sushi_count > 0 and not self.config.daily_trifles.today_is_done('sushi'):
            return False
        return True


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas2')
    d = Device(c)
    t = ScriptTask(c, d)

    t.run_guild_donate()
