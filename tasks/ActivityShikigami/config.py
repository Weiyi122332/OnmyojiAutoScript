# This Python file uses the following encoding: utf-8
"""式神活动统一配置。"""

from datetime import time, timedelta
from enum import Enum
import re

from pydantic import BaseModel, Field, field_serializer, model_validator, validator

from module.logger import logger
from module.config.multi_select import normalize_multi_select
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.config_base import ConfigBase, Time
from tasks.Component.config_scheduler import Scheduler


class ActivityTask(str, Enum):
    AP = '体力'
    AP100 = '百体'
    BOSS = '首领'
    FAKE_GOD = '伪神/爬塔'


DEFAULT_ACTIVITY_SEQUENCE = ('体力', '百体', '首领', '伪神/爬塔')
ACTIVITY_NAME_TO_FIELD = {
    '体力': 'ap',
    '百体': 'ap100',
    '首领': 'boss',
    '伪神/爬塔': 'fakegod',
}
ACTIVITY_NAME_ALIASES = {
    'ap': '体力',
    '体力': '体力',
    '古迹演武': '体力',
    'ap100': '百体',
    '百体': '百体',
    '100体': '百体',
    '刹那试炼': '百体',
    'boss': '首领',
    '首领': '首领',
    'fakegod': '伪神/爬塔',
    'fake_god': '伪神/爬塔',
    '伪神': '伪神/爬塔',
    '伪神降临': '伪神/爬塔',
    '磐长故地': '伪神/爬塔',
    '伪神/爬塔': '伪神/爬塔',
    '伟神/爬塔': '伪神/爬塔',
}
LEGACY_CLIMB_NAMES = {'climb', 'normal', '爬塔'}
# 旧配置中的已移除选项直接忽略，避免整个配置加载失败。
REMOVED_ACTIVITY_NAMES = {
    '探索', 'exploration', 'exp', '大富翁', 'richman', 'rich_man',
    '门票', 'pass',
}
CLIMB_TYPES = ('ap', 'boss', 'ap100')
BATTLE_TYPES = (*CLIMB_TYPES, 'fakegod')


def normalize_activity_sequence(value) -> list[str]:
    """保留列表顺序，兼容旧爬塔总开关及历史文本配置。"""
    values = list(DEFAULT_ACTIVITY_SEQUENCE) if value is None else normalize_multi_select(value)
    selected = []
    for item in values:
        raw_name = item.value if isinstance(item, ActivityTask) else str(item).strip()
        alias = raw_name.lower()
        if not alias or alias in REMOVED_ACTIVITY_NAMES:
            continue
        if alias in LEGACY_CLIMB_NAMES:
            # 旧“爬塔”展开为体力、首领和百体，保持原分支顺序。
            names = ('体力', '首领', '百体')
        else:
            name = ACTIVITY_NAME_ALIASES.get(alias)
            if name is None:
                raise ValueError(
                    f'活动执行顺序仅支持 {", ".join(DEFAULT_ACTIVITY_SEQUENCE)}，当前为 {raw_name}'
                )
            names = (name,)
        for name in names:
            if name not in selected:
                selected.append(name)
    return selected


class GeneralConfig(ConfigBase):
    task_sequence: list[ActivityTask] = Field(
        default=[
            ActivityTask.AP,
            ActivityTask.AP100,
            ActivityTask.BOSS,
            ActivityTask.FAKE_GOD,
        ],
        max_length=4,
        title='Activity Task Sequence',
        description='activity_task_sequence_help',
        json_schema_extra={'x-ui-type': 'task_list'},
    )
    ap_limit: int = Field(default=0, title='Ap Limit', ge=0, description='activity_ap_limit_help')
    boss_limit: int = Field(default=0, title='Boss Limit', ge=0)
    ap100_limit: int = Field(default=0, title='Ap100 Limit', ge=0, description='activity_ap100_limit_help')
    fakegod_limit: int = Field(default=0, title='Fakegod Limit', ge=0, description='activity_fakegod_limit_help')
    limit_time: Time = Field(
        default=Time(hour=1, minute=30),
        title='Activity Limit Time',
        description='activity_limit_time_help',
    )
    active_souls_clean: bool = Field(
        default=False,
        title='Active Souls Clean',
        description='active_souls_clean_help',
    )
    random_sleep: bool = Field(
        default=False,
        title='Activity Random Sleep',
        description='activity_random_sleep_help',
    )
    use_penta_pass: bool = Field(
        default=False,
        title='Use Penta Pass',
        description='use_penta_pass_help',
    )
    climb_drink_break: bool = Field(
        default=False,
        title='Climb Drink Break',
        description='climb_drink_break_help',
    )
    climb_drink_interval: str = Field(
        default='60,120',
        title='Climb Drink Interval',
        description='climb_drink_interval_help',
    )

    @property
    def limit_time_v(self) -> timedelta:
        if isinstance(self.limit_time, time):
            return timedelta(
                hours=self.limit_time.hour,
                minutes=self.limit_time.minute,
                seconds=self.limit_time.second,
            )
        return self.limit_time

    @property
    def task_sequence_v(self) -> list[str]:
        """按列表从上到下执行，删除或次数为零的活动不参与运行。"""
        return [
            name for name in normalize_activity_sequence(self.task_sequence)
            if self.activity_enabled(name)
        ]

    @property
    def climb_sequence_v(self) -> list[str]:
        """体力、首领和百体按原分支顺序执行，并跳过次数为零的项。"""
        return [name for name in CLIMB_TYPES if self.limit_for(name) > 0]

    def activity_enabled(self, activity_name: str) -> bool:
        field = ACTIVITY_NAME_TO_FIELD[activity_name]
        return self.limit_for(field) > 0

    def limit_for(self, action_type: str) -> int:
        return getattr(self, f'{action_type}_limit', 0)

    @validator('task_sequence', pre=True, always=True)
    def parse_task_sequence(cls, value):
        return normalize_activity_sequence(value)

    @field_serializer('task_sequence')
    def serialize_task_sequence(self, value) -> list[str]:
        return normalize_activity_sequence(value)

    @validator('limit_time', pre=True, always=True)
    def parse_limit_time(cls, value):
        if isinstance(value, str):
            if value.isdigit():
                delta = timedelta(seconds=int(value))
                return time(
                    hour=delta.seconds // 3600,
                    minute=delta.seconds // 60 % 60,
                    second=delta.seconds % 60,
                )
            try:
                return time.fromisoformat(value)
            except ValueError:
                logger.warning('Invalid activity limit_time value. Expected format: HH:MM:SS')
                return time(hour=1, minute=30)
        return value

    @validator('climb_drink_interval', pre=True, always=True)
    def parse_climb_drink_interval(cls, value):
        matched = re.fullmatch(r'\s*(\d+)\s*[,，]\s*(\d+)\s*', str(value))
        if matched is None:
            raise ValueError('爬塔喝水间隔必须填写“最小分钟,最大分钟”')
        lower, upper = (int(item) for item in matched.groups())
        if lower <= 0 or upper <= 0 or lower > upper:
            raise ValueError('爬塔喝水间隔必须为有效的正整数范围')
        return f'{lower},{upper}'


def check_soul_by_number(enable_switch: bool, group_team: str, label: str):
    if not enable_switch:
        return
    parts = group_team.split(',') if group_team else []
    if len(parts) != 2 or not all(part.strip().isdigit() for part in parts):
        raise ValueError(f'[{label}]御魂预设必须为数字组号和队伍号，格式为 组号,队伍号')


def check_soul_by_ocr(enable_switch: bool, group_team_name: str, label: str):
    if not enable_switch:
        return
    parts = group_team_name.split(',') if group_team_name else []
    if len(parts) != 2 or not all(part.strip() for part in parts):
        raise ValueError(f'[{label}]御魂预设名称必须为 组名,队伍名')


class SwitchSoulConfig(BaseModel):
    enable_switch_ap: bool = Field(default=False)
    ap_group_team: str = Field(default='-1,-1', description='switch_group_team_help')
    enable_switch_ap_by_name: bool = Field(default=False, description='enable_switch_by_name_help')
    ap_group_team_name: str = Field(default='')

    enable_switch_boss: bool = Field(default=False)
    boss_group_team: str = Field(default='-1,-1', description='switch_group_team_help')
    enable_switch_boss_by_name: bool = Field(default=False, description='enable_switch_by_name_help')
    boss_group_team_name: str = Field(default='')

    enable_switch_ap100: bool = Field(default=False)
    ap100_group_team: str = Field(default='-1,-1', description='switch_group_team_help')
    enable_switch_ap100_by_name: bool = Field(default=False, description='enable_switch_by_name_help')
    ap100_group_team_name: str = Field(default='')

    enable_switch_fakegod: bool = Field(default=False)
    fakegod_group_team: str = Field(default='-1,-1', description='switch_group_team_help')
    enable_switch_fakegod_by_name: bool = Field(default=False, description='enable_switch_by_name_help')
    fakegod_group_team_name: str = Field(default='')

    def validate_switch_soul(self):
        for label in BATTLE_TYPES:
            check_soul_by_number(
                getattr(self, f'enable_switch_{label}'),
                getattr(self, f'{label}_group_team'),
                label.upper(),
            )
            check_soul_by_ocr(
                getattr(self, f'enable_switch_{label}_by_name'),
                getattr(self, f'{label}_group_team_name'),
                label.upper(),
            )
        return self


class ActivityShikigami(ConfigBase):
    # OASX 按字段顺序排版：任务调度、通用设置、切换御魂、四种战斗配置。
    scheduler: Scheduler = Field(default_factory=Scheduler)
    general_config: GeneralConfig = Field(default_factory=GeneralConfig)
    switch_soul_config: SwitchSoulConfig = Field(default_factory=SwitchSoulConfig)

    ap_battle_conf: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
    boss_battle_conf: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
    ap100_battle_conf: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
    fakegod_battle_conf: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)

    @model_validator(mode='before')
    @classmethod
    def migrate_legacy_configs(cls, data):
        """保留旧爬塔和伪神配置，移除已废弃玩法的配置。"""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        for removed_field in ('exp_encounter_soul_config', 'exp_encounter_battle_conf',
                              'rich_man_battle_conf', '_legacy_rich_man',
                              'pass_battle_conf'):
            data.pop(removed_field, None)
        old_climb = data.pop('general_climb', None)
        old_fakegod = data.pop('_legacy_fakegod', None)

        general = dict(data.get('general_config') or {})
        if isinstance(old_climb, dict):
            for key in (
                'limit_time', 'ap_limit', 'boss_limit', 'ap100_limit', 'active_souls_clean',
                'random_sleep', 'use_penta_pass', 'climb_drink_break', 'climb_drink_interval',
            ):
                if key in old_climb:
                    general.setdefault(key, old_climb[key])

        if isinstance(old_fakegod, dict):
            run = old_fakegod.get('general_climb', {})
            if isinstance(run, dict):
                general.setdefault('fakegod_limit', run.get('pass_limit', 0))
                general.setdefault('limit_time', run.get('limit_time', '01:30:00'))

        if 'task_sequence' not in general:
            enabled_sequence = []
            if isinstance(old_climb, dict):
                enabled_sequence.append('爬塔')
            if isinstance(old_fakegod, dict) and old_fakegod.get('scheduler', {}).get('enable'):
                enabled_sequence.append('伪神降临')
            if enabled_sequence:
                general['task_sequence'] = ','.join(enabled_sequence)
        data['general_config'] = general

        soul = dict(data.get('switch_soul_config') or {})
        if isinstance(old_fakegod, dict):
            old_soul = old_fakegod.get('switch_soul_config', {})
            if isinstance(old_soul, dict):
                soul.setdefault('enable_switch_fakegod', old_soul.get('enable_switch_pass', False))
                soul.setdefault(
                    'enable_switch_fakegod_by_name', old_soul.get('enable_switch_pass_by_name', False),
                )
                soul.setdefault('fakegod_group_team', old_soul.get('pass_group_team', '-1,-1'))
                soul.setdefault('fakegod_group_team_name', old_soul.get('pass_group_team_name', ''))
        data['switch_soul_config'] = soul

        if isinstance(old_fakegod, dict):
            data.setdefault('fakegod_battle_conf', old_fakegod.get('pass_battle_conf', {}))
        return data
