# This Python file uses the following encoding: utf-8
from datetime import datetime
from tasks.MetaDemon.boss_battle import BossBattle
from tasks.MetaDemon.config import MetaDemonMode


class ScriptTask(BossBattle):
    """超鬼王战斗和协助入口。"""

    def run(self, *, grouped_assistance=False, batch_session=None):
        config = self.config.meta_demon
        modes = config.meta_demon_config.mode
        if grouped_assistance and (MetaDemonMode.BOSS_ASSIST not in modes
                                   or not config.assistance_config.batch_cooperation):
            return False
        for mode in modes:
            if mode == MetaDemonMode.BOSS_ASSIST:
                from tasks.MetaDemon.assistance import run_assistance
                self.start_time = datetime.now()
                if grouped_assistance:
                    return run_assistance(self, grouped=True, batch_session=batch_session)
                return run_assistance(self)
            if mode == MetaDemonMode.BOSS_BATTLE:
                self.start_time = datetime.now()
                return super().run()
        self.set_next_run(task="MetaDemon", success=True)
        self.finish_task()
