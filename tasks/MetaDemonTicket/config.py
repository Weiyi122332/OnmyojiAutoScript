from datetime import time, timedelta
from enum import Enum
from typing import ClassVar

from pydantic import Field, field_validator

from module.config.multi_select import normalize_multi_select
from module.cooperation import instance_name
from tasks.Component.config_base import ConfigBase, Time, dynamic_hide
from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_settings_layout import SettingsLayoutConfig, settings_section
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.GeneralInvite.config_invite import InviteConfig
from tasks.Component.SwitchSoul.switch_soul_config import SwitchSoulConfig
from tasks.EvoZone.config import KirinType, Layer
from tasks.Exploration.config import UserStatus


class TicketMode(str, Enum):
    AWAKE = '门票刷取：觉醒'
    EXPLORATION = '门票刷取：探索'


class MetaDemonTicketScheduler(Scheduler):
    waiting_for_realm_raid: bool = False
    hide_fields = dynamic_hide('waiting_for_realm_raid')


class TicketGeneralConfig(ConfigBase):
    mode: TicketMode = Field(default=TicketMode.AWAKE, title='刷票玩法',
                             description='探索沿用普通探索的副本、候补、加成、御魂、战斗设置及突破券阈值。个人突破已启用且突破券达标时，先清突破，再按探索设置的间隔继续刷票。')
    limit_time: Time = Field(default=Time(minute=45), description="limit_time_help")
    user_status: UserStatus = Field(default=UserStatus.ALONE, title='门票刷取身份')
    awake_buff_enable: bool = Field(default=False, title='觉醒启用加成')
    awake_kirin_type: KirinType = Field(default=KirinType.LIGHTNINGKIRIN, title='觉醒麒麟',
        description='门票刷取：觉醒使用的麒麟类型，仅影响超鬼王门票刷取。')
    awake_layer: Layer = Field(default=Layer.SEVEN, title='觉醒层数',
        description='门票刷取：觉醒使用的层数，可选一至十层；默认七层。')


    @property
    def limit_time_v(self) -> timedelta:
        if isinstance(self.limit_time, time):
            return timedelta(hours=self.limit_time.hour, minutes=self.limit_time.minute, seconds=self.limit_time.second)
        return self.limit_time


class TicketInviteConfig(InviteConfig):
    cooperation_script: str = Field(default='', title='刷票协同脚本', description='cooperation_script_help')

    @field_validator('cooperation_script')
    @classmethod
    def validate_cooperation_script(cls, value: str) -> str:
        return instance_name(value)


class MetaDemonTicket(ConfigBase):
    settings_layout_config: SettingsLayoutConfig = Field(default_factory=SettingsLayoutConfig)
    settings_layout: ClassVar[list[dict]] = [
        settings_section('scheduler', '任务调度', groups=[{'name': 'scheduler'}]),
        settings_section('general_config', '通用设置', groups=[{'name': 'general_config'}]),
        settings_section('invite_config', '通用邀请', groups=[{'name': 'invite_config'}]),
        settings_section('switch_soul_config', '切换御魂', groups=[{'name': 'switch_soul_config'}]),
        settings_section('general_battle_config', '战斗配置', groups=[{'name': 'general_battle_config'}]),
    ]

    scheduler: MetaDemonTicketScheduler = Field(default_factory=MetaDemonTicketScheduler)
    general_config: TicketGeneralConfig = Field(default_factory=TicketGeneralConfig)
    invite_config: TicketInviteConfig = Field(default_factory=TicketInviteConfig)
    switch_soul_config: SwitchSoulConfig = Field(default_factory=SwitchSoulConfig)
    general_battle_config: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)


def split_legacy_meta_demon(data: dict) -> dict:
    """将旧超鬼王刷票选项迁入独立任务，保留已有独立配置。"""
    old = data.get('meta_demon')
    if not isinstance(old, dict):
        return data
    boss = dict(old.get('meta_demon_config') or {})
    modes = normalize_multi_select(boss.get('mode', ['鬼王战斗']))
    aliases = {'门票刷取：觉醒七层': TicketMode.AWAKE.value, '门票刷取：探索绘卷': TicketMode.EXPLORATION.value}
    ticket_modes = [aliases.get(mode, mode) for mode in modes
                    if aliases.get(mode, mode) in (TicketMode.AWAKE.value, TicketMode.EXPLORATION.value)]
    old_preset = old.get('preset_config') or {}
    has_ticket_settings = (bool(ticket_modes) or 'ticket_farming_battle_conf' in old
                           or 'invite_config' in old or any(key.startswith('ticket_farming_') for key in old_preset))
    if not has_ticket_settings:
        return data

    data = dict(data)
    old = dict(old)
    general = dict(old.get('general_config') or {})
    ticket_general = {key: general.pop(key) for key in TicketGeneralConfig.model_fields if key in general}
    ticket_general['mode'] = ticket_modes[0] if ticket_modes else TicketMode.AWAKE.value
    if 'limit_time' in boss:
        ticket_general['limit_time'] = boss['limit_time']

    soul = dict(old.get('switch_soul_config') or {})
    by_name = soul.pop('ticket_farming_by_name', False)
    names = soul.pop('ticket_farming_group_team_name', '').split(',', 1)
    group_name, team_name = (part.strip() for part in names) if len(names) == 2 else ('', '')
    ticket_soul = {
        'enable': soul.pop('ticket_farming_enable', False) and not by_name,
        'switch_group_team': soul.pop('ticket_farming_group_team', '-1,-1'),
        'enable_switch_by_name': by_name,
        'group_name': group_name,
        'team_name': team_name,
    }

    battle = old.pop('ticket_farming_battle_conf', None)
    if battle is None:
        preset = old.get('preset_config') or {}
        battle = {
            'preset_enable': preset.get('ticket_farming_enable', False),
            'preset_group': preset.get('ticket_farming_group', 1),
            'preset_team': preset.get('ticket_farming_team', 1),
        }
    ticket_scheduler = dict(old.get('scheduler') or {})
    ticket_scheduler.pop('wait_interval', None)
    ticket_scheduler['enable'] = bool(ticket_modes and ticket_scheduler.get('enable'))
    data.setdefault('meta_demon_ticket', {
        'scheduler': ticket_scheduler,
        'general_config': ticket_general,
        'invite_config': old.pop('invite_config', {}),
        'switch_soul_config': ticket_soul,
        'general_battle_config': battle,
    })
    if ticket_modes:
        boss_modes = [mode for mode in modes if mode in ('鬼王战斗', '鬼王协助')]
        boss['mode'] = boss_modes or ['鬼王战斗']
        if not boss_modes:
            old['scheduler'] = {**(old.get('scheduler') or {}), 'enable': False}
    old['meta_demon_config'] = boss
    old['general_config'] = general
    old['switch_soul_config'] = soul
    data['meta_demon'] = old
    return data
