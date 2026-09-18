# This Python file uses the following encoding: utf-8
"""任务组的显示名称：给菜单 / 任务列表用的全局名称。

菜单是全局的（前端只拉一份菜单 + 一份翻译表），所以这里扫描各配置实例，
把改过名字的任务组收集起来，供 /home/additional_translate 和桌面 GUI 使用。
"""

import json
import time
from pathlib import Path

from module.logger import logger

# 任务组数量与默认名称前缀，和 tasks/TaskGroup/config.py 保持一致
GROUP_COUNT = 5
DEFAULT_NAME_PREFIX = '任务组'
# 缓存时间，避免 UI 每次取翻译都去读文件
_CACHE_SECONDS = 1.0
_cache = {'time': 0.0, 'names': {}}


def _default_name(index: int) -> str:
    return f'{DEFAULT_NAME_PREFIX} {index}'


def collect_group_names(force: bool = False) -> dict:
    """
    收集「任务组 -> 自定义名称」。

    多个配置实例都改了名字时，越新的配置文件优先（菜单是全局的，只显示一套名字）。

    :param force: True 时忽略缓存
    :return: {'TaskGroup1': '日常', ...}，只包含改过名字的组
    """
    now = time.time()
    if not force and now - _cache['time'] < _CACHE_SECONDS:
        return _cache['names']

    names = {}
    folder = Path.cwd() / 'config'
    try:
        files = [path for path in folder.glob('*.json') if path.is_file()]
        files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        files = []

    for path in files:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        for index in range(1, GROUP_COUNT + 1):
            key = f'TaskGroup{index}'
            if key in names:
                continue
            group = (data.get(f'task_group_{index}') or {}).get('group_config') or {}
            name = str(group.get('name') or '').strip()
            if name and name != _default_name(index) and name != DEFAULT_NAME_PREFIX:
                names[key] = name

    _cache['time'] = now
    _cache['names'] = names
    if names:
        logger.debug(f'Task group names: {names}')
    return names
