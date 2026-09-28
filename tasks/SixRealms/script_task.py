# This Python file uses the following encoding: utf-8
# @author AzurTian
from cached_property import cached_property
from datetime import datetime, timedelta
import re

from pathlib import Path
from module.base.timer import Timer
from module.exception import GameStuckError, TaskEnd
from tasks.Component.SwitchSoul.switch_soul_config import SwitchSoulConfig
from tasks.GameUi.navigator import GameUi

from tasks.SixRealms.config import SixRealmsType, SixRealms
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.GameUi.page import page_main, page_shikigami_records
from module.logger import logger
from tasks.SixRealms.assets import SixRealmsAssets
from tasks.SixRealms.moon_sea.moon_sea import MoonSea
from tasks.SixRealms.peacock_kingdom.peacock_kingdom import PeacockKingdom
from tasks.SixRealms.page import page_moon_sea, page_peacock_kingdom


class ScriptTask(GameUi, SwitchSoul):
    switched_soul = False

    @cached_property
    def moon_sea(self) -> MoonSea:
        return MoonSea(self.config, self.device)

    @cached_property
    def peacock_kingdom(self) -> PeacockKingdom:
        return PeacockKingdom(self.config, self.device)

    def run(self):
        _config = self.config.model.six_realms
        cnt = 0
        while True:
            if _config.six_realms_gate.stop_when_wanxiang_exhausted:
                gate_page = {
                    SixRealmsType.MOON_SEA: page_moon_sea,
                    SixRealmsType.PEACOCK_KINGDOM: page_peacock_kingdom,
                }.get(_config.six_realms_gate.six_realms_type)
                if gate_page is None:
                    raise ValueError(f'Invalid six_realms_type {_config.six_realms_gate.six_realms_type}')
                if self.read_wanxiang_blessing_count(gate_page) == 0:
                    logger.info('Wanxiang Blessings exhausted; stop before starting another run')
                    break
            else:
                if cnt >= _config.six_realms_gate.limit_count:
                    logger.info('Run out of count, exit')
                    break
                if datetime.now() - self.start_time >= _config.six_realms_gate.limit_time_v:
                    logger.info('Run out of time, exit')
                    break
            match _config.six_realms_gate.six_realms_type:
                case SixRealmsType.MOON_SEA:
                    self.switch_current_soul(_config.switch_soul_config)
                    self.moon_sea.run()
                case SixRealmsType.PEACOCK_KINGDOM:
                    self.switch_current_soul(_config.pk_switch_soul_conf)
                    self.peacock_kingdom.run()
                case _:
                    raise ValueError(f'Invalid six_realms_type {_config.six_realms_gate.six_realms_type}')
            cnt += 1
        self.goto_page(page_main)
        self.set_next_run('SixRealms', success=True, finish=True)
        raise TaskEnd

    def read_wanxiang_blessing_count(self, gate_page) -> int:
        """在六道之门开启界面连续两帧确认右上角的万象赐福数量。"""
        self.goto_page(gate_page)
        rule = SixRealmsAssets.O_SR_WANXIANG_BLESSING_COUNT
        timer = Timer(15).start()
        previous_count = None
        matches = 0
        last_text = None
        while not timer.reached():
            self.screenshot()
            last_text = str(rule.detect_text(self.device.image)).strip()
            if not re.fullmatch(r'\d{1,4}', last_text):
                matches = 0
                continue
            count = int(last_text)
            matches = matches + 1 if count == previous_count else 1
            previous_count = count
            if matches >= 2:
                logger.info(f'Remaining Wanxiang Blessings: {count}')
                return count
        raise GameStuckError(f'Cannot read Wanxiang Blessing count: {last_text!r}')

    def switch_current_soul(self, switch_soul_config: SwitchSoulConfig):
        """切换当前六道御魂"""
        if self.switched_soul:
            return
        if switch_soul_config.enable:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul(switch_soul_config.switch_group_team)
        if switch_soul_config.enable_switch_by_name:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul_by_name(switch_soul_config.group_name, switch_soul_config.team_name)
        self.switched_soul = True


if __name__ == '__main__':
    path = Path(r'D:\dev\OnmyojiAutoScript\tasks\SixRealms\moon_sea\ms')

    for file in path.iterdir():
        # 只处理文件，并且文件名以 gate1_ 开头
        if file.is_file() and file.name.startswith('gate1_'):
            new_name = 'ms_' + file.name[len('gate1_'):]
            new_path = file.with_name(new_name)

            print(f'{file.name} -> {new_name}')
            file.rename(new_path)

