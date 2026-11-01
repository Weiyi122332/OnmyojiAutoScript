# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from datetime import timedelta, datetime
from pydantic import BaseModel, Field
from pydantic import BeforeValidator
from typing import Annotated

from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import ConfigBase, DateTime, dynamic_hide
from tasks.Utils.config_enum import DemonClass


def _buy_all_enabled(value):
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str) and value.strip().lstrip('-').isdigit():
        return int(value) > 0
    return value


BuyAll = Annotated[bool, BeforeValidator(_buy_all_enabled)]


class ThousandThings(BaseModel):
    # 千物宝箱
    enable: bool = Field(title='Enable', default=False)
    earn_money: bool = Field(title='Earn Money', default=False, description='earn_money_help')
    mystery_amulet: bool = Field(title='Mystery Amulet', default=False)
    black_daruma_fragment: bool = Field(title='Black Daruma Fragment', default=False)
    ap: bool = Field(title='AP', default=False, description='ap_help')


class Consignment(BaseModel):
    # 寄售屋
    enable: bool = Field(title='Enable', default=False)
    buy_sale_ticket: bool = Field(title='Buy Sale Ticket', default=False, description='buy_sale_ticket_help')


class Scales(BaseModel):
    # 密卷屋 蛇皮
    enable: bool = Field(title='Enable', default=False)
    orochi_scales: BuyAll = Field(title='Orochi Scales', default=True, description='buy_all_remaining_help')
    demon_souls: BuyAll = Field(title='Demon Souls', default=True, description='buy_all_remaining_help')
    demon_class: DemonClass = Field(title='DemonClass', default=DemonClass.TSUCHIGUMO, description='demon_class_help')
    demon_position: int = Field(title='Demon Position', default=1, description='demon_position_help')
    picture_book_scrap: BuyAll = Field(title='Picture Book Scrap', default=True, description='buy_all_remaining_help')
    enable_book_auto: bool = Field(title='Enable Book Auto', default=False, description='enable_book_auto_help')
    picture_book_rule: str = Field(title='Picture Book Rule', default='auto', description='picture_book_rule_help')


class SpecialRoom(BaseModel):
    # 杂货铺 特殊购买
    enable: bool = Field(title='Enable', default=False)
    totem_pass: bool = Field(title='Totem Pass', default=False)
    medium_bondling_discs: BuyAll = Field(title='Medium Bondling Discs', default=False, description='buy_all_remaining_help')
    low_bondling_discs: BuyAll = Field(title='Low Bondling Discs', default=False, description='buy_all_remaining_help')


class HonorRoom(BaseModel):
    # 杂货铺 荣誉购买
    enable: bool = Field(title='Enable', default=False)
    mystery_amulet: bool = Field(title='Mystery Amulet', default=False, description='mystery_amulet_help_honor')
    black_daruma_scrap: bool = Field(title='Black Daruma Scrap', default=False, description='black_daruma_scrap_help_honor')


class FriendshipPoints(BaseModel):
    # 杂货铺 友情点
    enable: bool = Field(title='Enable', default=False)
    white_daruma: bool = Field(title='White Daruma', default=False)
    red_daruma: int = Field(title='Red Daruma', default=0)
    broken_amulet: int = Field(title='Broken Amulet', default=0)


class MedalRoom(BaseModel):
    # 杂货铺 勋章购买
    enable: bool = Field(title='Enable', default=False)
    black_daruma: bool = Field(title='Black Daruma', default=False)
    mystery_amulet: bool = Field(title='Mystery Amulet', default=False)
    ap_100: bool = Field(title='AP 100', default=False)
    random_soul: bool = Field(title='Random Soul', default=False)
    white_daruma: bool = Field(title='White Daruma', default=False)
    challenge_pass: BuyAll = Field(title='Challenge Pass', default=False, description='buy_all_remaining_help')
    red_daruma: int = Field(title='Red Daruma', default=0)
    broken_amulet: int = Field(title='Broken Amulet', default=0)


class Charisma(BaseModel):
    # 杂货铺 魅力购买
    enable: bool = Field(title='Enable', default=False)
    black_daruma_scrap: bool = Field(title='Black Daruma Scrap', default=False)
    mystery_amulet: bool = Field(title='Mystery Amulet', default=False)


class Shrine(BaseModel):
    # 神社 神龛
    enable: bool = Field(title='Enable', default=False)
    black_daruma: bool = Field(title='Black Daruma', default=False)
    white_daruma_five: bool = Field(title='White Daruma Five', default=False)
    white_daruma_four: bool = Field(title='White Daruma Four', default=False)


class Bondlings(BaseModel):
    # 契灵商店 契忆
    enable: bool = Field(title='Enable', default=False)
    random_soul: BuyAll = Field(title='Random Soul', default=False, description='buy_all_remaining_help')
    bondling_stone: BuyAll = Field(title='Bondling Stone', default=False, description='buy_all_remaining_help')
    high_bondling_discs: BuyAll = Field(title='High Bondling Discs', default=False, description='buy_all_remaining_help')
    medium_bondling_discs: BuyAll = Field(title='Medium Bondling Discs', default=False, description='buy_all_remaining_help')


class GuildStore(BaseModel):
    # 寮商店
    enable: bool = Field(title='Enable', default=False)
    honor_gift: bool = Field(default=False)
    mystery_amulet: bool = Field(title='Mystery Amulet', default=False)
    black_daruma_scrap: bool = Field(title='Black Daruma Scrap', default=False)
    skin_ticket: BuyAll = Field(title='Skin Ticket', default=False, description='buy_all_remaining_help')


class ItachiCoinShop(BaseModel):
    # 鼬乐币商店
    itachi_coin_buy_jade: bool = Field(
        default=False,
        description='itachi_coin_buy_jade_help',
    )


class WeeklyPurchase(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    itachi_coin_shop: ItachiCoinShop = Field(default_factory=ItachiCoinShop)
    special_room: SpecialRoom = Field(default_factory=SpecialRoom)
    honor_room: HonorRoom = Field(default_factory=HonorRoom)
    friendship_points: FriendshipPoints = Field(default_factory=FriendshipPoints)
    medal_room: MedalRoom = Field(default_factory=MedalRoom)
    charisma: Charisma = Field(default_factory=Charisma)

    thousand_things: ThousandThings = Field(default_factory=ThousandThings)
    consignment: Consignment = Field(default_factory=Consignment)
    scales: Scales = Field(default_factory=Scales)
    bondlings: Bondlings = Field(default_factory=Bondlings)
    shrine: Shrine = Field(default_factory=Shrine)
    guild_store: GuildStore = Field(default_factory=GuildStore)
