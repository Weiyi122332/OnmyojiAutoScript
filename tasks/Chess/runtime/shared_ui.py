"""棋局独立使用来源项目的公共识别，公共任务仍使用原有规则。"""

from copy import copy
import time

from module.atom.click import RuleClick
from module.atom.long_click import RuleLongClick
from module.base.decorator import cached_property
from module.exception import GameStuckError
from module.logger import logger
from tasks.ActivityShikigami.assets import ActivityShikigamiAssets
from tasks.Chess.assets import ChessAssets
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.GameUi.assets import GameUiAssets
from tasks.GlobalGame.assets import GlobalGameAssets


SHARED_UI_BINDINGS = (
    (GeneralBattleAssets, 'I_EXIT_ENSURE', 'I_SHARED_EXIT_ENSURE'),
    (GameUiAssets, 'I_ACTIVITY_SKIP', 'I_SHARED_ACTIVITY_SKIP'),
    (GameUiAssets, 'I_CHECK_MAIN', 'I_SHARED_CHECK_MAIN'),
    (GlobalGameAssets, 'I_G_ACCEPT', 'I_SHARED_G_ACCEPT'),
    (GlobalGameAssets, 'I_G_REJECT', 'I_SHARED_G_REJECT'),
    (GlobalGameAssets, 'I_G_CAT_FOOD', 'I_SHARED_G_CAT_FOOD'),
    (GlobalGameAssets, 'I_G_DOG_FOOD', 'I_SHARED_G_DOG_FOOD'),
    (GlobalGameAssets, 'I_G_JADE', 'I_SHARED_G_JADE'),
    (GlobalGameAssets, 'I_UI_CONFIRM', 'I_SHARED_UI_CONFIRM'),
    (GlobalGameAssets, 'I_UI_REWARD', 'I_SHARED_UI_REWARD'),
    (GlobalGameAssets, 'I_NETWORK_ABNORMAL', 'I_SHARED_NETWORK_ABNORMAL'),
    (GlobalGameAssets, 'I_NETWORK_ERROR', 'I_SHARED_NETWORK_ERROR'),
    (GlobalGameAssets, 'I_CLIENT_CLEAR', 'I_SHARED_CLIENT_CLEAR'),
    # 当前未知页关闭列表使用活动组件；棋局增加来源跳过模板作为首选。
    (ActivityShikigamiAssets, 'I_SKIP_BUTTON', 'I_SHARED_ACTIVITY_SKIP'),
)


class ChessNetworkRecoveryRequired(GameStuckError):
    """棋局重连失败时可直接交给当前调度器既有的异常重启处理。"""

    def __init__(self, message, *, reconnect=False):
        self.reconnect = reconnect
        super().__init__(message)


class ChessSharedUiMixin:
    @cached_property
    def _chess_ui_variants(self):
        variants = {}
        for owner, name, asset in SHARED_UI_BINDINGS:
            original = getattr(owner, name)
            variant = copy(getattr(ChessAssets, asset))
            variant.roi_front = list(variant.roi_front)
            # 同一按钮的两份模板共用点击间隔与过多点击保护名称。
            variant.name = original.name
            variants[id(original)] = (variant, original)
        return variants

    @cached_property
    def _chess_close_red(self):
        rule = copy(ChessAssets.I_SHARED_CLOSE_RED)
        rule.roi_front = list(rule.roi_front)
        return rule

    def _chess_ui_frame(self):
        return getattr(self.device, 'image_frame_id', None) or id(self.device.image)

    def appear(self, target, interval=None, threshold=None):
        variants = self._chess_ui_variants.get(id(target))
        if variants is None:
            return super().appear(target, interval=interval, threshold=threshold)
        hits = self.__dict__.setdefault('_chess_ui_hits', {})
        hits.pop(id(target), None)
        for rule in variants:
            if super().appear(rule, interval=interval, threshold=threshold):
                hits[id(target)] = (self._chess_ui_frame(), rule)
                return True
        return False

    def _chess_click_rule(self, target):
        variants = self._chess_ui_variants.get(id(target))
        if variants is None:
            return target
        hit = self.__dict__.get('_chess_ui_hits', {}).get(id(target))
        if hit is not None and hit[0] == self._chess_ui_frame():
            return hit[1]
        return variants[0]

    def appear_then_click(self, target, action=None, interval=None,
                          threshold=None, duration=None):
        if id(target) not in self._chess_ui_variants:
            return super().appear_then_click(
                target, action=action, interval=interval, threshold=threshold, duration=duration,
            )
        if not self.appear(target, interval=interval, threshold=threshold):
            return False
        click = self._chess_click_rule(target) if action is None else action
        x, y = click.coord()
        if action is None:
            self.device.click(x, y, control_name=target.name)
        elif isinstance(action, RuleLongClick):
            self.device.long_click(
                x, y, duration=(click.duration if duration is None else duration) / 1000,
                control_name=target.name,
            )
        elif isinstance(action, RuleClick):
            self.device.click(x, y, control_name=target.name)
        return True

    def click(self, click=None, interval=None):
        return super().click(self._chess_click_rule(click), interval=interval)

    def prepare_appear_cache(self, targets):
        expanded = []
        for target in targets:
            expanded.extend(self._chess_ui_variants.get(id(target), (target,)))
        return super().prepare_appear_cache(expanded)

    def _burst(self):
        if super()._burst():
            return True
        if self.appear_then_click(self._chess_close_red, interval=0.8):
            logger.info('Chess: close floating window with red cross')
            return True
        if (not getattr(self, '_chess_details_depth', 0)
                and self.appear(self.I_SHIKIGAMI_SPECIFICS)):
            if self.click(self.C_CLICK_CLOSE_SPECIFICS_AREA, interval=0.8):
                logger.info('Chess: globally close unexpected shikigami details')
            return True
        return False

    def _handle_network(self):
        deadline = None
        while True:
            if self.appear(GlobalGameAssets.I_NETWORK_ERROR):
                raise ChessNetworkRecoveryRequired('Chess: network reconnect required', reconnect=True)
            if not self.appear(GlobalGameAssets.I_NETWORK_ABNORMAL):
                return
            policy = self.config.global_game.emergency.when_network_abnormal
            policy = getattr(policy, 'value', policy)
            if policy == 'restart':
                raise ChessNetworkRecoveryRequired('Chess: network restart requested')
            if deadline is None:
                # 保持当前实例的 wait_10s 配置，也兼容来源框架的 wait_5s。
                wait = 5 if policy == 'wait_5s' else 10
                deadline = time.monotonic() + wait
                logger.warning(f'Chess: network abnormal; wait up to {wait} seconds')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ChessNetworkRecoveryRequired('Chess: network recovery wait timed out')
            self.device.sleep(min(0.25, remaining))
            # 使用原始截图，避免递归进入恢复流程。
            self.device.screenshot()

    def screenshot(self):
        self.device.screenshot()
        while True:
            self._handle_network()
            if not self._burst():
                return self.device.image
            # 弹窗消失后刷新再识别，不能把关闭前的图交给回目状态机。
            self.device.screenshot()

    def _create_chess_login(self):
        from tasks.Component.Login.service import LoginService

        class ChessLoginService(ChessSharedUiMixin, LoginService):
            """仅本次棋局重连使用扩展识别和截图复核。"""

        return ChessLoginService(config=self.config, device=self.device)

    def _reconnect_chess_network(self):
        from tasks.Restart.assets import RestartAssets

        self.device.stuck_record_clear()
        self.device.click_record_clear()
        deadline = time.monotonic() + 30
        try:
            login = self._create_chess_login()
            while True:
                self.device.screenshot()
                if login.appear(RestartAssets.I_LOGIN_8):
                    break
                if time.monotonic() >= deadline:
                    raise GameStuckError('Chess: reconnect did not reach login page within 30 seconds')
                login.appear_then_click(login.I_CLIENT_CLEAR, interval=1)
                self.device.sleep(0.25)
            if not login.app_handle_login():
                raise GameStuckError('Chess: reconnect login did not complete')
        except Exception as error:
            raise GameStuckError(f'Chess: network reconnect failed: {error}') from error
        self.device.stuck_record_clear()
        self.device.click_record_clear()
