# This Python file uses the following encoding: utf-8
# @brief    Configurations for Ryou Dokan Toppa (阴阳竂道馆突破配置)
# @author   jackyhwei
# @note     draft version without full test
# github    https://github.com/roarhill/oas
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from tasks.Component.SwitchSoul.switch_soul_config import SwitchSoulConfig
from tasks.Component.config_base import ConfigBase, Time, dynamic_hide
from tasks.Component.config_notify import TaskNotifyConfig
from tasks.Component.config_scheduler import Scheduler


class AttackAccountConfig(BaseModel):
    # 当天可攻击次数,用以记录当天运行历史,用作状态恢复,不用配置
    remain_attack_count: int = Field(default=-1, description='remain_attack_count_help')
    # remain_attack_count 值记录的时间,不用配置
    attack_date: str = Field(default='', description='attack_date_help')

    hide_fields = dynamic_hide('remain_attack_count', 'attack_date')

    def init_attack_count(self, callback=None):
        self.attack_date = ''
        self.remain_attack_count = -1
        if not callback:
            return
        callback()

    def set_attack_count(self, count=-1, callback=None):
        if count < 0:
            return
        self.attack_date = datetime.now().strftime("%Y-%m-%d")
        self.remain_attack_count = count
        if not callback:
            return
        callback()

    def del_attack_count(self, count, callback=None):
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self.attack_date or self.remain_attack_count < 0:
            self.attack_date = today
            self.remain_attack_count = -1
        else:
            self.remain_attack_count = max(0, self.remain_attack_count - count)
        if not callback:
            return
        callback()


class DokanConfig(BaseModel):
    # 只在周一到周四开启道馆
    monday_to_thursday: bool = Field(default=True, description='monday_to_thursday_help')
    # 任务结束时推送本次运行的结算截图；关闭时仍保存截图
    push_reward_images: bool = Field(default=True, description='push_reward_images_help')
    # 每馆首次点击准备后关闭游戏，10分钟后登录并继续道馆流程。
    prepare_offline_wait_enable: bool = Field(default=False, description='dokan_prepare_offline_wait_enable_help')
    # 道馆最小人数限制
    min_people_num: int = Field(default=-1, description='min_people_num_help')
    # MuMu原生鼠标滚轮，默认继续使用原来的手指滑动。
    native_wheel_enable: bool = Field(default=False, description='dokan_native_wheel_enable_help')
    # 超过此刷新次数后将最低防守人数减半，最多刷新20次
    find_dokan_refresh_count: int = Field(default=7, description='find_dokan_refresh_count_help')

    @model_validator(mode='before')
    @classmethod
    def migrate_wheel_setting(cls, data):
        if isinstance(data, dict) and 'scrcpy_wheel_enable' in data:
            data = dict(data)
            legacy = data.pop('scrcpy_wheel_enable')
            data.setdefault('native_wheel_enable', legacy)
        return data


class QQMessageConfig(BaseModel):
    qq_message_enable: bool = Field(default=False, description='qq_message_enable_help')
    welfare_plugin_url: str = Field(default='', description='welfare_plugin_url_help')
    welfare_plugin_token: str = Field(default='', description='welfare_plugin_token_help')
    qq_query_start_time: Time = Field(default=Time(hour=20), description='qq_query_start_time_help')
    qq_query_end_time: Time = Field(default=Time(hour=22), description='qq_query_end_time_help')
    qq_poll_interval: int = Field(default=60, ge=1, le=86400, description='qq_poll_interval_help')


class Dokan(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    dokan_config: DokanConfig = Field(default_factory=DokanConfig)
    qq_message_config: QQMessageConfig = Field(default_factory=QQMessageConfig)
    notification_config: TaskNotifyConfig = Field(default_factory=TaskNotifyConfig)
    dokan_member_switch_soul: SwitchSoulConfig = Field(default_factory=SwitchSoulConfig)
    attack_count_config: AttackAccountConfig = Field(default_factory=AttackAccountConfig)

    hide_fields = dynamic_hide('attack_count_config')
