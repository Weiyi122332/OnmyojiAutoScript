# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from cached_property import cached_property

from module.exception import TaskEnd
from module.logger import logger
from module.base.timer import Timer
import tasks.GameUi.page as pages

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main, page_team, page_shikigami_records
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.GeneralRoom.general_room import GeneralRoom
from tasks.Component.GeneralInvite.general_invite import GeneralInvite
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.GoldYoukai.assets import GoldYoukaiAssets


class ScriptTask(GameUi, GeneralBattle, GeneralRoom, GeneralInvite, SwitchSoul, GoldYoukaiAssets):

    def before_run(self):
        page_battle_result = self.navigator.resolve_page(pages.page_battle_result)
        page_battle_result.recognizer = pages.any_of(self.I_GOLD_WIN, page_battle_result.recognizer)

    def run(self):
        self.before_run()
        # 切换御魂
        if self.config.gold_youkai.switch_soul.enable:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul(self.config.gold_youkai.switch_soul.switch_group_team)

        if self.config.gold_youkai.switch_soul.enable_switch_by_name:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul_by_name(self.config.gold_youkai.switch_soul.group_name,
                                         self.config.gold_youkai.switch_soul.team_name)

        # 开启加成
        con = self.config.gold_youkai.gold_youkai
        if con.buff_gold_50_click or con.buff_gold_100_click:
            self.goto_page(page_main)
            self.open_buff()
            if con.buff_gold_50_click:
                self.gold_50()
            if con.buff_gold_100_click:
                self.gold_100()
            self.close_buff()
        count = 0
        while count < 2:
            self.goto_page(page_team)
            self.check_zones('金币妖怪')
            # 开始
            if not self.create_room():
                self.gold_exit(con)
            self.ensure_public()
            self.create_ensure()
            # 进入到了房间里面
            wait_timer = Timer(50)
            wait_timer.start()
            while 1:
                self.screenshot()

                if not self.is_in_room():
                    continue
                if wait_timer.reached():
                    # 超过时间依然挑战
                    logger.warning('Wait for too long and start the challenge')
                    self.click_fire()
                    count += 1
                    self.run_general_battle()
                    break
                if not self.appear(self.I_ADD_5_1):
                    # 有人进来了，可以进行挑战
                    logger.info('There is someone in the room and start the challenge')
                    self.click_fire()
                    count += 1
                    self.run_general_battle()
                    break
        # 退出 (要么是在组队界面要么是在庭院)
        self.gold_exit(con)

    def gold_exit(self, con):
        if con.buff_gold_50_click or con.buff_gold_100_click:
            self.goto_page(page_main)
            self.open_buff()
            if con.buff_gold_50_click:
                self.gold_50(False)
            if con.buff_gold_100_click:
                self.gold_100(False)
            self.close_buff()

        self.finish_task_navigation()
        self.set_next_run(task='GoldYoukai', success=True, finish=False)
        raise TaskEnd('GoldYoukai')


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()

