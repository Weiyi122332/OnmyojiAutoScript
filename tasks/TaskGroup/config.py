# This Python file uses the following encoding: utf-8
"""任务组：把多个已有任务按自定义顺序串成一组，用任务组自己的定时启动。"""

import json
import re
from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from module.config.multi_select import normalize_multi_select
from module.logger import logger
from tasks.Component.config_base import ConfigBase
from tasks.Component.config_scheduler import Scheduler

# 任务组自身所在目录，不能作为组内任务
GROUP_MODULE_DIR = 'TaskGroup'
# 每个任务组最多放多少个任务、项目里一共有几个任务组
TASKS_PER_GROUP = 10
GROUP_COUNT = 5
# 下拉框里「不设置」的取值
NONE_CHOICE = '不设置'

_missing_warned = False


class GroupTaskChoice(str, Enum):
    """
    任务组下拉框里可以选的任务。

    新增任务后，把任务名也加到这里（默认值就是任务名本身），下拉框里才会出现；
    运行时如果发现漏了会打日志提醒。
    """
    NONE = NONE_CHOICE
    # Script
    Restart = 'Restart'
    # Soul Zones
    Orochi = 'Orochi'
    Sougenbi = 'Sougenbi'
    FallenSun = 'FallenSun'
    EternitySea = 'EternitySea'
    SixRealms = 'SixRealms'
    OtherWorldTwilight = 'OtherWorldTwilight'
    # Daily Task
    DailyTrifles = 'DailyTrifles'
    AreaBoss = 'AreaBoss'
    GoldYoukai = 'GoldYoukai'
    ExperienceYoukai = 'ExperienceYoukai'
    Nian = 'Nian'
    TalismanPass = 'TalismanPass'
    DemonEncounter = 'DemonEncounter'
    Pets = 'Pets'
    SoulsTidy = 'SoulsTidy'
    Delegation = 'Delegation'
    WantedQuests = 'WantedQuests'
    Tako = 'Tako'
    AutoCheckinBigGod = 'AutoCheckinBigGod'
    # Liver Emperor Exclusive
    BondlingFairyland = 'BondlingFairyland'
    EvoZone = 'EvoZone'
    GoryouRealm = 'GoryouRealm'
    Exploration = 'Exploration'
    Hyakkiyakou = 'Hyakkiyakou'
    HeroTest = 'HeroTest'
    FindJade = 'FindJade'
    MemoryScrolls = 'MemoryScrolls'
    # Guild
    KekkaiUtilize = 'KekkaiUtilize'
    KekkaiActivation = 'KekkaiActivation'
    RealmRaid = 'RealmRaid'
    RyouToppa = 'RyouToppa'
    Dokan = 'Dokan'
    CollectiveMissions = 'CollectiveMissions'
    Hunt = 'Hunt'
    AbyssShadows = 'AbyssShadows'
    GuildBanquet = 'GuildBanquet'
    DemonRetreat = 'DemonRetreat'
    GuildActivityMonitor = 'GuildActivityMonitor'
    # Weekly Task
    TrueOrochi = 'TrueOrochi'
    WeeklyPurchase = 'WeeklyPurchase'
    Secret = 'Secret'
    WeeklyTrifles = 'WeeklyTrifles'
    MysteryShop = 'MysteryShop'
    Duel = 'Duel'
    Chess = 'Chess'
    # Activity Task
    ActivityShikigami = 'ActivityShikigami'
    MartialArts = 'MartialArts'
    MetaDemon = 'MetaDemon'
    FrogBoss = 'FrogBoss'
    FloatParade = 'FloatParade'
    Quiz = 'Quiz'
    KittyShop = 'KittyShop'
    DyeTrials = 'DyeTrials'
    GuguArtStudio = 'GuguArtStudio'


@lru_cache(maxsize=1)
def available_task_names() -> tuple:
    """
    项目里能作为组内任务的任务名，顺序跟 GUI 菜单一致。

    判定标准：tasks/<任务>/ 下同时有 config.py 和 script_task.py，
    并且 config.py 里定义了 scheduler（也就是能独立调度的任务）。
    """
    scan = set()
    root = Path.cwd() / 'tasks'
    try:
        folders = [path for path in root.iterdir() if path.is_dir()]
    except OSError:
        return tuple()
    for folder in folders:
        config_file, script_file = folder / 'config.py', folder / 'script_task.py'
        if not (config_file.exists() and script_file.exists()):
            continue
        if folder.name == GROUP_MODULE_DIR:
            continue
        try:
            text = config_file.read_text(encoding='utf-8')
        except OSError:
            continue
        if re.search(r'^\s+scheduler\s*:', text, re.M):
            scan.add(folder.name)

    names = []
    try:
        from module.config.config_menu import ConfigMenu
        for _menu_name, items in ConfigMenu().menu.items():
            for name in items:
                if name in scan and name not in names:
                    names.append(name)
    except Exception as exc:
        logger.warning(f'Task group: cannot read the config menu: {exc}')
    for name in sorted(scan):
        if name not in names:
            names.append(name)
    return tuple(names)


def resolve_group_tasks(value) -> list:
    """
    把「一行一个任务名」的文本（旧配置或手写）解析成任务名列表。

    支持中文名和英文名，顺序即填写顺序，重复的只保留第一次。
    """
    if value is None:
        return []
    if isinstance(value, str) and not value.strip():
        return []
    try:
        items = normalize_multi_select(value)
    except Exception:
        items = [value]

    aliases = _task_aliases()
    result = []
    for item in items:
        key = str(item).strip()
        if not key:
            continue
        command = aliases.get(key.lower()) or aliases.get(key.replace(' ', '').lower())
        if command is None:
            logger.warning(f'Task group: unknown task `{key}`, skipped')
            continue
        if command in result:
            continue
        result.append(command)
    return result


@lru_cache(maxsize=1)
def _chinese_task_names() -> dict:
    """读取「任务名 -> 中文名」对照表（OASX 补充翻译 + 桌面 GUI 的 Qt 翻译）。"""
    names = {}
    try:
        path = Path.cwd() / 'assets' / 'i18n' / 'zh-CN.json'
        for key, value in json.loads(path.read_text(encoding='utf-8')).items():
            if isinstance(value, str) and value.strip():
                names.setdefault(key, value.strip())
    except Exception:
        pass
    try:
        path = Path.cwd() / 'module' / 'config' / 'i18n' / 'zh_CN.xml'
        text = path.read_text(encoding='utf-8')
        for source, translation in re.findall(
                r'<source>(.*?)</source>\s*<translation>(.*?)</translation>', text, re.S):
            if source.strip() and translation.strip():
                names.setdefault(source.strip(), translation.strip())
    except Exception:
        pass
    return names


@lru_cache(maxsize=1)
def _task_aliases() -> dict:
    """中文名 / 英文名（大小写、空格不敏感）-> 任务名。"""
    chinese_names = _chinese_task_names()
    aliases = {}
    for name in available_task_names():
        for key in (name, chinese_names.get(name)):
            if not key:
                continue
            key = str(key).strip()
            aliases.setdefault(key.lower(), name)
            aliases.setdefault(key.replace(' ', '').lower(), name)
    return aliases


class TaskGroupConfigBase(BaseModel):
    """任务组的设置：名称 + 按 task_1、task_2 …… 顺序执行的任务 + 出错策略。"""
    name: str = Field(default='任务组', description='task_group_name_help')
    task_1: GroupTaskChoice = Field(default=GroupTaskChoice.NONE, description='task_group_slot_help')
    task_2: GroupTaskChoice = Field(default=GroupTaskChoice.NONE, description='task_group_slot_help')
    task_3: GroupTaskChoice = Field(default=GroupTaskChoice.NONE, description='task_group_slot_help')
    task_4: GroupTaskChoice = Field(default=GroupTaskChoice.NONE, description='task_group_slot_help')
    task_5: GroupTaskChoice = Field(default=GroupTaskChoice.NONE, description='task_group_slot_help')
    task_6: GroupTaskChoice = Field(default=GroupTaskChoice.NONE, description='task_group_slot_help')
    task_7: GroupTaskChoice = Field(default=GroupTaskChoice.NONE, description='task_group_slot_help')
    task_8: GroupTaskChoice = Field(default=GroupTaskChoice.NONE, description='task_group_slot_help')
    task_9: GroupTaskChoice = Field(default=GroupTaskChoice.NONE, description='task_group_slot_help')
    task_10: GroupTaskChoice = Field(default=GroupTaskChoice.NONE, description='task_group_slot_help')
    stop_on_error: bool = Field(default=True, description='task_group_stop_on_error_help')

    @model_validator(mode='before')
    @classmethod
    def sanitize_slots(cls, data):
        """兼容手改配置：不认识的任务名按「不设置」处理，避免整份配置读不出来。"""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        for index in range(1, TASKS_PER_GROUP + 1):
            key = f'task_{index}'
            value = data.get(key)
            if value is None or isinstance(value, GroupTaskChoice):
                continue
            if str(value) not in GroupTaskChoice._value2member_map_:
                # 手写成中文名 / 别名时，尽量翻译成任务名
                resolved = resolve_group_tasks([value])
                if len(resolved) == 1:
                    data[key] = resolved[0]
                    continue
                logger.warning(f'Task group: unknown task `{value}` in {key}, reset to {NONE_CHOICE}')
                data[key] = NONE_CHOICE
        return data

    @model_validator(mode='after')
    def warn_missing_choices(self):
        """项目里有任务没进下拉框时提醒一次（新增任务后需要补 GroupTaskChoice）。"""
        global _missing_warned
        if not _missing_warned:
            missing = [name for name in available_task_names()
                       if name not in GroupTaskChoice._value2member_map_]
            if missing:
                _missing_warned = True
                logger.warning('Task group: these tasks are not in the dropdown yet '
                               f'{missing}, add them to GroupTaskChoice in tasks/TaskGroup/config.py')
        return self

    @property
    def task_list(self) -> list:
        """
        按 task_1 -> task_10 的顺序取出设置了任务的名字。

        这里会把中文名 / 别名再翻译一次，防止手写或别的接口塞进来的是中文。

        :return: 任务名列表（未设置和重复的会被跳过）
        """
        aliases = _task_aliases()
        result = []
        for index in range(1, TASKS_PER_GROUP + 1):
            choice = getattr(self, f'task_{index}', GroupTaskChoice.NONE)
            name = str(getattr(choice, 'value', choice) or '').strip()
            if not name or name == NONE_CHOICE:
                continue
            command = aliases.get(name.lower()) or aliases.get(name.replace(' ', '').lower()) or name
            if command in result:
                continue
            result.append(command)
        return result


class TaskGroupConfig1(TaskGroupConfigBase):
    name: str = Field(default='任务组 1', description='task_group_name_help')


class TaskGroupConfig2(TaskGroupConfigBase):
    name: str = Field(default='任务组 2', description='task_group_name_help')


class TaskGroupConfig3(TaskGroupConfigBase):
    name: str = Field(default='任务组 3', description='task_group_name_help')


class TaskGroupConfig4(TaskGroupConfigBase):
    name: str = Field(default='任务组 4', description='task_group_name_help')


class TaskGroupConfig5(TaskGroupConfigBase):
    name: str = Field(default='任务组 5', description='task_group_name_help')


class TaskGroupBase(ConfigBase):
    """任务组：自己的定时 + 自己的任务列表。"""
    scheduler: Scheduler = Field(default_factory=Scheduler)
    group_config: TaskGroupConfigBase = Field(default_factory=TaskGroupConfigBase)


class TaskGroup1(TaskGroupBase):
    group_config: TaskGroupConfig1 = Field(default_factory=TaskGroupConfig1)


class TaskGroup2(TaskGroupBase):
    group_config: TaskGroupConfig2 = Field(default_factory=TaskGroupConfig2)


class TaskGroup3(TaskGroupBase):
    group_config: TaskGroupConfig3 = Field(default_factory=TaskGroupConfig3)


class TaskGroup4(TaskGroupBase):
    group_config: TaskGroupConfig4 = Field(default_factory=TaskGroupConfig4)


class TaskGroup5(TaskGroupBase):
    group_config: TaskGroupConfig5 = Field(default_factory=TaskGroupConfig5)


GROUP_CLASSES = (TaskGroup1, TaskGroup2, TaskGroup3, TaskGroup4, TaskGroup5)


def migrate_legacy_group(old) -> dict:
    """
    把旧版「子任务组」（一个组 + 一行一个任务名的文本框）转成任务组 1。

    :param old: 旧配置里的 task_group 字典
    :return: 新配置里 task_group_1 的字典
    """
    if not isinstance(old, dict):
        return {}
    group_config = dict(old.get('group_config') or {})
    legacy_tasks = resolve_group_tasks(group_config.pop('tasks', ''))
    group_config.pop('schedule_mode', None)
    group_config.setdefault('name', old.get('name') or '任务组 1')
    for index, task in enumerate(legacy_tasks[:TASKS_PER_GROUP], start=1):
        group_config[f'task_{index}'] = task
    return {
        'scheduler': old.get('scheduler') or {},
        'group_config': group_config,
    }
