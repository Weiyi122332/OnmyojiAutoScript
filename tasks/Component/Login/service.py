# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from module.base.timer import Timer
from module.exception import RequestHumanTakeover, GameTooManyClickError, GameStuckError
from module.logger import logger
from tasks.GameUi.assets import GameUiAssets
from tasks.GameUi.chess_battle import ChessBattleNavigationMixin
from tasks.Restart.assets import RestartAssets
from tasks.base_task import BaseTask


class LoginService(
    ChessBattleNavigationMixin,
    BaseTask,
    RestartAssets,
    GameUiAssets,
):
    character: str

    def __init__(self, *wargs, **kwargs):
        super().__init__(*wargs, **kwargs)
        self.character = self.config.restart.login_character_config.character
        self.O_LOGIN_SPECIFIC_SERVE.keyword = self.character

    def _courtyard_visible(self) -> bool:
        """判断当前是否已经进入庭院。

        登录流程在看不到「跳过/进入游戏」时会盲点屏幕中央来跳过登录动画，
        但游戏自动续连时会直接进入庭院：此时屏幕中央正是站着的阴阳师，
        点一下会弹出「闲庭模式/切换角色/姿度配饰」菜单（庭院背景随之变为
        展示场景），导致后续所有页面识别失败并抛 GamePageUnknownError。
        因此点中央之前先确认是否已经在庭院。

        Returns:
            命中任意一个庭院判据即返回 True。
        """

        # 底部导航属于固定 UI，不随庭院皮肤变化，因此优先使用；
        # 阈值取 0.85，避免登录动画的中间帧被误判成庭院而提前停止跳过动画。
        if self.appear(self.I_MAIN_GOTO_SHIKIGAMI_RECORDS, threshold=0.85):
            return True
        if self.appear(self.I_MAIN_GOTO_COLLECTION, threshold=0.85):
            return True
        # 最后再退回导航器使用的庭院标志（依赖庭院皮肤，可能失配）。
        return bool(self.appear(self.I_CHECK_MAIN))

    def _app_handle_login(self) -> bool:
        """
        最终是在庭院界面
        :return:
        """
        logger.hr('App login')
        self.device.stuck_record_add('LOGIN_CHECK')

        confirm_timer = Timer(1.5, count=2).start()
        orientation_timer = Timer(10)
        skip_login_animation = True
        login_success = False

        while 1:
            if not login_success and orientation_timer.reached():
                self.device.get_orientation()
                orientation_timer.reset()

            self.screenshot()
            if self.appear_then_click(
                self.I_RETURN_CHESS_CANCEL,
                interval=0.8,
            ):
                logger.info(
                    'Cancel returning to interrupted Chess battle; '
                    'wait for result flow'
                )
                continue
            if self.appear(self.I_CHECK_CHESS):
                logger.info(
                    'Login recovery reached Chess lobby; '
                    'finish recovery without returning to courtyard'
                )
                return True
            if self.chess_result_flow_visible():
                logger.info(
                    'Login recovery detected unfinished Chess result flow'
                )
                self.return_to_chess_lobby()
                return True
            if self.appear_then_click(self.I_CANCEL_BATTLE, interval=0.8):
                logger.info('Cancel continue battle')
                continue
            if self.appear(self.I_CHECK_MAIN, interval=0.2) and not self.appear(self.I_MAIN_GOTO_SHIKIGAMI_RECORDS):
                logger.info('The main had already appeared, but shikigami records had not yet appeared')
                if self.click(self.C_LOGIN_SCROLL_CLOSE_AREA, interval=2):
                    continue
            if self.appear(self.I_MAIN_GOTO_SHIKIGAMI_RECORDS, interval=0.2):
                if confirm_timer.reached():
                    logger.info('Login to main confirm (shikigami records button appears)')
                    break
            else:
                confirm_timer.reset()
            if self.appear(self.I_MAIN_GOTO_SHIKIGAMI_RECORDS, interval=0.5):
                logger.info('Login success: shikigami records button appears')
                login_success = True
            if self.appear(self.I_HARVEST_ZIDU, interval=1):
                self.I_HARVEST_ZIDU.roi_front[0] -= 200
                self.I_HARVEST_ZIDU.roi_front[1] -= 200
                if self.click(self.I_HARVEST_ZIDU, interval=2):
                    logger.info('Close zidu')
                continue
            if self.appear_then_click(self.I_UI_CONFIRM_SAMLL, interval=2.5):
                logger.info('Soul overflow confirm')
                continue
            if self.appear_then_click(self.I_LOGIN_LOAD_DOWN, interval=1):
                logger.info('Download inbetweening')
                continue
            if self.appear_then_click(self.I_WATCH_VIDEO_CANCEL, interval=0.6):
                logger.info('Close video')
                continue
            if self.appear_then_click(self.I_LOGIN_RED_CLOSE, interval=0.6):
                logger.info('Close red close')
                continue
            if self.appear_then_click(self.I_LOGIN_YELLOW_CLOSE, interval=0.6):
                logger.info('Close yellow close')
                continue
            if self.appear_then_click(self.I_LOGIN_LOGIN_GOTO_BIND_PHONE):
                while 1:
                    self.screenshot()
                    if self.appear_then_click(self.I_LOGIN_LOGIN_CANCEL_BIND_PHONE):
                        logger.info("Close bind phone")
                        break
                continue
            from tasks.Component.GeneralInvite.assets import GeneralInviteAssets as gia
            if self.appear_then_click(gia.I_I_REJECT, interval=0.8):
                logger.info("reject invites")
                continue
            if self.appear_then_click(self.I_LOGIN_LOGIN_ONMYOJI_GENIE):
                logger.info("click onmyoji genie")
                continue
            if self.appear(self.I_LOGIN_SPECIFIC_SERVE, interval=0.6) \
                    and self.ocr_appear_click(self.O_LOGIN_SPECIFIC_SERVE, interval=0.6):
                while True:
                    self.screenshot()
                    if self.appear(self.I_LOGIN_SPECIFIC_SERVE):
                        self.click(self.C_LOGIN_ENSURE_LOGIN_CHARACTER_IN_SAME_SVR, interval=2)
                        continue
                    break
                logger.info('login specific user')
                continue

            if self.appear(self.I_CREATE_ACCOUNT):
                logger.warning('Appear create account')
                raise GameStuckError('Appear create account')
            if self.appear(self.I_CHARACTARS, interval=1):
                logger.info('误入区服设置')
                self.device.click(x=106, y=535)
                continue
            if self.appear(self.I_EARLY_SERVER) and self.appear_then_click(self.I_EARLY_SERVER_CANCEL):
                logger.info('Cancel switch from early server to normal server')
                continue

            if self.appear(self.I_LOGIN_8, interval=0.6): # 进入登录页面后不再处理登录动画逻辑
                skip_login_animation = False
            if skip_login_animation and self._courtyard_visible():
                # 已经在庭院：屏幕中央是站着的阴阳师，盲点会点开姿度菜单。
                logger.info('Already in courtyard, skip clicking screen center')
                skip_login_animation = False
            if skip_login_animation:
                if self.ocr_appear_click(self.O_LOGIN_ANIMATION_SKIP, interval=2.5):  # 点击跳过登录动画
                    continue
                self.click(self.C_LOGIN_ANIMATION_CENTER, interval=5)  # 每5秒点击一次屏幕中央

            if self.ocr_appear_click(self.O_LOGIN_ENTER_GAME, interval=3) or self.ocr_appear_click(self.O_LOGIN_ENTER_GAME_OLD, interval=3):
                skip_login_animation = False  # 进入登录页面后不再处理登录动画逻辑
                self.wait_until_appear(self.I_LOGIN_SPECIFIC_SERVE, True, wait_time=5)
                continue
            if self.appear(self.I_LOGIN_SCROOLL_CLOSE) or self.appear(self.I_LOGIN_SCROOLL_OPEN):
                return login_success

    def app_handle_login(self) -> bool:
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        try:
            self._app_handle_login()
            return True
        except (GameTooManyClickError, GameStuckError) as e:
            logger.warning(e)
            self.device.app_stop()
            self.device.app_start()

        logger.critical('Login failed')
        logger.critical('Onmyoji server may be under maintenance, or you may lost network connection')
        raise RequestHumanTakeover

    def set_specific_usr(self, character: str):
        self.character = character
        self.O_LOGIN_SPECIFIC_SERVE.keyword = character
