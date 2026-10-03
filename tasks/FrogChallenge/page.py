from tasks.Component.RightActivity.assets import RightActivityAssets
from tasks.FrogChallenge.assets import FrogChallengeAssets
from tasks.GameUi.page import Page, any_of, page_main, page_shikigami_records
from tasks.GlobalGame.assets import GlobalGameAssets

# 青蛙瓷器挑战赛挑战页(点击庭院右侧图标直接进入, 没有中间页面)
page_frog_challenge = Page(
    any_of(FrogChallengeAssets.I_CHECK_FROG_CHALLENGE, FrogChallengeAssets.I_FC_FIRE)
)
page_frog_challenge.add_enter_failure_hooks(RightActivityAssets.I_TOGGLE_BUTTON)
page_frog_challenge.connect(
    page_main, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_frog_challenge->page_main"
)
page_main.connect(
    page_frog_challenge,
    FrogChallengeAssets.I_GOTO_FROG_CHALLENGE,
    key="page_main->page_frog_challenge",
)
