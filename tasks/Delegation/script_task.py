# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from time import sleep, monotonic
from datetime import time, datetime, timedelta

from module.logger import logger
from module.exception import GameStuckError, TaskEnd

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main, page_delegation
from tasks.Delegation.config import DelegationConfig
from tasks.Delegation.assets import DelegationAssets


class ScriptTask(GameUi, DelegationAssets):

    def run(self):
        self.goto_page(page_delegation)
        self.check_reward()
        con: DelegationConfig = self.config.delegation.delegation_config
        if con.miyoshino_painting:
            self.delegate_one('画')
        if con.bird_feather:
            self.delegate_one('鸟羽')
        if con.find_earring:
            self.delegate_one('寻找耳环')
        if con.cat_boss:
            self.delegate_one('猫老大')
        if con.miyoshino:
            self.delegate_one('接送')
        if con.strange_trace:
            self.delegate_one('痕迹')


        self.set_next_run(task='Delegation', success=True, finish=True)
        raise TaskEnd

    def delegate_one(self, name: str) -> bool:
        """
        委派一个任务
        :param name:
        :return:
        """
        def ui_click(click, stop):
            while 1:
                self.screenshot()
                if self.appear(stop):
                    break
                if self.click(click, interval=1.5):
                    continue
        logger.hr('Delegation one', 2)
        self.O_D_NAME.keyword = name
        self.screenshot()
        if not self.ocr_appear(self.O_D_NAME):
            logger.warning(f'Delegation: {name} not found')
            return False
        while 1:
            self.screenshot()
            if self.appear(self.I_D_START):
                break
            # 如果出现’召回‘ ’返回‘ 说明这个是现在委派中
            # 需要退出
            if self.appear(self.I_D_BACK):
                logger.warning(f'Delegation: {name} is in delegation')
                self.ui_click_until_disappear(self.I_D_BACK)
                self.wait_until_appear(self.I_REWARDS_MIN)
                return False
            if self.appear_then_click(self.I_D_SKIP, interval=0.8):
                continue
            if self.appear_then_click(self.I_D_CONFIRM, interval=0.8):
                continue
            if self.ocr_appear_click(self.O_D_NAME, interval=1):
                continue
        # 进入委派  fefe e  fe
        logger.info(f'Enter Delegation: {name}')
        ui_click(self.C_D_ALL, self.I_D_SELECT_FIRST)
        # 委派开始
        logger.info(f'Delegation: {name} start')
        while 1:
            self.screenshot()
            if not self.appear(self.I_D_START):
                break
            if self.click(self.C_D_ALL, interval=0.8):
                continue
            if self.appear_then_click(self.I_D_START, interval=1.8):
                continue
        # ui_click(self.C_D_5, self.I_D_SELECT_5)
        # self.ui_click_until_disappear(self.I_D_START)

    def _advance_delegation_reward(self) -> bool:
        """只在对应控件可见时推进领奖，点击后由下一帧确认状态。"""
        for rule in (self.I_REWARDS_DONE, self.I_REWARDS_GET,
                     self.I_REWARDS_FALSE, self.I_CHAT_1, self.I_CHAT_2):
            if self.appear(rule):
                self.click(rule, interval=1)
                return True
        if self.appear(self.I_REWARDS_CHAT):
            # 文字与对话标志同时命中才点击对话文字，避免误点列表背景。
            chat_text = self.O_D_DONE_CHAT.ocr(self.device.image).strip()
            self.click(self.O_D_DONE_CHAT if chat_text else self.I_REWARDS_CHAT,
                       interval=0.8)
            return True
        return False

    def check_reward(self):
        idle_since = monotonic()
        deadline = idle_since + 60
        while monotonic() < deadline:
            self.screenshot()
            if self._advance_delegation_reward():
                idle_since = monotonic()
                continue
            if self.appear(self.I_REWARDS_MIN):
                # 先检查完成任务，不能因为停留三秒就跳过尚未领取的奖励。
                if self.appear(self.I_D_DONE):
                    self.wait_delegation_done_reward()
                    idle_since = monotonic()
                    continue
                if monotonic() - idle_since >= 3:
                    return
            else:
                idle_since = monotonic()
            sleep(0.2)
        raise GameStuckError('Delegation: reward processing did not return to an idle task list')

    def wait_delegation_done_reward(self):
        """确认完成入口已打开；仍在列表时有限重试，再推进对话至领奖。"""
        attempts = 0
        retry_at = 0.0
        deadline = monotonic() + 25
        reward_seen = False
        list_frames = 0
        while monotonic() < deadline:
            self.screenshot()
            # 按实际页面分流，不把“完成点击已发出”当作“已进入奖励页”。
            if self.appear(self.I_REWARDS_DONE):
                logger.info('Delegation reward confirmation appeared')
                return
            if self._advance_delegation_reward():
                reward_seen = True
                list_frames = 0
                continue
            if self.appear(self.I_REWARDS_MIN):
                if reward_seen:
                    list_frames += 1
                    if list_frames >= 2:
                        logger.info('Delegation reward flow returned to task list')
                        return
                elif self.appear(self.I_D_DONE):
                    list_frames = 0
                    if monotonic() >= retry_at:
                        if attempts >= 3:
                            raise GameStuckError(
                                'Delegation: completed task is still on list after 3 entry clicks; '
                                'reward dialog never opened'
                            )
                        # 当前帧匹配完成标签，框内取点后向右100像素点击任务卡。
                        x, y = self.I_D_DONE.coord()
                        self.device.click(x=x + 100, y=y,
                                          control_name='DELEGATION_DONE_OFFSET_RIGHT_100')
                        attempts += 1
                        retry_at = monotonic() + 5
                        logger.info(f'Delegation open completed-task reward: attempt={attempts}/3; '
                                    f'click=({x + 100}, {y}); awaiting page confirmation')
                else:
                    list_frames = 0
            else:
                list_frames = 0
            sleep(0.2)
        raise GameStuckError(
            'Delegation: reward flow timed out; '
            f'entry_clicks={attempts}, reward_page_seen={reward_seen}'
        )


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device
    from memory_profiler import profile
    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)

    # t.delegate_one('弥助的画')
    t.run()


