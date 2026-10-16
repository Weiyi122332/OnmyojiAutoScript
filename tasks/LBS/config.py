# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from enum import Enum

from pydantic import BaseModel, Field, SerializationInfo, field_serializer
from tasks.Component.config_base import ConfigBase
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.config_scheduler import Scheduler
from tasks.Component.SwitchSoul.switch_soul_config import SwitchSoulConfig


class LBSMode(str, Enum):
    SOLO = '单人挑战'
    TEAM = '组队匹配'
    DRIVE = '开车模式'


class LBSConfig(BaseModel):
    # 限制次数（想打的次数/想开的次数，与活动剩余次数无关）
    limit_count: int = Field(default=30, description='lbs_limit_count_help')
    # 单人/组队刷完游戏内剩余次数，覆盖手动次数限制。
    finish_remaining: bool = Field(default=False, description='lbs_finish_remaining_help')
    # 运行模式
    mode: LBSMode = Field(default=LBSMode.SOLO, description='lbs_mode_help')

    @property
    def finish_remaining_enabled(self) -> bool:
        return self.finish_remaining and self.mode != LBSMode.DRIVE

    @field_serializer('finish_remaining')
    def serialize_finish_remaining(self, value: bool, info: SerializationInfo):
        if info.context and info.context.get('hide') and self.mode == LBSMode.DRIVE:
            return 0xABCDEF
        return value


class LBS(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    lbs_config: LBSConfig = Field(default_factory=LBSConfig)
    switch_soul: SwitchSoulConfig = Field(default_factory=SwitchSoulConfig)
    general_battle_config: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
