# This Python file uses the following encoding: utf-8
"""式神活动统一任务入口。"""

from module.logger import logger
from tasks.ActivityShikigami.activities.fake_god import FakeGodAct
from tasks.ActivityShikigami.activities.normal import NormalClimbAct
from tasks.ActivityShikigami.base_act import BaseAct
from tasks.ActivityShikigami.config import ACTIVITY_NAME_TO_FIELD


class ScriptTask(NormalClimbAct, FakeGodAct, BaseAct):

    def run(self):
        self.before_run()
        sequence = self.conf.general_config.task_sequence_v
        logger.info(f'ActivityShikigami execution sequence: {sequence}')
        for activity_name in sequence:
            if self.time_limit_reached():
                break
            action_type = ACTIVITY_NAME_TO_FIELD[activity_name]
            if action_type == 'fakegod':
                self.run_fakegod()
            else:
                self.run_climb(action_type)
        self.finish_activity_task()
