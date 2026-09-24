# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import copy
import datetime
import operator
import threading

from datetime import datetime, timedelta
from cached_property import cached_property
from threading import Lock

from module.base.filter import Filter
from module.config.config_updater import ConfigUpdater
from module.config.cron import cron_error, try_parse_cron
from module.config.config_manual import ConfigManual
from module.config.config_watcher import ConfigWatcher
from module.config.config_menu import ConfigMenu
from module.config.config_model import ConfigModel
from module.config.config_state import ConfigState
from module.config.scheduler import TaskScheduler
from module.config.utils import *
from module.notify.notify import Notifier

from module.exception import RequestHumanTakeover, ScriptError
from module.logger import logger


class Function:
    def __init__(self, key: str, data: dict):
        """
        输入的是每一个ConfigModel的一个字段对象
        :param data:
        """
        if isinstance(data, dict) is False:
            self.enable = False
            self.command = "Unknown"
            self.next_run = DEFAULT_TIME
            self.cron = ''
            return
        if data.get("scheduler") is None:
            self.enable = False
            self.command = "Unknown"
            self.next_run = DEFAULT_TIME
            self.cron = ''
            return

        self.enable: bool = data['scheduler']['enable']
        self.command: str = ConfigModel.type(key)
        # 定时规则（crontab），留空表示按间隔运行
        self.cron: str = str(data['scheduler'].get('cron') or '')
        next_run = data['scheduler']['next_run']
        if isinstance(next_run, str):
            next_run = datetime.strptime(next_run, "%Y-%m-%d %H:%M:%S")
        self.next_run: datetime = next_run
        priority = data['scheduler']['priority']
        if isinstance(priority, str):
            priority = int(priority)
        self.priority: int = priority
        if not isinstance(self.priority, int):
            logger.error(f"Invalid priority: {self.priority}")

        # self.enable = deep_get(data, keys="Scheduler.Enable", default=False)
        # self.command = deep_get(data, keys="Scheduler.Command", default="Unknown")
        # self.next_run = deep_get(data, keys="Scheduler.NextRun", default=DEFAULT_TIME)

    def __str__(self):
        enable = "Enable" if self.enable else "Disable"
        return f"{self.command} ({enable}, {self.priority}, {str(self.next_run)})"

    __repr__ = __str__

    def __eq__(self, other):
        if not isinstance(other, Function):
            return False

        if self.command == other.command and self.next_run == other.next_run:
            return True
        else:
            return False


def name_to_function(name):
    """
    Args:
        name (str):

    Returns:
        Function:
    """
    function = Function({})
    function.command = name
    function.enable = True
    return function


class Config(ConfigState, ConfigManual, ConfigWatcher, ConfigMenu):

    def __init__(self, config_name: str, task=None) -> None:
        """

        :param config_name:
        :param task:
        """
        super().__init__(config_name)  # 调用 ConfigState 的初始化方法
        super(ConfigManual, self).__init__()
        super(ConfigWatcher, self).__init__()
        super(ConfigMenu, self).__init__()
        self.model = ConfigModel(config_name=config_name)
        self.scheduler_update_dt = None  # 调度器更新时间

    def __getattr__(self, name):
        """
        一开始是打算直接继承ConfigModel的，但是pydantic会接管所有的变量
        故而选择持有ConfigModel
        :param name:
        :return:
        """
        try:
            return getattr(self.model, name)
        except AttributeError:
            # 这个导致 大量的无用log
            # logger.error(f'can not ask this variable {name}')
            return None  # 或者抛出异常，或者返回其他默认值

    @cached_property
    def lock_config(self) -> Lock:
        return Lock()

    @cached_property
    def notifier(self):
        notifier = Notifier(self.model.script.error.notify_config, enable=self.model.script.error.notify_enable)
        notifier.config_name = self.config_name.upper()
        logger.info(f'Notifier: {notifier.config_name}')
        return notifier

    def gui_args(self, task: str) -> str:
        """
        获取给gui显示的参数
        :return:
        """
        return self.model.gui_args(task=task)

    def get_arg(self, task: str, group: str, argument: str):
        """

        :param task:
        :param group:
        :param argument:
        :return: str/int/float
        """
        try:
            return self.data[task][group][argument]
        except:
            logger.exception(f'have no arg {task}.{group}.{argument}')

    def set_arg(self, task: str, group: str, argument: str, value) -> None:
        """

        :param task:
        :param group:
        :param argument:
        :param value:
        :return:
        """
        try:
            self.data[task][group][argument] = value
        except:
            logger.exception(f'have no arg {task}.{group}.{argument}')

    def reload(self):
        self.model = ConfigModel(config_name=self.config_name)

    def save(self) -> None:
        """
        保存配置文件
        :return:
        """
        self.model.write_json(self.config_name, self.model.dict())

    def task_group_members(self) -> set:
        """
        当前生效的所有任务组里的任务名。

        被加进任务组的任务由任务组接管调度，其中的「启动方案」失效，
        调度器不会再单独调度它们。

        :return: 任务名的集合，没有生效的任务组时返回空集合
        """
        members = set()
        try:
            from tasks.TaskGroup.config import GROUP_COUNT
        except Exception:
            GROUP_COUNT = 5
        for index in range(1, GROUP_COUNT + 1):
            try:
                group = getattr(self.model, f'task_group_{index}', None)
                if group is None or not group.scheduler.enable:
                    continue
                members.update(group.group_config.task_list)
            except Exception as e:
                logger.warning(f'Can not read the task group {index}: {e}')
        return members

    def update_scheduler(self) -> None:
        """
        更新调度器， 设置pending_task and waiting_task
        :return:
        """
        pending_task = []
        waiting_task = []
        error = []
        self.scheduler_update_dt = datetime.now()
        group_members = self.task_group_members()
        for key, value in self.model.dict().items():
            func = Function(key, value)
            if not func.enable:
                continue
            if not isinstance(func.next_run, datetime):
                error.append(func)
            elif func.next_run < self.scheduler_update_dt:
                pending_task.append(func)
            else:
                waiting_task.append(func)

        # 子任务组里的任务不再单独调度，统一由子任务组按顺序执行
        if group_members:
            suppressed = sorted({f.command for f in pending_task + waiting_task
                                 if f.command in group_members})
            if suppressed != self.__dict__.get('_task_group_suppressed'):
                self._task_group_suppressed = suppressed
                if suppressed:
                    logger.info(f'Tasks {suppressed} are in the task group, '
                                f'their own schedule is ignored')
            pending_task = [f for f in pending_task if f.command not in group_members]
            waiting_task = [f for f in waiting_task if f.command not in group_members]

        # f = Filter(regex=r"(.*)", attr=["command"])
        # f.load(self.SCHEDULER_PRIORITY)
        if pending_task:
            pending_task = TaskScheduler.schedule(rule=self.model.script.optimization.schedule_rule,
                                                  pending=pending_task)
            # 防止正在运行的任务被新上来的pending队列中的任务给顶替掉
            if self.model.running_task and pending_task:
                for i, obj in enumerate(pending_task):
                    if obj.command == self.model.running_task:
                        pending_task.insert(0, pending_task.pop(i))
                        logger.info(f'{self.model.running_task} is running')
                        break
        if waiting_task:
            # waiting_task = f.apply(waiting_task)
            waiting_task = sorted(waiting_task, key=operator.attrgetter("next_run"))
        if error:
            pending_task = error + pending_task

        self.pending_task = pending_task
        self.waiting_task = waiting_task

    def get_next(self) -> Function:
        """
        获取下一个要执行的任务
        :return:
        """
        self.update_scheduler()

        if self.pending_task:
            logger.info(f"Pending tasks: {[f.command for f in self.pending_task]}")
            task = self.pending_task[0]
            self.task = task
            logger.attr("Task", task)
            return task

        # 哪怕是没有任务，也要返回一个任务，这样才能保证调度器正常运行
        if self.waiting_task:
            logger.info("No task pending")
            task = copy.deepcopy(self.waiting_task[0])
            # task.next_run = (task.next_run + self.hoarding).replace(microsecond=0)
            logger.attr("Task", task)
            return task
        else:
            logger.critical("No task waiting or pending")
            logger.critical("Please enable at least one task")
            raise RequestHumanTakeover

    def get_schedule_data(self) -> dict[str, dict]:
        """
        获取调度器的数据， 但是你必须使用update_scheduler来更新信息
        :return:
        """
        # 根据调度器更新时间来判断是否有可运行的任务,保证逻辑一致性
        scheduler_update_dt = getattr(self, 'scheduler_update_dt', datetime.now())
        running = {}
        if self.task is not None and self.task.next_run < scheduler_update_dt:
            running = {"name": self.task.command, "next_run": str(self.task.next_run)}

        pending = []
        for p in self.pending_task[1:]:
            item = {"name": p.command, "next_run": str(p.next_run)}
            pending.append(item)

        waiting = []
        for w in self.waiting_task:
            item = {"name": w.command, "next_run": str(w.next_run)}
            waiting.append(item)

        data = {"running": running, "pending": pending, "waiting": waiting}
        return data

    def task_call(self, task: str = None, force_call=True):
        """
        回调任务，这会是在任务结束后调用
        :param task: 调用的任务的大写名称
        :param force_call:
        :return:
        """
        task = convert_to_underscore(task)
        if self.model.deep_get(self.model, keys=f'{task}.scheduler.next_run') is None:
            raise ScriptError(f"Task to call: `{task}` does not exist in user config")

        task_enable = self.model.deep_get(self.model, keys=f'{task}.scheduler.enable')
        if force_call or task_enable:
            logger.info(f"Task call: {task}")
            next_run = datetime.now().replace(
                microsecond=0
            )
            self.model.deep_set(self.model, keys=f'{task}.scheduler.next_run', value=next_run)
            self.save()
            return True
        else:
            logger.info(f"Task call: {task} (skipped because disabled by user)")
            return False

    def task_delay(self, task: str, start_time: datetime = None,
                   success: bool = None, target: datetime = None) -> None:
        """
        设置下次运行时间  当然这个也是可以重写的
        :param target: 可以自定义的下次运行时间
        :param success: 判断是成功的还是失败的时间间隔
        :param task: 任务名称，大驼峰的
        :param finish: 是完成任务后的时间为基准还是开始任务的时间为基准
        :return:
        """
        # 加载配置文件
        self.reload()
        # 任务预处理
        if not task:
            task = self.task.command
        task = convert_to_underscore(task)
        task_object = getattr(self.model, task, None)
        if not task_object:
            logger.warning(f'No task named {task}')
            return
        scheduler = getattr(task_object, 'scheduler', None)
        if not scheduler:
            logger.warning(f'No scheduler in {task}')
            return

        # 任务开始时间
        if not start_time:
            start_time = datetime.now().replace(microsecond=0)

        # 依次判断是否有自定义的下次运行时间
        run = []
        if success is not None:
            interval = (
                scheduler.success_interval
                if success
                else scheduler.failure_interval
            )
            if isinstance(interval, str):
                interval = timedelta(interval)
            run.append(start_time + interval)
        target_time = None
        if target is not None:
            target = [target] if not isinstance(target, list) else target
            target = nearest_future(target)
            run.append(target)
            target_time = target

        next_run = None
        # 排序
        if not len(run):
            raise ScriptError(
                "Missing argument in delay_next_run, should set at least one"
            )

        run = min(run).replace(microsecond=0)
        next_run = run

        # 定时规则（crontab）：填了就由它决定下次运行时间
        cron_text = str(getattr(scheduler, 'cron', '') or '').strip()
        if cron_text:
            expression = try_parse_cron(cron_text)
            if expression is None:
                logger.warning(f'{task}: cron `{cron_text}` is invalid '
                               f'({cron_error(cron_text)}), fallback to the interval schedule')
            else:
                # 以「任务开始/结束的时刻」为基准往后找，任务跑得比较久时不会重复排期；
                # 有明确的延后目标（例如「下周再跑」）时，从目标时间开始往后找
                base = max(start_time.replace(microsecond=0),
                           datetime.now().replace(microsecond=0))
                if isinstance(target_time, datetime) and target_time > base:
                    next_run = expression.next_after(target_time, inclusive=True)
                else:
                    next_run = expression.next_after(base)

        # 随机浮动：最终时间 = 上面的时间 + 0~float_time 的随机秒数（cron 规则同样生效）
        next_run += timedelta(seconds=random_float_seconds(getattr(scheduler, 'float_time', None)))

        # 将这些连接起来，方便日志输出
        kv = dict_to_kv(
            {
                "success": success,
                "target": target,
            },
            allow_none=False,
        )
        # logger.info(f"Delay task `{task}` to {next_run} ({kv})")

        # 保证线程安全的
        self.lock_config.acquire()
        try:
            scheduler.next_run = next_run
            self.save()
        finally:
            self.lock_config.release()
        # 设置
        logger.attr(f'{task}.scheduler.next_run', next_run)


if __name__ == '__main__':
    config = Config(config_name='oas1')
    config.notifier.push(title="0000", content="dddddddd")

    # print(config.get_next())
