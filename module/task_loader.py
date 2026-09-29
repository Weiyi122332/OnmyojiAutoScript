"""Locate task scripts from the project root, independent of the process cwd.

Task directories are part of the public configuration format. Keep their names
stable; both the scheduler and task groups use this resolver when running them.
"""

import re
from pathlib import Path


TASKS_DIR = Path(__file__).resolve().parent.parent / 'tasks'
_TASK_NAME = re.compile(r'[A-Za-z][A-Za-z0-9]*\Z')


def task_script_path(task: str) -> Path:
    """Return the script path for a task command such as ``DailyTrifles``."""
    if not isinstance(task, str) or not _TASK_NAME.fullmatch(task):
        raise ValueError(f'Invalid task name: {task!r}')
    return TASKS_DIR / task / 'script_task.py'


def load_task_script(task: str, module_name: str = 'script_task'):
    """Execute a task script afresh, preserving the existing loader semantics."""
    from module.base.utils import load_module

    return load_module(module_name, str(task_script_path(task)))
