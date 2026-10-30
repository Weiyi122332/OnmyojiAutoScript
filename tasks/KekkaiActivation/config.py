# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from enum import Enum
from pydantic import BaseModel, Field, field_validator
from tasks.Component.config_base import ConfigBase, TimeDelta, dynamic_hide
from tasks.Component.config_scheduler import Scheduler
from tasks.Utils.config_enum import ShikigamiClass


class CardType(str, Enum):
    ALTERNATE = '轮换'
    FISH = '斗鱼'
    TAIKO = '太鼓'
    

class ActivationScheduler(Scheduler):
    priority: int = Field(default=2, description='priority_help')
    success_interval: TimeDelta = Field(default=TimeDelta(days=1), description='success_interval_help')
    failure_interval: TimeDelta = Field(default=TimeDelta(hours=10), description='failure_interval_help')


class ActivationConfig(BaseModel):
    @field_validator('card_type', mode='before')
    @classmethod
    def migrate_rotation_name(cls, value):
        return CardType.ALTERNATE if value == '轮换斗鱼/太鼓' else value

    hide_fields = dynamic_hide('last_card_type', 'pending_card_type')

    card_type: CardType = Field(default=CardType.ALTERNATE, description='card_rule_help')
    last_card_type: CardType | None = Field(default=None, description='上次成功挂卡类型')
    pending_card_type: CardType | None = Field(default=None, description='已选中待激活的卡类型')
    min_taiko_num: int = Field(default=8, description='挂卡太鼓每小时最少收益,低于则不挂卡')
    min_fish_num: int = Field(default=16, description='挂卡斗鱼每小时最少收益,低于则不挂卡')
    exchange_before: bool = Field(default=True, description='exchange_before_help')
    exchange_max: bool = Field(default=True, description='exchange_max_help')
    auto_fill: bool = Field(default=False, description='auto_fill_help')
    shikigami_class: ShikigamiClass = Field(default=ShikigamiClass.N, description='shikigami_class_help')
    card_not_found_count: int = Field(default=0, description='未发现卡次数')


class KekkaiActivation(ConfigBase):
    scheduler: ActivationScheduler = Field(default_factory=ActivationScheduler)
    activation_config: ActivationConfig = Field(default_factory=ActivationConfig)
