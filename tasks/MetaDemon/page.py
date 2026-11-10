from tasks.GameUi.assets import GameUiAssets
from tasks.GameUi.matcher import any_of
from tasks.GameUi.page import (
    Page,
    page_act_list,
    page_activity,
    page_battle,
    page_battle_result,
    page_main,
    page_reward,
    page_shikigami_records,
    random_click,
    reward_random_click,
)
from module.exception import GameStuckError
from tasks.Component.RightActivity.assets import RightActivityAssets
from tasks.GlobalGame.assets import GlobalGameAssets
from tasks.MetaDemon.assets import MetaDemonAssets

page_act_list_meta_demon = Page(MetaDemonAssets.I_CHECK_ACT_LIST_METADEMON_ACT)
page_act_list.connect(page_act_list_meta_demon, MetaDemonAssets.L_GOTO_METADEMON_LIST, key="page_act_list->page_act_list_meta_demon")
page_act_list_meta_demon.connect(page_main, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_act_list_meta_demon->page_main")

page_act_list_meta_demon.connect(page_activity, GameUiAssets.I_ACT_LIST_GOTO_ACT, key="page_act_list_meta_demon->page_activity")


def handle_activity_overlays(task) -> bool:
    """处理遮挡鬼王入口的活动弹窗。"""
    rules = (
        (GlobalGameAssets.I_UI_REWARD, GlobalGameAssets.C_UI_REWARD),
        (MetaDemonAssets.I_ACTIVITY_SKIP_ENSURE, None),
        (GameUiAssets.I_ACTIVITY_SKIP, None),
        (MetaDemonAssets.I_MD_CLOSE_POPUP, None),
        (MetaDemonAssets.I_ACTIVITY_GENERAL_CLOSE_RED, None),
        (GameUiAssets.I_ACTIVITY_SIGNIN_CLOSE, None),
    )
    clicked = False
    for _ in range(6):
        task.screenshot()
        match = next(((rule, action) for rule, action in rules if task.appear(rule)), None)
        if match is None:
            return clicked
        rule, action = match
        task.device.sleep(0.2)
        task.screenshot()
        if task.appear_then_click(rule, action=action, interval=0):
            clicked = True
            task.device.click_record_clear()
            task.device.sleep(0.2)
    task.screenshot()
    if any(task.appear(rule) for rule, _ in rules):
        raise GameStuckError('MetaDemon activity overlay remains after six attempts')
    return clicked


def enter_meta_demon_activity(task) -> bool:
    if (task.appear_then_click(MetaDemonAssets.I_MAIN_GOTO_ACTIVITY, interval=0.8)
            or task.appear_then_click(GameUiAssets.I_MAIN_GOTO_ACTIVITY, interval=0.8)):
        return True
    if task.appear(GameUiAssets.I_CHECK_MAIN):
        task.appear_then_click(RightActivityAssets.I_TOGGLE_BUTTON, interval=0.5)
    return False


def enter_meta_demon_boss(task) -> bool:
    handle_activity_overlays(task)
    return (task.appear_then_click(MetaDemonAssets.I_MD_CHECK_MAIN_PAGE, interval=0.8)
            or task.appear_then_click(MetaDemonAssets.I_MD_CHECK_MAIN_PAGE_BACKUP, interval=0.8))


def configure_activity_navigation(navigator) -> None:
    """用同一张活动页面衔接超鬼王，适配只作用于当前导航会话。"""
    activity = navigator.resolve_page(page_activity)
    main = navigator.resolve_page(page_main)
    activity.recognizer = any_of(
        activity.recognizer, MetaDemonAssets.I_PAGE_CHECK_ACTIVITY,
        MetaDemonAssets.I_PAGE_CHECK_ACT_GENERAL_1,
        MetaDemonAssets.I_MD_CHECK_MAIN_PAGE, MetaDemonAssets.I_MD_CHECK_MAIN_PAGE_BACKUP,
    )
    activity.on_enter_success[:] = [handle_activity_overlays]
    activity.on_enter_failure[:] = [handle_activity_overlays]
    activity.on_leave_failure[:] = [handle_activity_overlays]
    for transition in main.transitions:
        if transition.key == 'page_main->page_activity':
            transition.action = enter_meta_demon_activity

page_meta_demon_boss = Page(MetaDemonAssets.I_CHECK_BOSS_PAGE)
page_meta_demon_boss.add_enter_success_hooks(MetaDemonAssets.I_MD_CLOSE_POPUP)
page_meta_demon_boss.connect(page_activity, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_meta_demon_boss->page_activity")
page_activity.connect(page_meta_demon_boss, enter_meta_demon_boss, key="page_activity->page_meta_demon_boss")

page_reward.connect(
    page_meta_demon_boss,
    reward_random_click(),
    key="page_reward->page_meta_demon_boss",
)
page_battle_result.connect(page_meta_demon_boss, random_click(), key="page_battle_result->page_meta_demon_boss")
