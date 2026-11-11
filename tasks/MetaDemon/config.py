from typing import ClassVar
from tasks.Component.config_settings_layout import SettingsLayoutConfig, settings_section
# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from tasks.Component.config_base import ConfigBase, MultiLine, TimeDelta
from tasks.Component.SwitchAccount.switch_account_config import AccountInfo
from pydantic import Field, field_validator, model_validator
from module.config.multi_select import normalize_multi_select
from module.cooperation import instance_name
from enum import IntEnum, Enum
from tasks.Component.config_scheduler import Scheduler


class BossType(IntEnum):
    ONE_STAR = 1
    TWO_STARS = 2
    THREE_STARS = 3
    FOUR_STARS = 4
    FIVE_STARS = 5
    SIX_STARS = 6
    MONEY = 7


class MetaDemonMode(str, Enum):
    BOSS_BATTLE = '鬼王战斗'
    BOSS_ASSIST = '鬼王协助'


class MetaDemonConfig(ConfigBase):
    mode: list[MetaDemonMode] = Field(default=[MetaDemonMode.BOSS_BATTLE], max_length=1, title='运行模式',
        json_schema_extra={'ui_exclusive_groups': [['鬼王战斗', '鬼王协助']]})

    @field_validator('mode', mode='before')
    @classmethod
    def parse_modes(cls, value):
        selected = list(dict.fromkeys(MetaDemonMode(item) for item in normalize_multi_select(value)))
        if len(selected) > 1:
            raise ValueError('鬼王战斗和鬼王协助至多选择一种')
        return selected

    auto_tea: bool = Field(default=False, description='疲劳度满时是否自动喝茶, 关闭则自动根据调度器等待间隔时间安排下一次调度')
    fire_sequence: str = Field(
        default='1 2 3 4',
        description='用空格分隔星级，从左到右挑战填写的星级。例如填 3 2，先打三星再打二星。主页显示下一只为六星时结束。',
    )
    high_star_powerful_enable: bool = Field(
        default=False, title='启用高星强力追击', description='仅对五星、六星鬼王生效。',
    )
    powerful_count: int = Field(
        default=1, ge=1, title='强力追击次数', description='每只高星鬼王的前几次挑战使用强力追击，之后改用普通追击。',
    )
    synthesis_list: str = Field(default='1', description='鬼王合成列表(空格分隔),支持1-5星合成,例:1 2 3(合成一星,二星,三星鬼王)')

    @model_validator(mode='before')
    @classmethod
    def migrate_powerful_list(cls, data):
        if isinstance(data, dict) and 'powerful_list' in data and 'high_star_powerful_enable' not in data:
            stars = str(data['powerful_list']).split()
            return {**data, 'high_star_powerful_enable': '5' in stars or '6' in stars}
        return data

    @property
    def fire_sequence_v(self) -> list[BossType]:
        stars = [int(value) for value in self.fire_sequence.replace('，', ' ').replace(',', ' ').split()]
        if any(star not in range(1, 7) for star in stars):
            raise ValueError('鬼王挑战顺序只能填写 1 到 6 星')
        return list(dict.fromkeys(BossType(star) for star in stars))

    @property
    def synthesis_list_v(self) -> list[BossType]:
        synthesis_list_text = self.synthesis_list.strip()
        if synthesis_list_text == '':
            return []
        synthesis_num_list = synthesis_list_text.split()
        synthesis_boss_type_list = [BossType(int(num_text)) for num_text in synthesis_num_list]
        return synthesis_boss_type_list


class MetaDemonQuickPresetConfig(ConfigBase):
    enable: bool = Field(default=False, title='启用快速预设',
        description='挑战前按首领名称选择预设。连续使用同一预设时复用当前阵容。')
    preset_rules: str = Field(default='预设组1:ALL', title='首领预设规则',
        description='示例：预设组1:月读,雪御前;预设组2:ALL。首领名以半角逗号分隔，规则以半角分号分隔；ALL 表示其他未指定的怪物。')
    preset_groups: str = Field(default='预设组1,默认分组,队伍1', title='预设组列表',
        description='格式：预设组名,御魂分组名,队伍名；例如：预设组1,队伍租借,第4日单体通用阵容。不同预设组以半角分号分隔。')
    skip_equip_soul: bool = Field(default=False, title='不装配御魂',
        description='启用快速预设时，选中预设后直接点击出战。')

    def named_presets(self) -> dict[str, tuple[str, str]]:
        groups = {}
        for row in self.preset_groups.split(';'):
            if not row.strip():
                continue
            parts = [part.strip() for part in row.split(',')]
            if len(parts) != 3 or not all(parts):
                raise ValueError(f'预设组需填写：预设组名,御魂分组名,队伍名：{row}')
            name, group, team = parts
            if name in groups:
                raise ValueError(f'预设组名重复：{name}')
            groups[name] = (group, team)
        presets = {}
        for row in self.preset_rules.split(';'):
            if not row.strip():
                continue
            name, separator, targets = row.partition(':')
            name = name.strip()
            if not separator or name not in groups:
                raise ValueError(f'规则引用了不存在的预设组或缺少半角冒号：{row}')
            for boss in targets.split(','):
                boss = boss.strip()
                if not boss:
                    raise ValueError(f'首领名不能为空：{row}')
                boss = 'ALL' if boss.upper() == 'ALL' else boss
                if boss in presets:
                    raise ValueError(f'首领规则重复：{boss}')
                presets[boss] = groups[name]
        if not presets:
            raise ValueError('请填写至少一条上阵预设规则')
        return presets

    @model_validator(mode='before')
    @classmethod
    def migrate_legacy_presets(cls, value):
        if not isinstance(value, dict):
            return value
        value = dict(value)
        if 'high_star_custom_preset' in value:
            value.setdefault('preset_rules', value['high_star_custom_preset'])
        rule = value.get('preset_rules', '')
        if '(' not in rule:
            return value
        import ast
        import re
        groups, rules, targets = [], [], {}
        for row in re.split(r'[;；]+', rule):
            if not row.strip():
                continue
            parts = re.split(r'[:：]', row, maxsplit=1)
            if len(parts) != 2:
                return value
            try:
                target = ast.literal_eval(parts[1].strip())
            except (ValueError, SyntaxError):
                return value
            if not isinstance(target, (tuple, list)) or len(target) != 2:
                return value
            if tuple(target) == (1, 1):
                target = ('默认分组', '队伍1')
            if not all(isinstance(part, str) and part.strip() for part in target):
                return value
            target = tuple(part.strip() for part in target)
            if target not in targets:
                name = f'预设组{len(targets) + 1}'
                targets[target] = name
                groups.append(','.join((name, *target)))
            rules.append(f'{targets[target]}:{parts[0].strip()}')
        return {**value, 'preset_groups': ';'.join(groups), 'preset_rules': ';'.join(rules)}


class AssistanceRole(str, Enum):
    ASSIST = '协助'
    OFFERING = '上供'


class MetaDemonAssistanceConfig(ConfigBase):
    cooperation_script: str = Field(default='', title='鬼王协助协同脚本',
        description='关联另一端的本地脚本。协助者接收上供端的鬼王截图，并在好友列表中匹配后挑战。')
    batch_cooperation: bool = Field(default=False, title='整批鬼王协同', description='batch_cooperation_help')
    batch_accounts: MultiLine = Field(default='', title='整批上供账号', description='batch_accounts_help')
    role: AssistanceRole = Field(default=AssistanceRole.OFFERING, title='鬼王协助身份',
        description='上供召唤六星鬼王并分享；协助从超鬼王主页寻找好友分享的鬼王并挑战。')
    friend_names: str = Field(default='', title='分享好友名字',
        description='填写游戏内好友完整名字；多个名字用分号或换行分隔，按名称精确匹配，不使用近似名字。')
    poll_interval: int = Field(default=5, ge=2, le=60, title='协助轮询间隔（秒）',
        description='上供按此间隔检查是否已击杀，协助按此间隔重新寻找好友分享。')

    @field_validator('cooperation_script')
    @classmethod
    def validate_cooperation_script(cls, value: str) -> str:
        return instance_name(value)

    @staticmethod
    def parse_accounts(value: str) -> list[AccountInfo]:
        accounts = []
        for index, line in enumerate(value.splitlines(), 1):
            if not line.strip():
                continue
            fields = [field.strip() for field in line.split('|')]
            if not 2 <= len(fields) <= 5 or not all(fields[:2]):
                raise ValueError(f'整批上供账号第 {index} 行需要填写账号和服务器')
            account, server, character, platform, aliases = fields + [''] * (5 - len(fields))
            if platform not in ('', '安卓', '苹果'):
                raise ValueError(f'整批上供账号第 {index} 行的平台应为安卓或苹果')
            accounts.append(AccountInfo(account=account, svr=server, character=character,
                                        apple_or_android=platform != '苹果', account_alias=aliases))
        return accounts

    @field_validator('batch_accounts')
    @classmethod
    def validate_batch_accounts(cls, value: str) -> str:
        cls.parse_accounts(value)
        return value

    @property
    def friends(self) -> list[str]:
        import re
        return list(dict.fromkeys(name.strip() for name in re.split(r'[;；\n\r]+', self.friend_names) if name.strip()))


class MetaDemonScheduler(Scheduler):
    wait_interval: TimeDelta = Field(default=TimeDelta(hours=1, minutes=40), description='疲劳度满时等多长时间后再次运行本任务,建议设置等待完全恢复疲劳度所需的时间\n例:100分钟恢复100点疲劳度,再次运行必定可以继续战斗')

class MetaDemon(ConfigBase):
    settings_layout_config: SettingsLayoutConfig = Field(default_factory=SettingsLayoutConfig)
    settings_layout: ClassVar[list[dict]] = [
        settings_section('scheduler', '任务调度', groups=[{'name': 'scheduler'}]),
        settings_section('general_config', '通用设置', groups=[
            {'name': 'meta_demon_config', 'fields': ['mode']},
            {'name': 'assistance_config', 'fields': ['friend_names']},
            {'name': 'meta_demon_config', 'fields': [key for key in MetaDemonConfig.model_fields if key != 'mode']},
            {'name': 'assistance_config', 'fields': ['role']},
        ]),
        settings_section('quick_preset_config', '快速预设', groups=[{'name': 'quick_preset_config'}]),
        settings_section('assistance_config', '鬼王协助', groups=[
            {'name': 'assistance_config', 'fields': [key for key in MetaDemonAssistanceConfig.model_fields if key not in ('friend_names', 'role')]},
        ]),
    ]

    scheduler: MetaDemonScheduler = Field(default_factory=MetaDemonScheduler)
    meta_demon_config: MetaDemonConfig = Field(default_factory=MetaDemonConfig)
    quick_preset_config: MetaDemonQuickPresetConfig = Field(default_factory=MetaDemonQuickPresetConfig)
    assistance_config: MetaDemonAssistanceConfig = Field(default_factory=MetaDemonAssistanceConfig)

    @model_validator(mode='before')
    @classmethod
    def migrate_quick_loadout(cls, data):
        if not isinstance(data, dict):
            return data
        quick = data.get('quick_preset_config', {})
        general = data.get('general_config', {})
        if (not isinstance(quick, dict) or 'enable' in quick
                or not isinstance(general, dict) or not general.get('high_star_quick_loadout_enable')):
            return data
        if quick.get('high_star_custom_preset_enable'):
            return {**data, 'quick_preset_config': {**quick, 'enable': True}}
        soul = data.get('switch_soul_config', {})
        names = soul.get('high_star_group_team_name', '') if isinstance(soul, dict) else ''
        old_preset = data.get('preset_config', {})
        if not names and isinstance(old_preset, dict):
            names = f"{old_preset.get('high_star_group_name', '')},{old_preset.get('high_star_preset_name', '')}"
        parts = [part.strip() for part in str(names).split(',')]
        if len(parts) == 2 and all(parts):
            quick = {**quick, 'enable': True, 'preset_rules': '预设组1:ALL',
                     'preset_groups': ','.join(('预设组1', *parts))}
        return {**data, 'quick_preset_config': quick}
