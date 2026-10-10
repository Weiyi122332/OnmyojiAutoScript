# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from enum import Enum

from datetime import timedelta
from pydantic import BaseModel, Field, validator

from tasks.Component.config_base import MultiLine
from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import ConfigBase, TimeDelta
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.SwitchSoul.switch_soul_config import SwitchSoulConfig


class MC(str, Enum):
    NONE = '不选择'
    AW1 = '觉醒一'
    AW2 = '觉醒二'
    AW3 = '觉醒三'
    GR1 = '御灵一'
    GR2 = '御灵二'
    GR3 = '御灵三'
    SO1 = '御魂一'
    SO2 = '御魂二'
    FEED = '养成'  # 喂N卡


class MissionsConfig(BaseModel):
    missions_select: MC = Field(default=MC.AW1, title='可选任务 1',
                               description='当前任务匹配任意一个已选任务就提交，不分先后顺序')
    missions_select_2: MC = Field(default=MC.NONE, title='可选任务 2',
                                 description='选择其他可提交的任务；不选择表示停用此项')
    missions_select_3: MC = Field(default=MC.NONE, title='可选任务 3',
                                 description='选择其他可提交的任务；不选择表示停用此项')
    refresh_count: int = Field(default=15, ge=0, title='刷新次数上限',
                               description='未匹配已选任务时最多刷新几次；0 表示只检查当前任务，无法刷新时提前结束')

    @property
    def selected_missions(self) -> tuple[MC, ...]:
        """忽略停用项和重复选择，保留所有可提交的任务。"""
        return tuple(dict.fromkeys(mission for mission in (
            self.missions_select, self.missions_select_2, self.missions_select_3,
        ) if mission != MC.NONE))


class CollectiveMissions(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    missions_config: MissionsConfig = Field(default_factory=MissionsConfig)


if __name__ == '__main__':
    print(MC('觉醒一'))
