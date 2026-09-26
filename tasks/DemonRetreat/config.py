# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from datetime import timedelta
from pydantic import BaseModel, Field

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.SwitchSoul.switch_soul_config import SwitchSoulConfig
from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import ConfigBase, Time


class DemonRetreatTime(ConfigBase):
    # 自定义运行时间
    custom_run_time: Time = Field(default=Time(hour=10, minute=0, second=0), description='demon_retreat_time_help')


class DemonRetreatStart(ConfigBase):
    auto_start: bool = Field(default=False, description='demon_retreat_auto_start_help')
    difficulty: int = Field(default=1, ge=1, le=8, description='demon_retreat_difficulty_help')


class DemonRetreat(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    demon_retreat_time: DemonRetreatTime = Field(default_factory=DemonRetreatTime)
    demon_retreat_start: DemonRetreatStart = Field(default_factory=DemonRetreatStart)
    general_battle: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
    switch_soul_config: SwitchSoulConfig = Field(default_factory=SwitchSoulConfig)
