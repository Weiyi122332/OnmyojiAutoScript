# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import random
import re
import time
from datetime import datetime

from module.atom.image import RuleImage

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.QuickLoadout.config import QuickLoadoutConfig, QuickLoadoutMode
from tasks.MetaDemon.quick_loadout import FrameQuickLoadout
from tasks.GameUi.game_ui import GameUi
from tasks.MetaDemon.config import MetaDemon, BossType
from tasks.MetaDemon.assets import MetaDemonAssets
from tasks.MetaDemon.synthesis import parse_synthesis_material_level
from tasks.MetaDemon.ticket_stars import recognize_summon_preview, recognize_ticket_stars
import tasks.MetaDemon.page as ipages

from module.logger import logger
from module.exception import TaskEnd


class BossBattle(GeneralBattle, FrameQuickLoadout, GameUi, MetaDemonAssets):
    """超鬼王"""

    class State:
        done: bool = False
        targets_finished: bool = False
        synthesis_done: bool = False

    conf: MetaDemon = None
    cur_boss_type: BossType = None
    total_count: int = 0
    _current_boss_attempts: int = 0

    def _quick_loadout_fight(self, frame):
        return super()._quick_loadout_fight(
            frame, fight_file='./tasks/MetaDemon/md/md_quick_loadout_frame_fight.png',
        )

    @property
    def enable_powerful_fire(self) -> bool:
        config = self.conf.meta_demon_config
        return (config.high_star_powerful_enable
                and self.cur_boss_type in (BossType.FIVE_STARS, BossType.SIX_STARS)
                and self._current_boss_attempts < config.powerful_count)

    def before_run(self):
        ipages.configure_activity_navigation(self.navigator)
        self.State = BossBattle.State()
        self._preset_boss_generation = None
        self._last_quick_loadout = None
        self._boss_generation = 0
        self.cur_boss_type = None
        self.total_count = 0
        self._current_boss_attempts = 0
        self.conf = self.config.meta_demon

    def run(self):
        self.before_run()
        try:
            sequence = self.conf.meta_demon_config.fire_sequence_v
        except ValueError:
            logger.warning('鬼王挑战顺序只能填写 1 到 6 星')
            self.set_next_run(task='MetaDemon', success=False)
            raise TaskEnd
        if not sequence:
            logger.info('鬼王挑战顺序为空，结束任务')
            self.set_next_run(task='MetaDemon', success=True)
            raise TaskEnd
        self.goto_page(ipages.page_meta_demon_boss)
        while not self.State.done:
            self.screenshot()
            current_page = self.get_current_page()
            match current_page:
                case ipages.page_activity:
                    self.goto_page(ipages.page_meta_demon_boss)
                case ipages.page_meta_demon_boss:
                    if not self.check_and_prepare_battle(sequence):
                        break
                    if not self.start_battle(sequence) and not self.appear(self.I_MD_SETTLING):
                        break
                case ipages.page_battle:
                    self.battle_wait(False)
                case ipages.page_reward:
                    self.click(ipages.reward_random_click(), interval=0.6)
                case ipages.page_battle_result:
                    self.click(ipages.random_click(), interval=0.6)
                case _:
                    time.sleep(random.uniform(0.7, 1.4))
        if self.State.targets_finished and self.total_count > 0:
            self.push_targets_finished(sequence)
        self.set_next_run(task='MetaDemon', success=self.State.done)
        self.finish_task()

    def push_targets_finished(self, sequence):
        stars = '、'.join(f'{int(star)} 星' for star in sequence)
        content = f'已打完目标星级的鬼王（{stars}）'
        logger.info(content)
        try:
            notifier = self.config.notifier
            if notifier.enable and not notifier.push(title='超鬼王挑战完成', content=content):
                logger.warning('超鬼王完成通知发送失败')
        except Exception as exc:
            logger.warning(f'超鬼王完成通知发送失败：{exc}')

    def start_battle(self, sequence, should_continue=None):
        if self.cur_boss_type not in sequence:
            logger.warning('当前鬼王星级未确认或不在挑战顺序中，跳过挑战')
            return False
        logger.hr('Click fire, start battle')
        last_challenge = time.monotonic()
        while should_continue is None or should_continue():
            self.screenshot()
            if self.is_in_battle(False):
                self.total_count += 1
                self._current_boss_attempts += 1
                self.run_general_battle(
                    GeneralBattleConfig(),
                    battle_key='meta_demon',
                    exit_matcher=self.I_MD_SETTLING if should_continue is not None else None,
                )
                return True
            if self.appear(self.I_MD_DRINK_TEA, interval=1.2):  # 出现喝茶弹窗
                if self.conf.meta_demon_config.auto_tea:
                    self.click(self.I_MD_DRINK_TEA)  # 喝茶
                    continue
                # 不喝茶则结束任务安排下一次运行
                self.ui_click_until_disappear(self.I_MD_CLOSE_POPUP, interval=0.6)
                self.set_next_run('MetaDemon', target=datetime.now() + self.conf.scheduler.wait_interval)
                self.finish_task()
            if self.appear(self.I_MD_SETTLING):
                return False
            if self.appear_then_click(self.I_MD_FIRE, interval=0.8) or self.appear(self.I_MD_FIRE):
                last_challenge = time.monotonic()
            elif should_continue is not None and time.monotonic() - last_challenge >= 5:
                return False
        return False

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

    def check_and_prepare_battle(self, sequence) -> bool:
        """确认鬼王星级后准备战斗。"""
        logger.hr('battle prepare', 2)
        if self.appear(self.I_MD_SUMMON_BOSS) and not self.appear(self.I_MD_GET_BOSS):
            preview = self.next_summon_star()
            if self.stop_at_six_star_preview(preview, sequence):
                return False
            if preview is not None:
                self.synthesis_boss_ticket()
        return (self.check_and_switch_ticket(sequence=sequence, stop_at_six=True)
                and self.check_fatigue() and self.check_and_switch_soul() and self.check_and_switch_powerful())

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
            if click_cnt >= max_cnt:  # 兜底,多次点击开始合成都没有出现获得奖励则退出
                break
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
                        logger.warning('连续三次无法确认目标合成星级，跳过本星级')
                        break
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
            self.set_next_run('MetaDemon', target=datetime.now() + self.conf.scheduler.wait_interval)
            self.finish_task()
        return True

    def next_summon_star(self) -> BossType | None:
        if not self.appear(self.I_MD_SWITCH_TICKET):
            return None
        stars = recognize_summon_preview(self.device.image, self.I_MD_SWITCH_TICKET.roi_front)
        return BossType(stars) if stars is not None else None

    def stop_at_six_star_preview(self, preview, sequence) -> bool:
        if preview != BossType.SIX_STARS:
            return False
        self.State.done = True
        self.State.targets_finished = BossType.SIX_STARS not in sequence
        logger.info('主页显示下一只为六星，结束鬼王战斗')
        return True

    def read_ticket_counts(self, tickets) -> dict[BossType, int] | None:
        visible = {star: tuple(ticket.roi_front) for star, ticket in tickets.items()
                   if self.ticket_matches_star(ticket, star)}
        if not visible:
            return None
        rule = self.O_MD_TICKET_COUNTS
        rows = rule.detect_and_ocr(self.device.image)
        if len(rows) != len(visible):
            return None
        counts = {}
        for row in rows:
            match = re.fullmatch(r'持有\s*[:：]?\s*([0-9]+)', row.ocr_text.strip())
            center = rule.roi[0] + row.box[:, 0].mean()
            star = next((star for star, (x, _, width, _) in visible.items() if x <= center < x + width), None)
            if not match or star is None or star in counts:
                return None
            counts[star] = int(match[1])
        return counts

    def check_and_switch_ticket(self, sequence=None, *, stop_at_six=False):
        """使用当前帧的星级、数量和选中标记确认召唤。"""
        if sequence is None:
            sequence = self.conf.meta_demon_config.fire_sequence_v
        if not sequence:
            return False
        logger.hr('Summon boss')
        tickets = {
            BossType.ONE_STAR: self.I_MD_ONE_STAR,
            BossType.TWO_STARS: self.I_MD_TWO_STARS,
            BossType.THREE_STARS: self.I_MD_THREE_STARS,
            BossType.FOUR_STARS: self.I_MD_FOUR_STARS,
            BossType.FIVE_STARS: self.I_MD_FIVE_STARS,
            BossType.SIX_STARS: self.I_MD_SIX_STARS,
        }
        pending_star = None
        missing_inventory = None
        deadline = time.monotonic() + 25
        settle_until = 0.0
        while time.monotonic() < deadline:
            self.screenshot()
            if self.appear(self.I_MD_FIRE):
                if pending_star is not None:
                    self.current_count = 0
                    self.cur_boss_type = pending_star
                    self._boss_generation = getattr(self, '_boss_generation', 0) + 1
                    self._current_boss_attempts = 0
                    logger.info(f'已确认召唤 {int(pending_star)} 星鬼王')
                if self.cur_boss_type not in sequence:
                    logger.warning('当前鬼王星级未确认或不在挑战顺序中，结束本轮')
                    return False
                return True

            panel_open = self.appear(self.I_MD_GET_BOSS)
            if pending_star is not None and not panel_open:
                continue
            preview = self.next_summon_star()
            if pending_star is None and stop_at_six and self.stop_at_six_star_preview(preview, sequence):
                if panel_open:
                    self.appear_then_click(self.I_MD_CLOSE_POPUP, interval=0.8)
                return False
            if time.monotonic() < settle_until:
                continue
            if pending_star is None and self.appear(self.I_MD_TICKET_EMPTY):
                self.State.done = self.State.targets_finished = True
                logger.info('召唤队列无门票')
                self.appear_then_click(self.I_MD_CLOSE_POPUP, interval=0.8)
                return False
            if not panel_open:
                missing_inventory = None
                if preview is not None or self.appear(self.I_MD_SUMMON_BOSS):
                    self.cur_boss_type = None
                if self.appear_then_click(self.I_MD_SWITCH_TICKET, interval=1.5):
                    settle_until = time.monotonic() + 1.5
                continue

            self.cur_boss_type = None
            inventory = self.read_ticket_counts(tickets)
            if inventory is None or (preview is not None and not inventory.get(preview)):
                missing_inventory = None
                settle_until = time.monotonic() + 0.8
                continue
            target_star = next((star for star in sequence if inventory.get(star, 0) > 0), None)
            if pending_star is not None and target_star != pending_star:
                continue
            if target_star is None:
                if missing_inventory == inventory:
                    self.State.done = self.State.targets_finished = True
                    logger.info('已核对召唤队列，目标星级门票已用完')
                    self.appear_then_click(self.I_MD_CLOSE_POPUP, interval=0.8)
                    return False
                missing_inventory = inventory
                settle_until = time.monotonic() + 0.8
                continue

            missing_inventory = None
            target = tickets[target_star]
            if self.appear(self.I_MD_CHECK_SELECTED):
                marker_x, _, marker_w, _ = self.I_MD_CHECK_SELECTED.roi_front
                x, _, width, _ = target.roi_front
                if x <= marker_x + marker_w / 2 <= x + width:
                    # The main page shows the automatic queue. The panel's own
                    # marker confirms which ticket its button will actually use.
                    if stop_at_six and (preview is None or not self.check_fatigue()):
                        continue
                    if self.appear_then_click(self.I_MD_GET_BOSS, interval=1.5):
                        pending_star = target_star
                        settle_until = time.monotonic() + 3
                    continue
            self.click(target, interval=1.0)
        logger.warning('未能确认鬼王召唤，结束本轮')
        return False

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
            self.goto_page(ipages.page_meta_demon_boss)
            self.screenshot()
            if not self.appear(self.I_MD_FIRE):  # 处于boss界面但是没有挑战按钮
                return False
        enabled, disabled = self.I_MD_ENABLE_POWERFUL_FIRE, self.I_MD_DISABLE_POWERFUL_FIRE
        click, stop = (disabled, enabled) if self.enable_powerful_fire else (enabled, disabled)
        self.ui_click(click, stop, interval=0.6)
        return True

    def check_and_switch_soul(self) -> bool:
        """通过快速预设为当前鬼王装魂并上阵。"""
        settings = self.conf.quick_preset_config
        if not settings.enable or self._preset_boss_generation == self._boss_generation:
            return True
        try:
            presets = settings.named_presets()
        except ValueError as exc:
            logger.error(f'超鬼王快速预设配置错误：{exc}')
            return False
        target = presets.get('ALL')
        if len(presets) > 1 or target is None:
            boss_name = self._read_quick_loadout_stage_name(self.O_BOSS_NAME)
            if not self._normalize_name(boss_name):
                logger.warning('未识别到首领名称，暂不上阵')
                return False
            _, target, _ = self._match_custom_preset(boss_name, presets)
            if target is None:
                logger.error(f'首领 {boss_name} 无匹配预设，请配置对应名称或 ALL')
                return False
        quick = QuickLoadoutConfig(enable=True, mode=QuickLoadoutMode.OCR,
                                  group_name=target[0], preset_name=target[1])
        if not self.run_quick_loadout(quick, frame=self.F_QUICK_LOADOUT_FRAME,
                                      skip_equip_soul=settings.skip_equip_soul):
            return False
        self._preset_boss_generation = self._boss_generation
        return True

    def finish_task(self):
        self.goto_page(ipages.page_main)
        raise TaskEnd
