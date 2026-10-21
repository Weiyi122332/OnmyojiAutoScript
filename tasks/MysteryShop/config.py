# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from datetime import timedelta, datetime, time
from pydantic import BaseModel, Field
from tasks.Component.GeneralInvite.config_invite import InviteBaseConfig as InviteConfig

from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import ConfigBase, Time


class ShopConfig(BaseModel):
    time_of_mystery: Time = Field(default=Time(hour=0, minute=0, second=0), description='time_of_mystery_help')
    mystery_amulet: bool = Field(default=False)
    black_daruma_scrap: bool = Field(default=False)
    shop_kaiko_3: bool = Field(default=False)
    shop_kaiko_4: bool = Field(default=False)


class MysteryShop(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    shop_config: ShopConfig = Field(default_factory=ShopConfig)
    invite_config: InviteConfig = Field(default_factory=InviteConfig)

