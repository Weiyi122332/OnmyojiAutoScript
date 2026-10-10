"""磐长故地地图选点及门票挑战流程。"""

import random
import time

from module.exception import GamePageUnknownError
from module.logger import logger
from tasks.ActivityShikigami.base_act import ActivityResourceNotEnough
from tasks.ActivityShikigami.assets import ActivityShikigamiAssets
import tasks.ActivityShikigami.page as pages


def select_fakegod_target(task):
    """从当前地图识别可挑战据点，兼容地图缩放及据点位置变化。"""
    for _ in range(3):
        task.screenshot()
        if not task.appear(ActivityShikigamiAssets.I_FG_AS_CHECK_MAIN_2):
            return False
        if task.appear_then_click(ActivityShikigamiAssets.I_FG_AS_TO_PASS, interval=0):
            task.device.click_record_clear()
            return True
        time.sleep(0.5)
    message = '磐长故地战斗据点识别失败，停止式神活动；未确认门票耗尽'
    logger.warning(message)
    raise GamePageUnknownError(message)


class FakeGodAct:
    def setup_fakegod_pages(self):
        page_act = self.navigator.resolve_page(pages.page_act)
        page_map = self.navigator.resolve_page(pages.page_fakegod_map)
        page_action = self.navigator.resolve_page(pages.page_fakegod_action)

        page_act.connect(page_map, ActivityShikigamiAssets.I_FG_TO_BATTLE_MAIN, key='activity->fakegod_map')
        page_map.connect(page_action, select_fakegod_target, key='fakegod_map->action')

    def _goto_fakegod_action(self, destination) -> bool:
        try:
            self.goto_page(destination)
        except ActivityResourceNotEnough:
            return False
        self._sync_fakegod_team_lock()
        return True

    def run_fakegod(self):
        logger.hr('Start activity: Fakegod', 1)
        self.setup_fakegod_pages()
        destination = pages.page_fakegod_action
        if not self._goto_fakegod_action(destination):
            return

        while True:
            self.screenshot()
            current_page = self.get_current_page()
            if current_page == destination:
                if not self.prepare_next_action('fakegod'):
                    return
                try:
                    self._run_fakegod_action(destination)
                except ActivityResourceNotEnough:
                    logger.info('Fakegod action resource exhausted')
                    return
                continue
            if current_page in (pages.page_battle_prepare, pages.page_battle):
                self.run_general_battle(
                    self.battle_config('fakegod'),
                    battle_key='activity_fakegod',
                )
                continue
            if current_page == pages.page_reward:
                self.click(self._battle_settlement_click(), interval=1.5)
                continue
            if current_page is None:
                time.sleep(0.5)
                continue
            if self.time_limit_reached() or self.action_count['fakegod'] >= self.action_limit('fakegod'):
                return
            if not self._goto_fakegod_action(destination):
                return

    def _run_fakegod_action(self, destination):
        self.screenshot()
        remain = self.O_FG_REMAIN_PASS.ocr_digit(self.device.image)
        trial = remain <= 0
        self.switch_soul_for(
            'fakegod',
            self.I_FG_BATTLE_MAIN_TO_RECORDS,
            return_page=destination,
            exit_records=True,
        )
        if trial:
            entered = self.verify_zero_ticket(
                'ActivityShikigami fakegod action',
                lambda: self._enter_fakegod_battle(max_times=1),
            )
        else:
            entered = self._enter_fakegod_battle()
        if not entered:
            raise ActivityResourceNotEnough
        self.record_action('fakegod')
        self.run_general_battle(
            self.battle_config('fakegod'),
            battle_key='activity_fakegod',
        )

    def _enter_fakegod_battle(self, max_times: int | None = None) -> bool:
        click_times = 0
        fallback = max_times is not None
        max_times = max_times or random.randint(3, 5)
        while True:
            self.screenshot()
            if self.is_in_battle(False):
                return True
            if click_times >= max_times:
                return False if fallback else self._raise_fakegod_resource_error()
            if self.appear(self.I_UI_BACK_RED, interval=1):
                return False if fallback else self._raise_fakegod_resource_error()
            if self.appear_then_click(self.I_UI_CONFIRM_SAMLL, interval=1) or \
                    self.appear_then_click(self.I_UI_CONFIRM, interval=1):
                continue
            if self.appear_then_click(self.I_FG_ACT_FIRE, interval=1):
                self.device.click_record_clear()
                click_times += 1
                if fallback:
                    return self._wait_fakegod_trial_result(timeout=3.0)

    @staticmethod
    def _raise_fakegod_resource_error():
        raise ActivityResourceNotEnough

    def _wait_fakegod_trial_result(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.screenshot()
            if self.is_in_battle(False):
                return True
            if self.appear(self.I_UI_CONFIRM_SAMLL) or self.appear(self.I_UI_CONFIRM):
                return False
            if self.appear(self.I_UI_BACK_RED):
                return False
            time.sleep(0.2)
        return False

    def _sync_fakegod_team_lock(self):
        if self.battle_config('fakegod').lock_team_enable:
            self.ui_click(self.I_FG_UNLOCK, stop=self.I_FG_LOCK, interval=1.5)
        else:
            self.ui_click(self.I_FG_LOCK, stop=self.I_FG_UNLOCK, interval=1.5)
