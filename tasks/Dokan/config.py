# This Python file uses the following encoding: utf-8
# @brief    Configurations for Ryou Dokan Toppa (阴阳竂道馆突破配置)
# @author   jackyhwei
# @note     draft version without full test
# github    https://github.com/roarhill/oas
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.SwitchSoul.switch_soul_config import SwitchSoulConfig
from tasks.Component.config_base import ConfigBase, Time, dynamic_hide
from tasks.Component.config_notify import TaskNotifyConfig
from tasks.Component.config_scheduler import Scheduler


class AttackAccountConfig(BaseModel):
    # 当天可攻击次数,用以记录当天运行历史,用作状态恢复,不用配置
    remain_attack_count: int = Field(default=2, description='remain_attack_count_help')
    # remain_attack_count 值记录的时间,不用配置
    attack_date: str = Field(default='2023-01-01', description='attack_date_help')
    # 每日最大挑战次数(1-2,默认2次)
    daily_attack_count: int = Field(default=2, description='daily_attack_count_help')

    hide_fields = dynamic_hide('remain_attack_count', 'attack_date')

    def init_attack_count(self, callback=None):
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self.attack_date:
            self.attack_date = today
            self.remain_attack_count = 2
        if not callback:
            return
        callback()

    def set_attack_count(self, count=2, callback=None):
        if count < 0:
            return
        self.attack_date = datetime.now().strftime("%Y-%m-%d")
        self.remain_attack_count = count
        if not callback:
            return
        callback()

    def del_attack_count(self, count, callback=None):
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self.attack_date:
            self.attack_date = today
            self.remain_attack_count = 2
        self.remain_attack_count -= count
        if not callback:
            return
        callback()


class DokanConfig(BaseModel):
    dokan_run_time: Time = Field(Time(hour=20, minute=0, second=0), description='dokan_run_time_help')
    # 攻击优先顺序: 见习=0,初级=1...
    dokan_attack_priority: int = Field(default=0, description='dokan_attack_priority_help')
    # 只在周一到周四开启道馆
    monday_to_thursday: bool = Field(default=True, description='monday_to_thursday_help')
    # 任务结束时推送本次运行的结算截图；关闭时仍保存截图
    push_reward_images: bool = Field(default=True, description='push_reward_images_help')
    # 道馆最小人数限制
    min_people_num: int = Field(default=-1, description='min_people_num_help')
    # 超过此刷新次数后将最低防守人数减半，最多刷新20次
    find_dokan_refresh_count: int = Field(default=7, description='find_dokan_refresh_count_help')


class QQMessageConfig(BaseModel):
    qq_message_enable: bool = Field(default=False, description='qq_message_enable_help')
    welfare_plugin_url: str = Field(default='', description='welfare_plugin_url_help')
    welfare_plugin_token: str = Field(default='', description='welfare_plugin_token_help')
    qq_query_start_time: Time = Field(default=Time(hour=20), description='qq_query_start_time_help')
    qq_query_end_time: Time = Field(default=Time(hour=22), description='qq_query_end_time_help')
    qq_poll_interval: int = Field(default=60, ge=1, le=86400, description='qq_poll_interval_help')


class DokanBattleConfig(GeneralBattleConfig):
    continuous_battle: bool = True

    @field_validator('continuous_battle', mode='after')
    @classmethod
    def validate_continuous_battle(cls, v):
        return True


class Dokan(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    dokan_config: DokanConfig = Field(default_factory=DokanConfig)
    qq_message_config: QQMessageConfig = Field(default_factory=QQMessageConfig)
    notification_config: TaskNotifyConfig = Field(default_factory=TaskNotifyConfig)
    dokan_member_battle_conf: DokanBattleConfig = Field(default_factory=DokanBattleConfig)
    dokan_member_switch_soul: SwitchSoulConfig = Field(default_factory=SwitchSoulConfig)
    attack_count_config: AttackAccountConfig = Field(default_factory=AttackAccountConfig)
