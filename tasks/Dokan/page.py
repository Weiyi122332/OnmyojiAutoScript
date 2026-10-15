from tasks.Dokan.assets import DokanAssets
from tasks.GameUi.action import sequence
from tasks.GameUi.default_pages import (page_shirin, page_shikigami_records, page_battle, page_battle_result,
                                        page_battle_prepare, page_reward, random_click, page_main)
from tasks.GameUi.matcher import any_of
from tasks.GameUi.page_definition import Page
from tasks.GlobalGame.assets import GlobalGameAssets

# 道馆地图页面
page_dokan_map = Page(any_of(DokanAssets.I_RYOU_DOKAN_FOUND_DOKAN, DokanAssets.I_RYOU_DOKAN_FINDING_DOKAN))
page_shirin.connect(page_dokan_map, DokanAssets.I_SCENE_SHENSHE, key="page_shirin->page_dokan_map")
page_dokan_map.connect(page_shirin, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_dokan_map->page_shirin")


def map_enter_dokan(task) -> bool:
    try_count = 0
    while try_count < 5:
        task.screenshot()
        if task.appear(task.I_RYOU_DOKAN_CHECK):
            return True
        pos = task.O_DOKAN_MAP.ocr_full(task.device.image)
        if pos != (0, 0, 0, 0):
            x = pos[0] + pos[2] / 2  # 取中间
            y = pos[1] - 20  # 往上偏移20
            task.device.click(x=x, y=y, control_name='dokan_map_goto_dokan')
        try_count += 1
    return False


# 道馆页面(必须道馆已经开启才可以调用)
page_dokan = Page(DokanAssets.I_RYOU_DOKAN_CHECK)
page_dokan.connect(page_dokan_map,
                   sequence(DokanAssets.I_RYOU_DOKAN_DOKAN_QUIT, DokanAssets.I_RYOU_DOKAN_EXIT_ENSURE,
                            success_index=1),
                   key="page_dokan->page_dokan_map")
page_dokan_map.connect(page_dokan, action=map_enter_dokan, key="page_dokan_map->page_dokan")
# 道馆->道馆地图->神社->寮->庭院  导航器会误认为(道馆->式神录->庭院)返回庭院最快, 增加花费可以减少惩罚纠错过程
page_dokan.connect(page_shikigami_records, DokanAssets.I_RYOU_DOKAN_SHIKIGAMI, key="page_dokan->page_shikigami_records", cost=4)
# 庭院->寮->神社->道馆地图->道馆  导航器会误认为(庭院->式神录->道馆)进入道馆最快, 同理需要增加花费
page_shikigami_records.connect(page_dokan, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_shikigami_records->page_dokan", cost=4)
