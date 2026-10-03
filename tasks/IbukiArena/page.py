from tasks.Component.RightActivity.assets import RightActivityAssets
from tasks.GameUi.page import Page, any_of, page_main, page_shikigami_records
from tasks.GlobalGame.assets import GlobalGameAssets
from tasks.IbukiArena.assets import IbukiArenaAssets

# 伊吹之擂主界面
page_ibuki = Page(any_of(IbukiArenaAssets.I_CHECK_IBUKI, IbukiArenaAssets.I_GOTO_ARENA))
page_ibuki.add_enter_failure_hooks(RightActivityAssets.I_TOGGLE_BUTTON)
page_ibuki.connect(
    page_main, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_ibuki->page_main"
)
page_main.connect(
    page_ibuki, IbukiArenaAssets.I_MAIN_TO_IBUKI, key="page_main->page_ibuki"
)

# 狭间幻境挑战界面
page_ibuki_arena = Page(IbukiArenaAssets.I_CHECK_ARENA)
page_ibuki_arena.connect(
    page_ibuki, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_ibuki_arena->page_ibuki"
)
page_ibuki.connect(
    page_ibuki_arena, IbukiArenaAssets.I_GOTO_ARENA, key="page_ibuki->page_ibuki_arena"
)
