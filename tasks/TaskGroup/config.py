# This Python file uses the following encoding: utf-8
"""子任务组：把多个已有任务按自定义顺序串成一组运行。"""

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from module.config.multi_select import normalize_multi_select
from module.logger import logger
from tasks.Component.config_base import ConfigBase, MultiLine
from tasks.Component.config_scheduler import Scheduler

# 这个任务自身的命令名
TASK_GROUP_COMMAND = 'TaskGroup'


@lru_cache(maxsize=1)
def available_task_names() -> tuple[str, ...]:
    """
    返回可以加入子任务组的任务名（大驼峰格式）。

    判定标准和调度器一致：配置文件里有 scheduler 的项就是可以独立运行的任务。

    Returns:
        tuple[str, ...]: 任务名列表，顺序与配置文件的定义顺序一致。
    """
    try:
        from module.config.config_model import ConfigModel
        model_fields = ConfigModel.model_fields
    except Exception as exc:
        logger.warning(f'Task group: cannot read the task list: {exc}')
        return tuple()

    names = []
    for key, field in model_fields.items():
        annotation = field.annotation
        if not hasattr(annotation, 'model_fields'):
            continue
        if 'scheduler' not in annotation.model_fields:
            continue
        name = getattr(annotation, '__name__', None) or ConfigModel.type(key)
        if name == TASK_GROUP_COMMAND or name in names:
            continue
        if not (Path.cwd() / 'tasks' / name / 'script_task.py').exists():
            # 只有配置、没有脚本的任务（例如御魂悲鸣）不能单独运行，也不能进任务组
            continue
        names.append(name)
    return tuple(names)


@lru_cache(maxsize=1)
def _chinese_task_names() -> dict[str, str]:
    """
    读取「任务名 -> 中文名」的对照表。

    数据来源有两处：OASX 的补充翻译（assets/i18n/zh-CN.json）和
    桌面 GUI 的 Qt 翻译（module/config/i18n/zh_CN.xml）。

    Returns:
        dict[str, str]: 英文任务名到中文名的映射。
    """
    import re

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
def _task_aliases() -> dict[str, str]:
    """
    任务别名表：中文名 / 英文名（大小写、空格不敏感）-> 大驼峰任务名。

    Returns:
        dict[str, str]: 小写别名到大驼峰任务名的映射。
    """
    chinese_names = _chinese_task_names()
    aliases = {}
    for name in available_task_names():
        keys = [name, chinese_names.get(name)]
        for key in keys:
            if not key:
                continue
            key = str(key).strip()
            aliases.setdefault(key.lower(), name)
            aliases.setdefault(key.replace(' ', '').lower(), name)
    return aliases


def resolve_group_tasks(value) -> list[str]:
    """
    把配置里填写的文本解析成按顺序排列的任务名。

    Args:
        value: 多行文本、列表或逗号分隔的字符串，每项一个任务名。

    Returns:
        list[str]: 去重后的任务名列表，顺序与填写顺序一致。
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
        if command == TASK_GROUP_COMMAND:
            logger.warning('Task group: a task group cannot contain another task group, skipped')
            continue
        if command in result:
            logger.info(f'Task group: duplicated task `{command}`, keep the first one')
            continue
        result.append(command)
    return result


class TaskGroupConfig(BaseModel):
    tasks: MultiLine = Field(default='', description='task_group_tasks_help')
    stop_on_error: bool = Field(default=True, description='task_group_stop_on_error_help')

    @property
    def task_list(self) -> list[str]:
        """
        组内任务列表，顺序即执行顺序。

        Returns:
            list[str]: 大驼峰任务名列表。
        """
        return resolve_group_tasks(self.tasks)


class TaskGroup(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    group_config: TaskGroupConfig = Field(default_factory=TaskGroupConfig)
