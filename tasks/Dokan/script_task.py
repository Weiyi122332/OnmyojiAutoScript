# This Python file uses the following encoding: utf-8
# @brief    Ryou Dokan Toppa (阴阳竂道馆突破功能)
# @author   AzurTian
# @note     draft version without full test
import time

import re
from datetime import timedelta
from pathlib import Path
from random import uniform
from time import sleep
from uuid import uuid4

from future.backports.datetime import datetime

from module.base.timer import Timer
from module.exception import TaskEnd
from module.logger import logger
from module.notify.task_notify import resolve_task_notifier
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.GeneralBattle.general_battle import GeneralBattle, ExitMatcher, BattleContext, \
    BattleAction
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.Component.config_base import Time
from tasks.Dokan.assets import DokanAssets
from tasks.Dokan.config import Dokan, QQMessageConfig
from tasks.Dokan.reward_recognition import count_blue_tickets_in_png
from tasks.Dokan.qq_monitor import QQDokanState
import tasks.Dokan.page as pages
from tasks.GameUi.game_ui import GameUi

def position_offset(src, offset: tuple):
    return src[0] + offset[0], src[1] + offset[1], src[2] + offset[2], src[3] + offset[3]

class DokanFinishedError(Exception):
    pass

class DokanNotStartedError(Exception):
    pass

class DokanRefreshLimitError(Exception):
    pass

DOKAN_REWARD_SCREENSHOT_DIR = Path('log/screenshots/dokan')
DOKAN_REWARD_CAPTURE_DELAY = 1.0
DOKAN_NEXT_SELECTION_WAIT_RANGE = (70.0, 90.0)
MAX_WELFARE_DOKAN_REFRESH_COUNT = 20

class ScriptTask(GameUi, SwitchSoul, GeneralBattle, DokanAssets):
    _reuse_image_match_results: bool = True  # 仅道馆启用同帧识别结果和相同规则副本的复用。
    attack_priority_selected: bool = False
    switch_member_soul_done: bool = False
    dokan_owner_battle: bool = False  # 馆主战标识(会在多个可识别到馆主战的位置进行设置)
    found_dokan_cnt: int = 0  # 已经寻找道馆的次数
    second_dokan_ready: bool = False
    conf: Dokan = None

    def _register_custom_pages(self) -> None:
        page_battle_result = self.navigator.resolve_page(pages.page_battle_result)
        if page_battle_result is None:
            return
        page_battle_result.recognizer = pages.any_of(self.I_RYOU_DOKAN_TOPPA_RANK, self.I_RYOU_DOKAN_WIN,
                                                     page_battle_result.recognizer)
        page_battle_result.priority = 75
        page_reward = self.navigator.resolve_page(pages.page_reward)
        if page_reward is None:
            return
        page_reward.recognizer = pages.any_of(self.I_RYOU_DOKAN_BATTLE_OVER, page_reward.recognizer)
        page_reward.priority = 75

    def _exit_matcher(self) -> ExitMatcher | None:
        return pages.any_of(self.I_RYOU_DOKAN_CENTER_TOP, self.I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_DONE)

    def _get_battle_screenshot_interval(self, page: pages.Page) -> float | str | None:
        # 馆员战会直接回到准备页，缩短两帧确认等待以便尽快开始下一场。
        if page == pages.page_battle:
            return 0.3
        return super()._get_battle_screenshot_interval(page)

    def _handle_prepare(self, context: BattleContext, config: GeneralBattleConfig) -> BattleAction:
        if self.appear(self.I_RYOU_DOKAN_BATTLE_MASTER_FIRST) or self.appear(self.I_RYOU_DOKAN_BATTLE_MASTER_SECOND):
            self.dokan_owner_battle = True
        if self.dokan_owner_battle:
            return BattleAction.QUICK_EXIT
        return super()._handle_prepare(context, config)

    def _handle_in_battle(self, context: BattleContext, config: GeneralBattleConfig) -> BattleAction:
        if self.appear(self.I_RYOU_DOKAN_BATTLE_MASTER_FIRST) or self.appear(self.I_RYOU_DOKAN_BATTLE_MASTER_SECOND):
            self.dokan_owner_battle = True  # 防止直接在战斗界面识别, 因此在这继续更新一次馆主战标识
        if self.dokan_owner_battle:
            logger.info("Skip owner battle: leave the battle before attacking")
            return BattleAction.QUICK_EXIT
        return super()._handle_in_battle(context, config)

    def _handle_reward(self, context: BattleContext, config: GeneralBattleConfig) -> BattleAction:
        """Save the visible dojo reward before the battle handler closes it."""
        if self._capture_dokan_reward_if_visible(context) is False:
            return BattleAction.CONTINUE
        return super()._handle_reward(context, config)

    def _capture_dokan_reward_if_visible(self, context: BattleContext | None = None) -> bool | None:
        reward_visible = self.appear(self.I_RYOU_DOKAN_BATTLE_OVER) or self.appear(self.I_UI_REWARD)
        if not reward_visible:
            if context is None:
                self._dokan_reward_captured_outside_battle = False
                self._dokan_reward_captured_context = None
                self._dokan_reward_captured_round = None
            return
        details_visible = (
            self.appear(self.I_REWARD_PARTICULARS)
            or self.appear(self.I_REWARD_PARTICULARS_ORCHI)
        )
        if details_visible:
            return
        if context is None:
            if getattr(self, '_dokan_reward_captured_outside_battle', False):
                return
        elif (getattr(self, '_dokan_reward_captured_context', None) is context
              and getattr(self, '_dokan_reward_captured_round', None) == context.continuous_count):
            return
        if not self._wait_for_dokan_reward_ready():
            return False
        if context is not None:
            self._dokan_reward_captured_context = context
            self._dokan_reward_captured_round = context.continuous_count
        self._dokan_reward_captured_outside_battle = True
        self._save_reward_image(context)
        return True

    def _wait_for_dokan_reward_ready(self) -> bool:
        """结算出现后等待一秒，重新截图并确认仍在奖励页面。"""
        logger.info("Waiting 1s before taking the dojo reward screenshot")
        sleep(DOKAN_REWARD_CAPTURE_DELAY)
        self.screenshot()
        reward_visible = self.appear(self.I_RYOU_DOKAN_BATTLE_OVER) or self.appear(self.I_UI_REWARD)
        return (reward_visible and not self.appear(self.I_REWARD_PARTICULARS)
                and not self.appear(self.I_REWARD_PARTICULARS_ORCHI))

    def _reward_screenshot_directory(self) -> Path:
        run_dir = getattr(self, '_dokan_reward_run_directory', None)
        if run_dir is not None:
            return run_dir
        profile = re.sub(r'[^\w-]', '_', str(self.config.config_name)).strip('_') or 'default'
        run_id = f"{datetime.now():%Y%m%d_%H%M%S_%f}_{uuid4().hex[:8]}"
        self._dokan_reward_run_directory = DOKAN_REWARD_SCREENSHOT_DIR / profile / run_id
        return self._dokan_reward_run_directory

    def _save_reward_image(self, context: BattleContext | None) -> None:
        try:
            screenshot_dir = self._reward_screenshot_directory()
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            battle_key = context.battle_key if context is not None else 'dokan_settlement'
            filename = f"{datetime.now():%Y%m%d_%H%M%S_%f}_{battle_key}.png"
            screenshot_file = screenshot_dir / filename
            self.device.image_save(screenshot_file)
            logger.info(f'Dokan reward screenshot saved: {screenshot_file}')
        except Exception as exc:
            logger.warning(f'Dokan reward screenshot failed: {exc}')

    def _push_current_run_reward_images(self) -> None:
        """Send this task run's screenshots together, then remove only sent files."""
        run_dir = getattr(self, '_dokan_reward_run_directory', None)
        if run_dir is None or not run_dir.exists():
            return
        screenshots = sorted(run_dir.glob('*.png'))
        if not screenshots:
            return
        try:
            images = [screenshot.read_bytes() for screenshot in screenshots]
            reward_summary = self._dokan_reward_blue_ticket_summary(images)
        except Exception as exc:
            logger.warning(f'Dokan reward screenshots could not be read: {exc}')
            return
        if not self.conf.dokan_config.push_reward_images:
            logger.info('Dokan reward screenshots kept because dojo notifications are disabled')
            return
        notifier = resolve_task_notifier(self.config, getattr(self.conf, 'notification_config', None))
        if not notifier.enable:
            logger.info('Dokan reward screenshots kept because notifications are disabled')
            return
        try:
            sent = notifier.push_images(images, title=f'{datetime.now():%Y-%m-%d} 道馆结算奖励',
                                        content=reward_summary)
        except Exception as exc:
            logger.warning(f'Dokan reward notification failed: {exc}')
            return
        if not sent:
            logger.warning(f'Dokan reward screenshots kept after failed notification: {run_dir}')
            return
        for screenshot in screenshots:
            try:
                screenshot.unlink()
            except OSError as exc:
                logger.warning(f'Cannot remove sent Dokan screenshot {screenshot}: {exc}')
        try:
            run_dir.rmdir()
        except OSError:
            pass

    def _dokan_reward_blue_ticket_summary(self, images: list[bytes]) -> str:
        """在任务结束后识别已保存的截图；识别失败仍推送原图。"""
        quantities = []
        details = []
        for index, image in enumerate(images, start=1):
            try:
                quantity = count_blue_tickets_in_png(image)
            except Exception as exc:
                logger.warning(f'Dokan blue ticket recognition failed for screenshot {index}: {exc}')
                quantity = None
            quantities.append(quantity)
            text = f'{quantity} 张' if quantity is not None else '数量未识别'
            details.append(f'截图 {index}：蓝票{text}')
            logger.info(f'Dokan reward screenshot {index}: blue tickets={quantity}')
        total = sum(quantity for quantity in quantities if quantity is not None)
        unknown_count = quantities.count(None)
        logger.info(f'Dokan reward blue tickets: total={total}, unrecognized screenshots={unknown_count}')
        if unknown_count:
            headline = f'蓝票已识别合计：{total} 张（另有 {unknown_count} 张截图数量未识别）'
        else:
            headline = f'蓝票合计：{total} 张'
        return '\n'.join([headline, *details])

    def _push_dokan_refresh_limit_notification(self) -> None:
        notifier = resolve_task_notifier(self.config, getattr(self.conf, 'notification_config', None))
        if not notifier.enable:
            logger.warning('Dokan refresh limit reached, but notifications are disabled')
            return
        try:
            notifier.push(
                title='道馆达到最大刷新次数',
                content=f'福利寮道馆已刷新{MAX_WELFARE_DOKAN_REFRESH_COUNT}次，仍未找到符合条件的道馆。任务已结束，今日不再重试。',
            )
        except Exception as exc:
            logger.warning(f'Dokan refresh limit notification failed: {exc}')

    def exit_battle(self, skip_first: bool = False) -> bool:
        """
            尝试退出战斗界面
            1. 普通战斗结束,连续点击即可退出
                a. 存在战斗奖励
                b. 战斗失败,
            2. 在战斗界面,但是战斗还未开始(右下角有准备按钮)
                需要点击左上角退出按钮,然后点击确定
            3. 馆主战斗过程中,寮友打败馆主,弹出框体,可点击空白区域取消该框体.
            综上,点击左上角退出按钮区域
        """
        logger.info("try to quit battle...")
        while True:
            self.screenshot()
            if self.appear(self.I_RYOU_DOKAN_CENTER_TOP):
                return True
            if self.appear(self.I_RYOU_DOKAN_QUIT_BATTLE_ENSURE):
                self.ui_click_until_disappear(self.I_RYOU_DOKAN_QUIT_BATTLE_ENSURE)
                return True
            self.screenshot()
            if not self.appear(self.I_RYOU_DOKAN_CENTER_TOP):
                self.click(self.C_DOKAN_BATTLE_QUIT_AREA, interval=3)
                continue
            self.wait_until_appear(self.I_RYOU_DOKAN_CENTER_TOP, True, 3)
        return False

    def before_run(self):
        self.dokan_owner_battle = False
        self.switch_member_soul_done = False
        self.attack_priority_selected = False
        self.found_dokan_cnt = 0
        self.second_dokan_ready = False
        self._dokan_reward_captured_context = None
        self._dokan_reward_captured_round = None
        self._dokan_reward_captured_outside_battle = False
        self._dokan_reward_run_directory = None
        pages.page_dokan_rank = self.navigator.add_page(pages.Page(self.I_RYOU_DOKAN_TOPPA_RANK, priority=75, register=False))
        pages.page_dokan_rank.connect(pages.page_dokan, pages.random_click, key="page_dokan_rank->page_dokan")

    def run(self):
        self.before_run()
        self.conf = self.config.model.dokan
        qq_settings = getattr(self.conf, 'qq_message_config', QQMessageConfig())
        if qq_settings.qq_message_enable and not QQDokanState(self.config.config_name).flags(qq_settings)[0]:
            logger.info('尚未确认今天开启福利寮，等待下次检测')
            self.set_next_run(task='Dokan', target=datetime.now() + timedelta(seconds=qq_settings.qq_poll_interval))
            raise TaskEnd
        if self.conf.dokan_config.monday_to_thursday and datetime.now().weekday() >= 4:
            logger.warning("weekend, exit")
            self.next_run(True)
            raise TaskEnd
        # 清空历史次数，首次进入筛选页面后读取游戏实际剩余次数。
        self.conf.attack_count_config.init_attack_count(callback=self.config.save)
        unknown_page_timer = Timer(10)
        self.goto_page(pages.page_dokan_map)
        refresh_limit_reached = False
        try:
            while True:
                self.screenshot()
                self._capture_dokan_reward_if_visible()
                current_page = self.get_current_page()
                match current_page:
                    case None:
                        self.device.click_record_clear()
                        self.device.stuck_record_clear()
                        time.sleep(0.5)
                    case pages.page_dokan_map:
                        self.run_on_dokan_map()
                    case pages.page_dokan:
                        self.run_on_dokan()
                    case pages.page_battle_prepare | pages.page_battle:
                        self.run_on_battle()
                    case pages.page_battle_result:
                        self.click(pages.random_click(ltrb=(False, False, True, False)), interval=1.5)
                    case _:
                        if not unknown_page_timer.started():
                            unknown_page_timer.start()
                        if unknown_page_timer.started() and unknown_page_timer.reached():  # 10秒都是非道馆界面, 则尝试回到道馆
                            unknown_page_timer = Timer(10)
                            self.goto_page(pages.page_dokan)
        except DokanFinishedError:
            is_dokan_activated = True
        except DokanRefreshLimitError:
            is_dokan_activated = False
            refresh_limit_reached = True
        except DokanNotStartedError:
            is_dokan_activated = False
        self.goto_page(pages.page_main)
        self.next_run(skip_today=refresh_limit_reached, is_dokan_activated=is_dokan_activated)
        self._push_current_run_reward_images()
        if refresh_limit_reached:
            self._push_dokan_refresh_limit_notification()
        raise TaskEnd

    def run_on_dokan(self):
        """道馆页面逻辑处理"""
        self.prepare_appear_cache([
            self.I_RYOU_DOKAN_GATHERING,
            self.I_RYOU_DOKAN_MASTER_BATTLE,
            self.I_RYOU_DOKAN_START_CHALLENGE,
            self.I_RYOU_DOKAN_CD,
            self.I_RYOU_DOKAN_ABANDONED_TOPPA_ABANDONED,
            self.I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY,
            self.I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN,
            self.I_RYOU_DOKAN_TODAY_ATTACK_COUNT,
            self.I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_DONE,
            self.I_DOKAN_BOSS_WAITING
        ])
        self.device.stuck_record_clear()
        if self.appear(self.I_RYOU_DOKAN_GATHERING):  # 正在集结
            logger.debug(f"Dokan is gathering...")
            self.switch_priority()  # 选择优先级
            self.switch_soul_in_dokan()  # 切换馆员御魂
            self.device.click_record_clear()
            return
        if self.appear(self.I_DOKAN_BOSS_WAITING) or self.appear(self.I_RYOU_DOKAN_MASTER_BATTLE):  # 馆主战标识
            self.dokan_owner_battle = True
        if self.dokan_owner_battle:
            self.skip_owner_and_battle_again()
            return
        if not self.appear(self.I_DOKAN_BOSS_WAITING) and self.appear(self.I_RYOU_DOKAN_START_CHALLENGE):  # 可挑战
            self.switch_soul_in_dokan()  # 防止进来晚了错过集结阶段的御魂切换
            if self.click_until_in_battle():
                self.run_general_battle(self.conf.dokan_member_battle_conf, battle_key='dokan_member')
            return
        if not self.appear(self.I_DOKAN_BOSS_WAITING) and self.appear(self.I_RYOU_DOKAN_CD):  # 可观战
            self.device.click_record_clear()
            return
        if (self.appear(self.I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY)
                or self.appear(self.I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN)
                or self.appear(self.I_RYOU_DOKAN_ABANDONED_TOPPA_ABANDONED)
                or self.appear(self.I_RYOU_DOKAN_TODAY_ATTACK_COUNT)
                or self.appear(self.I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_DONE)):
            self.skip_owner_and_battle_again()

    def click_until_in_battle(self) -> bool:
        """点击挑战直到进入战斗"""
        timeout_timer = Timer(5).start()
        while True:
            self.screenshot()
            if self.is_in_battle(False):
                return True
            if timeout_timer.reached():
                break
            self.appear_then_click(self.I_RYOU_DOKAN_START_CHALLENGE, interval=2)
        return False

    def run_on_dokan_map(self):
        """道馆地图页面逻辑处理"""
        if self.appear(self.I_RYOU_DOKAN_FINDING_DOKAN):  # 道馆未开启
            retrying_skipped_owner = self.second_dokan_ready
            if self.found_dokan_cnt > 0 and not retrying_skipped_owner:
                raise DokanNotStartedError
            if retrying_skipped_owner and self.found_dokan_cnt >= 2:
                raise DokanFinishedError
            remaining = self.update_remain_attack_count()
            if remaining < 0:
                logger.warning('未识别到道馆剩余次数，结束本次筛选')
                raise DokanNotStartedError
            if remaining == 0:
                logger.info('游戏显示道馆剩余0次，结束任务')
                raise DokanFinishedError
            if not retrying_skipped_owner and not self.ensure_dokan_created():
                logger.warning('Create Dokan failed, stop before selecting a target')
                raise DokanNotStartedError
            self.second_dokan_ready = False
            # 寻找合适道馆,找不到直接退出
            if not self.find_dokan():
                raise DokanNotStartedError
            # 寻找到道馆后等一会页面刷新
            self.wait_until_appear(self.I_RYOU_DOKAN_CENTER_TOP, True, 5)
            return
        if self.appear(self.I_RYOU_DOKAN_FOUND_DOKAN):  # 道馆已开启
            self.goto_page(pages.page_dokan)  # 跳转到道馆

    def run_on_battle(self):
        """处理战斗页面逻辑(正常来说是一定不会进入该逻辑的)"""
        if self.appear(self.I_RYOU_DOKAN_BATTLE_MASTER_FIRST) or \
                self.appear(self.I_RYOU_DOKAN_BATTLE_MASTER_SECOND):
            self.dokan_owner_battle = True
            self.run_general_battle(self.build_quick_exit_config(self.conf.dokan_member_battle_conf),
                                    battle_key='dokan_member')
            return
        self.run_general_battle(self.conf.dokan_member_battle_conf, battle_key='dokan_member')

    def switch_priority(self):
        """选择优先级"""
        if self.attack_priority_selected:
            return
        self.goto_page(pages.page_dokan_priority)
        self.goto_page(pages.page_dokan)
        self.attack_priority_selected = True

    def find_dokan(self) -> bool:
        """只挑战带“鑫”图标且符合防守人数要求的福利寮。"""
        self.found_dokan_cnt += 1
        configured_refresh_count = self.config.dokan.dokan_config.find_dokan_refresh_count
        num_fresh = 0
        # 赏金图标仅用于定位列表项，不读取赏金或计算系数。
        backup = {'i_point_bounty': self.I_RIGHTPAD_POINT_BOUNTY.roi_back,
                  'i_point_people_num': self.I_CENTER_POINT_PEOPLE_NUMBER.roi_back,
                  'i_xin_icon': self.I_RIGHTPAD_XIN_ICON.roi_back}

        def restore_roi():
            self.I_RIGHTPAD_POINT_BOUNTY.roi_back = backup['i_point_bounty']
            self.I_CENTER_POINT_PEOPLE_NUMBER.roi_back = backup['i_point_people_num']
            self.I_RIGHTPAD_XIN_ICON.roi_back = backup['i_xin_icon']

        def find_challengeable():
            restore_roi()
            self.screenshot()
            candidates = self.find_all_element(self.I_RIGHTPAD_POINT_BOUNTY, (0, 0, 0, 50))
            logger.info(f'find elements list:{candidates}')
            for idx, item in enumerate(candidates):
                self.device.click_record_clear()
                logger.info(f"------start no.{idx} =={item}-----------")
                self.screenshot()
                while self.appear(self.I_CENTER_CHALLENGE):
                    self.click(self.C_DOKAN_CANCEL_SELECT_DOKAN, interval=1.5)
                    self.wait_animate_stable(self.C_DOKAN_CANCEL_SELECT_DOKAN_CHECK_ANIMATE,
                                             interval=0.5, timeout=1.5)
                self.I_RIGHTPAD_XIN_ICON.roi_back = (item[0] - 15, max(0, item[1] - 90), 100, 95)
                self.screenshot()
                if not self.appear(self.I_RIGHTPAD_XIN_ICON):
                    logger.info(f"skip dojo without Xin emblem: idx={idx} item={item}")
                    continue
                self.I_RIGHTPAD_POINT_BOUNTY.roi_back = position_offset(item, (-10, -10, 20, 20))
                if not self.ui_click_until_appear_or_timeout(self.I_RIGHTPAD_POINT_BOUNTY, self.I_CENTER_CHALLENGE,
                                                             interval=1.5, timeout=8):
                    logger.info(f"can't find challenge button,idx={idx} item={item}")
                    continue
                self.screenshot()
                if not self.appear(self.I_CENTER_POINT_PEOPLE_NUMBER):
                    logger.warning(f"can't find point people number image, item={item}")
                    continue
                self.O_DOKAN_CENTER_PEOPLE_NUMBER.roi = position_offset(
                    self.I_CENTER_POINT_PEOPLE_NUMBER.roi_front, (0, 0, 0, 30))
                people = self.O_DOKAN_CENTER_PEOPLE_NUMBER.detect_text(self.device.image)
                match = re.search(r"(\d+)", people)
                if not match:
                    logger.warning(f"can't find people number in ocr result,item={item}, people={people}")
                    continue
                people = float(match.group())
                min_people_num = self.config.dokan.dokan_config.min_people_num
                if num_fresh > configured_refresh_count:
                    min_people_num /= 2
                if people < min_people_num:
                    logger.info(f"welfare guild people num too small: {people} < {min_people_num}")
                    continue
                logger.info(f"find welfare guild: people_num:{people}")
                return True
            return False

        try:
            while num_fresh < MAX_WELFARE_DOKAN_REFRESH_COUNT:
                for _ in range(3):
                    sleep(3)
                    if find_challengeable():
                        logger.info("find challengeable welfare dokan")
                        self.ui_click(self.I_CENTER_CHALLENGE, self.I_CHALLENGE_ENSURE, interval=1)
                        self.ui_click_until_disappear(self.I_CHALLENGE_ENSURE, interval=1)
                        self.config.dokan.attack_count_config.del_attack_count(1, self.config.save)
                        return True
                    self.swipe(self.S_DOKAN_LIST_UP)
                restore_roi()
                logger.info("=========refresh dokan list=========")
                self.ui_click(self.C_DOKAN_REFRESH, self.I_REFRESH_ENSURE, interval=1)
                self.ui_click_until_disappear(self.I_REFRESH_ENSURE, interval=1)
                num_fresh += 1
                logger.info("Refresh Done")
                if num_fresh == configured_refresh_count + 1:
                    logger.info('Welfare guild minimum defender count reduced by half')
            logger.warning(f'No eligible Xin-emblem dojo after {num_fresh} refreshes')
            raise DokanRefreshLimitError
        finally:
            restore_roi()

    def ensure_dokan_created(self) -> bool:
        """灰色按钮表示已建立道馆；可点击时先完成建立，再开始筛选。"""
        for attempt in range(1, 3):
            self.screenshot()
            if self.appear(self.I_RYOU_DOKAN_CREATE_DOKAN_ENSURE):
                return self.creat_dokan()

            button = next((item for item in (
                self.I_RYOU_DOKAN_CREATE_DOKAN, self.I_RYOU_DOKAN_HAVE_DOKAN
            ) if self.appear(item)), None)
            if button is None:
                logger.warning(
                    f'Dokan create/have marker not recognized: '
                    f'attempt={attempt}/2'
                )
                sleep(0.5)
                continue

            # 两个按钮的轮廓相同，模板相关性超过 0.96，必须额外区分颜色。
            # 只取图标中央，避开彩色地图背景和底部文字。
            x, y, w, h = button.roi_front
            icon = self.device.image[
                y + h // 4:y + 3 * h // 4,
                x + w // 4:x + 3 * w // 4,
                :3,
            ]
            if icon.size == 0:
                continue
            mean_chroma = float((icon.max(axis=2) - icon.min(axis=2)).mean())
            if mean_chroma < 10:
                logger.info('Dokan create button is grey; own Dokan already exists, start selecting a target')
                return True

            logger.info(f'Create Dokan before selecting a target: attempt={attempt}/2')
            self.click(button)

            if self.wait_until_appear(
                    self.I_RYOU_DOKAN_CREATE_DOKAN_ENSURE,
                    True,
                    3,
            ):
                logger.info('Create Dokan dialog opened')
                return self.creat_dokan()

        logger.warning(
            'Could not confirm that own Dokan exists or create it; '
            'stop before selecting a target'
        )
        return False

    def creat_dokan(self) -> bool:
        # 点击创建道馆
        # 当 成功建立道馆并关闭道馆信息窗口后退出
        #  或 点击创建道馆按钮无反应(道馆已经建立的情况下),5秒后退出
        while True:
            self.screenshot()
            if self.appear(self.I_RYOU_DOKAN_DOKAN_INFO_CLOSE):
                self.ui_click_until_disappear(self.I_RYOU_DOKAN_DOKAN_INFO_CLOSE)
                logger.info("Create Dokan Success")
                return True
            if self.appear(self.I_RYOU_DOKAN_CREATE_DOKAN_ENSURE):
                self.ui_click_until_appear_or_timeout(self.I_RYOU_DOKAN_CREATE_DOKAN_ENSURE,
                                                      stop=self.I_RYOU_DOKAN_DOKAN_INFO_CLOSE, interval=2, timeout=10)
                continue
            if self.ui_click_until_appear_or_timeout(self.I_RYOU_DOKAN_CREATE_DOKAN,
                                                     self.I_RYOU_DOKAN_CREATE_DOKAN_ENSURE, 2, 10):
                continue
            return False

    def find_all_element(self, item, offset: tuple) -> list[tuple[int, int, int, int]]:
        """
        NOTE: 仅适配查找道馆列表
        在当前对象中查找所有匹配的项目，并返回它们的信息列表。

        此函数的目的是通过循环搜索和匹配给定的项目，并将匹配的项目信息存储到一个列表中。
        如果项目出现，则将其添加到列表中，并根据预定义的规则调整项目的位置。

        参数:
        - item: 需要查找的项目。
        - offset: 如果当前区域查找不到,扩大查找区域的大小

        返回值:
        返回一个包含所有匹配项目信息的列表。
        """
        res_list = []
        while 1:
            if (item.roi_back[0] + item.roi_back[2] > (1280 + offset[2])) or (
                    item.roi_back[1] + item.roi_back[3] > (720 + offset[3])):
                break
            if self.appear(item):
                res_list.append(item.roi_front.copy())
                # 刷新搜索区域,使用上个搜索结果的Y坐标作为起始点的Y坐标,搜索结果的高度作为起始搜索高度
                item.roi_back = position_offset(item.roi_back, (
                    0, item.roi_front[1] + item.roi_front[3] - item.roi_back[1], 0,
                    item.roi_front[3] - item.roi_back[3]))
            item.roi_back = position_offset(item.roi_back, offset)
        return res_list

    def update_remain_attack_count(self) -> int:
        """
        根据道馆地图界面 或 打完道馆后 的寮境界面,更新配置信息
        @return:
        @rtype:
        """
        self.screenshot()
        count = -1
        if self.appear(self.I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_ZERO) or self.appear(
                self.I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_DONE):
            logger.info("I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_ZERO/DONE found")
            count = 0
        elif self.appear(self.I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_ONE):
            logger.info("I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_ONE found")
            count = 1
        elif self.appear(self.I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_TWO):
            logger.info("I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_TWO found")
            count = 2
        else:
            logger.info("dont find REMAIN_ATTACK_COUNT PIC")
            count = -1
        self.config.dokan.attack_count_config.set_attack_count(count, self.config.save)
        return count

    def skip_owner_and_battle_again(self) -> bool:
        """馆主阶段放弃突破；有第二次机会时再战，否则保留赏金。"""
        can_retry = self.can_battle_again()
        remaining = None
        retry_wait_logged = False
        timeout = Timer(15).start()
        while not timeout.reached():
            self.screenshot()
            settlement_visible = (self.appear(self.I_RYOU_DOKAN_TODAY_ATTACK_COUNT)
                                  or self.appear(self.I_RYOU_DOKAN_REMAIN_ATTACK_COUNT_DONE))
            if settlement_visible and (remaining is None or remaining < 0):
                remaining = self.update_remain_attack_count()
                can_retry = self.can_battle_again()
            # 投票控件优先于今日次数提示，第一次放弃后该提示也会出现。
            if can_retry and self.appear(self.I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN):
                if self.appear_then_click(self.I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN, interval=1):
                    self.wait_until_disappear(self.I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN, timeout=3)
                    self.screenshot()
                    if not self.appear(self.I_RYOU_DOKAN_FAILED_VOTE_BATTLE_AGAIN):
                        logger.info("Skipped owner battle and selected Battle Again")
                        self.wait_for_next_dokan_selection()
                        return True
            elif not can_retry and self.appear(self.I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY):
                if self.appear_then_click(self.I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY, interval=1):
                    self.wait_until_disappear(self.I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY, timeout=3)
                    self.screenshot()
                    if not self.appear(self.I_RYOU_DOKAN_FAILED_VOTE_KEEP_BOUNTY):
                        self.dokan_owner_battle = False
                        logger.info("Skipped owner battle and kept the bounty on the last attempt")
                        return True
            elif self.appear(self.I_RYOU_DOKAN_TOPPA_RANK):
                self.click(self.C_DOKAN_TOPPA_RANK_CLOSE_AREA, interval=1)
            elif (self.appear(self.I_DOKAN_ABANDONED_TOPPA_TITLE)
                  and self.appear(self.I_RYOU_DOKAN_ABANDONED_TOPPA_ABANDONED)):
                self.appear_then_click(self.I_RYOU_DOKAN_ABANDONED_TOPPA_ABANDONED, interval=1)
            elif settlement_visible:
                if remaining < 0 or can_retry:
                    if not retry_wait_logged:
                        logger.info(f"Dokan has {remaining} remaining attempt(s); waiting for the Battle Again vote")
                        retry_wait_logged = True
                    # 本次已结束，等待投票出现，不能重新点击放弃突破。
                else:
                    self.dokan_owner_battle = False
                    logger.info("Dokan challenge ended while skipping owner battle")
                    raise DokanFinishedError
            elif self.appear(self.I_DOKAN_ABANDONED_TOPPA_ENSURE):
                self.appear_then_click(self.I_DOKAN_ABANDONED_TOPPA_ENSURE, interval=1)
            elif self.appear(self.I_DOKAN_ABANDONED_TOPPA_RIGHT):
                self.appear_then_click(self.I_DOKAN_ABANDONED_TOPPA_RIGHT, interval=1)
            elif self.appear(self.I_DOKAN_ABANDONED_TOPPA):
                self.appear_then_click(self.I_DOKAN_ABANDONED_TOPPA, interval=1)
            sleep(0.5)
        logger.warning("Skip owner battle timed out before voting")
        return False

    def can_battle_again(self) -> bool:
        """以游戏识别的剩余次数决定再战，单次任务最多挑战两馆。"""
        attack_count = self.conf.attack_count_config
        return attack_count.remain_attack_count > 0 and self.found_dokan_cnt < 2

    def wait_for_next_dokan_selection(self) -> None:
        """再战后回庭院等待70～90秒，再进入道馆进行第二次筛选。"""
        logger.info("道馆再战：返回庭院")
        self.goto_page(pages.page_main)
        wait_seconds = uniform(*DOKAN_NEXT_SELECTION_WAIT_RANGE)
        logger.info(f"道馆再战：在庭院等待 {wait_seconds:.1f} 秒")
        self.device.stuck_record_clear()
        self.device.stuck_record_add('PAUSE')
        try:
            sleep(wait_seconds)
        finally:
            self.device.stuck_record_clear()
        logger.info("道馆再战：等待结束，重新进入道馆")
        self.goto_page(pages.page_dokan_map)
        self.dokan_owner_battle = False
        self.attack_priority_selected = False
        self.second_dokan_ready = True

    def switch_soul_in_dokan(self):
        """本次任务仅切换一次馆员御魂，第二次道馆沿用。"""
        if self.switch_member_soul_done:
            return
        logger.hr('Start switch soul', 2)
        switch_soul = self.config.dokan.dokan_member_switch_soul
        if switch_soul.enable:
            self.goto_page(pages.page_shikigami_records)
            self.run_switch_soul(switch_soul.switch_group_team)
            self.goto_page(pages.page_dokan)
        elif switch_soul.enable_switch_by_name:
            self.goto_page(pages.page_shikigami_records)
            self.run_switch_soul_by_name(switch_soul.group_name, switch_soul.team_name)
            self.goto_page(pages.page_dokan)
        else:
            logger.info('Skip switch soul')
        self.switch_member_soul_done = True

    def next_run(self, skip_today=False, is_dokan_activated=False):
        """
            设置下次运行时间
            该函数假定道馆时间设置为:每天固定时间尝试开启(例如:19:00),成功后设置为明天固定时间(例如19:00)
                                失败则在短时间(例如:2分钟)内再次尝试开启道馆任务
            此假定应该符合绝大多数人需求,如果存在其他需求,,,help yourself

        @param skip_today: 是否跳过今天,True->当作当天的道馆已成功打掉,False->无效
                            为了跳过周五->周天
        @type skip_today: bool
        @param is_dokan_activated:
        @type is_dokan_activated: bool
        @return:
        @rtype:
        """
        now = datetime.now()
        run_time: Time = self.config.model.dokan.dokan_config.dokan_run_time
        run_time_dt = datetime.combine(now.date(), run_time)
        if skip_today:
            if self.conf.dokan_config.monday_to_thursday and now.weekday() >= 4:  # 直接设置下周一的道馆时间
                self.set_next_run(task="Dokan",
                                  target=datetime.combine(now.date() + timedelta(days=7 - now.weekday()), run_time))
                return
            self.set_next_run(task="Dokan", target=datetime.combine(now.date() + timedelta(days=1), run_time))
            return
        # 道馆没有开启
        if not is_dokan_activated:
            # 在服务器时间之前,设置为服务器时间
            if now < run_time_dt:
                self.set_next_run(task="Dokan", target=run_time_dt)
                return
            # 在服务器时间之后,如超过1小时,则直接当作成功;未超过则当作失败
            if now - run_time_dt > timedelta(hours=1):
                self.set_next_run(task="Dokan",
                                  target=datetime.combine(now.date() + timedelta(days=1), run_time))
                return
            # 时间在道馆开启时间附近，failure_interval后执行
            self.set_next_run(task="Dokan", target=now + self.config.dokan.scheduler.failure_interval)
            return
        # 道馆已开启
        # 如果打两次,当前是第一次,设置为failure_interval后运行
        if self.config.dokan.attack_count_config.remain_attack_count == 1:
            self.set_next_run(task="Dokan", target=now + self.config.dokan.scheduler.failure_interval)
            return
        # 其余情况当作成功
        self.set_next_run(task="Dokan", target=datetime.combine(now.date() + timedelta(days=1), run_time))

if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('日常1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.run()
