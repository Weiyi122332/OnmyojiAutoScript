"""密集活动奖励和御魂详情只点击底部空白，胜负结算保持原区域。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from module.atom.click import RuleClick
from module.atom.scatter import RuleScatter
from tasks.ActivityShikigami.base_act import BaseAct
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.GeneralBattle.general_battle import BattleAction
from tasks.GameUi.default_pages import close_reward_details, handle_battle_reward_page, reward_random_click
from tasks.GameUi.page import page_battle_result, page_reward


class ActivityRewardBlankAreaTest(unittest.TestCase):
    def make_task(self, page=page_reward, details=False):
        task = BaseAct.__new__(BaseAct)
        task.navigator = SimpleNamespace(current_page=page)
        task.device = SimpleNamespace(click_record_clear=Mock())
        task.current_action_type = 'ap100'
        task.C_SAFE_RANDOM_CLICK_AREA_ACT = RuleScatter(
            roi_front=(0, 0, 1280, 720), roi_back=(0, 0, 1280, 720),
            polygon=((40, 40), (1240, 40), (1240, 700), (40, 700)),
            focus_count=2, name='activity_scatter',
        )
        task.appear = Mock(side_effect=lambda rule: details and rule is task.I_REWARD_PARTICULARS_ORCHI)
        task.appear_then_click = Mock(return_value=False)
        task.click = Mock(return_value=True)
        return task

    def assert_blank_click(self, click):
        self.assertEqual(click.name, 'ACT_REWARD_BLANK_CLICK')
        self.assertEqual(click.roi_front, (500, 660, 360, 40))
        self.assertEqual(click.roi_back, click.roi_front)
        self.assertFalse(click.functional)

    def test_reward_clicks_stay_outside_full_reward_grid_and_detail_panel(self):
        task = self.make_task()
        click = task._battle_settlement_click()
        self.assert_blank_click(click)
        RuleClick.reset_task_points()
        for _ in range(200):
            x, y = click.coord()
            self.assertGreaterEqual(x, 500)
            self.assertLess(x, 860)
            self.assertGreaterEqual(y, 660)
            self.assertLess(y, 700)

    def test_result_page_keeps_existing_scatter_area_and_state(self):
        task = self.make_task(page_battle_result)
        click = task._battle_settlement_click()
        self.assertIsInstance(click, RuleScatter)
        self.assertEqual(click.polygon, task.C_SAFE_RANDOM_CLICK_AREA_ACT.polygon)
        self.assertIs(click._scatter_state, task.C_SAFE_RANDOM_CLICK_AREA_ACT._scatter_state)

    def test_general_battle_reward_uses_bottom_blank_area(self):
        task = self.make_task()
        context = SimpleNamespace(reward_no_battle_ts=1.0, is_win=False, last_page=page_reward)
        self.assertEqual(task._handle_reward(context, GeneralBattleConfig()), BattleAction.CONTINUE)
        self.assertTrue(context.is_win)
        task.click.assert_called_once()
        self.assert_blank_click(task.click.call_args.args[0])

    def test_reward_details_are_closed_from_the_same_blank_area(self):
        task = self.make_task(details=True)
        self.assertTrue(close_reward_details(task))
        task.click.assert_called_once()
        self.assert_blank_click(task.click.call_args.args[0])
        self.assertEqual(task.click.call_args.kwargs['interval'], 0.8)

    def test_detail_overlay_does_not_fall_through_to_another_reward_click(self):
        task = self.make_task(details=True)
        context = SimpleNamespace(reward_no_battle_ts=1.0, is_win=True, last_page=page_reward)
        self.assertEqual(task._handle_reward(context, GeneralBattleConfig()), BattleAction.CONTINUE)
        task.click.assert_called_once()
        self.assert_blank_click(task.click.call_args.args[0])
        task.appear_then_click.assert_not_called()

    def test_navigation_reward_hook_uses_activity_blank_area(self):
        task = self.make_task()
        self.assertTrue(handle_battle_reward_page(task))
        self.assert_blank_click(task.click.call_args.args[0])

    def test_no_details_does_not_click(self):
        task = self.make_task()
        self.assertFalse(close_reward_details(task))
        task.click.assert_not_called()

    def test_other_tasks_keep_previous_reward_and_detail_regions(self):
        regions = ((17, 105, 57, 368), (1186, 113, 81, 388))
        task = SimpleNamespace(appear=Mock(return_value=True), click=Mock())
        self.assertTrue(close_reward_details(task))
        self.assertIn(task.click.call_args.args[0].roi_front, regions)
        self.assertIn(reward_random_click(task).roi_front, regions)
        self.assertIn(reward_random_click().roi_front, regions)


if __name__ == '__main__':
    unittest.main()
