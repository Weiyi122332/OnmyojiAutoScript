# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import random
import time
from datetime import datetime

from module.atom.image import RuleImage

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.QuickLoadout.config import QuickLoadoutConfig, QuickLoadoutMode
from tasks.MetaDemon.quick_loadout import FrameQuickLoadout
from tasks.GameUi.game_ui import GameUi
from tasks.MetaDemon.config import (
    BossType, MetaDemon, MetaDemonBattlePreset, MetaDemonRentalLineup,
    PRESET_GROUPS, SPECIAL_BOSS_PRESETS,
)
from tasks.MetaDemon.assets import MetaDemonAssets
from tasks.MetaDemon.synthesis import parse_synthesis_material_level
from tasks.MetaDemon.ticket_stars import recognize_boss_stars, recognize_summon_preview, recognize_ticket_stars
import tasks.MetaDemon.page as ipages

from module.logger import logger
from module.exception import MetaDemonError, ScriptError, TaskEnd


RENTAL_LINEUP_NAMES = {
    MetaDemonRentalLineup.GROUP: '群体',
    MetaDemonRentalLineup.SINGLE: '单体',
    MetaDemonRentalLineup.NORMAL_ATTACK: '普攻',
}


class BossBattle(GeneralBattle, FrameQuickLoadout, GameUi, MetaDemonAssets):
    """超鬼王"""

    class State:
        done: bool = False
        synthesis_done: bool = False

    conf: MetaDemon = None
    cur_boss_type: BossType = None
    total_count: int = 0
    _current_boss_attempts: int = 0
    _active_preset: MetaDemonBattlePreset | None = None

    def _quick_loadout_fight(self, frame):
        return super()._quick_loadout_fight(
            frame, fight_file='./tasks/MetaDemon/md/md_quick_loadout_frame_fight.png',
        )

    @property
    def enable_powerful_fire(self) -> bool:
        return (self._active_preset is not None
                and self._current_boss_attempts < self._active_preset.powerful_count)

    def before_run(self):
        ipages.configure_activity_navigation(self.navigator)
        self.State = BossBattle.State()
        self._active_preset = None
        self._last_quick_loadout = None
        self.cur_boss_type = None
        self.total_count = 0
        self._current_boss_attempts = 0
        self.conf = self.config.meta_demon
        if self.conf.scheduler.waiting_for_fatigue:
            with self.config.lock_config:
                self.conf.scheduler.waiting_for_fatigue = False
                self.config.save()

    def run(self):
        try:
            self._run_boss_queue()
        except TaskEnd:
            raise
        except Exception as exc:
            # 任务组只知道外层任务名，用专用异常保留超鬼王的停止策略。
            raise MetaDemonError(str(exc)) from exc

    def _run_boss_queue(self):
        self.before_run()
        self.goto_page(ipages.page_meta_demon_boss)
        while not self.State.done:
            self.screenshot()
            current_page = self.get_current_page()
            match current_page:
                case ipages.page_activity:
                    self.goto_page(ipages.page_meta_demon_boss)
                case ipages.page_meta_demon_boss:
                    if not self.check_and_prepare_battle():
                        if self.State.done:
                            break
                        raise ScriptError('超鬼王：战斗准备失败，召唤队列尚未完成')
                    if not self.start_battle() and not self.appear(self.I_MD_SETTLING):
                        raise ScriptError('超鬼王：未能进入战斗，且未检测到结算状态')
                case ipages.page_battle:
                    self.battle_wait(False)
                case ipages.page_reward:
                    self.click(ipages.reward_random_click(), interval=0.6)
                case ipages.page_battle_result:
                    self.click(ipages.random_click(), interval=0.6)
                case _:
                    time.sleep(random.uniform(0.7, 1.4))
        if self.State.done and self.total_count > 0:
            self.push_targets_finished()
        self.set_next_run(task='MetaDemon', success=self.State.done)
        self.finish_task()

    def push_targets_finished(self):
        content = '已打完召唤队列中的鬼王'
        logger.info(content)
        try:
            notifier = self.config.notifier
            if notifier.enable and not notifier.push(title='超鬼王挑战完成', content=content):
                logger.warning('超鬼王完成通知发送失败')
        except Exception as exc:
            logger.warning(f'超鬼王完成通知发送失败：{exc}')

    def start_battle(self):
        if self.cur_boss_type is None or self._active_preset is None:
            raise ScriptError('超鬼王：当前鬼王星级或快速预设尚未确认，无法开始战斗')
        logger.hr('Click fire, start battle')
        while True:
            self.screenshot()
            if self.is_in_battle(False):
                self.total_count += 1
                self._current_boss_attempts += 1
                self.run_general_battle(
                    GeneralBattleConfig(),
                    battle_key='meta_demon',
                )
                return True
            if self.appear(self.I_MD_DRINK_TEA_FREE, interval=1.2):
                self.click(self.I_MD_DRINK_TEA_FREE)  # 花合战每日首次免费，不受喝茶开关限制
                continue
            if self.appear(self.I_MD_DRINK_TEA, interval=1.2):  # 出现付费喝茶弹窗
                if self.conf.meta_demon_config.auto_tea:
                    self.click(self.I_MD_DRINK_TEA)  # 喝茶
                    continue
                # 不喝茶则结束任务安排下一次运行
                self.ui_click_until_disappear(self.I_MD_CLOSE_POPUP, interval=0.6)
                self.wait_for_fatigue()
            if self.appear(self.I_MD_SETTLING):
                return False
            self.appear_then_click(self.I_MD_FIRE, interval=0.8)

    def battle_wait(self, random_click_swipt_enable: bool) -> bool:
        self.device.stuck_record_add('BATTLE_STATUS_S')
        self.device.click_record_clear()
        logger.info(f"Start battle process on {self.cur_boss_type.name if self.cur_boss_type else 'None'}")
        win = False
        while True:
            self.screenshot()
            if self.appear(self.I_MD_SUMMON_BOSS, interval=0.8) or \
                    self.appear(self.I_MD_SWITCH_TICKET, interval=0.8) or \
                    self.appear(self.I_MD_FIRE, interval=0.8):
                break
            if self.appear(self.I_WIN, interval=0.8):
                win = True
                self.click(ipages.random_click())
                continue
            if self.appear(self.I_FALSE, interval=0.8):
                win = False
                self.click(ipages.random_click())
                continue
            if self.appear(self.I_MD_SETTLING, interval=3.5):
                logger.info('wait result')
                time.sleep(random.uniform(3, 5))
                continue
        logger.info(f'battle win: {win}')
        logger.info(f'battle count: {self.total_count}')
        return win

    def check_and_prepare_battle(self) -> bool:
        """确认鬼王星级后准备战斗。"""
        logger.hr('battle prepare', 2)
        return (self.summon_boss() and self.check_fatigue() and self.prepare_boss_preset()
                and self.check_and_switch_powerful())

    def synthesis_boss_ticket(self):
        """合成鬼王"""
        if self.State.synthesis_done:
            return
        logger.hr('synthesis boss ticket')
        self.State.synthesis_done = True
        if len(self.conf.meta_demon_config.synthesis_list_v) <= 0:
            return
        type_ticket_dict: dict[BossType, tuple[RuleImage, int]] = {
            BossType.ONE_STAR: (self.I_MD_SYNTHESIS_ONE_STAR, 3),
            BossType.TWO_STARS: (self.I_MD_SYNTHESIS_TWO_STAR, 3),
            BossType.THREE_STARS: (self.I_MD_SYNTHESIS_THREE_STAR, 3),
            BossType.FOUR_STARS: (self.I_MD_SYNTHESIS_FOUR_STAR, 3),
            BossType.FIVE_STARS: (self.I_MD_SYNTHESIS_FIVE_STAR, 2),
        }
        synthesis_list = self.conf.meta_demon_config.synthesis_list_v
        self.ui_click(self.I_MD_SYNTHESIS, self.I_MD_START_SYNTHESIS, interval=0.6)
        for boss_type in synthesis_list:
            self.do_synthesis(type_ticket_dict[boss_type][0], type_ticket_dict[boss_type][1], boss_type)
        self.ui_click(self.I_MD_CLOSE_POPUP, self.I_MD_SHIKIGAMI, interval=0.6)  # 关闭弹窗退回到鬼王界面

    def do_synthesis(self, target_boss_ticket: RuleImage, need_ticket: int, material_level: BossType):
        """开始合成鬼王
        :param target_boss_ticket: 目标鬼王级别门票
        :param need_ticket: 合成当前级别鬼王需要的门票数量
        :param material_level: 配置要求消耗的材料星级，必须与标题 OCR 换算结果一致
        """
        if not self.ticket_matches_star(target_boss_ticket, material_level, synthesis=True):
            logger.info(f'{target_boss_ticket} not recognized, skip synthesis')
            return
        click_cnt, max_cnt = 0, random.randint(2, 3)
        verification_failures = 0
        while True:
            self.screenshot()
            if self.appear(self.I_MD_SYNTHESIS_NEED_MONEY, interval=0.8):  # 出现花钱购买合成券
                self.ui_click(self.I_MD_CLOSE_POPUP, self.I_MD_START_SYNTHESIS, interval=0.6)  # 关闭购买弹窗
                break
            if self.appear(self.I_UI_REWARD, interval=0.8):  # 出现获得奖励说明合成成功
                self.click(ipages.random_click(), interval=0.6)
                click_cnt = 0  # 清空点击标志
                continue
            if self.appear(self.I_MD_SYNTHESIS_EMPTY, interval=0.8):  # 有空位
                empty_list = self.I_MD_SYNTHESIS_EMPTY.match_all_any(self.device.image, frame_id=self.device.image_frame_id)
                if len(empty_list) < need_ticket:  # 空位数量小于需要的门票数量->门票不够则退出
                    logger.info(f'{target_boss_ticket} ticket not enough, skip synthesis')
                    break
            if click_cnt >= max_cnt:
                raise ScriptError('超鬼王：多次点击合成后仍未出现奖励，无法确认合成结果')
            if not self.ticket_matches_star(target_boss_ticket, material_level, synthesis=True):
                logger.info('合成材料未通过底部星级复核，跳过本星级')
                break
            if self.click(target_boss_ticket, interval=2):
                # 选中后重新截图，不能拿点击之前的标题验证。
                time.sleep(0.3)
                self.screenshot()
                title = self.O_SYNTHESIS_LEVEL.ocr(self.device.image)
                detected_level = parse_synthesis_material_level(title)
                if detected_level != int(material_level):
                    verification_failures += 1
                    logger.warning(
                        f'合成星级验证失败: 标题={title!r}, 材料星级={detected_level}, '
                        f'要求={int(material_level)}, 重试={verification_failures}/3'
                    )
                    if verification_failures >= 3:
                        raise ScriptError('超鬼王：连续三次无法确认目标合成星级')
                    continue
                verification_failures = 0
                if self.appear_then_click(self.I_MD_START_SYNTHESIS, interval=2.5):  # 点击开始合成
                    click_cnt += 1
                continue
        logger.info(f'{target_boss_ticket} synthesis done')

    def check_fatigue(self):
        logger.hr('Check fatigue')
        current, remain, total = self.O_MD_FATIGUE.ocr_digit_counter(self.device.image)
        # 不喝茶且当前疲劳度已满
        if not self.conf.meta_demon_config.auto_tea and (current > total or remain < 0):
            self.wait_for_fatigue()
        return True

    def wait_for_fatigue(self):
        """疲劳等待使用独立恢复时间，不对齐常规 cron 或随机浮动。"""
        self.config.reload()
        scheduler = self.config.meta_demon.scheduler
        next_run = (datetime.now() + scheduler.wait_interval).replace(microsecond=0)
        with self.config.lock_config:
            scheduler.next_run = next_run
            scheduler.waiting_for_fatigue = True
            self.config.save()
        logger.info(f'超鬼王等待疲劳恢复，下次运行：{next_run}（不受 cron 影响）')
        self.finish_task()

    def next_summon_star(self) -> BossType | None:
        if not self.appear(self.I_MD_SWITCH_TICKET):
            return None
        stars = recognize_summon_preview(self.device.image, self.I_MD_SWITCH_TICKET.roi_front)
        return BossType(stars) if stars is not None else None

    def current_boss_star(self) -> BossType | None:
        stars = recognize_boss_stars(self.device.image)
        return BossType(stars) if stars is not None else None

    def summon_boss(self) -> bool:
        """按主页显示的下一只星级直接召唤。"""
        pending_star = None
        checking_empty = False
        deadline = time.monotonic() + 25
        settle_until = 0.0
        while time.monotonic() < deadline:
            self.screenshot()
            if self.appear(self.I_MD_FIRE):
                if pending_star is not None or self.cur_boss_type is None:
                    # 重启后没有召唤记录，仍可从已有鬼王的头像下恢复星级。
                    star = self.current_boss_star() or pending_star
                    if star is None:
                        continue
                    self.current_count = 0
                    self.cur_boss_type = star
                    self._current_boss_attempts = 0
                    self._active_preset = None
                    logger.info(f'已确认当前 {int(star)} 星鬼王')
                return True

            if pending_star is None and self.appear(self.I_MD_TICKET_EMPTY):
                self.State.done = True
                logger.info('召唤队列无门票')
                self.appear_then_click(self.I_MD_CLOSE_POPUP, interval=0.8)
                return False

            if time.monotonic() < settle_until or self.appear(self.I_MD_SETTLING):
                continue
            if self.appear(self.I_MD_GET_BOSS):
                if checking_empty:
                    raise ScriptError('超鬼王：召唤队列仍有门票，但无法识别下一只鬼王星级')
                if self.appear_then_click(self.I_MD_CLOSE_POPUP, interval=0.8):
                    settle_until = time.monotonic() + 0.8
                continue
            preview = self.next_summon_star()
            if preview is None:
                if pending_star is None and self.appear_then_click(self.I_MD_SWITCH_TICKET, interval=1.5):
                    checking_empty = True
                    settle_until = time.monotonic() + 1.5
                continue
            if not self.appear(self.I_MD_SUMMON_BOSS):
                continue
            self.cur_boss_type = None
            checking_empty = False
            if pending_star is not None and pending_star != preview:
                continue
            if not self.State.synthesis_done:
                self.synthesis_boss_ticket()
                continue
            if not self.check_fatigue():
                return False
            if self.appear_then_click(self.I_MD_SUMMON_BOSS, interval=1.5):
                pending_star = preview
                settle_until = time.monotonic() + 3

        raise ScriptError('超鬼王：25 秒内未能确认当前鬼王星级或召唤结果')

    def ticket_matches_star(self, ticket: RuleImage, star: BossType, *, synthesis=False) -> bool:
        if not self.appear(ticket):
            return False
        image = self.device.image
        if recognize_ticket_stars(image, ticket.roi_front, synthesis=synthesis) == int(star):
            return True
        # The best template hit can be a different star level. Inspect the other
        # non-overlapping candidates before deciding the desired ticket is absent.
        matches = ticket.match_all_any(image, frame_id=self.device.image_frame_id)
        for _, x, y, width, height in sorted(matches, reverse=True):
            area = (x, y, width, height)
            if recognize_ticket_stars(image, area, synthesis=synthesis) == int(star):
                ticket.roi_front = list(area)
                return True
        logger.info(f'门票模板命中但底部星级未通过复核：目标 {int(star)} 星')
        return False

    def check_and_switch_powerful(self) -> bool:
        """检查并切换是否开启强力"""
        logger.hr('process power fire')
        if not self.appear(self.I_MD_FIRE):
            self.screenshot()
            if not self.appear(self.I_MD_FIRE):  # 处于boss界面但是没有挑战按钮
                raise ScriptError('超鬼王：切换强力追击前未找到挑战按钮')
        enabled, disabled = self.I_MD_ENABLE_POWERFUL_FIRE, self.I_MD_DISABLE_POWERFUL_FIRE
        click, stop = (disabled, enabled) if self.enable_powerful_fire else (enabled, disabled)
        self.ui_click(click, stop, interval=0.6)
        return True

    def prepare_boss_preset(self) -> bool:
        if self._active_preset is not None:
            return True
        if self.cur_boss_type is None:
            raise ScriptError('超鬼王：未确认当前鬼王星级，无法选择快速预设')

        name = ''
        if self.cur_boss_type >= BossType.FIVE_STARS:
            name = self._normalize_name(self._read_quick_loadout_stage_name(self.O_BOSS_NAME))
            if not name:
                raise ScriptError('超鬼王：无法识别当前鬼王名称，无法选择对应快速预设')
        preset = self.conf.preset_for(self.cur_boss_type, name)
        preset_group = ('low_star_preset' if self.cur_boss_type <= BossType.FOUR_STARS
                        else SPECIAL_BOSS_PRESETS.get(name, 'high_star_preset'))
        rental_name = RENTAL_LINEUP_NAMES.get(preset.rental_lineup)
        logger.info(
            f'鬼王 {int(self.cur_boss_type)} 星 {name}，快速预设：{PRESET_GROUPS[preset_group]}，'
            f'强力追击次数：{preset.powerful_count}，'
            f'阵容：{rental_name or preset.preset_numbers or preset.preset_name or "沿用当前阵容"}'
        )
        quick = None
        if rental_name:
            quick = QuickLoadoutConfig(enable=True, mode=QuickLoadoutMode.OCR,
                                      group_name=self.RENTAL_GROUP_NAME, preset_name=rental_name)
        elif preset.preset_numbers:
            group, team = map(int, preset.preset_numbers.split(','))
            quick = QuickLoadoutConfig(enable=True, mode=QuickLoadoutMode.NUMBER,
                                      group_number=group, preset_number=team)
        elif preset.group_name or preset.preset_name or preset.switch_soul:
            if not preset.group_name or not preset.preset_name:
                raise ScriptError('超鬼王：请填写快速预设编号，或同时填写分组名和队伍名')
            quick = QuickLoadoutConfig(enable=True, mode=QuickLoadoutMode.OCR,
                                      group_name=preset.group_name, preset_name=preset.preset_name)

        if quick and not self.run_quick_loadout(
            quick, frame=self.F_QUICK_LOADOUT_FRAME, skip_equip_soul=bool(rental_name) or not preset.switch_soul,
        ):
            raise ScriptError(f'超鬼王：快速预设切换失败（{PRESET_GROUPS[preset_group]}）')
        self._active_preset = preset
        return True

    def finish_task(self):
        self.goto_page(ipages.page_main)
        raise TaskEnd
