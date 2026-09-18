# This Python file uses the following encoding: utf-8
"""子任务组：按配置的顺序依次运行多个已有任务。"""

from pathlib import Path
from datetime import datetime

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
from tasks.TaskGroup.config import TASK_GROUP_COMMAND, TaskGroupScheduleMode

# 这些异常代表游戏或环境本身出了问题，需要交给调度器统一处理
# （重开游戏 / 请求人工介入），不管「出错时停止本组」怎么设置都不会继续执行
FATAL_EXCEPTIONS = (GameBugError,
                    GameNotRunningError,
                    GamePageUnknownError,
                    GameStuckError,
                    GameTooManyClickError,
                    RequestHumanTakeover,
                    ScriptError)


class ScriptTask(BaseTask):
    """子任务组本身不做游戏操作，只负责按顺序调用组内的任务。"""

    # 组内任务使用它们自己的配置运行，不需要单独配置或启用；
    # 它们的「启动方案」由子任务组接管，调度器不会再单独调度它们。

    def run(self):
        conf = self.config.task_group.group_config
        tasks = conf.task_list
        if not tasks:
            logger.warning('Task group is empty, nothing to run')
            logger.warning('Fill one task name per line in the task list')
            self.set_next_run(task=TASK_GROUP_COMMAND, success=False, finish=True)
            raise TaskEnd(TASK_GROUP_COMMAND)

        by_subtask = conf.schedule_mode == TaskGroupScheduleMode.SUBTASK
        if by_subtask:
            # 按子任务自己的定时规则运行：只跑已经到期的任务，顺序还是配置的顺序
            run_tasks = self._due_tasks(tasks)
            if not run_tasks:
                logger.info('No task in the group is due, skip this round')
                self._save_group_next_run(tasks)
                raise TaskEnd(TASK_GROUP_COMMAND)
            logger.info(f'Task group runs the due task(s) {run_tasks}')
        else:
            # 按任务组自己的定时规则运行：每次到期都按顺序跑一遍组内任务
            run_tasks = tasks
            logger.info(f'Task group runs all task(s) {run_tasks}')

        success = True
        for index, task in enumerate(run_tasks, start=1):
            try:
                finished = self._run_task(index, len(run_tasks), task)
            except TaskEnd:
                raise
            except Exception as error:
                fatal = isinstance(error, FATAL_EXCEPTIONS)
                logger.exception(error)
                logger.error(f'Task group: `{task}` raised {type(error).__name__}')
                if fatal or conf.stop_on_error:
                    logger.warning(f'Task group aborts at `{task}`')
                    raise
                logger.warning(f'Task group skips `{task}` and runs the next task')
                success = False
                self._delay_task(task)
                continue
            if not finished:
                success = False
                self._delay_task(task)
                if conf.stop_on_error:
                    logger.warning(f'Task group stops at `{task}` because of the error above')
                    break
                logger.warning(f'Task group skips `{task}` and runs the next task')

        if by_subtask:
            self._save_group_next_run(tasks)
        else:
            self.set_next_run(task=TASK_GROUP_COMMAND, success=success, finish=True)
        if success:
            logger.info(f'Task group finished: {run_tasks}')
        else:
            logger.warning(f'Task group finished with error: {run_tasks}')
        raise TaskEnd(TASK_GROUP_COMMAND)

    def _task_next_run(self, task: str):
        """
        读取组内任务自己的下次运行时间。

        :param task: 大驼峰任务名
        :return: 下次运行时间，任务没有配置或时间不合法时返回 None
        """
        task_object = getattr(self.config.model, convert_to_underscore(task), None)
        next_run = getattr(getattr(task_object, 'scheduler', None), 'next_run', None)
        if isinstance(next_run, str):
            try:
                next_run = datetime.strptime(next_run, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                return None
        return next_run if isinstance(next_run, datetime) else None

    def _due_tasks(self, tasks: list) -> list:
        """
        挑出已经到期的任务，顺序和配置一致。

        :param tasks: 组内任务名列表
        :return: 已到期的任务名列表
        """
        now = datetime.now()
        due = []
        for task in tasks:
            next_run = self._task_next_run(task)
            if next_run is None or next_run <= now:
                due.append(task)
            else:
                logger.info(f'Task group: `{task}` is not due until {next_run}, skip')
        return due

    def _delay_task(self, task: str) -> None:
        """
        按任务自己的失败间隔把它延后，避免任务组一直重跑同一个任务。

        :param task: 大驼峰任务名
        """
        if self._task_next_run(task) is None:
            return
        self.set_next_run(task=task, success=False, finish=True)

    def _save_group_next_run(self, tasks: list) -> None:
        """
        按组内任务自己的定时规则更新任务组的下次运行时间。

        :param tasks: 组内任务名列表
        """
        times = [time for time in (self._task_next_run(task) for task in tasks)
                 if isinstance(time, datetime)]
        if not times:
            return
        self.set_next_run(task=TASK_GROUP_COMMAND, target=min(times), server=False)

    def _run_task(self, index: int, total: int, task: str) -> bool:
        """
        运行组内的一个任务。

        :param index: 当前是第几个子任务（从 1 开始）
        :param total: 子任务总数
        :param task: 大驼峰任务名
        :return: 子任务是否正常运行结束
        子任务抛出的异常（TaskEnd 除外）不在这里吞掉，交给调度器按单任务的方式来处理。
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
