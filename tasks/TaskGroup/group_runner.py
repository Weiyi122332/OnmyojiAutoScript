# This Python file uses the following encoding: utf-8
"""任务组的运行逻辑：按配置的顺序把组内任务跑一遍。"""

from pathlib import Path

from module.atom.click import RuleClick
from module.atom.scatter import RuleScatter
from module.base.utils import load_module
from module.config.utils import convert_to_underscore
from module.exception import (GameBugError,
                              GameNotRunningError,
                              GamePageUnknownError,
                              GameStuckError,
                              GameTooManyClickError,
                              RequestHumanTakeover,
                              ScriptError,
                              TaskEnd)
from module.logger import logger
from tasks.base_task import BaseTask

# 这些异常代表游戏或环境本身出了问题，需要交给调度器统一处理
# （重开游戏 / 请求人工介入），不管「出错时停止本组」怎么设置都不会继续执行
FATAL_EXCEPTIONS = (GameBugError,
                    GameNotRunningError,
                    GamePageUnknownError,
                    GameStuckError,
                    GameTooManyClickError,
                    RequestHumanTakeover,
                    ScriptError)


class TaskGroupRunner(BaseTask):
    """
    任务组本身不做游戏操作，只负责按顺序调用组内的任务。

    定时由任务组自己决定（启用开关 + 下次运行时间 + 成功/失败间隔），
    每次启动都把组内任务从头到尾按配置的顺序跑一遍；
    组内任务自己的「启动方案」失效，调度器不会再单独调度它们。
    """

    # 子类填自己的任务名，例如 'TaskGroup1'
    command = ''

    def run(self):
        field = convert_to_underscore(self.command)
        group = getattr(self.config.model, field, None)
        if group is None:
            logger.error(f'Task group: config `{field}` does not exist, nothing to run')
            raise TaskEnd(self.command)

        conf = group.group_config
        tasks = conf.task_list
        title = conf.name or self.command
        logger.info(f'Task group `{title}` ({self.command}) starts, {len(tasks)} task(s): {tasks}')
        if not tasks:
            logger.warning(f'任务组「{title}」里还没有选任务，请在配置里把任务加到列表')
            self.set_next_run(task=self.command, success=False, finish=True)
            raise TaskEnd(self.command)

        success = True
        for index, task in enumerate(tasks, start=1):
            try:
                finished = self._run_task(index, len(tasks), task)
            except TaskEnd:
                raise
            except Exception as error:
                fatal = isinstance(error, FATAL_EXCEPTIONS)
                logger.exception(error)
                logger.error(f'Task group `{title}`: `{task}` raised {type(error).__name__}')
                if fatal or conf.stop_on_error:
                    logger.warning(f'Task group `{title}` stops at `{task}`')
                    raise
                logger.warning(f'Task group `{title}` skips `{task}` and runs the next task')
                success = False
                self._mark_task_failed(task)
                continue
            if not finished:
                success = False
                self._mark_task_failed(task)
                if conf.stop_on_error:
                    logger.warning(f'Task group `{title}` stops at `{task}` because of the error above')
                    break
                logger.warning(f'Task group `{title}` skips `{task}` and runs the next task')

        self.set_next_run(task=self.command, success=success, finish=True)
        if success:
            logger.info(f'Task group `{title}` finished: {tasks}')
        else:
            logger.warning(f'Task group `{title}` finished with error: {tasks}')
        raise TaskEnd(self.command)

    def _mark_task_failed(self, task: str) -> None:
        """
        按任务自己的失败间隔记一次失败。

        任务组有它自己的定时，这里主要是让这个任务的「下次运行时间」保持合理，
        以后把它从任务组里拿出来单独跑时，不会因为时间停在很久以前而立刻重跑。
        """
        self.set_next_run(task=task, success=False, finish=True)

    def _run_task(self, index: int, total: int, task: str) -> bool:
        """
        运行组内的一个任务。

        :param index: 当前是第几个任务（从 1 开始）
        :param total: 任务总数
        :param task: 任务名
        :return: 任务是否正常运行结束（抛出的异常不在这里吞掉）
        """
        module_path = Path.cwd() / 'tasks' / task / 'script_task.py'
        if not module_path.exists():
            logger.error(f'Task group: `{task}` has no {module_path}, skipped')
            return False

        logger.hr(f'Task group [{index}/{total}]: {task}', level=1)
        # 与调度器运行单个任务时保持一致，避免上一轮的落点和卡死记录影响下一个任务
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        RuleClick.reset_task_points()
        RuleScatter.begin_task(task)
        try:
            task_module = load_module(f'task_group_{task}', str(module_path))
            task_module.ScriptTask(config=self.config, device=self.device).run()
        except TaskEnd as end:
            logger.info(f'Task group: `{task}` finished. {end}')
        finally:
            RuleScatter.end_task(task)

        return True
