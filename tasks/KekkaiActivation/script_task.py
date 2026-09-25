# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time

import random
import re
from cached_property import cached_property
from datetime import datetime, timedelta
from module.atom.click import RuleClick

from module.base.timer import Timer
from module.atom.image_grid import ImageGrid
from module.atom.image import RuleImage
from module.base.utils import point2str
from module.logger import logger
from module.exception import TaskEnd, GameStuckError
from tasks.KekkaiUtilize.page import page_guild_realm, page_guild_realm_growth, page_guild_card

from tasks.KekkaiUtilize.script_task import ScriptTask as KU
from tasks.KekkaiUtilize.utils import CardClass
from tasks.KekkaiActivation.assets import KekkaiActivationAssets
from tasks.KekkaiActivation.utils import parse_rule
from tasks.KekkaiActivation.config import ActivationConfig
from tasks.Utils.config_enum import ShikigamiClass
from tasks.GameUi.page import page_main, page_guild
from tasks.KekkaiActivation.config import CardType

""" 结界挂卡 """
class ScriptTask(KU, KekkaiActivationAssets):

    def run(self):
        con = self.config.kekkai_activation.activation_config
        # 进入寮结界
        self.goto_page(page_guild_realm)

        if con.exchange_before:
            self.check_max_lv(con.shikigami_class, con.auto_fill)
        # 收取经验
        self.harvest_card()
        # 开始挂卡
        self.run_activation(con)
        self.goto_page(page_guild_realm)

        if con.exchange_max:
            self.check_max_lv(con.shikigami_class, con.auto_fill)
        self.goto_page(page_main)

        raise TaskEnd('KekkaiActivation')

    @cached_property
    def dict_card_image(self) -> dict:
        match_targets = {
            CardClass.TAIKO6: self.I_CARDS_KAIKO_6,
            CardClass.TAIKO5: self.I_CARDS_KAIKO_5,
            CardClass.TAIKO4: self.I_CARDS_KAIKO_4,
            CardClass.TAIKO3: self.I_CARDS_KAIKO_3,
            CardClass.FISH6: self.I_CARDS_FISH_6,
            CardClass.FISH5: self.I_CARDS_FISH_5,
            CardClass.FISH4: self.I_CARDS_FISH_4,
            CardClass.FISH3: self.I_CARDS_FISH_3,
            CardClass.MOON6: self.I_CARDS_MOON_6,
            CardClass.MOON5: self.I_CARDS_MOON_5,
            CardClass.MOON4: self.I_CARDS_MOON_4,
            CardClass.MOON3: self.I_CARDS_MOON_3,
            CardClass.MOON2: self.I_CARDS_MOON_2,
            CardClass.MOON1: self.I_CARDS_MOON_1
        }
        return match_targets

    @cached_property
    def dict_image_card(self) -> dict:
        return {v: k for k, v in self.dict_card_image.items()}

    @cached_property
    def order_targets(self) -> ImageGrid:
        rule = self.config.kekkai_activation.activation_config.card_type
        if rule == CardType.TAIKO:
            return ImageGrid([self.I_CARDS_KAIKO_6, self.I_CARDS_KAIKO_5])
        elif rule == CardType.FISH:
            return ImageGrid([self.I_CARDS_FISH_6, self.I_CARDS_FISH_5])
        else:
            logger.error('Unknown utilize rule')
            raise ValueError('Unknown utilize rule')

    def run_activation(self, _config: ActivationConfig) -> bool:
        """
        执行挂卡，要求在结界的界面
        顺便把下一次执行也设置了
        :return: 挂卡成功（）返回True，失败(时间没到提前来了)返回False
        退出的时候还是在挂卡界面而不是结界界面
        """
        self.goto_page(page_guild_card)
        # 太诡异了 为什么有这么长的动画, 那么长的动画先休息一会
        logger.hr('Start activation')
        time.sleep(0.5)
        while 1:
            self.screenshot()
            card_status = self.check_card_status()
            card_effect = self.check_card_effect()

            # 不稳定太，等待动画结束
            if not card_status and not card_effect:
                # 黄色的 ”激活“
                if self.appear(self.I_A_ACTIVATE_YELLOW, threshold=0.95):
                    continue
                if self.appear(self.I_A_DEMOUNT):
                    # 现在在动画里面
                    logger.info('Now in the animation')
                    logger.info('Now there is no card')
                    continue
            # 如果这张卡生效着，在使用中
            if card_status and card_effect:
                logger.info('Card is using')
                interval = self.ocr_time()
                self.set_next_run("KekkaiActivation", target=interval+datetime.now())
                return False
            # 如果已经选中这张卡了， 那就激活这张卡
            if card_status and not card_effect:
                logger.info('Card is selected but not using')
                while 1:
                    self.screenshot()
                    if self.appear(self.I_A_INVITE, threshold=0.8):
                        logger.info('Card is activated')
                        break
                    if self.appear_then_click(self.I_UI_CONFIRM, interval=0.6):
                        continue
                    if self.appear_then_click(self.I_A_ACTIVATE_YELLOW, interval=1):
                        continue
                interval = self.ocr_time(True)
                self.set_next_run("KekkaiActivation", target=interval + datetime.now())
                return True
            # 如果是什么都没有，那就是可以开始挂卡了
            if not card_status and not card_effect:
                logger.info('Card is not selected also not using')
                self.screening_card(_config.card_type)

    def check_card_status(self, screenshot=False) -> bool:
        """
        判断使用有挂卡在上面了， 判断依据就是如果没看就可以显示背景图
        :param screenshot:
        :return: 如果有卡在上面了返回True，否则返回False
        """
        if screenshot:
            self.screenshot()
        return not self.appear(self.I_A_EMPTY)

    def check_card_effect(self, screenshot=False) -> bool:
        """
        检查这张卡是否生效了, 如果是出现的“邀请”那就是生效了， 如果是“激活”那就是还没生效
        :param screenshot:
        :return: 生效返回True
        """
        if screenshot:
            self.screenshot()
        if self.appear(self.I_A_INVITE, threshold=0.8):
            return True
        elif self.appear(self.I_A_ACTIVATE_YELLOW):
            return False
        logger.info('Unknown card effect')
        while 1:
            self.screenshot()
            if self.appear(self.I_A_INVITE, threshold=0.7):
                return True
            elif self.appear(self.I_A_ACTIVATE_YELLOW):
                return False
            elif self.appear(self.I_A_ACTIVATE_GRAY):
                return False

    def ocr_time(self, screenshot=False) -> timedelta or None:
        if screenshot:
            self.screenshot()
        delta = self.O_CARD_ALL_TIME.ocr_duration(self.device.image)
        if not isinstance(delta, timedelta):
            logger.warning('OCR error')
            return None
        if delta == timedelta(0):
            logger.error('The remaining time detected for this card is 0')
            logger.error('This may be due to the fact that the card has not yet been collected')
            raise GameStuckError
        return delta

    def screening_card(self, rule: str):
        """
        开始挑选卡
        :return:
        """

        if rule == CardType.TAIKO:
            card_class = CardClass.TAIKO
            target_class = self.I_A_CARD_KAIKO
        elif rule == CardType.FISH:
            card_class = CardClass.FISH
            target_class = self.I_A_CARD_FISH
        else:
            logger.warning('Unknown card rule')
            self.push_notify(content='Unknown card rule')
            return

        while 1:
            self.screenshot()

            if self.appear(target_class):
                time.sleep(0.3)
                self.screenshot()
                if self.appear(target_class):
                    break
            if self.click(self.C_A_SELECT_CARD_LIST, interval=2.5):
                continue
        logger.info('Appear card class: {}'.format(card_class))
        while 1:
            self.screenshot()
            if not self.appear(target_class):
                break
            if self.appear_then_click(target_class, interval=1):
                continue
        logger.info('Selected card class: {}'.format(card_class))

        # 找最优卡
        while 1:
            self.screenshot()
            target = self.check_card_num()
            if target is None:
                # 未发现卡，处理逻辑
                self._card_not_found()
            if self.appear(self.I_A_EMPTY):
                while 1:
                    self.screenshot()
                    if not self.appear(self.I_A_EMPTY):
                        self.config.kekkai_activation.activation_config.card_not_found_count = 0
                        self.config.save()
                        message = f'✅ 确认挂卡: {self.picked_card_desc}'
                        self.save_image(content=message, push_flag=False, wait_time=0)
                        return
                    if self.click(target, interval=1):
                        continue

    # ---------- 结界卡星级识别 ---------- #
    # 图片模板自带卡片底部的星级图标，所以匹配位置可以用来推算星级图标中心
    STAR_ICON_HEIGHT = 24
    # 收益文字行与星级图标中心的允许偏差（列表一行高约 100 像素，取半行高）
    STAR_ROW_TOLERANCE = 60
    # 最近一次选中的卡片描述，用于日志与截图说明
    picked_card_desc = ''

    def star_targets_of_type(self, rule: CardType) -> dict:
        """当前卡种可用的星级模板 {星级: RuleImage}；太鼓/斗鱼只有 3 星及以上的模板"""
        if rule == CardType.TAIKO:
            card_classes = (
                CardClass.TAIKO3, CardClass.TAIKO4, CardClass.TAIKO5, CardClass.TAIKO6
            )
        elif rule == CardType.FISH:
            card_classes = (
                CardClass.FISH3, CardClass.FISH4, CardClass.FISH5, CardClass.FISH6
            )
        else:
            return {}
        images = self.dict_card_image
        return {
            int(card_class.value.split('_')[-1]): images[card_class]
            for card_class in card_classes
            if card_class in images
        }

    def detect_card_stars(self, rule: CardType) -> list:
        """
        识别结界卡列表界面里每张卡的星级
        :return: [{'star': 星级, 'center': (x, y)}]，按从上到下排序；没有识别到返回 []
        """
        targets = self.star_targets_of_type(rule)
        if not targets:
            return []

        matches = []
        for star, image in targets.items():
            result = image.match_all_any(
                self.device.image,
                frame_id=self.device.image_frame_id,
            )
            for score, x, y, w, h in result:
                # 星级图标固定绘制在卡片最底部
                center = (x + w / 2, y + h - min(h, self.STAR_ICON_HEIGHT) / 2)
                matches.append({'star': star, 'score': score, 'center': center})

        # 同一张卡可能同时命中多个星级模板，保留置信度最高的那个
        rows = []
        for match in sorted(matches, key=lambda item: item['center'][1]):
            for row in rows:
                if abs(row['center'][0] - match['center'][0]) <= 35 \
                        and abs(row['center'][1] - match['center'][1]) <= 25:
                    if match['score'] > row['score']:
                        row.update(match)
                    break
            else:
                rows.append(dict(match))
        rows.sort(key=lambda item: item['center'][1])
        if rows:
            logger.info(f'识别到星级: {[row["star"] for row in rows]}')
        return rows

    def match_star_of_row(self, star_rows: list, result) -> int or None:
        """
        把 OCR 到的一行收益匹配到距离最近的卡片，返回其星级
        :return: 无法判断星级时返回 None
        """
        if not star_rows:
            return None
        box = result.box
        y_center = self.O_CHECK_CARD_NUMBER.roi[1] + (float(box[0][1]) + float(box[2][1])) / 2
        nearest = min(star_rows, key=lambda item: abs(item['center'][1] - y_center))
        if abs(nearest['center'][1] - y_center) > self.STAR_ROW_TOLERANCE:
            logger.warning(f'未能把收益行匹配到卡片: {result.ocr_text}')
            return None
        return nearest['star']

    def check_card_num(self):
        con = self.config.kekkai_activation.activation_config
        rule = con.card_type
        if rule == CardType.TAIKO:
            min_card_num = con.min_taiko_num
            check_card = "勾玉"
        elif rule == CardType.FISH:
            min_card_num = con.min_fish_num
            check_card = "体力"
        else:
            logger.error('Unknown utilize rule')
            raise ValueError('Unknown utilize rule')

        # 星级要求：最低星级设为 1 表示不做星级限制
        min_star = con.min_star
        need_star = min_star >= 2
        star_miss_count = 0
        self.picked_card_desc = ''

        ocr_count = 0
        while 1:
            self.screenshot()
            results = self.O_CHECK_CARD_NUMBER.detect_and_ocr(self.device.image)
            ocr_count += 1
            # 第一步：筛选出包含 "体力或者勾玉" 的结果
            filtered_results = [result for result in results if check_card in result.ocr_text]
            logger.info(f"识别到卡: {[result.ocr_text for result in filtered_results]}")

            # 第二步：识别每张卡的星级（星级图标在卡片底部）
            star_rows = self.detect_card_stars(rule) if need_star else []
            if star_rows:
                star_miss_count = 0
            elif need_star and filtered_results:
                star_miss_count += 1
                logger.warning(f'⚠️ 未识别到结界卡星级（第{star_miss_count}次），无法判断卡片星级')
                if star_miss_count >= 2:
                    # 星级模板可能和当前游戏版本不匹配，此时保留原有的按收益选择
                    logger.warning('⚠️ 连续多次未识别到星级，本次运行降级为仅按每小时收益选择结界卡')
                    need_star = False

            # 第三步：提取数字，并过滤掉不满足星级要求的卡片
            numeric_results = []
            for result in filtered_results:
                # 使用正则表达式提取所有数字
                numbers = [int(num) for num in re.findall(r'\d+', result.ocr_text)]
                if not numbers:  # 没有提取到数字
                    continue
                if numbers[0] < min_card_num:
                    logger.info(f'⏭️ 跳过收益不达标的卡: {result.ocr_text}（要求≥{min_card_num}）')
                    continue
                star = None
                if need_star:
                    star = self.match_star_of_row(star_rows, result)
                    if star is None:
                        logger.warning(f'⏭️ 跳过无法判断星级的卡: {result.ocr_text}')
                        continue
                    if star < min_star:
                        logger.info(f'⏭️ 跳过{star}星卡: {result.ocr_text}（要求≥{min_star}星）')
                        continue
                    logger.info(f'✅ {star}星卡满足要求: {result.ocr_text}')
                numeric_results.append((numbers[0], result, star))  # 按第一个数字排序

            if numeric_results:
                # 按数字大到小排序
                card_num, max_result, star = max(numeric_results, key=lambda x: x[0])

                box = max_result.box  # 获取边界框坐标
                x_min = self.O_CHECK_CARD_NUMBER.roi[0] + box[0][0]
                y_min = self.O_CHECK_CARD_NUMBER.roi[1] + box[0][1]
                width = box[1][0] - box[0][0]
                height = box[2][1] - box[1][1]
                roi = int(x_min), int(y_min), int(width), int(height)

                target = RuleClick(roi_front=roi, roi_back=roi, name="tmpclick")
                star_text = f'{star}星 ' if star else ''
                self.picked_card_desc = f'{rule.value} {star_text}{card_num}/时'
                logger.info(f"选择挂卡: [{max_result.ocr_text}] {roi} {star_text}{card_num}/时")

                return target
            else:
                if ocr_count > 3:
                    logger.error('多次未找到符合条件的结果, 退出')
                    return None
                logger.warning("未找到符合条件的结果, 准备往上滑动")
                duration = 2
                safe_pos_x = random.randint(200, 400)
                safe_pos_y = random.randint(580, 600)
                p1 = (safe_pos_x, safe_pos_y)
                p2 = (safe_pos_x, safe_pos_y - 410)
                logger.info('Swipe %s -> %s, %sS ' % (point2str(*p1), point2str(*p2), duration))
                self.device.swipe_adb(p1, p2, duration=duration)
                time.sleep(1)
                continue

    def _card_not_found(self):
        # 获取配置引用
        activation_config = self.config.kekkai_activation.activation_config
        # 多少分钟后重试
        retry_minutes = 180
        retry_count = 3
        # 递增未找到卡的计数器
        activation_config.card_not_found_count += 1

        if activation_config.card_not_found_count >= retry_count:
            # 达到重试上限时的处理
            log_msg = f"⚠️{activation_config.card_type}卡未检出（累计{retry_count}次），{retry_minutes}分钟后重试"
            activation_config.card_not_found_count = 0  # 重置计数器并延长下次执行时间
            next_run = datetime.now() + timedelta(minutes=retry_minutes)
        else:
            # # 未达上限切换卡类型
            new_type = (
                CardType.FISH
                if activation_config.card_type == CardType.TAIKO
                else CardType.TAIKO
            )
            log_msg = f"🔄{activation_config.card_type}卡未检出 → 切换{new_type}"
            activation_config.card_type = new_type
            next_run = datetime.now()

        # 统一记录日志和推送
        self.save_image(content=log_msg, push_flag=True)

        # 保存配置并设置下次执行
        self.config.save()
        self.set_next_run("KekkaiActivation", target=next_run)
        raise TaskEnd

    def harvest_card(self):
        """
        收卡的经验
        :return:
        """
        self.appear_then_click(self.I_A_HARVEST_EXP)  # 如果到最后没有领的话有下面的一些图片
        self.appear_then_click(self.I_A_HARVEST_FISH4)  # 斗鱼4/5区别不大 斗鱼的如果一直没有领的话
        self.appear_then_click(self.I_A_HARVEST_KAIKO_4)  # 太鼓4
        self.appear_then_click(self.I_A_HARVEST_KAIKO_3)  # 太鼓3
        self.appear_then_click(self.I_A_HARVEST_KAIKO_6)  # 太鼓6
        self.appear_then_click(self.I_A_HARVEST_FISH_6)  # 斗鱼6
        self.appear_then_click(self.I_A_HARVEST_MOON_3)  # 太阴3
        self.appear_then_click(self.I_A_HARVEST_FISH_3)  # 斗鱼三
