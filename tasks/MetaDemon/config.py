# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import ast
import re
from enum import Enum, IntEnum
from typing import Annotated, ClassVar

from pydantic import Field, field_validator, model_validator

from module.config.multi_select import normalize_multi_select
from tasks.Component.config_base import ConfigBase, TimeDelta, dynamic_hide
from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_settings_layout import SettingsLayoutConfig, settings_section


class BossType(IntEnum):
    ONE_STAR = 1
    TWO_STARS = 2
    THREE_STARS = 3
    FOUR_STARS = 4
    FIVE_STARS = 5
    SIX_STARS = 6
    MONEY = 7


SPECIAL_BOSS_PRESETS = {
    '月读': 'tsukuyomi_preset',
    '酒吞童子': 'shuten_doji_preset',
    '鬼王酒吞童子': 'oni_king_shuten_doji_preset',
    '雪御前': 'yuki_gozen_preset',
    '修罗鬼童丸': 'shura_kidomaru_preset',
    '鬼童丸': 'kidomaru_preset',
}
PRESET_GROUPS = {
    'low_star_preset': '1–4 星通用',
    'high_star_preset': '5–6 星通用',
    **{key: name for name, key in SPECIAL_BOSS_PRESETS.items()},
}


class MetaDemonRentalLineup(str, Enum):
    NONE = 'meta_demon_rental_none'
    GROUP = 'meta_demon_rental_group'
    SINGLE = 'meta_demon_rental_single'
    NORMAL_ATTACK = 'meta_demon_rental_normal_attack'


PERSONAL_PRESET_FIELD = {'ui_visible_when': {'rental_lineup': MetaDemonRentalLineup.NONE.value}}
PowerfulChaseCount = Annotated[int, Field(
    ge=0, title='强力追击次数',
    description='每只鬼王的前几次挑战使用强力追击。填 0 时使用普通追击。',
)]


class MetaDemonConfig(ConfigBase):
    auto_tea: bool = Field(default=False, description='疲劳度满时自动喝茶。关闭时按调度器的等待间隔恢复疲劳。')
    synthesis_list: str = Field(
        default='1', description='填写要合成的鬼王门票星级，支持 1 至 5 星，用空格分隔。',
    )

    @property
    def synthesis_list_v(self) -> list[BossType]:
        return [BossType(int(value)) for value in self.synthesis_list.split()]


class MetaDemonBattlePreset(ConfigBase):
    powerful_count: PowerfulChaseCount = 0
    rental_lineup: MetaDemonRentalLineup = Field(
        default=MetaDemonRentalLineup.NONE, title='使用租借阵容',
        description='选择群体、单体或普攻后，在挑战前直接上阵对应的租借队伍。',
    )
    switch_soul: bool = Field(
        default=False, title='切换御魂',
        description='启用后在挑战前上阵个人预设并装配御魂。连续使用同一预设时复用已装配的御魂。',
        json_schema_extra=PERSONAL_PRESET_FIELD,
    )
    preset_numbers: str = Field(
        default='', title='预设编号',
        description='例如 1,1 表示第一个个人分组的第一队。队伍租借跳过计数。留空可按名称选择。',
        json_schema_extra=PERSONAL_PRESET_FIELD,
    )
    group_name: str = Field(
        default='', title='预设分组名', description='填写游戏中快速预设的分组名称。',
        json_schema_extra=PERSONAL_PRESET_FIELD,
    )
    preset_name: str = Field(
        default='', title='预设队伍名',
        description='上阵和装配共用这支队伍。关闭切换御魂且编号和名称都留空时沿用当前阵容。',
        json_schema_extra=PERSONAL_PRESET_FIELD,
    )

    @field_validator('group_name', 'preset_name')
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip()

    @field_validator('preset_numbers')
    @classmethod
    def normalize_preset_numbers(cls, value: str) -> str:
        if not value.strip():
            return ''
        match = re.fullmatch(r'\s*([1-7])\s*[,，]\s*([1-9][0-9]*)\s*', value)
        if not match:
            raise ValueError('请按 1,1 的格式填写预设编号，分组为 1 至 7，队伍编号为正整数')
        return ','.join(match.groups())


class MetaDemonHighStarPreset(MetaDemonBattlePreset):
    powerful_count: PowerfulChaseCount = 1


class MetaDemonScheduler(Scheduler):
    wait_interval: TimeDelta = Field(
        default=TimeDelta(hours=1, minutes=40), description='疲劳度满时等待多久再运行超鬼王。',
    )
    waiting_for_fatigue: bool = False
    hide_fields = dynamic_hide('waiting_for_fatigue')


def legacy_battle_disabled(data: dict) -> bool:
    """The old assistance and empty modes did not run the normal battle."""
    settings = data.get('meta_demon_config')
    return (isinstance(settings, dict) and 'mode' in settings
            and '鬼王战斗' not in normalize_multi_select(settings['mode']))


def legacy_preset_targets(data: dict, quick: dict) -> dict[str, tuple[str, str]]:
    """Read the previous named rules and the older tuple-based rules."""
    if 'enable' not in quick:
        if not (data.get('general_config') or {}).get('high_star_quick_loadout_enable'):
            return {}
        if not quick.get('high_star_custom_preset_enable'):
            names = (data.get('switch_soul_config') or {}).get('high_star_group_team_name', '')
            old_preset = data.get('preset_config') or {}
            if not names:
                names = f"{old_preset.get('high_star_group_name', '')},{old_preset.get('high_star_preset_name', '')}"
            pair = tuple(part.strip() for part in names.split(','))
            return {'ALL': pair} if len(pair) == 2 and all(pair) else {}
    elif not quick['enable']:
        return {}

    groups = {}
    for row in quick.get('preset_groups', '预设组1,默认分组,队伍1').split(';'):
        parts = [part.strip() for part in row.split(',')]
        if len(parts) == 3 and all(parts):
            group, category, team = parts
            groups[group] = (category, team)

    targets = {}
    rules = quick.get('preset_rules', quick.get('high_star_custom_preset', '预设组1:ALL'))
    for row in rules.replace('；', ';').replace('：', ':').split(';'):
        left, sep, right = (part.strip() for part in row.partition(':'))
        if not sep or not left or not right:
            continue
        target = groups.get(left)
        names = right
        if target is None:
            names = left
            try:
                pair = ast.literal_eval(right)
            except (ValueError, SyntaxError):
                continue
            if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                continue
            if tuple(pair) == (1, 1):
                pair = ('默认分组', '队伍1')
            if not all(isinstance(part, str) and part.strip() for part in pair):
                continue
            target = tuple(part.strip() for part in pair)
        for name in names.split(','):
            name = name.strip()
            if name:
                targets['ALL' if name.upper() == 'ALL' else name] = target
    return targets


class MetaDemon(ConfigBase):
    settings_layout_config: SettingsLayoutConfig = Field(default_factory=SettingsLayoutConfig)
    settings_layout: ClassVar[list[dict]] = [
        settings_section('scheduler', '任务调度', groups=[{'name': 'scheduler'}]),
        settings_section('general_config', '通用设置', groups=[{'name': 'meta_demon_config'}]),
        settings_section('quick_presets', '快速预设', select_variant=True, variants=[
            {'id': key, 'label': label, 'groups': [{'name': key}]}
            for key, label in PRESET_GROUPS.items()
        ]),
    ]

    scheduler: MetaDemonScheduler = Field(default_factory=MetaDemonScheduler)
    meta_demon_config: MetaDemonConfig = Field(default_factory=MetaDemonConfig)
    low_star_preset: MetaDemonBattlePreset = Field(default_factory=MetaDemonBattlePreset)
    high_star_preset: MetaDemonHighStarPreset = Field(default_factory=MetaDemonHighStarPreset)
    tsukuyomi_preset: MetaDemonHighStarPreset = Field(default_factory=MetaDemonHighStarPreset)
    shuten_doji_preset: MetaDemonHighStarPreset = Field(default_factory=MetaDemonHighStarPreset)
    oni_king_shuten_doji_preset: MetaDemonHighStarPreset = Field(default_factory=MetaDemonHighStarPreset)
    yuki_gozen_preset: MetaDemonHighStarPreset = Field(default_factory=MetaDemonHighStarPreset)
    shura_kidomaru_preset: MetaDemonHighStarPreset = Field(default_factory=MetaDemonHighStarPreset)
    kidomaru_preset: MetaDemonHighStarPreset = Field(default_factory=MetaDemonHighStarPreset)

    def preset_for(self, star: BossType, boss_name: str = '') -> MetaDemonBattlePreset:
        if star <= BossType.FOUR_STARS:
            return self.low_star_preset
        return getattr(self, SPECIAL_BOSS_PRESETS.get(boss_name, 'high_star_preset'))

    @model_validator(mode='before')
    @classmethod
    def migrate_legacy_settings(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if legacy_battle_disabled(data):
            data['scheduler'] = {**(data.get('scheduler') or {}), 'enable': False}

        settings = data.get('meta_demon_config') or {}
        count = None
        if 'high_star_powerful_enable' in settings or 'powerful_list' in settings:
            powerful = settings.get('high_star_powerful_enable')
            if powerful is None:
                powerful = bool({'5', '6'} & set(str(settings.get('powerful_list', '')).split()))
            count = settings.get('powerful_count', 1) if powerful else 0
        quick = data.get('quick_preset_config')
        if not isinstance(quick, dict):
            quick = {}
        targets = legacy_preset_targets(data, quick)
        for key, label in PRESET_GROUPS.items():
            if key in data:
                continue
            low = key == 'low_star_preset'
            target = targets.get(label, targets.get('ALL')) if not low or 'enable' in quick else None
            if target or (count is not None and not low):
                preset = {}
                if count is not None and not low:
                    preset['powerful_count'] = count
                if target:
                    preset.update(group_name=target[0], preset_name=target[1],
                                  switch_soul=not quick.get('skip_equip_soul', False))
                data[key] = preset
        return data
