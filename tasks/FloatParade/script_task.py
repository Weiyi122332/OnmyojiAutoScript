# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time
from time import sleep

from tasks.GameUi.task_pages import page_fp_main, page_fp_task, page_fp_placement
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main
from tasks.TalismanPass.assets import TalismanPassAssets
from tasks.FloatParade.assets import FloatParadeAssets
from tasks.FloatParade.config import FloatParadeConfig, LevelReward

from module.logger import logger
from module.exception import TaskEnd
from module.base.timer import Timer

class ScriptTask(GameUi, FloatParadeAssets, TalismanPassAssets):

    conf: FloatParadeConfig

    def run(self):
        self.conf = self.config.float_parade.float_parade
        self.goto_page(page_main)
        if not self.appear(self.I_FP_ACCESS):
            logger.warn('Cannot find float parade enter button, exit')
            self.set_next_run(task='FloatParade', success=False, finish=True)
            raise TaskEnd
        self.goto_page(page_fp_main)
        self.collect_exp()
        self.collect_placement_reward()
        # 收取花车等级奖励
        # self.get_flower(con.level_reward1, con.level_reward2) # 第一种
        self.finish_task_navigation()
        self.set_next_run(task='FloatParade', success=True, finish=True)
        raise TaskEnd('FloatParade')

    def collect_exp(self):
        """收取花车经验"""
        logger.hr('Collect exp', 3)
        self.goto_page(page_fp_task)
        sleep(1.5)  # 逆天UI, 没有完成也会一闪而过I_FP_GETALL1
        self.screenshot()
        if not self.appear(self.I_FP_GETALL1):
            logger.info('Not appear get exp button')
            return
        self.ui_get_reward(self.I_FP_GETALL1)
        self.goto_page(page_fp_main)

    def get_flower(self, level1: LevelReward = LevelReward.TWO, level2: LevelReward = LevelReward.TWO):
        """
        收取花合战等级奖励
        :return:
        """
        match_level = {
            LevelReward.ONE: self.I_TP_LEVEL_1,
            LevelReward.TWO: self.I_TP_LEVEL_2,
            LevelReward.THREE: self.I_TP_LEVEL_3,
        }
        self.screenshot()
        if not self.appear(self.I_FP_GETALL0):
            logger.info('No any level reward')
            return
        logger.info('Appear level reward')
        # self.ui_click(self.I_FP_GETALL0, self.I_TP_GET_ALL)
        logger.info('Click level reward')
        check_timer = Timer(2)
        check_timer.start()
        while 1:
            self.screenshot()
            # 批量选择
            if self.appear_then_click(self.I_BATCH_SELECTION, interval=1.5):
                continue
            if self.appear_then_click(self.I_BATCH_SELECTION_CONFIRM, interval=0.8):
                continue

            if self.appear(self.I_FP_GIFT_FLAG1) and self.appear_then_click(match_level[level1], interval=0.8):
                logger.info(f'Select {level1} reward')
                if self.appear_then_click(self.I_OVERFLOW_CONFIRME, interval=0.8):
                    pass
                check_timer.reset()
                continue

            if self.appear(self.I_FP_GIFT_FLAG2) and self.appear_then_click(match_level[level2], interval=0.8):
                logger.info(f'Select {level2} reward')
                if self.appear_then_click(self.I_OVERFLOW_CONFIRME, interval=0.8):
                    pass
                check_timer.reset()
                continue

            if self.ui_reward_appear_click(False):
                logger.info('Get reward')
                check_timer.reset()
                continue
            if check_timer.reached():
                logger.warning('No reward and break')
                break
            if self.appear_then_click(self.I_FP_GETALL0, interval=2.1):
                logger.info('Get all reward')
                check_timer.reset()
                continue

    def collect_placement_reward(self):
        """收取放置奖励"""
        logger.hr('Collect placement reward', 3)
        self.goto_page(page_fp_placement)
        if self.appear(self.I_FP_PR_CANNOT_GET):
            logger.warn('Not have placement reward, exit')
        else:
            logger.info('Get placement reward')
            self.ui_get_reward(self.I_FP_PR_CAN_GET)
        self.goto_page(page_fp_main)


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device
    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()
