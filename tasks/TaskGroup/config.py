# This Python file uses the following encoding: utf-8
"""任务组：把多个已有任务按自定义顺序串成一组，用任务组自己的定时启动。"""

import json
import re
from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, field_serializer, model_validator

from module.config.multi_select import normalize_multi_select
from module.logger import logger
from tasks.Component.config_base import ConfigBase
from tasks.Component.config_scheduler import Scheduler

# 任务组自身所在目录，不能作为组内任务
GROUP_MODULE_DIR = 'TaskGroup'
# 每个任务组最多放多少个任务、项目里一共有几个任务组
TASKS_PER_GROUP = 10
GROUP_COUNT = 5
# 旧版固定 10 个下拉框时，空位写的是这个值，读旧配置时跳过
NONE_CHOICE = '不设置'

_missing_warned = False


class GroupTaskChoice(str, Enum):
    """
    任务组里可以添加的任务。

    新增任务后，把任务名也加到这里（默认值就是任务名本身），界面上才会出现；
    运行时如果发现漏了会打日志提醒。
    """
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


def normalize_task_names(value) -> list:
    """
    把界面上 / 配置里的任务名整理成一份任务名列表。

    任务名的顺序就是填写（拖动）的顺序；支持中文名和英文名，
    不认识的、重复的、旧版的「不设置」都会跳过，只保留第一次出现的任务名。

    :param value: 任务名列表，也可以是一行一个 / 逗号分隔的文本（旧配置或手写）
    :return: 任务名列表，例如 ['DailyTrifles', 'Pets']
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
        key = str(getattr(item, 'value', item) or '').strip()
        if not key or key == NONE_CHOICE:
            continue
        # 已经是任务名就直接用；否则按中文名 / 别名翻译一次。
        # 这里不依赖任务扫描的结果，免得在别的目录读配置时把手写的任务名吃掉。
        command = key if key in GroupTaskChoice._value2member_map_ \
            else aliases.get(key.lower()) or aliases.get(key.replace(' ', '').lower())
        if not command:
            logger.warning(f'Task group: unknown task `{key}`, skipped')
            continue
        if command == GROUP_MODULE_DIR or command in result:
            continue
        result.append(command)
    return result


def resolve_group_tasks(value) -> list:
    """
    把「一行一个任务名」的文本（旧配置或手写）解析成任务名列表。

    支持中文名和英文名，顺序即填写顺序，重复的只保留第一次。
    """
    return normalize_task_names(value)


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
    """任务组的设置：名称 + 一份按顺序执行的任务列表 + 出错策略。"""
    name: str = Field(default='任务组', description='task_group_name_help')
    # 组内任务：界面上可以「新增任务」加进来、拖动改顺序，跑的时候从上往下执行。
    # 默认是空列表（不加任务这一组就什么都不跑）。
    # x-ui-type 是给前端看的：让界面用可拖动排序的列表（task_list）来渲染这个字段，
    # 而不是默认的多选下拉框（multi_enum）。
    tasks: list[GroupTaskChoice] = Field(default=[], max_length=TASKS_PER_GROUP,
                                         title='Tasks',
                                         description='task_group_tasks_help',
                                         json_schema_extra={'x-ui-type': 'task_list'})
    # 从第几项开始运行：平时是 1（整组从头跑）；上一次在第 N 项出错停下时会被写成 N，
    # 下次就从第 N 项接着跑；整组跑完自动改回 1。运行状态，也可以自己手动填。
    start_index: int = Field(default=1, ge=1, le=TASKS_PER_GROUP,
                             description='task_group_start_index_help')
    stop_on_error: bool = Field(default=True, description='task_group_stop_on_error_help')

    @model_validator(mode='before')
    @classmethod
    def migrate_tasks(cls, data):
        """
        整理组内任务列表，顺便兼容旧配置和手改配置。

        - 旧版是 task_1 ~ task_10 十个下拉框，这里按原来的顺序收成一份列表；
        - 手写成一行一个 / 逗号分隔的文本时也能认出来；
        - 不认识的任务名直接跳过，避免整份配置读不出来。
        """
        if not isinstance(data, dict):
            return data
        data = dict(data)
        slots = []
        for index in range(1, TASKS_PER_GROUP + 1):
            key = f'task_{index}'
            if key in data:
                slots.append(data.pop(key))

        value = data.get('tasks')
        if value is None:
            items = []
        elif isinstance(value, (list, tuple, set)):
            items = list(value)
        else:
            items = [value]
        # 两个都有时以新的 tasks 为准，旧的 slot 排在后面（重复的会被去掉）
        tasks = normalize_task_names(items + slots)
        if len(tasks) > TASKS_PER_GROUP:
            logger.warning(f'Task group: at most {TASKS_PER_GROUP} tasks, '
                           f'these are ignored: {tasks[TASKS_PER_GROUP:]}')
            tasks = tasks[:TASKS_PER_GROUP]
        data['tasks'] = tasks
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
        按界面上的顺序取出组内任务名。

        :return: 任务名列表（不认识的和重复的会被跳过）
        """
        return normalize_task_names(self.tasks)

    @field_serializer('tasks')
    def serialize_tasks(self, value) -> list:
        """
        保存配置 / 传给前端时，tasks 永远是一份任务名列表。

        桌面端（老 GUI）把这个字段当文本框填，直接写进来的是多行文本，
        这里统一转成列表，免得配置文件里留下一个字符串。
        """
        return normalize_task_names(value)

    def set_task_list(self, value) -> list:
        """
        直接换掉整份任务列表（界面上新增 / 拖动 / 删除后回写用）。

        :param value: 任务名列表，也可以是一行一个 / 逗号分隔的文本
        :return: 真正写进去的任务名列表
        """
        tasks = normalize_task_names(value)[:TASKS_PER_GROUP]
        self.tasks = [GroupTaskChoice(name) for name in tasks]
        return tasks


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
    group_config.pop('schedule_mode', None)
    group_config.setdefault('name', old.get('name') or '任务组 1')
    # 旧版把任务名写成多行文本，新的 tasks 列表在读配置时会自动把它认成一份列表
    group_config.setdefault('tasks', [])
    return {
        'scheduler': old.get('scheduler') or {},
        'group_config': group_config,
    }
