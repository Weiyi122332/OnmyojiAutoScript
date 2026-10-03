import time

from module.exception import TaskEnd
from module.logger import logger
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.GameUi.default_pages import random_click
from tasks.GameUi.game_ui import GameUi
from tasks.FrogChallenge.assets import FrogChallengeAssets
from tasks.FrogChallenge.config import FrogChallenge
import tasks.FrogChallenge.page as pages


class ScriptTask(GeneralBattle, GameUi, SwitchSoul, FrogChallengeAssets):
    """青蛙瓷器挑战赛"""

    conf: FrogChallenge = None

    # 连续识别不到骰子奖励进度时的退出保护(避免识别失败后无脑点挑战)
    ocr_fail_limit = 3
    # 连续挑战但奖励进度不涨时的退出保护(避免挑战点不中时空转)
    no_progress_limit = 3

    def run(self):
        self.conf = self.config.frog_challenge
        self.switch_soul()
        # 点击庭院右侧图标直接进入挑战页面, 没有中间页面
        self.goto_page(pages.page_frog_challenge)
        success = self.run_challenge()
        self.goto_page(pages.page_main)
        self.set_next_run(task='FrogChallenge', success=success, finish=success)
        raise TaskEnd

    def run_challenge(self) -> bool:
        """循环挑战, 上限以"神秘骰子奖励进度"实时识别为准

        进度形如 25/50: 左边是今日已经获取的骰子, 右边是今日可以获取的总量;
        每次挑战 25 个骰子, 奖励最多累计 3 天(右值会变成 50/100/150),
        所以不写死次数, 全部以实时识别为准。
        本活动没有锁定阵容功能, 所以不切换锁定, 由通用战斗直接点准备进战斗。

        Returns:
            bool: True 表示今日奖励刷满; False 表示识别/挑战异常提前退出
        """
        logger.hr('FrogChallenge battle', 2)
        battle_count = 0
        ocr_fail_count = 0
        no_progress_count = 0
        last_acquired = -1
        while True:
            self.screenshot()
            # 首次进入的剧情: 跳过
            if self.appear_then_click(self.I_FC_SKIP, interval=0.8):
                logger.info('Skip story')
                continue
            current_page = self.get_current_page()
            if current_page == pages.page_frog_challenge:
                # 战斗按钮变成"无奖励"状态: 今日没奖励了, 收工
                if self.appear(self.I_FC_FIRE_STOP):
                    logger.info('No reward battle left, exit')
                    return True
                # 今日已经获取/今日可以获取
                acquired, remain, total = self.O_MYSTERY_DICE_REWARD.ocr(
                    self.device.image
                )
                if total <= 0:
                    ocr_fail_count += 1
                    logger.warning(
                        f'Cannot read dice reward [{ocr_fail_count}/{self.ocr_fail_limit}]'
                    )
                    if ocr_fail_count >= self.ocr_fail_limit:
                        logger.warning('Dice reward unrecognizable, exit')
                        return False
                    time.sleep(0.5)
                    continue
                ocr_fail_count = 0
                logger.info(f'Dice reward today {acquired}/{total}, remain {remain}')
                if acquired >= total:
                    logger.info('Today reward reached, exit')
                    return True
                # 上一轮挑战没有让进度涨, 说明挑战没打起来
                if last_acquired >= 0 and acquired <= last_acquired:
                    no_progress_count += 1
                    logger.warning(
                        f'Reward progress not increased [{no_progress_count}/{self.no_progress_limit}]'
                    )
                    if no_progress_count >= self.no_progress_limit:
                        logger.warning('Cannot start challenge, exit')
                        return False
                else:
                    no_progress_count = 0
                last_acquired = acquired
                # 挑战
                if self.appear_then_click(self.I_FC_FIRE, interval=1.2):
                    logger.info(
                        f'Battle [{battle_count + 1}], reward {acquired}/{total}'
                    )
                    time.sleep(0.5)
                    if self.appear(self.O_CLICK_ANYWHERE_CONTINUE, interval=1):
                        random_click(ltrb=(True, False, False, False))
                    self.run_general_battle(
                        config=self.conf.general_battle_config,
                        exit_matcher=pages.page_frog_challenge,
                    )
                    battle_count += 1
                    self.device.stuck_record_clear()
                    continue
            time.sleep(0.2)

    def switch_soul(self):
        """切换御魂"""
        if self.conf.switch_soul_config.enable:
            self.goto_page(pages.page_shikigami_records)
            self.run_switch_soul(self.conf.switch_soul_config.switch_group_team)
        if self.conf.switch_soul_config.enable_switch_by_name:
            self.goto_page(pages.page_shikigami_records)
            self.run_switch_soul_by_name(
                self.conf.switch_soul_config.group_name,
                self.conf.switch_soul_config.team_name,
            )


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()
