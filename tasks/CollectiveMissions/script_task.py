# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time
from time import sleep

import random
import re
import numpy as np
from cached_property import cached_property
from enum import Enum
from datetime import timedelta
from module.atom.image import RuleImage

from module.exception import TaskEnd, RequestHumanTakeover
from module.logger import logger
from module.base.timer import Timer
from module.atom.ocr import RuleOcr
from tasks.CollectiveMissions.config import MC
from tasks.CollectiveMissions.page import page_collective_missions

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main, page_guild
from tasks.CollectiveMissions.assets import CollectiveMissionsAssets


class ScriptTask(GameUi, CollectiveMissionsAssets):
    """阴阳寮集体任务"""

    current_mission: MC | None = None

    def run(self):
        self.goto_page(page_collective_missions)
        logger.info('Start to detect missions')
        self.get_task_reward()
        if self.is_finish():
            self.goto_page(page_main)
            self.set_next_run(task='CollectiveMissions', success=True)
            raise TaskEnd
        mission_config = self.config.collective_missions.missions_config
        target_missions = mission_config.selected_missions
        selected = self.select_and_update_cur_mission(target_missions, max_switch=mission_config.refresh_count)
        if not selected or self.current_mission not in target_missions:
            target_names = ', '.join(mission.value for mission in target_missions)
            logger.warning(f'Mission selection failed, skip targets: {target_names}')
            self.goto_page(page_main)
            self.set_next_run(task='CollectiveMissions', success=False)
            raise TaskEnd
        match self.current_mission:
            case MC.FEED:
                success = self._feed()  # 喂 N 卡
            case MC.AW1 | MC.AW2 | MC.AW3 | MC.GR1 | MC.GR2 | MC.GR3:
                success = self._donate()  # 捐材料
            case MC.SO1 | MC.SO2:
                success = self._soul()  # 捐御魂
        self.goto_page(page_main)
        self.set_next_run(task='CollectiveMissions', success=success)
        raise TaskEnd

    def _read_mission_text(self) -> str:
        """名称为空时等待画面变化，只对变化后的名称区域做单行识别。"""
        previous_region = None
        mission_text = ''
        x, y, width, height = self.O_CM_2.roi
        for attempt in range(3):
            self.screenshot()
            region = self.device.image[y:y + height, x:x + width]
            if previous_region is None or not np.array_equal(region, previous_region):
                # 任务名称是固定横排文字，不调用完整文字检测；相同画面不重复识别。
                mission_text = self.O_CM_2.ocr_single_line(self.device.image).strip()
                previous_region = region.copy()
            if mission_text:
                return mission_text
            logger.warning(f'No mission name detected ({attempt + 1}/3)')
            if attempt < 2:
                sleep(0.4)
        return ''

    def select_and_update_cur_mission(self, mission: MC | tuple[MC, ...], max_switch: int = 15) -> bool:
        """当前任务匹配任意目标就提交，最多刷新配置的次数。
        :return: 已确认当前任务属于可提交任务时返回True
        """
        self.current_mission = None
        target_missions = (mission,) if isinstance(mission, MC) else mission
        target_missions = tuple(dict.fromkeys(target for target in target_missions if target != MC.NONE))
        if not target_missions:
            logger.warning('No collective mission selected, skip')
            return False
        target_names = ', '.join(target.value for target in target_missions)
        pre_mission = ''
        switch_fail_cnt, max_retry = 0, random.randint(2, 3)  # 点了没反应, 可能之前已经做了其他任务导致无法切换
        switch_cnt = 0
        logger.info(f'Accepted missions: {target_names}; refresh limit: {max_switch}')
        while True:
            mission_text = self._read_mission_text()
            if not mission_text:
                logger.warning(f'Cannot identify current mission, skip targets: {target_names}')
                return False
            # 识别当前任务
            try:
                detect_mission = MC(mission_text)
                logger.info(f"Current: {detect_mission.value}, targets: {target_names}")
                self.current_mission = detect_mission
                if detect_mission in target_missions:
                    logger.info(f"Success select mission[{mission_text}]")
                    return True
            except ValueError:
                logger.warning(f'Unknown {mission_text}, skip')

            # 最后一次切换也必须先识别，再检查上限。
            switch_fail_cnt = 0 if pre_mission != mission_text else (switch_fail_cnt + 1)
            if switch_fail_cnt >= max_retry:
                logger.warning(f'Cannot switch mission: current={mission_text}, targets={target_names}')
                self.current_mission = None
                return False
            if switch_cnt >= max_switch:
                logger.warning(f'Cannot find target missions: {target_names}, current={mission_text}, exit')
                self.current_mission = None
                return False
            logger.info('Try switch to next mission')
            if not self.appear_then_click(self.I_CM_SWITCH, interval=0.6):
                logger.warning(f'Mission switch button unavailable: current={mission_text}, targets={target_names}')
                self.current_mission = None
                return False
            pre_mission = mission_text
            self.current_mission = None
            switch_cnt += 1
            sleep(random.uniform(0.6, 1.2))
            self.device.click_record_clear()

    def _open_submission(self, expected: RuleImage) -> bool:
        """打开一次提交窗口，确认类型；不匹配或5秒内未出现则退出。"""
        deadline = time.monotonic() + 5
        clicked = False
        window_markers = (self.I_CM_PRESENT, self.I_SL_SUBMIT, self.I_FEED_HEAP)
        while True:
            self.screenshot()
            if self.appear(expected):
                return True
            for marker in window_markers:
                if marker is not expected and self.appear(marker):
                    logger.warning(f'Unexpected mission submission window: expected={expected}, actual={marker}')
                    return False
            if time.monotonic() >= deadline:
                logger.warning(f'Mission submission window did not appear within 5s: {expected}')
                return False
            if not clicked:
                self.click(self.C_CM_1)
                clicked = True
            sleep(0.2)

    def _donate(self):
        """捐材料"""
        if not self._open_submission(self.I_CM_PRESENT):
            return False
        logger.info('Start to donate')
        # 判断哪一个的材料最多
        self.screenshot()
        max_index = 0
        max_number = 0
        for i, ocr in enumerate([self.O_CM_1_MATTER, self.O_CM_2_MATTER,
                                 self.O_CM_3_MATTER, self.O_CM_4_MATTER]):
            curr, remain, total = ocr.ocr(self.device.image)
            if total > max_number:
                max_number = total
                max_index = i
        if max_number <= 30:
            logger.info('The number of all matter is less than 30')
            logger.info('Please check your game resolution')
            raise RequestHumanTakeover
        match_swipe = {
            0: self.S_CM_MATTER_1,
            1: self.S_CM_MATTER_2,
            2: self.S_CM_MATTER_3,
            3: self.S_CM_MATTER_4,
        }
        # 滑动到最多的材料
        random_click = [self.I_CM_ADD_1, self.I_CM_ADD_2, self.I_CM_ADD_3, self.I_CM_ADD_4]
        window_control = self.config.script.device.control_method == 'window_message'
        swipe_count = 0
        click_count = 0
        while 1:
            self.screenshot()
            if self.appear(self.I_CM_MATTER):
                break
            if not window_control and self.swipe(match_swipe[max_index], interval=2.5):
                swipe_count += 1
                time.sleep(1.5)
                continue
            # 为什么使用window_message无法滑动
            if window_control and click_count > 30:
                logger.info('Swipe to the most matter failed')
                logger.info('Please check your game resolution')
                break
            if window_control and self.click(random.choice(random_click), interval=0.7):
                click_count += 1
                continue
            if not window_control and swipe_count >= 5:
                logger.info('Swipe to the most matter failed')
                logger.info('Please check your game resolution')
                raise RequestHumanTakeover
        logger.info('Swipe to the most matter')
        self.get_reward_and_close(self.I_CM_PRESENT)
        logger.info('Donate finished')
        return True

    def _soul(self):
        """提交御魂"""
        if not self._open_submission(self.I_SL_SUBMIT):
            return False
        while 1:
            self.screenshot()
            number_text = self.O_SL_NUMBER.ocr(self.device.image)
            submit_number = int(re.findall(r'\d+', number_text)[-1])
            if submit_number > 0:
                break
            if self.ocr_appear(self.O_SL_LEVEL):
                # 如果没有识别到这个，那就说明没有御魂可以提交了，要退出
                logger.warning('No soul can be submit')
                self.ui_click(self.I_UI_BACK_RED, self.I_CM_RECORDS)
                return False
            if self.click(self.L_SL_LONG, interval=2.5):
                time.sleep(1)
                continue
        logger.info('Start to collect soul rewards')
        self.get_reward_and_close(self.I_SL_SUBMIT)
        logger.info('Finish to collect soul rewards')
        return True

    def _feed(self):
        """提交N卡"""
        logger.info('Start to feed N')
        if not self._open_submission(self.I_FEED_HEAP):
            return False
        logger.info('Submit to feed N')
        click_list = random.sample([self.L_FEED_CLICK_1, self.L_FEED_CLICK_2, self.L_FEED_CLICK_3, self.L_FEED_CLICK_4], 2)
        while 1:
            self.screenshot()
            if self.appear(self.I_FEED_SUBMIT):
                break
            for click in click_list:
                self.click(click)
        logger.info('Start to collect feed N rewards')
        self.get_reward_and_close(self.I_FEED_SUBMIT)
        logger.info('Finish to collect feed N rewards')
        return True

    def is_finish(self):
        """判断寮三十是否已经捐满"""
        self.screenshot()
        current, remain, total = self.O_CM_NUMBER.ocr(self.device.image)
        if current == total == 30:
            logger.info('Today\'s missions have been completed')
            return True
        return False

    def get_task_reward(self):
        """获取其他已完成的任务奖励"""
        timeout_timer = Timer(3).start()
        process_reward = False
        while not timeout_timer.reached():
            self.maybe_screenshot()
            if not self.appear(self.I_CM_GET_REWARD):
                break
            process_reward = True
            logger.info('Discover the tasks that have been completed')
            self.get_reward_and_close(self.I_CM_GET_REWARD)
            timeout_timer.reset()
        if process_reward:
            logger.info('Get task reward finished')
        else:
            logger.info('No task reward')

    def get_reward_and_close(self,  target: RuleImage):
        # 捐赠可能有双倍的，需要领两次
        reward_number = 0
        timeout_timer = Timer(3).start()
        while not timeout_timer.reached():
            self.screenshot()
            if reward_number >= 2:
                break
            if self.ui_reward_appear_click(False):
                reward_number += 1
                continue
            if self.appear_then_click(target, interval=1):
                continue
        self.ui_reward_appear_click(True)  # 兜底再尝试领取一次


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device
    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()

