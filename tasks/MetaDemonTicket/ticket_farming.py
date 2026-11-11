"""超鬼王门票刷取，复用觉醒和探索的战斗流程。"""
from datetime import datetime, timedelta
from enum import Enum

from pydantic import Field
from module.base.decorator import cached_property

from module.base.timer import Timer
from module.exception import GameStuckError, TaskEnd
from module.logger import logger
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.EvoZone.config import EvoZone, EvoZoneConfig, UserStatus as AwakeUserStatus
from tasks.EvoZone.script_task import ScriptTask as AwakeTask
from tasks.Exploration.config import (
    AutoRotate, Exploration, ExplorationConfig, ExplorationLevel,
    UserStatus as ExplorationUserStatus,
)
from tasks.Exploration.page import page_exp_entrance, page_exp_main
from tasks.Exploration.script_task import ScriptTask as ExplorationTask
from tasks.GameUi.default_pages import page_reward
import tasks.GameUi.page as pages
from tasks.MetaDemonTicket.config import TicketMode
from tasks.MetaDemon.assets import MetaDemonAssets
from tasks.GameUi.assets import GameUiAssets


class ExplorationDifficulty(str, Enum):
    SIMPLE = '简单'
    HARD = '困难'


class TicketExplorationConfig(ExplorationConfig):
    difficulty: ExplorationDifficulty = Field(default=ExplorationDifficulty.HARD)


class TicketsFull(Exception):
    """达到单刷或协同满票目标，停止开启下一场战斗。"""


class TicketPartnerFinished(Exception):
    """协同伙伴结束门票阶段。"""


class RealmRaidThresholdReached(Exception):
    """突破券达标，先结束本轮探索再交给突破任务。"""


def metademon_tickets_full(task) -> bool:
    """读取当前奖励截图的门票/上限；无有效上限时不判满。"""
    # I_REWARD is the red-daruma settlement image; I_UI_REWARD is the
    # separate "获得奖励" banner and does not identify this battle reward screen.
    if not task.appear(GeneralBattleAssets.I_REWARD):
        return False
    current, remaining, total = GeneralBattleAssets.O_METADEMON_PASS.ocr_digit_counter(task.device.image)
    if total <= 0 or current < 0:
        logger.warning('超鬼王门票 OCR 未识别到有效计数')
        return False
    logger.info(f'超鬼王门票: {current}/{total}')
    return current >= total


class TicketRewardMixin:
    def screenshot(self):
        result = super().screenshot()
        peer = getattr(self, '_ticket_peer', '')
        if peer and not self._ticket_farming_complete and self._battle_context is None:
            runtime = self.config.cooperation_runtime
            status = runtime.peer_task_completion('MetaDemonTicket', peer, self._ticket_phase_started)
            if status == 'tickets_full' and self._ticket_full:
                raise TicketsFull
            if status == 'ticket_finished':
                raise TicketPartnerFinished
            token = runtime.pending_room_check('MetaDemonTicket', peer)
            if token:
                runtime.answer_room_check('MetaDemonTicket', peer, token, self.is_in_room(False))
        return result

    def _cooperation_rooms_ready(self) -> bool:
        runtime = self.config.cooperation_runtime
        peer = self._ticket_peer
        token = getattr(self, '_cooperation_room_token', None)
        if token:
            ready = runtime.room_check_result('MetaDemonTicket', peer, token)
            if ready is None:
                return False
            self._cooperation_room_token = None
            if ready:
                return True
        self._cooperation_room_token = runtime.request_room_check('MetaDemonTicket', peer)
        return False

    def check_ticket_reward(self):
        if getattr(self, '_ticket_farming_complete', False) or getattr(self, '_ticket_full', False):
            return
        if metademon_tickets_full(self):
            self._mark_tickets_full()

    def _mark_tickets_full(self):
        logger.info('门票已满')
        self._ticket_full = True
        peer = getattr(self, '_ticket_peer', '')
        if not peer:
            raise TicketsFull
        self.config.cooperation_runtime.notify_task_completion('MetaDemonTicket', peer, 'tickets_full')
        logger.info('本号门票已满，继续组队直到对方满票')

    def _handle_reward(self, context, config):
        self.check_ticket_reward()
        return super()._handle_reward(context, config)

    def install_ticket_reward_hook(self):
        reward = self.navigator.resolve_page(page_reward)
        # 导航进入奖励页时也必须先 OCR，再执行原来的结算点击。
        reward.on_enter_success.insert(0, lambda task: task.check_ticket_reward())


class AwakeTicketTask(TicketRewardMixin, AwakeTask):
    @cached_property
    def _config(self):
        return ticket_farming_config(self.config.meta_demon_ticket, TicketMode.AWAKE)

    def _infer_task_category(self):
        return 'evo_zone'


class ExplorationTicketTask(TicketRewardMixin, ExplorationTask, MetaDemonAssets):
    @cached_property
    def _config(self):
        return ticket_farming_config(self.config.meta_demon_ticket, TicketMode.EXPLORATION,
                                     self.config.exploration)

    def _infer_task_category(self):
        return 'exploration'

    @property
    def exp_page_handle_dict(self):
        handlers = super().exp_page_handle_dict
        original = handlers[page_reward]

        def reward():
            self.check_ticket_reward()
            return original()

        handlers[page_reward] = reward
        return handlers

    def activate_realm_raid(self, con_scrolls, con, current_page):
        raid = self.config.realm_raid
        if not raid.scheduler.enable:
            return
        count = self.read_realm_raid_tickets(current_page)
        threshold = max(con_scrolls.scrolls_threshold, raid.raid_config.number_base)
        if count and count >= threshold:
            logger.info(f'探索突破券 {count}/30，达到阈值 {threshold}')
            raise RealmRaidThresholdReached

    def arrive_end(self) -> bool:
        # 28章直接匹配
        if (self._config.exploration_config.exploration_level == ExplorationLevel.EXPLORATION_28
                and self.appear(self.I_SWIPE_END)):
            return True
        return super(ExplorationTask, self).arrive_end()

    def ensure_exploration_team_locked(self) -> bool:
        """按战斗配置切换探索阵容锁，下一帧重新确认。"""
        if self._config.exploration_config.auto_rotate == AutoRotate.yes:
            return False
        lock_enabled = self._config.general_battle_config.lock_team_enable
        expected, toggle = self.I_EXP_LOCK, self.I_EXP_UNLOCK
        if not lock_enabled:
            expected, toggle = toggle, expected
        if self.appear(expected):
            return False
        if self.appear_then_click(toggle, interval=1):
            logger.info(f'Exploration: set team lock to {lock_enabled}')
            return True
        return False

    def run_on_exp_entrance(self):
        self.collect_treasure_box()
        self.fire_monster_type = ''  # 入口处重置怪物类型
        self.need_exit = False
        match self.user_status:
            case ExplorationUserStatus.LEADER:
                if self.check_and_invite(self._config.invite_config.default_invite):
                    return
                if datetime.now() - self.wait_start_time >= timedelta(seconds=10) or self.current_count == 0:
                    self.ensure_difficulty(ExplorationDifficulty.HARD)
                    self.enter_team()
            case ExplorationUserStatus.ALONE:
                difficulty = self.solo_difficulty
                if difficulty is not None:
                    self.ensure_difficulty(difficulty)
                self.goto_page(page_exp_main)
            case ExplorationUserStatus.MEMBER:
                self.check_then_accept()
                self.device.stuck_record_clear()

    @property
    def solo_difficulty(self) -> ExplorationDifficulty | None:
        return self._config.exploration_config.difficulty

    def ensure_difficulty(self, difficulty: ExplorationDifficulty) -> None:
        hard = difficulty == ExplorationDifficulty.HARD
        selector = self.C_SELECT_HARD if hard else self.C_SELECT_NORMAL
        timeout = Timer(8).start()
        matched = False
        while not timeout.reached():
            self.screenshot()
            if not self.appear(self.I_E_EXPLORATION_CLICK):
                matched = False
                continue
            if self.appear(self.I_EXP_CREATE_TEAM) == hard:
                if matched:
                    return
                matched = True
                continue
            matched = False
            self.click(selector, interval=1)
        raise GameStuckError(f'未确认探索难度：{difficulty.value}')

    def run_on_exp(self):
        if (not getattr(self, '_ticket_farming_complete', False)
                and not getattr(self, '_ticket_full', False)
                and exploration_tickets_full(self)):
            self._mark_tickets_full()
        self.fire_monster_type = ''  # 入口处重置怪物类型
        self.need_exit = False
        match self.user_status:
            case ExplorationUserStatus.LEADER:
                # TODO: 队长宝箱收集(游戏问题导致邀请和宝箱出现时间不一致, 一旦先点中宝箱就会出现卡死), 当前先取消队长在探索界面的宝箱收集
                if self.check_and_invite(self._config.invite_config.default_invite):
                    return
                if datetime.now() - self.wait_start_time >= timedelta(seconds=10) or self.current_count == 0:
                    self.goto_page(page_exp_entrance)
            case ExplorationUserStatus.ALONE:
                self.collect_treasure_box()
                self.goto_page(page_exp_entrance)
            case ExplorationUserStatus.MEMBER:
                self.collect_treasure_box()
                self.check_then_accept()
                self.device.stuck_record_clear()


def ticket_farming_config(meta, mode, exploration: Exploration | None = None):
    """觉醒使用门票任务设置，探索复用普通探索的副本、战斗设置和突破券阈值。"""
    common = meta.general_config
    if mode == TicketMode.AWAKE:
        return EvoZone(
            evo_zone_config=EvoZoneConfig(user_status=AwakeUserStatus(common.user_status.value),
                layer=common.awake_layer, kirin_type=common.awake_kirin_type,
                limit_time=common.limit_time, limit_count=2 ** 31 - 1,
                soul_buff_enable=common.awake_buff_enable),
            switch_soul_config=meta.switch_soul_config.model_copy(),
            general_battle_config=meta.general_battle_config, invite_config=meta.invite_config)
    if mode == TicketMode.EXPLORATION:
        config = (exploration if exploration is not None else Exploration()).model_copy(deep=True)
        settings = config.exploration_config.model_dump()
        settings.update(user_status=common.user_status, limit_time=common.limit_time,
                        minions_cnt=2 ** 31 - 1)
        config.exploration_config = TicketExplorationConfig(**settings)
        config.scheduler = meta.scheduler.model_copy(deep=True)
        config.invite_config = meta.invite_config.model_copy(deep=True)
        config.scrolls.scrolls_enable = False
        if config.exploration_config.auto_rotate == AutoRotate.yes:
            config.general_battle_config.lock_team_enable = False
        return config
    raise ValueError(f'未知门票刷取模式: {mode}')


def exploration_tickets_full(task) -> bool | None:
    """读取探索地图上的门票数量，识别失败时留给结算页复核。"""
    if not task.appear(GameUiAssets.I_CHECK_EXPLORATION):
        return None
    current, _, total = MetaDemonAssets.O_METADEMON_PASS_EXP.ocr_digit_counter(task.device.image)
    if current < 0 or total <= 0:
        return None
    logger.info(f'探索门票: {current}/{total}')
    return current >= total


def tickets_full_before_farming(owner) -> bool:
    """Check the courtyard's exploration landing page before any farming setup."""
    owner.goto_page(pages.page_exploration)
    for _ in range(3):
        owner.screenshot()
        full = exploration_tickets_full(owner)
        if full is not None:
            return full
    logger.warning('探索入口未识别到有效超鬼王门票计数，继续刷取并由奖励页检测满票')
    return False


def run_ticket_farming(owner, mode) -> bool:
    """运行所选刷票玩法，门票满后停止开启新的战斗。"""
    if mode not in (TicketMode.AWAKE, TicketMode.EXPLORATION):
        raise ValueError(f'未知门票刷取模式: {mode}')
    config = getattr(owner, 'config', None)
    runtime = getattr(config, 'cooperation_runtime', None)
    meta = config.meta_demon_ticket
    peer = ''
    if (runtime is None and meta.invite_config.cooperation_script
            and meta.general_config.user_status != ExplorationUserStatus.ALONE):
        logger.warning('超鬼王刷票协同服务未就绪，本轮稍后重试')
        return False
    if runtime is not None:
        target = meta.invite_config.cooperation_script or runtime.peers.get('MetaDemonTicket', '')
        if target and meta.general_config.user_status != ExplorationUserStatus.ALONE:
            if runtime.matches_meta_demon_tickets(target):
                peer = target
            else:
                logger.warning(f'超鬼王门票刷取协同配置不匹配：{target}，跳过本轮，避免按本号满票提前退出')
                return False
    local_full = tickets_full_before_farming(owner)
    if local_full and not peer:
        logger.info('超鬼王门票已满，跳过门票刷取')
        return True
    role = config.meta_demon_ticket.general_config.user_status
    limit_time = config.meta_demon_ticket.general_config.limit_time_v
    if mode == TicketMode.AWAKE:
        runner = AwakeTicketTask(config, owner.device)
    elif mode == TicketMode.EXPLORATION:
        runner = ExplorationTicketTask(config, owner.device)
    else:
        raise ValueError(f'未知门票刷取模式: {mode}')
    runner.start_time = datetime.now()
    runner.current_count = 0
    runner.limit_count = 2 ** 31 - 1
    runner._ticket_farming_complete = False
    runner._ticket_full = local_full
    if mode == TicketMode.AWAKE:
        runner._register_custom_pages()
    runner.install_ticket_reward_hook()
    buff_opened = False
    exploration_started = False
    cooperation_started = False
    realm_raid_due = False
    result = False
    try:
        if peer:
            runner._ticket_phase_started = runtime.begin_completion_phase('MetaDemonTicket', peer)
            if not runtime.prepare(config, 'MetaDemonTicket', peer, defer=False):
                return False
            cooperation_started = True
            runtime.peers['MetaDemonTicket'] = peer
            runner._ticket_peer = peer
            if local_full:
                runtime.notify_task_completion('MetaDemonTicket', peer, 'tickets_full')
                logger.info('本号门票已满，继续组队直到对方满票')
        if mode == TicketMode.AWAKE:
            soul = runner._config.switch_soul_config
            if soul.enable or soul.enable_switch_by_name:
                runner.goto_page(pages.page_shikigami_records)
                if soul.enable_switch_by_name:
                    runner.run_switch_soul_by_name(soul.group_name, soul.team_name)
                else:
                    runner.run_switch_soul(soul.switch_group_team)
            if config.meta_demon_ticket.general_config.awake_buff_enable:
                runner.goto_page(pages.page_main)
                runner.open_buff()
                runner.awake(is_open=True)
                buff_opened = True
                runner.close_buff()
            runner.limit_time = limit_time
            if role == ExplorationUserStatus.LEADER:
                runner.run_leader()
            elif role == ExplorationUserStatus.MEMBER:
                runner.run_member()
            else:
                runner.run_alone()
        else:
            exploration_started = True
            runner.pre_process()
            runner.limit_time = limit_time
            runner.exec_exp_page()
    except TicketsFull:
        result = True
        if cooperation_started:
            logger.info('双方门票已满，结束协同刷取')
    except TicketPartnerFinished:
        logger.info('协同伙伴已结束门票刷取，退出组队')
    except RealmRaidThresholdReached:
        realm_raid_due = True
    finally:
        runner._ticket_farming_complete = True
        if cooperation_started:
            runtime.notify_task_completion('MetaDemonTicket', peer, 'tickets_full' if result else 'ticket_finished')
        if exploration_started:
            runner.close_exploration_buffs()
        if cooperation_started or (not peer and role != ExplorationUserStatus.ALONE) or buff_opened:
            runner.goto_page(pages.page_main)
        if buff_opened:
            runner.open_buff()
            runner.awake(is_open=False)
            runner.close_buff()
    if realm_raid_due:
        config.reload()
        if config.task_call('RealmRaid', force_call=False):
            cooldown = max(runner._config.scrolls.scrolls_cd, timedelta(seconds=1))
            owner.set_next_run(task='MetaDemonTicket', target=datetime.now() + cooldown)
            raise TaskEnd
    return result
